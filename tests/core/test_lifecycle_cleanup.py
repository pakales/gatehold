from __future__ import annotations

import os
import shutil
import socket
import sqlite3
from pathlib import Path
from typing import cast

import psutil
import pytest
from helpers import ConfigFactory

from gatehold.admission import GateholdService
from gatehold.host import StaticHostProbe
from gatehold.lifecycle import (
    ProcessCleanupResult,
    ProcessIdentity,
    PsutilProcessLifecycle,
)
from gatehold.models import (
    ClaimRequest,
    ClearanceDecision,
    ResourceRequest,
    WorkloadClass,
)
from gatehold.privacy import secret_digest
from gatehold.resources import PROFILE_MARKER_NAME
from gatehold.store import STATE_MARKER_NAME, GateholdStore, StoredRuntimeOwnership


def _request(
    owner: str,
    *,
    workstream: str | None = None,
    port: bool = False,
    browser_profile: bool = False,
    simulator: bool = False,
) -> ClaimRequest:
    return ClaimRequest(
        owner_id=owner,
        workstream=workstream or f"cleanup lane {owner}",
        scopes=(f"src/{owner}",),
        workload=WorkloadClass.LIGHT,
        resources=ResourceRequest(
            port=port,
            browser_profile=browser_profile,
            simulator=simulator,
        ),
    )


class ToggleProcessLifecycle:
    def __init__(self) -> None:
        self.complete = False
        self.cleanup_calls = 0

    def capture(self, pid: int) -> ProcessIdentity:
        return ProcessIdentity(
            pid=pid,
            pgid=pid,
            session_id=pid,
            create_time=100.0,
            boot_time=50.0,
        )

    def cleanup(self, runtime: StoredRuntimeOwnership) -> ProcessCleanupResult:
        del runtime
        self.cleanup_calls += 1
        return ProcessCleanupResult(
            complete=self.complete,
            terminated=int(self.complete),
            skipped_unowned=int(not self.complete),
        )


class FakeSimulatorLifecycle:
    def __init__(self, *, booted: bool, boot_succeeds: bool = True) -> None:
        self.booted = booted
        self.boot_succeeds = boot_succeeds
        self.calls: list[str] = []
        self.boot_calls: list[str] = []
        self.shutdown_calls: list[str] = []

    def is_booted(self, udid: str) -> bool:
        self.calls.append(f"is_booted:{udid}")
        return self.booted

    def boot(self, udid: str) -> None:
        self.calls.append(f"boot:{udid}")
        self.boot_calls.append(udid)
        if not self.boot_succeeds:
            raise RuntimeError("simulated ambiguous boot failure")
        self.booted = True

    def shutdown(self, udid: str) -> None:
        self.calls.append(f"shutdown:{udid}")
        self.shutdown_calls.append(udid)
        self.booted = False


def test_partial_process_cleanup_keeps_workstream_authority_until_verified(
    config_factory: ConfigFactory,
) -> None:
    process = ToggleProcessLifecycle()
    service = GateholdService(
        config_factory(),
        host_probe=StaticHostProbe(),
        process_lifecycle=process,
    )
    request = _request("owner", workstream="shared cleanup work")
    claimed = service.claim(request)
    assert claimed.lease is not None
    service.register_managed_process(
        lease_id=claimed.lease.lease_id,
        pid=91_100,
        run_token="r" * 32,
    )

    service.release(
        lease_id=claimed.lease.lease_id,
        owner_id=request.owner_id,
        heartbeat_token=claimed.lease.heartbeat_token,
    )

    snapshot = service.snapshot()
    assert [lease.lease_id for lease in snapshot.active_leases] == [claimed.lease.lease_id]
    competing = service.claim(_request("competitor", workstream="shared cleanup work"))
    assert competing.decision is ClearanceDecision.DETERMINISTIC_HOLD
    with service.store.reader() as connection:
        pending = service.store.get_runtime_ownership(
            connection,
            claimed.lease.lease_id,
        )
    assert pending is not None
    assert pending.state == "partial"
    assert pending.terminal_state == "released"
    assert pending.resources_finalized is False

    process.complete = True
    cleaned = service.cleanup_runtime(
        lease_id=claimed.lease.lease_id,
        reason="test_recovery",
    )

    assert cleaned.complete is True
    assert cleaned.resources_finalized is True
    assert service.snapshot().active_leases == ()


