"""Argparse CLI for Gatehold's local state, daemon, and managed command runs."""

from __future__ import annotations

import argparse
import json
import os
import signal
import stat
import subprocess  # noqa: S404 - only the explicit run command executes argv.
import sys
import tempfile
import threading
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

import uvicorn

from .admission import GateholdError, GateholdService
from .api import create_app
from .config import GateholdConfig
from .host import StaticHostProbe
from .lifecycle import RUN_LEASE_ENV, RUN_PROVENANCE_ENV
from .models import (
    ClaimOutcome,
    ClaimRequest,
    ClearanceDecision,
    LeaseState,
    ResourceRequest,
    WorkloadClass,
)
from .privacy import new_secret, safe_child_environment
from .security import ensure_daemon_token
from .semantic import OpenAISemanticComparator
from .store import secure_state_permissions
from .supervisor import ACTIVATION_BYTE

QUEUE_TIMEOUT_EXIT = 75
HOLD_EXIT = 73
LEASE_LOST_EXIT = 74
CLEANUP_QUARANTINED_EXIT = 72
PROCESS_POLL_SECONDS = 0.1
PROCESS_TERMINATE_GRACE_SECONDS = 5.0
HEARTBEAT_JOIN_TIMEOUT_SECONDS = 5.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gatehold",
        description="Local clearance control for parallel coding agents.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="private state directory (default: GATEHOLD_STATE_DIR or ~/.gatehold)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="initialize private local state")

    daemon = subparsers.add_parser("daemon", help="serve read-only loopback status")
    daemon.add_argument("--port", type=int, default=None)
    daemon.add_argument(
        "--dashboard-origin",
        action="append",
        default=[],
        help="exact HTTPS dashboard origin allowed to read sanitized local status",
    )

    status = subparsers.add_parser("status", help="print a sanitized local snapshot")
    status.add_argument("--recent", type=int, default=20)

    claim = subparsers.add_parser("claim", help="claim or resume a local lane")
    _add_claim_arguments(claim, allow_resume=True)

    heartbeat = subparsers.add_parser("heartbeat", help="extend an active lease")
    heartbeat.add_argument("lease_id")
    heartbeat.add_argument("--owner", required=True)
    heartbeat.add_argument("--token")
    heartbeat.add_argument("--ttl", type=int)

    release = subparsers.add_parser("release", help="release an active lease")
    release.add_argument("lease_id")
    release.add_argument("--owner", required=True)
    release.add_argument("--token")

    run = subparsers.add_parser(
        "run",
        help="wait for clearance, run argv with shell disabled, and release",
    )
    _add_claim_arguments(run, allow_resume=False)
    run.add_argument("--wait-timeout", type=float, default=300)
    run.add_argument("--poll-interval", type=float, default=1)
    run.add_argument(
        "argv",
        nargs=argparse.REMAINDER,
        help="command after --",
    )
    run.add_argument(
        "--pass-env",
        action="append",
        default=[],
        metavar="NAME",
        help="pass one validated non-secret environment variable to the command",
    )

    subparsers.add_parser("demo", help="run a bounded synthetic replay demo")
    return parser


