from __future__ import annotations

import json
import socket
import stat
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI

from gatehold.admission import GateholdService
from gatehold.cli import (
    CLEANUP_QUARANTINED_EXIT,
    HOLD_EXIT,
    LEASE_LOST_EXIT,
    QUEUE_TIMEOUT_EXIT,
    main,
)
from gatehold.config import GateholdConfig
from gatehold.host import StaticHostProbe
from gatehold.lifecycle import (
    RUN_LEASE_ENV,
    RUN_PROVENANCE_ENV,
    ProcessCleanupResult,
    RuntimeCleanupResult,
)
from gatehold.models import (
    ClaimRequest,
    ClearanceDecision,
    ResourceRequest,
    WorkloadClass,
)


def _port_available(_port: int) -> bool:
    return True


class _ActivationPipe:
    def write(self, value: bytes) -> int:
        return len(value)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _stub_cli_process_registration(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep fake PIDs out of psutil while exercising real durable cleanup."""

    def register(
        self: GateholdService,
        *,
        lease_id: str,
        pid: int,
        run_token: str,
    ) -> None:
        del self, lease_id, pid, run_token

    monkeypatch.setattr(GateholdService, "register_managed_process", register)


def test_init_creates_private_state_without_printing_token(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "state"

    exit_code = main(["--state-dir", str(state_dir), "init"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert captured.err == ""
    assert payload["status"] == "initialized"
    assert payload["journal_mode"] == "wal"
    assert payload["token_file"] == str(state_dir / "daemon.token")
    assert "token" not in payload
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((state_dir / "gatehold.sqlite3").stat().st_mode) == 0o600
    assert stat.S_IMODE((state_dir / "daemon.token").stat().st_mode) == 0o600


def test_daemon_always_binds_loopback_with_quiet_access_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_uvicorn_run(
        app: FastAPI,
        *,
        host: str,
        port: int,
        access_log: bool,
        log_level: str,
    ) -> None:
        captured.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "access_log": access_log,
                "log_level": log_level,
            }
        )

    monkeypatch.setattr("gatehold.cli.uvicorn.run", fake_uvicorn_run)
    exit_code = main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "daemon",
            "--port",
            "47821",
            "--dashboard-origin",
            "https://dashboard.example.test",
        ]
    )

    assert exit_code == 0
    assert isinstance(captured["app"], FastAPI)
    assert captured == {
        "app": captured["app"],
        "host": "127.0.0.1",
        "port": 47_821,
        "access_log": False,
        "log_level": "warning",
    }


def test_managed_run_uses_literal_argv_shell_false_and_scrubs_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-secret")
    monkeypatch.setenv("GATEHOLD_QUEUE_TOKEN", "fake-queue-secret")
    monkeypatch.setenv("GATEHOLD_HEARTBEAT_TOKEN", "fake-heartbeat-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-aws-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-github-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake-secret")
    monkeypatch.setenv("PATH", "/safe/bin:/usr/bin:/bin")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    monkeypatch.setenv("NPM_CONFIG_CACHE", str(tmp_path / "npm-cache"))
    monkeypatch.delenv("GATEHOLD_PORT", raising=False)
    monkeypatch.setattr(
        "gatehold.resources._port_is_available",
        _port_available,
    )
    cleanup_ports: list[int] = []

    def cleanup_port_available(_self: object, port: int) -> bool:
        cleanup_ports.append(port)
        return True

    monkeypatch.setattr(
        "gatehold.lifecycle.LoopbackPortLifecycle.is_available",
        cleanup_port_available,
    )

    class CompletedProcess:
        pid = 91_001
        stdin = _ActivationPipe()

        def poll(self) -> int:
            return 7

        def terminate(self) -> None:
            raise AssertionError("completed child must not be terminated")

        def wait(self, timeout: float) -> int:
            del timeout
            return 7

        def kill(self) -> None:
            raise AssertionError("completed child must not be killed")

    def fake_subprocess_popen(
        command: list[str],
        *,
        shell: bool,
        env: dict[str, str],
        stdin: int,
        start_new_session: bool,
    ) -> CompletedProcess:
        calls.append(
            {
                "command": command,
                "shell": shell,
                "env": env,
                "stdin": stdin,
                "start_new_session": start_new_session,
            }
        )
        return CompletedProcess()

    monkeypatch.setattr("gatehold.cli.subprocess.Popen", fake_subprocess_popen)
    literal_argument = "; touch /tmp/gatehold-must-never-execute"
    exit_code = main(
        [
            "--state-dir",
            str(state_dir),
            "run",
            "--owner",
            "owner",
            "--workstream",
            "managed test",
            "--scope",
            "src/managed",
            "--light",
            "--ttl",
            "15",
            "--port",
            "--browser-profile",
            "--no-semantic",
            "--wait-timeout",
            "0",
            "--pass-env",
            "UV_CACHE_DIR",
            "--pass-env",
            "NPM_CONFIG_CACHE",
            "--",
            "/usr/local/bin/fake-tool",
            literal_argument,
        ]
    )

    assert exit_code == 7
    assert len(calls) == 1
    call = calls[0]
    supervisor_argv = cast(list[str], call["command"])
    assert supervisor_argv[:4] == [
        sys.executable,
        "-m",
        "gatehold.supervisor",
        "--result-file",
    ]
    result_path = Path(supervisor_argv[4])
    assert result_path.parent == state_dir / "runtime-results"
    assert result_path.suffix == ".exit"
    assert supervisor_argv[5:] == [
        "--",
        "/usr/local/bin/fake-tool",
        literal_argument,
    ]
    assert call["shell"] is False
    assert call["stdin"] == subprocess.PIPE
    assert call["start_new_session"] is True
    child_environment = cast(dict[str, str], call["env"])
    assert "OPENAI_API_KEY" not in child_environment
    assert "GATEHOLD_QUEUE_TOKEN" not in child_environment
    assert "GATEHOLD_HEARTBEAT_TOKEN" not in child_environment
    assert "AWS_SECRET_ACCESS_KEY" not in child_environment
    assert "GITHUB_TOKEN" not in child_environment
    assert "DATABASE_URL" not in child_environment
    assert child_environment["PATH"] == "/safe/bin:/usr/bin:/bin"
    assert child_environment["HOME"] == str(tmp_path / "home")
    assert child_environment["TMPDIR"] == str(tmp_path / "tmp")
    assert child_environment["LANG"] == "C.UTF-8"
    assert child_environment["UV_CACHE_DIR"] == str(tmp_path / "uv-cache")
    assert child_environment["NPM_CONFIG_CACHE"] == str(tmp_path / "npm-cache")
    assert child_environment["GATEHOLD_PORT"].isdigit()
    assert child_environment["GATEHOLD_BROWSER_PROFILE"].startswith(str(state_dir))
    assert child_environment[RUN_LEASE_ENV] == result_path.stem
    assert child_environment[RUN_PROVENANCE_ENV].startswith("gh_")
    assert cleanup_ports == [int(child_environment["GATEHOLD_PORT"])]

    service = GateholdService(
        GateholdConfig(state_dir=state_dir),
        host_probe=StaticHostProbe(),
    )
    snapshot = service.snapshot()
    assert snapshot.active_leases == ()
    with service.store.transaction() as connection:
        lease = service.store.get_lease(connection, result_path.stem)
        runtime = service.store.get_runtime_ownership(connection, result_path.stem)
    assert lease is not None and lease.state.value == "released"
    assert runtime is not None and runtime.state == "cleaned"
    assert runtime.resources_finalized is True
    receipt_json = "".join(receipt.model_dump_json() for receipt in snapshot.recent_receipts)
    assert "fake-tool" in receipt_json
    assert "/usr/local/bin" not in receipt_json


def test_managed_run_rejects_protected_pass_env_before_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-secret")

    exit_code = main(
        [
            "--state-dir",
            str(state_dir),
            "run",
            "--owner",
            "owner",
            "--workstream",
            "invalid-pass-env",
            "--scope",
            "src/invalid-pass-env",
            "--light",
            "--no-semantic",
            "--pass-env",
            "OPENAI_API_KEY",
            "--",
            "fake-tool",
        ]
    )

    service = GateholdService(
        GateholdConfig(state_dir=state_dir),
        host_probe=StaticHostProbe(),
    )

    assert exit_code == 2
    assert "may not forward protected variable OPENAI_API_KEY" in capsys.readouterr().err
    assert service.snapshot().active_leases == ()


def test_managed_run_quarantines_success_when_port_cleanup_is_unconfirmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "state"
    cleanup_ports: list[int] = []
    monkeypatch.setattr(
        "gatehold.resources._port_is_available",
        _port_available,
    )

    def cleanup_port_unavailable(_self: object, port: int) -> bool:
        cleanup_ports.append(port)
        return False

    monkeypatch.setattr(
        "gatehold.lifecycle.LoopbackPortLifecycle.is_available",
        cleanup_port_unavailable,
    )

    class RunningSupervisor:
        pid = 91_005
        stdin = _ActivationPipe()

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            raise AssertionError("cleanup must not guess signals for an unregistered process")

        def wait(self, timeout: float) -> int:
            del timeout
            raise AssertionError("the supervisor result is already available")

        def kill(self) -> None:
            raise AssertionError("cleanup must not guess signals for an unregistered process")

    def fake_popen(
        command: list[str],
        *,
        shell: bool,
        env: dict[str, str],
        stdin: int,
        start_new_session: bool,
    ) -> RunningSupervisor:
        del command, env, stdin
        assert shell is False
        assert start_new_session is True
        return RunningSupervisor()

    monkeypatch.setattr("gatehold.cli.subprocess.Popen", fake_popen)

    def completed_supervisor_result(_path: Path) -> int:
        return 0

    monkeypatch.setattr(
        "gatehold.cli._consume_supervisor_result",
        completed_supervisor_result,
    )

    exit_code = main(
        [
            "--state-dir",
            str(state_dir),
            "run",
            "--owner",
            "owner",
            "--workstream",
            "port-quarantine",
            "--scope",
            "src/port-quarantine",
            "--light",
            "--port",
            "--no-semantic",
            "--wait-timeout",
            "0",
            "--",
            "fake-tool",
        ]
    )

    service = GateholdService(
        GateholdConfig(state_dir=state_dir),
        host_probe=StaticHostProbe(),
    )
    snapshot = service.snapshot()

    assert exit_code == CLEANUP_QUARANTINED_EXIT
    assert "ambiguous runtime quarantined" in capsys.readouterr().err
    assert len(snapshot.active_leases) == 1
    active_lease = snapshot.active_leases[0]
    assert active_lease.resources.port is not None
    assert cleanup_ports
    assert set(cleanup_ports) == {active_lease.resources.port}
    with service.store.reader() as connection:
        runtime = service.store.get_runtime_ownership(
            connection,
            active_lease.lease_id,
        )
    assert runtime is not None
    assert runtime.state == "partial"
    assert runtime.resources_finalized is False


def test_managed_run_terminates_and_kills_child_when_heartbeat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class HangingProcess:
        def __init__(self) -> None:
            self.pid = 91_002
            self.stdin = _ActivationPipe()
            self.terminated = False
            self.killed = False

        def poll(self) -> int | None:
            return -9 if self.killed else None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float) -> int:
            if not self.killed:
                raise subprocess.TimeoutExpired("fake-tool", timeout)
            return -9

        def kill(self) -> None:
            self.killed = True

    process = HangingProcess()

    def fake_popen(
        command: list[str],
        *,
        shell: bool,
        env: dict[str, str],
        stdin: int,
        start_new_session: bool,
    ) -> HangingProcess:
        del command, shell, env, stdin, start_new_session
        return process

    def fail_heartbeat(
        service: GateholdService,
        lease_id: str,
        owner_id: str,
        token: str,
        interval: float,
        stop: object,
        failed: object,
    ) -> None:
        del service, lease_id, owner_id, token, interval, stop
        failed.set()  # type: ignore[attr-defined]

    monkeypatch.setattr("gatehold.cli.subprocess.Popen", fake_popen)
    monkeypatch.setattr("gatehold.cli._heartbeat_loop", fail_heartbeat)

    def cleanup(
        self: GateholdService,
        *,
        lease_id: str,
        reason: str,
        child_exit_code: int | None = None,
    ) -> RuntimeCleanupResult:
        del self, child_exit_code
        process.terminated = True
        process.killed = True
        return RuntimeCleanupResult(
            lease_id=lease_id,
            complete=True,
            process=ProcessCleanupResult(complete=True, terminated=1, killed=1),
            simulator_shutdown=False,
            resources_finalized=False,
        )

    monkeypatch.setattr(GateholdService, "cleanup_runtime", cleanup)
    exit_code = main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "run",
            "--owner",
            "owner",
            "--workstream",
            "lease-loss",
            "--scope",
            "src/lease-loss",
            "--light",
            "--ttl",
            "15",
            "--no-semantic",
            "--",
            "fake-tool",
        ]
    )

    assert exit_code == LEASE_LOST_EXIT
    assert process.terminated is True
    assert process.killed is True
    assert "heartbeat failed" in capsys.readouterr().err


def test_managed_run_preserves_child_exit_when_release_is_already_expired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class CompletedProcess:
        pid = 91_003
        stdin = _ActivationPipe()

        def poll(self) -> int:
            return 9

        def terminate(self) -> None:
            raise AssertionError

        def wait(self, timeout: float) -> int:
            del timeout
            return 9

        def kill(self) -> None:
            raise AssertionError

    def fake_popen(
        command: list[str],
        *,
        shell: bool,
        env: dict[str, str],
        stdin: int,
        start_new_session: bool,
    ) -> CompletedProcess:
        del command, shell, env, stdin, start_new_session
        return CompletedProcess()

    monkeypatch.setattr("gatehold.cli.subprocess.Popen", fake_popen)

    def expired_release(self: GateholdService, **kwargs: object) -> None:
        del self, kwargs
        raise RuntimeError("lease already expired")

    monkeypatch.setattr(GateholdService, "release", expired_release)
    exit_code = main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "run",
            "--owner",
            "owner",
            "--workstream",
            "expired-release",
            "--scope",
            "src/expired-release",
            "--light",
            "--no-semantic",
            "--",
            "fake-tool",
        ]
    )

    assert exit_code == 9
    assert "release could not be confirmed" in capsys.readouterr().err


def test_ctrl_c_terminates_managed_child_and_returns_130(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def static_claim_service(
        config: GateholdConfig,
        *,
        no_semantic: bool,
    ) -> GateholdService:
        del no_semantic
        return GateholdService(
            config,
            host_probe=StaticHostProbe(),
            semantic_comparator=None,
        )

    monkeypatch.setattr("gatehold.cli._claim_service", static_claim_service)

    class InterruptedProcess:
        def __init__(self) -> None:
            self.pid = 91_004
            self.stdin = _ActivationPipe()
            self.terminated = False

        def poll(self) -> int | None:
            if self.terminated:
                return -15
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float) -> int:
            del timeout
            return -15

        def kill(self) -> None:
            raise AssertionError

    process = InterruptedProcess()

    def fake_popen(
        command: list[str],
        *,
        shell: bool,
        env: dict[str, str],
        stdin: int,
        start_new_session: bool,
    ) -> InterruptedProcess:
        del command, shell, env, stdin, start_new_session
        return process

    monkeypatch.setattr("gatehold.cli.subprocess.Popen", fake_popen)

    def cleanup(
        self: GateholdService,
        *,
        lease_id: str,
        reason: str,
        child_exit_code: int | None = None,
    ) -> RuntimeCleanupResult:
        del self, child_exit_code
        process.terminated = True
        return RuntimeCleanupResult(
            lease_id=lease_id,
            complete=True,
            process=ProcessCleanupResult(complete=True, terminated=1),
            simulator_shutdown=False,
            resources_finalized=False,
        )

    monkeypatch.setattr(GateholdService, "cleanup_runtime", cleanup)

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("gatehold.cli.time.sleep", interrupt)
    exit_code = main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "run",
            "--owner",
            "owner",
            "--workstream",
            "interrupt",
            "--scope",
            "src/interrupt",
            "--light",
            "--no-semantic",
            "--",
            "fake-tool",
        ]
    )

    assert exit_code == 130
    assert process.terminated is True


def test_managed_run_requires_explicit_executable_and_valid_polling(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = [
        "--state-dir",
        str(tmp_path / "state"),
        "run",
        "--owner",
        "owner",
        "--workstream",
        "work",
        "--scope",
        "src/work",
        "--no-semantic",
    ]

    missing_command = main(base)
    missing_error = capsys.readouterr().err
    invalid_poll = main([*base, "--poll-interval", "0", "--", "fake-tool"])
    poll_error = capsys.readouterr().err

    assert missing_command == 2
    assert "requires an executable" in missing_error
    assert invalid_poll == 2
    assert "poll-interval" in poll_error


def test_managed_run_timeout_cancels_queue_so_next_heavy_is_granted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    config = GateholdConfig(state_dir=state_dir, max_heavy_slots=1)
    service = GateholdService(config, host_probe=StaticHostProbe())
    active_request = ClaimRequest(
        owner_id="active",
        workstream="active",
        scopes=("src/active",),
        workload=WorkloadClass.HEAVY,
    )
    active = service.claim(active_request)
    assert active.lease is not None
    monkeypatch.setenv("GATEHOLD_MAX_HEAVY", "1")

    exit_code = main(
        [
            "--state-dir",
            str(state_dir),
            "run",
            "--owner",
            "timed-out",
            "--workstream",
            "timed-out",
            "--scope",
            "src/timed-out",
            "--heavy",
            "--no-semantic",
            "--wait-timeout",
            "0",
            "--",
            "fake-tool",
        ]
    )

    assert exit_code == QUEUE_TIMEOUT_EXIT
    assert service.snapshot().queue == ()
    service.release(
        lease_id=active.lease.lease_id,
        owner_id=active_request.owner_id,
        heartbeat_token=active.lease.heartbeat_token,
    )
    next_outcome = service.claim(
        ClaimRequest(
            owner_id="next",
            workstream="next",
            scopes=("src/next",),
            workload=WorkloadClass.HEAVY,
        )
    )
    assert next_outcome.decision is ClearanceDecision.GRANTED


def test_ctrl_c_while_waiting_cancels_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    config = GateholdConfig(state_dir=state_dir, max_heavy_slots=1)
    service = GateholdService(config, host_probe=StaticHostProbe())
    active = service.claim(
        ClaimRequest(
            owner_id="active",
            workstream="active",
            scopes=("src/active",),
            workload=WorkloadClass.HEAVY,
        )
    )
    assert active.lease is not None
    monkeypatch.setenv("GATEHOLD_MAX_HEAVY", "1")

    def static_claim_service(
        candidate_config: GateholdConfig,
        *,
        no_semantic: bool,
    ) -> GateholdService:
        del candidate_config, no_semantic
        return service

    monkeypatch.setattr("gatehold.cli._claim_service", static_claim_service)

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("gatehold.cli.time.sleep", interrupt)
    exit_code = main(
        [
            "--state-dir",
            str(state_dir),
            "run",
            "--owner",
            "interrupted",
            "--workstream",
            "interrupted",
            "--scope",
            "src/interrupted",
            "--heavy",
            "--no-semantic",
            "--wait-timeout",
            "10",
            "--",
            "fake-tool",
        ]
    )

    assert exit_code == 130
    assert service.snapshot().queue == ()
    assert any(event.kind == "request.cancelled" for event in service.events_after(0))


def test_claim_exit_codes_distinguish_hold_and_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "state"
    config = GateholdConfig(state_dir=state_dir, max_heavy_slots=1)
    service = GateholdService(config, host_probe=StaticHostProbe())
    active = service.claim(
        ClaimRequest(
            owner_id="active",
            workstream="protected-work",
            scopes=("src/active",),
            workload=WorkloadClass.HEAVY,
        )
    )
    assert active.lease is not None
    monkeypatch.setenv("GATEHOLD_MAX_HEAVY", "1")

    hold_exit = main(
        [
            "--state-dir",
            str(state_dir),
            "claim",
            "--owner",
            "held",
            "--workstream",
            "protected-work",
            "--scope",
            "src/held",
            "--no-semantic",
        ]
    )
    held_payload = json.loads(capsys.readouterr().out)
    queue_exit = main(
        [
            "--state-dir",
            str(state_dir),
            "claim",
            "--owner",
            "queued",
            "--workstream",
            "other-work",
            "--scope",
            "src/queued",
            "--no-semantic",
        ]
    )
    queued_payload = json.loads(capsys.readouterr().out)

    assert hold_exit == HOLD_EXIT
    assert held_payload["decision"] == "DETERMINISTIC_HOLD"
    assert queue_exit == QUEUE_TIMEOUT_EXIT
    assert queued_payload["decision"] == "QUEUED"
    assert "heavy_slot_limit" in queued_payload["reasons"]


def test_release_accepts_generated_token_without_echoing_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "state"
    config = GateholdConfig(state_dir=state_dir)
    service = GateholdService(config, host_probe=StaticHostProbe())
    request = ClaimRequest(
        owner_id="owner",
        workstream="release",
        scopes=("src/release",),
        workload=WorkloadClass.LIGHT,
        resources=ResourceRequest(),
    )
    claimed = service.claim(request)
    assert claimed.lease is not None
    token = claimed.lease.heartbeat_token

    exit_code = main(
        [
            "--state-dir",
            str(state_dir),
            "release",
            claimed.lease.lease_id,
            "--owner",
            request.owner_id,
            "--token",
            token,
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert token not in captured.out
    assert token not in captured.err
    payload = json.loads(captured.out)
    assert payload["lease_id"] == claimed.lease.lease_id
    assert payload["state"] == "released"
    assert payload["released_at"] is not None


def test_release_returns_quarantine_exit_when_cleanup_is_not_verified(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reservation.bind(("127.0.0.1", 0))
    port = int(reservation.getsockname()[1])
    reservation.close()
    state_dir = tmp_path / "state"
    config = GateholdConfig(state_dir=state_dir, port_start=port, port_end=port)
    service = GateholdService(config, host_probe=StaticHostProbe())
    request = ClaimRequest(
        owner_id="owner",
        workstream="release-quarantine",
        scopes=("src/release-quarantine",),
        workload=WorkloadClass.LIGHT,
        resources=ResourceRequest(port=True),
    )
    claimed = service.claim(request)
    assert claimed.lease is not None
    token = claimed.lease.heartbeat_token

    external_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    external_listener.bind(("127.0.0.1", port))
    external_listener.listen(1)
    try:
        exit_code = main(
            [
                "--state-dir",
                str(state_dir),
                "release",
                claimed.lease.lease_id,
                "--owner",
                request.owner_id,
                "--token",
                token,
            ]
        )
        captured = capsys.readouterr()

        assert exit_code == CLEANUP_QUARANTINED_EXIT
        assert token not in captured.out
        assert token not in captured.err
        payload = json.loads(captured.out)
        assert payload["lease_id"] == claimed.lease.lease_id
        assert payload["state"] == "active"
        assert payload["released_at"] is None
        assert "cleanup remains pending or quarantined" in captured.err
        assert len(service.snapshot().active_leases) == 1
    finally:
        external_listener.close()

    cleanup = service.cleanup_runtime(
        lease_id=claimed.lease.lease_id,
        reason="test_listener_closed",
    )
    assert cleanup.complete is True
    assert cleanup.resources_finalized is True