def test_reused_process_identity_is_quarantined_without_any_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = StoredRuntimeOwnership(
        lease_id="lease-reused",
        provenance="managed_run",
        pid=91_200,
        pgid=91_200,
        session_id=91_200,
        process_create_time=100.0,
        boot_time=float(psutil.boot_time()),
        run_token_sha256=secret_digest("expected-run-token"),
        browser_profile_owned=False,
        profile_device=None,
        profile_inode=None,
        profile_marker_sha256=None,
        simulator_owned=False,
        simulator_state="none",
        simulator_udid=None,
        simulator_boot_intent_at=None,
        simulator_owned_at=None,
        simulator_cleaned_at=None,
        port_process_owned=False,
        state="active",
        terminal_state="released",
        resources_finalized=False,
        registered_at=1.0,
        updated_at=1.0,
        cleanup_started_at=None,
        cleanup_claim_token=None,
        cleanup_attempts=0,
    )

    class ReusedProcess:
        pid = 91_200

        def create_time(self) -> float:
            return 200.0

        def environ(self) -> dict[str, str]:
            return {}

    class ReusedGroupLifecycle(PsutilProcessLifecycle):
        def _group_members(self, pgid: int) -> tuple[psutil.Process, ...]:
            assert pgid == runtime.pgid
            return cast(tuple[psutil.Process, ...], (ReusedProcess(),))

    def reject_signal(*_arguments: object) -> None:
        raise AssertionError("an unowned or reused process must never be signalled")

    monkeypatch.setattr(os, "killpg", reject_signal)
    result = ReusedGroupLifecycle(term_grace_seconds=0).cleanup(runtime)

    assert result.complete is False
    assert result.terminated == 0
    assert result.killed == 0
    assert result.skipped_unowned == 1


def test_external_port_listener_is_not_touched_and_blocks_final_release(
    config_factory: ConfigFactory,
) -> None:
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reservation.bind(("127.0.0.1", 0))
    port = int(reservation.getsockname()[1])
    reservation.close()
    service = GateholdService(
        config_factory(port_start=port, port_end=port),
        host_probe=StaticHostProbe(),
    )
    request = _request("port-owner", port=True)
    claimed = service.claim(request)
    assert claimed.lease is not None
    assert claimed.lease.resources.port == port

    external_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    external_listener.bind(("127.0.0.1", port))
    external_listener.listen(1)
    try:
        service.release(
            lease_id=claimed.lease.lease_id,
            owner_id=request.owner_id,
            heartbeat_token=claimed.lease.heartbeat_token,
        )
        assert external_listener.fileno() >= 0
        assert len(service.snapshot().active_leases) == 1
        with service.store.reader() as connection:
            pending = service.store.get_runtime_ownership(
                connection,
                claimed.lease.lease_id,
            )
        assert pending is not None
        assert pending.state == "partial"
        assert pending.resources_finalized is False
    finally:
        external_listener.close()

    cleaned = service.cleanup_runtime(
        lease_id=claimed.lease.lease_id,
        reason="external_listener_closed",
    )
    assert cleaned.complete is True
    assert cleaned.resources_finalized is True
    assert service.snapshot().active_leases == ()


def test_replaced_profile_directory_is_quarantined_and_never_deleted(
    config_factory: ConfigFactory,
) -> None:
    service = GateholdService(
        config_factory(),
        host_probe=StaticHostProbe(),
    )
    request = _request("profile-owner", browser_profile=True)
    claimed = service.claim(request)
    assert claimed.lease is not None
    profile = Path(claimed.lease.resources.browser_profile or "")
    marker_value = (profile / PROFILE_MARKER_NAME).read_text(encoding="utf-8")

    shutil.rmtree(profile)
    profile.mkdir(mode=0o700)
    (profile / PROFILE_MARKER_NAME).write_text(marker_value, encoding="utf-8")
    replacement = profile / "human-session.txt"
    replacement.write_text("must survive", encoding="utf-8")

    service.release(
        lease_id=claimed.lease.lease_id,
        owner_id=request.owner_id,
        heartbeat_token=claimed.lease.heartbeat_token,
    )

    assert replacement.read_text(encoding="utf-8") == "must survive"
    assert len(service.snapshot().active_leases) == 1
    with service.store.reader() as connection:
        pending = service.store.get_runtime_ownership(
            connection,
            claimed.lease.lease_id,
        )
    assert pending is not None
    assert pending.state == "partial"
    assert pending.resources_finalized is False

    shutil.rmtree(profile)
    cleaned = service.cleanup_runtime(
        lease_id=claimed.lease.lease_id,
        reason="replacement_removed_by_owner",
    )
    assert cleaned.complete is True
    assert cleaned.resources_finalized is True


