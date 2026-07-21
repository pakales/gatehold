from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Lock

import pytest
from helpers import ConfigFactory, MutableClock

from gatehold.admission import (
    CredentialError,
    GateholdService,
    LeaseNotActiveError,
    RequestNotQueuedError,
)
from gatehold.config import GateholdConfig
from gatehold.conflicts import canonical_workstream
from gatehold.host import StaticHostProbe
from gatehold.models import (
    ClaimRequest,
    ClearanceDecision,
    ConflictKind,
    LeaseState,
    ReasonCode,
    RequestState,
    SemanticAssessment,
    SemanticCandidate,
    SemanticReason,
    SemanticVerdict,
    WorkloadClass,
)
from gatehold.privacy import scope_digest
from gatehold.store import (
    STATE_MARKER_CONTENT,
    STATE_MARKER_NAME,
    GateholdStore,
    secure_state_permissions,
)


class CountingClearComparator:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = Lock()

    def compare(
        self,
        candidate: SemanticCandidate,
        active: SemanticCandidate,
        *,
        active_lease_id: str,
    ) -> SemanticAssessment:
        del candidate, active
        with self._lock:
            self.calls += 1
        return SemanticAssessment(
            verdict=SemanticVerdict.CLEAR,
            model="fake-clear",
            compared_lease_id=active_lease_id,
            reason=SemanticReason.NONE,
        )


def _request(
    owner: str,
    workstream: str,
    scope: str,
    *,
    workload: WorkloadClass = WorkloadClass.HEAVY,
    ttl_seconds: int = 60,
) -> ClaimRequest:
    return ClaimRequest(
        owner_id=owner,
        workstream=workstream,
        scopes=(scope,),
        workload=workload,
        ttl_seconds=ttl_seconds,
    )


def test_store_initializes_wal_and_private_permissions(
    config_factory: ConfigFactory,
) -> None:
    config = config_factory()
    store = GateholdStore(config)
    store.initialize()

    assert store.journal_mode() == "wal"
    assert secure_state_permissions(config) == {
        "state_dir": "0o700",
        "database": "0o600",
        "profiles": "0o700",
    }
    marker = config.state_dir / STATE_MARKER_NAME
    assert marker.read_bytes() == STATE_MARKER_CONTENT
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600

    with store.transaction():
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{config.database_path}{suffix}")
            if sidecar.exists():
                assert stat.S_IMODE(sidecar.stat().st_mode) & 0o077 == 0


def test_store_rejects_symlink_state_directory(
    tmp_path: Path, config_factory: ConfigFactory
) -> None:
    target = tmp_path / "real-state"
    target.mkdir()
    original_mode = stat.S_IMODE(target.stat().st_mode)
    symlink = tmp_path / "state-link"
    symlink.symlink_to(target, target_is_directory=True)
    config = config_factory(state_dir=symlink)

    with pytest.raises(RuntimeError, match="real directory"):
        GateholdStore(config).initialize()
    assert stat.S_IMODE(target.stat().st_mode) == original_mode
    assert not (target / STATE_MARKER_NAME).exists()


def test_environment_config_preserves_final_symlink_for_store_rejection(
    tmp_path: Path,
) -> None:
    target = tmp_path / "real-state"
    target.mkdir(mode=0o755)
    original_mode = stat.S_IMODE(target.stat().st_mode)
    symlink = tmp_path / "state-link"
    symlink.symlink_to(target, target_is_directory=True)

    config = GateholdConfig.from_environment(state_dir=symlink)

    assert config.state_dir == symlink
    assert config.state_dir.is_symlink()
    with pytest.raises(RuntimeError, match="real directory"):
        GateholdStore(config).initialize()
    assert stat.S_IMODE(target.stat().st_mode) == original_mode
    assert not (target / STATE_MARKER_NAME).exists()


def test_store_adopts_an_existing_empty_private_directory(
    tmp_path: Path,
    config_factory: ConfigFactory,
) -> None:
    state_dir = tmp_path / "fresh-private-state"
    state_dir.mkdir(mode=0o700)
    state_dir.chmod(0o700)
    config = config_factory(state_dir=state_dir)

    GateholdStore(config).initialize()

    assert (state_dir / STATE_MARKER_NAME).read_bytes() == STATE_MARKER_CONTENT
    assert config.database_path.is_file()
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700