def _add_claim_arguments(
    parser: argparse.ArgumentParser,
    *,
    allow_resume: bool,
) -> None:
    parser.add_argument("--owner", required=True)
    parser.add_argument("--workstream", required=True)
    parser.add_argument("--scope", action="append", required=True)
    workload = parser.add_mutually_exclusive_group()
    workload.add_argument(
        "--light",
        dest="workload",
        action="store_const",
        const=WorkloadClass.LIGHT.value,
    )
    workload.add_argument(
        "--heavy",
        dest="workload",
        action="store_const",
        const=WorkloadClass.HEAVY.value,
    )
    parser.set_defaults(workload=WorkloadClass.HEAVY.value)
    parser.add_argument("--ttl", type=int, default=900)
    parser.add_argument("--port", action="store_true")
    parser.add_argument("--browser-profile", action="store_true")
    parser.add_argument("--simulator", action="store_true")
    parser.add_argument("--summary")
    parser.add_argument("--no-semantic", action="store_true")
    if allow_resume:
        parser.add_argument("--request-id")
        parser.add_argument("--queue-token")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return _dispatch(arguments)
    except (GateholdError, RuntimeError, ValueError) as error:
        print(f"gatehold: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def _dispatch(arguments: argparse.Namespace) -> int:
    config = _config(arguments)
    command = str(arguments.command)
    if command == "init":
        service = GateholdService(config, semantic_comparator=None)
        ensure_daemon_token(config.token_path)
        _print_json(
            {
                "status": "initialized",
                "state_dir": str(config.state_dir),
                "database": str(config.database_path),
                "token_file": str(config.token_path),
                "journal_mode": service.store.journal_mode(),
                "permissions": secure_state_permissions(config),
            }
        )
        return 0
    if command == "daemon":
        service = GateholdService(config, semantic_comparator=None)
        token = ensure_daemon_token(config.token_path)
        origins = _dashboard_origins(arguments.dashboard_origin)
        app = create_app(
            service,
            daemon_token=token,
            dashboard_origins=origins,
        )
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=config.daemon_port,
            access_log=False,
            log_level="warning",
        )
        return 0
    if command == "status":
        if arguments.recent < 0 or arguments.recent > 100:
            raise ValueError("--recent must be between 0 and 100")
        snapshot = GateholdService(config, semantic_comparator=None).snapshot(
            recent_receipts=arguments.recent
        )
        print(snapshot.model_dump_json(indent=2))
        return 0
    if command == "claim":
        service = _claim_service(config, no_semantic=arguments.no_semantic)
        outcome = service.claim(
            _claim_request(arguments),
            request_id=arguments.request_id,
            queue_token=(
                arguments.queue_token or os.getenv("GATEHOLD_QUEUE_TOKEN")
                if arguments.request_id
                else arguments.queue_token
            ),
        )
        print(outcome.model_dump_json(indent=2))
        if outcome.decision is ClearanceDecision.GRANTED:
            return 0
        return QUEUE_TIMEOUT_EXIT if outcome.decision is ClearanceDecision.QUEUED else HOLD_EXIT
    if command == "heartbeat":
        token = arguments.token or os.getenv("GATEHOLD_HEARTBEAT_TOKEN")
        if not token:
            raise ValueError("--token or GATEHOLD_HEARTBEAT_TOKEN is required")
        outcome = GateholdService(config, semantic_comparator=None).heartbeat(
            lease_id=arguments.lease_id,
            owner_id=arguments.owner,
            heartbeat_token=token,
            ttl_seconds=arguments.ttl,
        )
        print(outcome.model_dump_json(indent=2))
        return 0
    if command == "release":
        token = arguments.token or os.getenv("GATEHOLD_HEARTBEAT_TOKEN")
        if not token:
            raise ValueError("--token or GATEHOLD_HEARTBEAT_TOKEN is required")
        outcome = GateholdService(config, semantic_comparator=None).release(
            lease_id=arguments.lease_id,
            owner_id=arguments.owner,
            heartbeat_token=token,
        )
        print(outcome.model_dump_json(indent=2))
        if outcome.state is LeaseState.RELEASED:
            return 0
        print(
            "gatehold: release requested; cleanup remains pending or quarantined",
            file=sys.stderr,
        )
        return CLEANUP_QUARANTINED_EXIT
    if command == "run":
        return _run_managed(config, arguments)
    if command == "demo":
        return _demo()
    raise RuntimeError(f"unsupported command: {command}")


def _config(arguments: argparse.Namespace) -> GateholdConfig:
    config = GateholdConfig.from_environment(state_dir=arguments.state_dir)
    daemon_port = getattr(arguments, "port", None) if str(arguments.command) == "daemon" else None
    if daemon_port is not None:
        config = config.model_copy(update={"daemon_port": daemon_port})
        config = GateholdConfig.model_validate(config.model_dump())
    return config


def _claim_service(
    config: GateholdConfig,
    *,
    no_semantic: bool,
) -> GateholdService:
    api_key = os.getenv("OPENAI_API_KEY")
    comparator = None
    if not no_semantic and api_key:
        comparator = OpenAISemanticComparator(
            api_key=api_key,
            model=config.model,
            timeout_seconds=config.model_timeout_seconds,
        )
    return GateholdService(config, semantic_comparator=comparator)


def _claim_request(arguments: argparse.Namespace) -> ClaimRequest:
    return ClaimRequest(
        owner_id=arguments.owner,
        workstream=arguments.workstream,
        scopes=tuple(arguments.scope),
        workload=WorkloadClass(arguments.workload),
        ttl_seconds=arguments.ttl,
        resources=ResourceRequest(
            port=arguments.port,
            browser_profile=arguments.browser_profile,
            simulator=arguments.simulator,
        ),
        semantic_summary=arguments.summary,
    )