def test_prebooted_simulator_is_external_and_never_shutdown(
    config_factory: ConfigFactory,
) -> None:
    udid = "prebooted-exact-udid"
    simulator = FakeSimulatorLifecycle(booted=True)
    service = GateholdService(
        config_factory(simulators=(udid,)),
        host_probe=StaticHostProbe(),
        simulator_lifecycle=simulator,
    )
    request = _request("sim-owner", simulator=True)
    claimed = service.claim(request)
    assert claimed.lease is not None
    assert claimed.lease.resources.simulator == udid

    assert service.prepare_managed_simulator(lease_id=claimed.lease.lease_id) is False
    with service.store.reader() as connection:
        runtime = service.store.get_runtime_ownership(
            connection,
            claimed.lease.lease_id,
        )
    assert runtime is not None
    assert runtime.simulator_state == "external"
    assert runtime.simulator_udid == udid
    assert runtime.simulator_owned is False

    service.release(
        lease_id=claimed.lease.lease_id,
        owner_id=request.owner_id,
        heartbeat_token=claimed.lease.heartbeat_token,
    )

    assert simulator.calls == [f"is_booted:{udid}"]
    assert simulator.boot_calls == []
    assert simulator.shutdown_calls == []
    assert service.snapshot().active_leases == ()


def test_gatehold_boots_and_shuts_down_only_the_exact_owned_simulator(
    config_factory: ConfigFactory,
) -> None:
    udid = "gatehold-owned-exact-udid"
    simulator = FakeSimulatorLifecycle(booted=False)
    service = GateholdService(
        config_factory(simulators=(udid,)),
        host_probe=StaticHostProbe(),
        simulator_lifecycle=simulator,
    )
    request = _request("owned-sim", simulator=True)
    claimed = service.claim(request)
    assert claimed.lease is not None
    assert claimed.lease.resources.simulator == udid

    assert service.prepare_managed_simulator(lease_id=claimed.lease.lease_id) is True
    with service.store.reader() as connection:
        runtime = service.store.get_runtime_ownership(
            connection,
            claimed.lease.lease_id,
        )
    assert runtime is not None
    assert runtime.simulator_state == "owned"
    assert runtime.simulator_udid == udid
    assert runtime.simulator_owned is True
    assert runtime.simulator_boot_intent_at is not None
    assert runtime.simulator_owned_at is not None

    service.release(
        lease_id=claimed.lease.lease_id,
        owner_id=request.owner_id,
        heartbeat_token=claimed.lease.heartbeat_token,
    )

    assert simulator.boot_calls == [udid]
    assert simulator.shutdown_calls == [udid]
    assert simulator.booted is False
    assert service.snapshot().active_leases == ()
    with service.store.reader() as connection:
        cleaned = service.store.get_runtime_ownership(
            connection,
            claimed.lease.lease_id,
        )
    assert cleaned is not None
    assert cleaned.simulator_state == "cleaned"
    assert cleaned.simulator_owned is False
    assert cleaned.simulator_cleaned_at is not None