def test_store_refuses_to_chmod_or_adopt_unrecognized_existing_directory(
    tmp_path: Path,
    config_factory: ConfigFactory,
) -> None:
    state_dir = tmp_path / "shared-state"
    state_dir.mkdir(mode=0o755)
    state_dir.chmod(0o755)
    sentinel = state_dir / "keep.txt"
    sentinel.write_text("shared", encoding="utf-8")
    config = config_factory(state_dir=state_dir)

    with pytest.raises(RuntimeError, match="refusing to adopt"):
        GateholdStore(config).initialize()

    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o755
    assert sentinel.read_text(encoding="utf-8") == "shared"
    assert not (state_dir / STATE_MARKER_NAME).exists()
    assert not config.database_path.exists()


def test_store_rejects_symlink_database(tmp_path: Path, config_factory: ConfigFactory) -> None:
    state_dir = tmp_path / "state"
    config = config_factory(state_dir=state_dir)
    GateholdStore(config).initialize()
    config.database_path.unlink()
    target = tmp_path / "outside.sqlite3"
    target.touch()
    (state_dir / "gatehold.sqlite3").symlink_to(target)

    with pytest.raises(RuntimeError, match="regular file"):
        GateholdStore(config).initialize()


def test_store_transaction_rolls_back_on_failure(
    config_factory: ConfigFactory,
) -> None:
    store = GateholdStore(config_factory())
    store.initialize()

    with pytest.raises(RuntimeError, match="force rollback"), store.transaction() as connection:
        store.insert_event(
            connection,
            kind="test.rollback",
            occurred_at=1,
            detail={"safe": True},
        )
        raise RuntimeError("force rollback")

    assert store.events_after(0) == ()


def test_direct_deterministic_workstream_and_scope_conflicts_are_authoritative(
    config_factory: ConfigFactory,
) -> None:
    comparator = CountingClearComparator()
    service = GateholdService(
        config_factory(),
        host_probe=StaticHostProbe(),
        semantic_comparator=comparator,
    )
    granted = service.claim(_request("owner-a", "Release Audit", "src/release"))
    assert granted.decision is ClearanceDecision.GRANTED
    assert granted.lease is not None

    same_workstream = service.claim(_request("owner-b", "  release   AUDIT ", "docs/unrelated"))
    assert same_workstream.decision is ClearanceDecision.DETERMINISTIC_HOLD
    assert same_workstream.reasons == (ReasonCode.WORKSTREAM_CONFLICT,)
    assert same_workstream.conflicts[0].kind is ConflictKind.WORKSTREAM
    assert same_workstream.conflicts[0].lease_id == granted.lease.lease_id

    same_scope = service.claim(_request("owner-c", "Different work", "src/release/api"))
    assert same_scope.decision is ClearanceDecision.DETERMINISTIC_HOLD
    assert same_scope.reasons == (ReasonCode.SCOPE_CONFLICT,)
    assert same_scope.conflicts[0].kind is ConflictKind.SCOPE
    assert same_scope.conflicts[0].lease_id == granted.lease.lease_id

    assert comparator.calls == 0


def test_concurrent_same_workstream_claims_produce_one_grant_and_one_hold(
    config_factory: ConfigFactory,
) -> None:
    config = config_factory(max_heavy_slots=2)
    first_service = GateholdService(config, host_probe=StaticHostProbe())
    second_service = GateholdService(config, host_probe=StaticHostProbe())
    barrier = Barrier(2)

    def claim(service: GateholdService, owner: str, scope: str) -> ClearanceDecision:
        barrier.wait(timeout=5)
        return service.claim(_request(owner, "Shared Release Work", scope)).decision

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(claim, first_service, "owner-a", "src/a")
        second = pool.submit(claim, second_service, "owner-b", "src/b")
        decisions = [first.result(timeout=15), second.result(timeout=15)]

    assert decisions.count(ClearanceDecision.GRANTED) == 1
    assert decisions.count(ClearanceDecision.DETERMINISTIC_HOLD) == 1
    snapshot = first_service.snapshot()
    assert len(snapshot.active_leases) == 1
    assert snapshot.active_leases[0].workstream_sha256