def _run_managed(config: GateholdConfig, arguments: argparse.Namespace) -> int:
    command = list(arguments.argv)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        raise ValueError("run requires an executable after --")
    if arguments.wait_timeout < 0:
        raise ValueError("--wait-timeout must be non-negative")
    if arguments.poll_interval <= 0 or arguments.poll_interval > 30:
        raise ValueError("--poll-interval must be greater than 0 and at most 30")
    child_environment = safe_child_environment(
        os.environ,
        pass_names=arguments.pass_env,
    )

    service = _claim_service(config, no_semantic=arguments.no_semantic)
    request = _claim_request(arguments)
    deadline = time.monotonic() + arguments.wait_timeout
    outcome: ClaimOutcome | None = None
    try:
        outcome = service.claim(request, executable_name=command[0])
        while outcome.decision is ClearanceDecision.QUEUED:
            if time.monotonic() >= deadline:
                _cancel_queue_best_effort(service, outcome)
                return QUEUE_TIMEOUT_EXIT
            time.sleep(arguments.poll_interval)
            outcome = service.claim(
                request,
                request_id=outcome.request_id,
                queue_token=outcome.queue_token,
                executable_name=command[0],
            )
    except KeyboardInterrupt:
        if outcome is not None and outcome.decision is ClearanceDecision.QUEUED:
            _cancel_queue_best_effort(service, outcome)
        raise
    if outcome.decision is not ClearanceDecision.GRANTED or outcome.lease is None:
        return HOLD_EXIT

    lease = outcome.lease
    if lease.resources.port is not None:
        child_environment["GATEHOLD_PORT"] = str(lease.resources.port)
    if lease.resources.browser_profile is not None:
        child_environment["GATEHOLD_BROWSER_PROFILE"] = lease.resources.browser_profile
    if lease.resources.simulator is not None:
        child_environment["GATEHOLD_SIMULATOR"] = lease.resources.simulator
    run_token = new_secret()
    child_environment[RUN_LEASE_ENV] = lease.lease_id
    child_environment[RUN_PROVENANCE_ENV] = run_token

    stop_heartbeat = threading.Event()
    heartbeat_failed = threading.Event()
    interval = max(5.0, request.ttl_seconds / 3)
    heartbeater = threading.Thread(
        target=_heartbeat_loop,
        args=(
            service,
            lease.lease_id,
            request.owner_id,
            lease.heartbeat_token,
            interval,
            stop_heartbeat,
            heartbeat_failed,
        ),
        daemon=True,
        name="gatehold-heartbeat",
    )
    process: subprocess.Popen[bytes] | None = None
    heartbeat_started = False
    cleanup_reason = "normal_exit"
    result_path = config.runtime_results_dir / f"{lease.lease_id}.exit"
    try:
        if lease.resources.simulator is not None:
            service.prepare_managed_simulator(lease_id=lease.lease_id)
        supervisor_command = [
            sys.executable,
            "-m",
            "gatehold.supervisor",
            "--result-file",
            str(result_path),
            "--",
            *command,
        ]
        try:
            process = subprocess.Popen(  # noqa: S603 - explicit argv contract.
                supervisor_command,
                shell=False,
                env=child_environment,
                stdin=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            executable = Path(command[0]).name
            raise GateholdError(
                f"could not start {executable}: {error.strerror or 'OS error'}"
            ) from None
        try:
            service.register_managed_process(
                lease_id=lease.lease_id,
                pid=process.pid,
                run_token=run_token,
            )
        except Exception:
            _terminate_process(process)
            raise GateholdError("managed runtime provenance could not be recorded") from None
        if process.stdin is None:
            _terminate_process(process)
            raise GateholdError("managed runtime activation channel is unavailable")
        try:
            process.stdin.write(ACTIVATION_BYTE)
            process.stdin.flush()
            process.stdin.close()
        except OSError:
            _terminate_process(process)
            raise GateholdError("managed runtime could not be activated") from None
        heartbeater.start()
        heartbeat_started = True
        while True:
            return_code = _consume_supervisor_result(result_path)
            if return_code is not None:
                cleanup_complete = _cleanup_runtime_best_effort(
                    service,
                    lease_id=lease.lease_id,
                    reason=cleanup_reason,
                    child_exit_code=return_code,
                )
                if return_code == 0 and not cleanup_complete:
                    return CLEANUP_QUARANTINED_EXIT
                return return_code
            return_code = process.poll()
            if return_code is not None:
                cleanup_reason = "supervisor_exited"
                return int(return_code)
            if heartbeat_failed.is_set():
                cleanup_reason = "heartbeat_lost"
                print(
                    "gatehold: lease heartbeat failed; terminating managed command",
                    file=sys.stderr,
                )
                _cleanup_runtime_best_effort(
                    service,
                    lease_id=lease.lease_id,
                    reason=cleanup_reason,
                    child_exit_code=None,
                )
                return LEASE_LOST_EXIT
            time.sleep(PROCESS_POLL_SECONDS)
    except KeyboardInterrupt:
        cleanup_reason = "interrupted"
        if process is not None:
            _cleanup_runtime_best_effort(
                service,
                lease_id=lease.lease_id,
                reason=cleanup_reason,
                child_exit_code=None,
            )
        raise
    finally:
        stop_heartbeat.set()
        if heartbeat_started:
            heartbeater.join(timeout=HEARTBEAT_JOIN_TIMEOUT_SECONDS)
        _cleanup_runtime_best_effort(
            service,
            lease_id=lease.lease_id,
            reason=cleanup_reason,
            child_exit_code=None,
        )
        with suppress(OSError):
            result_path.unlink()
        try:
            service.release(
                lease_id=lease.lease_id,
                owner_id=request.owner_id,
                heartbeat_token=lease.heartbeat_token,
            )
        except Exception:
            # Cleanup confirmation must never replace the real child/lease-loss exit.
            print(
                "gatehold: lease release could not be confirmed",
                file=sys.stderr,
            )


def _cleanup_runtime_best_effort(
    service: GateholdService,
    *,
    lease_id: str,
    reason: str,
    child_exit_code: int | None,
) -> bool:
    try:
        result = service.cleanup_runtime(
            lease_id=lease_id,
            reason=reason,
            child_exit_code=child_exit_code,
        )
    except Exception:
        print(
            "gatehold: owned runtime cleanup could not be confirmed",
            file=sys.stderr,
        )
        return False
    if not result.complete:
        print(
            "gatehold: ambiguous runtime quarantined; unowned processes were not touched",
            file=sys.stderr,
        )
    return result.complete


def _consume_supervisor_result(path: Path) -> int | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise GateholdError("managed runtime result provenance is invalid")
    try:
        value = int(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, ValueError):
        raise GateholdError("managed runtime result is invalid") from None
    if value < -255 or value > 255:
        raise GateholdError("managed runtime result is out of range")
    with suppress(FileNotFoundError):
        path.unlink()
    return value


def _cancel_queue_best_effort(
    service: GateholdService,
    outcome: ClaimOutcome,
) -> None:
    if outcome.queue_token is None:
        return
    try:
        service.cancel_queue(
            request_id=outcome.request_id,
            queue_token=outcome.queue_token,
        )
    except Exception:
        print(
            "gatehold: queued request cancellation could not be confirmed",
            file=sys.stderr,
        )


def _heartbeat_loop(
    service: GateholdService,
    lease_id: str,
    owner_id: str,
    token: str,
    interval: float,
    stop: threading.Event,
    failed: threading.Event,
) -> None:
    while not stop.wait(interval):
        try:
            service.heartbeat(
                lease_id=lease_id,
                owner_id=owner_id,
                heartbeat_token=token,
            )
        except Exception:
            failed.set()
            return


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            # The CLI cannot safely block forever on a broken process handle.
            return


def _dashboard_origins(cli_values: Sequence[str]) -> tuple[str, ...]:
    environment_values = tuple(
        value.strip()
        for value in os.getenv("GATEHOLD_DASHBOARD_ORIGINS", "").split(",")
        if value.strip()
    )
    return tuple(dict.fromkeys((*environment_values, *cli_values)))


def _demo() -> int:
    with tempfile.TemporaryDirectory(prefix="gatehold-demo-") as directory:
        config = GateholdConfig(
            state_dir=Path(directory),
            max_heavy_slots=1,
            port_start=52_000,
            port_end=52_010,
        )
        service = GateholdService(
            config,
            host_probe=StaticHostProbe(cpu_percent=12, memory_percent=24),
            semantic_comparator=None,
        )
        first = service.claim(
            ClaimRequest(
                owner_id="demo-agent-a",
                workstream="checkout-release",
                scopes=("app/checkout",),
                resources=ResourceRequest(port=True, browser_profile=True),
            )
        )
        second = service.claim(
            ClaimRequest(
                owner_id="demo-agent-b",
                workstream="checkout-release",
                scopes=("app/checkout/payment",),
            )
        )
        _print_json(
            {
                "source": "synthetic_replay",
                "disclosure": (
                    "Bounded replay data; not a claim about current live workstation state."
                ),
                "granted_receipt": first.receipt.model_dump(mode="json"),
                "held_receipt": second.receipt.model_dump(mode="json"),
                "snapshot": service.snapshot().model_dump(mode="json"),
            }
        )
    return 0


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))