def test_ambiguous_boot_intent_is_quarantined_without_guessed_shutdown(
    config_factory: ConfigFactory,
) -> None:
    udid = "ambiguous-exact-udid"
    simulator = FakeSimulatorLifecycle(booted=False, boot_succeeds=False)
    service = GateholdService(
        config_factory(simulators=(udid,)),
        host_probe=StaticHostProbe(),
        simulator_lifecycle=simulator,
    )
    request = _request("ambiguous-sim", simulator=True)
    claimed = service.claim(request)
    assert claimed.lease is not None

    with pytest.raises(RuntimeError, match="ownership is unresolved"):
        service.prepare_managed_simulator(lease_id=claimed.lease.lease_id)

    with service.store.reader() as connection:
        intent = service.store.get_runtime_ownership(
            connection,
            claimed.lease.lease_id,
        )
    assert intent is not None
    assert intent.simulator_state == "boot_intent"
    assert intent.simulator_udid == udid
    assert intent.simulator_owned is False
    assert intent.simulator_boot_intent_at is not None

    service.release(
        lease_id=claimed.lease.lease_id,
        owner_id=request.owner_id,
        heartbeat_token=claimed.lease.heartbeat_token,
    )

    assert simulator.calls == [f"is_booted:{udid}", f"boot:{udid}"]
    assert simulator.shutdown_calls == []
    snapshot = service.snapshot()
    assert [lease.lease_id for lease in snapshot.active_leases] == [claimed.lease.lease_id]
    with service.store.reader() as connection:
        partial = service.store.get_runtime_ownership(
            connection,
            claimed.lease.lease_id,
        )
        allocation = connection.execute(
            """
            SELECT lease_id
            FROM allocations
            WHERE resource_type = 'simulator' AND resource_key = ?
            """,
            (udid,),
        ).fetchone()
    assert partial is not None
    assert partial.state == "partial"
    assert partial.terminal_state == "released"
    assert partial.resources_finalized is False
    assert partial.simulator_state == "boot_intent"
    assert allocation is not None
    assert allocation["lease_id"] == claimed.lease.lease_id

    competing = service.claim(
        _request(
            "ambiguous-competitor",
            workstream="different simulator work",
            simulator=True,
        )
    )
    assert competing.decision is ClearanceDecision.QUEUED
    assert competing.lease is None
    assert simulator.shutdown_calls == []


def test_v2_runtime_schema_migrates_legacy_simulator_ownership_fail_closed(
    config_factory: ConfigFactory,
) -> None:
    config = config_factory(simulators=("legacy-exact-udid",))
    config.state_dir.mkdir(parents=True, mode=0o700)
    connection = sqlite3.connect(config.database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE leases (
                lease_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                owner_id TEXT NOT NULL,
                workstream TEXT NOT NULL,
                workstream_key TEXT NOT NULL,
                scopes_json TEXT NOT NULL,
                scope_sha256 TEXT NOT NULL,
                workload TEXT NOT NULL,
                ttl_seconds INTEGER NOT NULL,
                heartbeat_token_sha256 TEXT NOT NULL,
                state TEXT NOT NULL,
                resources_json TEXT NOT NULL,
                executable_name TEXT,
                created_at REAL NOT NULL,
                heartbeat_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE TABLE runtime_ownership (
                lease_id TEXT PRIMARY KEY,
                provenance TEXT NOT NULL,
                pid INTEGER,
                pgid INTEGER,
                session_id INTEGER,
                process_create_time REAL,
                boot_time REAL,
                run_token_sha256 TEXT,
                browser_profile_owned INTEGER NOT NULL,
                profile_device INTEGER,
                profile_inode INTEGER,
                profile_marker_sha256 TEXT,
                simulator_owned INTEGER NOT NULL DEFAULT 0,
                port_process_owned INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL,
                terminal_state TEXT,
                resources_finalized INTEGER NOT NULL DEFAULT 0,
                registered_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                cleanup_started_at REAL,
                cleanup_claim_token TEXT,
                cleanup_attempts INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO leases VALUES (
                'legacy-lease', 'legacy-request', 'legacy-owner',
                'legacy-work', 'legacy-work', '["src/legacy"]', 'scope-digest',
                'light', 60, 'heartbeat-digest', 'active',
                '{"port":null,"browser_profile":null,"simulator":"legacy-exact-udid"}',
                NULL, 1.0, 1.0, 61.0
            );
            INSERT INTO runtime_ownership VALUES (
                'legacy-lease', 'legacy-unverified',
                NULL, NULL, NULL, NULL, NULL, NULL,
                0, NULL, NULL, NULL,
                1, 0, 'active', NULL, 0, 1.0, 1.0, NULL, NULL, 0
            );
            """
        )
    finally:
        connection.close()
    config.database_path.chmod(0o600)

    store = GateholdStore(config)
    store.initialize()

    with store.reader() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(runtime_ownership)").fetchall()
        }
        migrated = store.get_runtime_ownership(connection, "legacy-lease")
        schema_version = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
    assert {
        "simulator_state",
        "simulator_udid",
        "simulator_boot_intent_at",
        "simulator_owned_at",
        "simulator_cleaned_at",
    } <= columns
    assert migrated is not None
    assert migrated.simulator_state == "boot_intent"
    assert migrated.simulator_udid == "legacy-exact-udid"
    assert migrated.simulator_owned is False
    assert migrated.simulator_owned_at is None
    assert schema_version is not None
    assert schema_version["value"] == "3"
    assert (config.state_dir / STATE_MARKER_NAME).is_file()