def test_heavy_slot_limit_and_fifo_are_enforced_across_resume(
    config_factory: ConfigFactory,
) -> None:
    service = GateholdService(
        config_factory(max_heavy_slots=1),
        host_probe=StaticHostProbe(),
    )
    active_request = _request("owner-active", "active", "src/active")
    first_waiter_request = _request("owner-first", "first waiter", "src/first")
    second_waiter_request = _request("owner-second", "second waiter", "src/second")

    active = service.claim(active_request)
    first_waiter = service.claim(first_waiter_request)
    second_waiter = service.claim(second_waiter_request)
    assert active.lease is not None
    assert first_waiter.decision is ClearanceDecision.QUEUED
    assert first_waiter.reasons == (ReasonCode.HEAVY_SLOT_LIMIT,)
    assert first_waiter.queue_position == 1
    assert first_waiter.queue_token is not None
    assert second_waiter.decision is ClearanceDecision.QUEUED
    assert second_waiter.reasons == (
        ReasonCode.FIFO_WAIT,
        ReasonCode.HEAVY_SLOT_LIMIT,
    )
    assert second_waiter.queue_position == 2
    assert second_waiter.queue_token is not None

    service.release(
        lease_id=active.lease.lease_id,
        owner_id=active_request.owner_id,
        heartbeat_token=active.lease.heartbeat_token,
    )
    second_still_waits = service.claim(
        second_waiter_request,
        request_id=second_waiter.request_id,
        queue_token=second_waiter.queue_token,
    )
    assert second_still_waits.decision is ClearanceDecision.QUEUED
    assert second_still_waits.reasons == (ReasonCode.FIFO_WAIT,)
    assert second_still_waits.queue_position == 2

    first_admitted = service.claim(
        first_waiter_request,
        request_id=first_waiter.request_id,
        queue_token=first_waiter.queue_token,
    )
    assert first_admitted.decision is ClearanceDecision.GRANTED
    assert first_admitted.lease is not None
    service.release(
        lease_id=first_admitted.lease.lease_id,
        owner_id=first_waiter_request.owner_id,
        heartbeat_token=first_admitted.lease.heartbeat_token,
    )

    second_admitted = service.claim(
        second_waiter_request,
        request_id=second_waiter.request_id,
        queue_token=second_waiter.queue_token,
    )
    assert second_admitted.decision is ClearanceDecision.GRANTED


def test_abandoned_queue_expires_before_fifo_and_cannot_block_next_heavy(
    config_factory: ConfigFactory,
) -> None:
    clock = MutableClock()
    config = config_factory(max_heavy_slots=1, queue_ttl_seconds=300)
    service = GateholdService(
        config,
        host_probe=StaticHostProbe(),
        now=clock,
    )
    active_request = _request("active", "active", "src/active")
    abandoned_request = _request("abandoned", "abandoned", "src/abandoned")

    active = service.claim(active_request)
    abandoned = service.claim(abandoned_request)
    assert active.lease is not None
    assert abandoned.decision is ClearanceDecision.QUEUED
    assert abandoned.queue_token is not None

    service.release(
        lease_id=active.lease.lease_id,
        owner_id=active_request.owner_id,
        heartbeat_token=active.lease.heartbeat_token,
    )
    clock.advance(seconds=301)

    next_request = _request("next", "next", "src/next")
    next_outcome = service.claim(next_request)

    assert next_outcome.decision is ClearanceDecision.GRANTED
    with service.store.reader() as connection:
        stored = service.store.get_request(connection, abandoned.request_id)
    assert stored is not None
    assert stored.status is RequestState.EXPIRED
    events = service.events_after(0)
    assert any(
        event.kind == "request.expired" and event.request_id == abandoned.request_id
        for event in events
    )


def test_host_pressure_queues_heavy_work_with_all_reasons(
    config_factory: ConfigFactory,
) -> None:
    service = GateholdService(
        config_factory(cpu_limit_percent=70, memory_limit_percent=80),
        host_probe=StaticHostProbe(cpu_percent=70, memory_percent=95),
    )

    outcome = service.claim(_request("owner", "heavy", "src/heavy"))

    assert outcome.decision is ClearanceDecision.QUEUED
    assert outcome.reasons == (
        ReasonCode.HOST_CPU_PRESSURE,
        ReasonCode.HOST_MEMORY_PRESSURE,
    )
    assert outcome.queue_token is not None
    assert outcome.receipt.reasons == outcome.reasons
    assert service.snapshot().queue[0].reasons == outcome.reasons


def test_light_work_bypasses_heavy_slot_and_host_pressure(
    config_factory: ConfigFactory,
) -> None:
    probe = StaticHostProbe()
    service = GateholdService(
        config_factory(max_heavy_slots=1),
        host_probe=probe,
    )
    first = service.claim(_request("heavy", "heavy", "src/heavy"))
    assert first.decision is ClearanceDecision.GRANTED
    probe.cpu_percent = 100
    probe.memory_percent = 100

    light = service.claim(
        _request(
            "light",
            "light",
            "src/light",
            workload=WorkloadClass.LIGHT,
        )
    )
    assert light.decision is ClearanceDecision.GRANTED


def test_heartbeat_extends_ttl_and_expiry_reclaims_lease(
    config_factory: ConfigFactory,
) -> None:
    clock = MutableClock()
    service = GateholdService(
        config_factory(),
        host_probe=StaticHostProbe(),
        now=clock,
    )
    request = _request(
        "owner",
        "heartbeat work",
        "src/heartbeat",
        workload=WorkloadClass.LIGHT,
        ttl_seconds=20,
    )
    claimed = service.claim(request)
    assert claimed.lease is not None
    original_expiry = claimed.lease.expires_at

    clock.advance(seconds=10)
    heartbeat = service.heartbeat(
        lease_id=claimed.lease.lease_id,
        owner_id=request.owner_id,
        heartbeat_token=claimed.lease.heartbeat_token,
        ttl_seconds=30,
    )
    assert heartbeat.heartbeat_at == clock.value
    assert heartbeat.expires_at == clock.value + timedelta(seconds=30)
    assert heartbeat.expires_at > original_expiry

    clock.advance(seconds=29)
    assert len(service.snapshot().active_leases) == 1
    clock.advance(seconds=1)
    assert service.reap_expired() == 1
    assert service.snapshot().active_leases == ()
    with pytest.raises(LeaseNotActiveError, match="expired"):
        service.heartbeat(
            lease_id=claimed.lease.lease_id,
            owner_id=request.owner_id,
            heartbeat_token=claimed.lease.heartbeat_token,
        )


def test_release_requires_credentials_and_is_not_repeatable(
    config_factory: ConfigFactory,
) -> None:
    service = GateholdService(config_factory(), host_probe=StaticHostProbe())
    request = _request(
        "owner",
        "release work",
        "src/release",
        workload=WorkloadClass.LIGHT,
    )
    claimed = service.claim(request, executable_name="/usr/local/bin/python3")
    assert claimed.lease is not None
    assert claimed.receipt.executable_name == "python3"

    with pytest.raises(CredentialError, match="invalid lease credentials"):
        service.release(
            lease_id=claimed.lease.lease_id,
            owner_id="other-owner",
            heartbeat_token=claimed.lease.heartbeat_token,
        )
    with pytest.raises(CredentialError, match="invalid lease credentials"):
        service.release(
            lease_id=claimed.lease.lease_id,
            owner_id=request.owner_id,
            heartbeat_token="x" * 32,
        )

    released = service.release(
        lease_id=claimed.lease.lease_id,
        owner_id=request.owner_id,
        heartbeat_token=claimed.lease.heartbeat_token,
    )
    assert released.lease_id == claimed.lease.lease_id
    assert released.state is LeaseState.RELEASED
    assert released.released_at is not None
    assert released.receipt.expires_at is None
    assert service.snapshot().active_leases == ()
    with pytest.raises(LeaseNotActiveError, match="released"):
        service.release(
            lease_id=claimed.lease.lease_id,
            owner_id=request.owner_id,
            heartbeat_token=claimed.lease.heartbeat_token,
        )


def test_resume_rejects_wrong_token_or_changed_request(
    config_factory: ConfigFactory,
) -> None:
    service = GateholdService(
        config_factory(max_heavy_slots=1),
        host_probe=StaticHostProbe(cpu_percent=99),
    )
    request = _request("owner", "queued work", "src/queued")
    queued = service.claim(request)
    assert queued.queue_token is not None

    with pytest.raises(CredentialError, match="invalid queue token"):
        service.claim(
            request,
            request_id=queued.request_id,
            queue_token="x" * 32,
        )
    changed = _request("owner", "changed work", "src/queued")
    with pytest.raises(CredentialError, match="does not match"):
        service.claim(
            changed,
            request_id=queued.request_id,
            queue_token=queued.queue_token,
        )


def test_admitted_request_cannot_be_resumed(
    config_factory: ConfigFactory,
) -> None:
    probe = StaticHostProbe(cpu_percent=99)
    service = GateholdService(
        config_factory(cpu_limit_percent=50),
        host_probe=probe,
    )
    request = _request("owner", "admitted", "src/admitted")
    queued = service.claim(request)
    assert queued.queue_token is not None
    probe.cpu_percent = 0
    admitted = service.claim(
        request,
        request_id=queued.request_id,
        queue_token=queued.queue_token,
    )
    assert admitted.lease is not None

    with service.store.reader() as connection:
        stored = service.store.get_request(connection, admitted.request_id)
    assert stored is not None
    assert stored.status is RequestState.ADMITTED
    with pytest.raises(RequestNotQueuedError, match="admitted"):
        service.claim(
            request,
            request_id=admitted.request_id,
            queue_token=queued.queue_token,
        )


def test_snapshot_and_events_expose_hashes_not_raw_ownership(
    config_factory: ConfigFactory,
) -> None:
    service = GateholdService(config_factory(), host_probe=StaticHostProbe())
    request = _request(
        "private-owner",
        "Secret Release Lane",
        "/Users/private/Secret Repo/src",
        workload=WorkloadClass.LIGHT,
    )
    outcome = service.claim(request, executable_name="/private/bin/secret-runner")
    assert outcome.lease is not None

    snapshot_json = service.snapshot().model_dump_json()
    assert "private-owner" not in snapshot_json
    assert "Secret Release Lane" not in snapshot_json
    assert "/Users/private" not in snapshot_json
    assert "secret-runner" in snapshot_json
    assert scope_digest(request.scopes) in snapshot_json
    assert canonical_workstream(request.workstream) not in snapshot_json

    events_json = "".join(event.model_dump_json() for event in service.events_after(0))
    assert "private-owner" not in events_json
    assert "Secret Release Lane" not in events_json
    assert "/Users/private" not in events_json
    assert "secret-runner" not in events_json


def test_database_and_sidecars_never_store_plaintext_credentials(
    config_factory: ConfigFactory,
) -> None:
    config = config_factory(cpu_limit_percent=50)
    service = GateholdService(
        config,
        host_probe=StaticHostProbe(cpu_percent=99),
    )
    queued = service.claim(_request("owner", "queued", "src/queued"))
    assert queued.queue_token is not None

    relaxed = GateholdService(config, host_probe=StaticHostProbe())
    admitted = relaxed.claim(
        _request(
            "light-owner",
            "light",
            "src/light",
            workload=WorkloadClass.LIGHT,
        )
    )
    assert admitted.lease is not None
    secrets = (
        queued.queue_token.encode(),
        admitted.lease.heartbeat_token.encode(),
    )
    for path in config.state_dir.glob("gatehold.sqlite3*"):
        data = path.read_bytes()
        assert all(secret not in data for secret in secrets)


def test_state_modes_ignore_process_umask(
    config_factory: ConfigFactory,
) -> None:
    previous = os.umask(0)
    try:
        config = config_factory()
        GateholdStore(config).initialize()
    finally:
        os.umask(previous)

    assert stat.S_IMODE(config.state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(config.browser_profiles_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(config.database_path.stat().st_mode) == 0o600
