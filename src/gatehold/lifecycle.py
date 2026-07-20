"""Owned runtime cleanup with durable provenance and fail-closed process guards."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import stat
import subprocess  # noqa: S404 - fixed xcrun argv only.
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import psutil

from .config import GateholdConfig
from .models import LeaseState
from .privacy import new_secret, secret_digest
from .resources import PROFILE_MARKER_NAME
from .store import GateholdStore, StoredRuntimeOwnership

RUN_LEASE_ENV = "GATEHOLD_LEASE_ID"
RUN_PROVENANCE_ENV = "GATEHOLD_RUN_PROVENANCE"
DEFAULT_TERM_GRACE_SECONDS = 5.0
DEFAULT_CLEANUP_RETRY_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    pgid: int
    session_id: int
    create_time: float
    boot_time: float


@dataclass(frozen=True, slots=True)
class ProcessCleanupResult:
    complete: bool
    terminated: int = 0
    killed: int = 0
    skipped_unowned: int = 0


@dataclass(frozen=True, slots=True)
class RuntimeCleanupResult:
    lease_id: str
    complete: bool
    process: ProcessCleanupResult
    simulator_shutdown: bool
    resources_finalized: bool


class ProcessLifecycleAdapter(Protocol):
    def capture(self, pid: int) -> ProcessIdentity | None: ...

    def cleanup(self, runtime: StoredRuntimeOwnership) -> ProcessCleanupResult: ...


class SimulatorLifecycleAdapter(Protocol):
    def is_booted(self, udid: str) -> bool: ...

    def boot(self, udid: str) -> None: ...

    def shutdown(self, udid: str) -> None: ...


class PortLifecycleAdapter(Protocol):
    def is_available(self, port: int) -> bool: ...


class ProfileLifecycleAdapter(Protocol):
    def remove_owned(
        self,
        path: str,
        runtime: StoredRuntimeOwnership,
    ) -> bool: ...


class PsutilProcessLifecycle:
    """Terminate only processes proven to belong to Gatehold's managed run."""

    def __init__(self, *, term_grace_seconds: float = DEFAULT_TERM_GRACE_SECONDS) -> None:
        self.term_grace_seconds = term_grace_seconds

    def capture(self, pid: int) -> ProcessIdentity | None:
        try:
            process = psutil.Process(pid)
            return ProcessIdentity(
                pid=pid,
                pgid=os.getpgid(pid),
                session_id=os.getsid(pid),
                create_time=float(process.create_time()),
                boot_time=float(psutil.boot_time()),
            )
        except (OSError, psutil.Error):
            return None

    def cleanup(self, runtime: StoredRuntimeOwnership) -> ProcessCleanupResult:
        if runtime.pgid is None or runtime.run_token_sha256 is None:
            return ProcessCleanupResult(complete=runtime.provenance != "managed_run")
        if runtime.boot_time is not None and abs(runtime.boot_time - psutil.boot_time()) > 1:
            return ProcessCleanupResult(complete=True)

        members = self._group_members(runtime.pgid)
        if not members:
            return ProcessCleanupResult(complete=True)

        owned = self._owned_members(runtime, members)
        skipped = len(members) - len(owned)
        if not owned:
            # A reused PID or unknown group member is quarantined, never signalled.
            return ProcessCleanupResult(complete=False, skipped_unowned=skipped)

        owned_pids = {process.pid for process in owned}
        group_is_exclusively_owned = (
            runtime.pid == runtime.pgid
            and runtime.session_id == runtime.pgid
            and owned_pids == {process.pid for process in members}
        )
        if group_is_exclusively_owned:
            try:
                os.killpg(runtime.pgid, signal.SIGTERM)
            except ProcessLookupError:
                return ProcessCleanupResult(
                    complete=True,
                    skipped_unowned=skipped,
                )
            except PermissionError:
                return ProcessCleanupResult(
                    complete=False,
                    skipped_unowned=skipped,
                )
        else:
            for process in owned:
                try:
                    process.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        _, alive = psutil.wait_procs(owned, timeout=self.term_grace_seconds)
        killed = 0
        for process in alive:
            try:
                process.kill()
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if alive:
            psutil.wait_procs(alive, timeout=self.term_grace_seconds)

        remaining = self._owned_members(
            runtime,
            self._group_members(runtime.pgid),
        )
        return ProcessCleanupResult(
            complete=not remaining,
            terminated=len(owned),
            killed=killed,
            skipped_unowned=skipped,
        )

    def _group_members(self, pgid: int) -> tuple[psutil.Process, ...]:
        members: list[psutil.Process] = []
        for process in psutil.process_iter():
            try:
                if os.getpgid(process.pid) == pgid:
                    members.append(process)
            except (OSError, psutil.Error):
                continue
        return tuple(members)

    def _owned_members(
        self,
        runtime: StoredRuntimeOwnership,
        members: tuple[psutil.Process, ...],
    ) -> tuple[psutil.Process, ...]:
        expected_token = runtime.run_token_sha256
        if expected_token is None:
            return ()
        by_pid = {process.pid: process for process in members}
        owned_pids: set[int] = set()

        root: psutil.Process | None = None
        if runtime.pid is not None and runtime.process_create_time is not None:
            candidate = by_pid.get(runtime.pid)
            if candidate is not None:
                try:
                    if abs(candidate.create_time() - runtime.process_create_time) < 0.01:
                        root = candidate
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    root = None
        if root is not None:
            owned_pids.add(root.pid)
            if runtime.pid == runtime.pgid and runtime.session_id == runtime.pgid:
                for process in members:
                    try:
                        if os.getsid(process.pid) == runtime.session_id:
                            owned_pids.add(process.pid)
                    except OSError:
                        continue
            with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                owned_pids.update(
                    child.pid for child in root.children(recursive=True) if child.pid in by_pid
                )

        for process in members:
            try:
                marker = process.environ().get(RUN_PROVENANCE_ENV)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
            if marker and secret_digest(marker) == expected_token:
                owned_pids.add(process.pid)
        return tuple(process for process in members if process.pid in owned_pids)


class SimctlLifecycle:
    """macOS simulator adapter; no device is shut down unless Gatehold booted it."""

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds

    def is_booted(self, udid: str) -> bool:
        result = self._run("list", "devices", "--json")
        try:
            payload: object = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("simulator state could not be read") from error
        if not isinstance(payload, dict):
            raise RuntimeError("simulator state could not be read")
        payload_map = cast(dict[str, object], payload)
        devices = payload_map.get("devices")
        if not isinstance(devices, dict):
            raise RuntimeError("simulator state could not be read")
        devices_map = cast(dict[str, object], devices)
        for values in devices_map.values():
            if not isinstance(values, list):
                continue
            for device in cast(list[object], values):
                if (
                    isinstance(device, dict)
                    and cast(dict[str, object], device).get("udid") == udid
                    and cast(dict[str, object], device).get("state") == "Booted"
                ):
                    return True
        return False

    def boot(self, udid: str) -> None:
        result = self._run("boot", udid)
        if result.returncode != 0:
            raise RuntimeError("allocated simulator could not be booted")

    def shutdown(self, udid: str) -> None:
        result = self._run("shutdown", udid)
        if result.returncode != 0:
            raise RuntimeError("owned simulator could not be shut down")

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        xcrun = shutil.which("xcrun")
        if xcrun is None:
            raise RuntimeError("xcrun is unavailable")
        try:
            return subprocess.run(  # noqa: S603 - fixed trusted executable and argv.
                [xcrun, "simctl", *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=_simctl_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError("simulator command failed") from error


class LoopbackPortLifecycle:
    def is_available(self, port: int) -> bool:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
        finally:
            probe.close()
        return True


class SafeProfileLifecycle:
    """Delete only the exact marked directory Gatehold originally created."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def remove_owned(
        self,
        path: str,
        runtime: StoredRuntimeOwnership,
    ) -> bool:
        candidate = Path(path)
        if candidate.parent != self.root or not candidate.name.startswith("profile-"):
            return False
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            return True
        if stat.S_ISLNK(info.st_mode):
            candidate.unlink()
            return True
        if (
            not stat.S_ISDIR(info.st_mode)
            or runtime.profile_device is None
            or runtime.profile_inode is None
            or runtime.profile_marker_sha256 is None
            or info.st_dev != runtime.profile_device
            or info.st_ino != runtime.profile_inode
        ):
            return False
        marker = candidate / PROFILE_MARKER_NAME
        try:
            marker_info = marker.lstat()
            if stat.S_ISLNK(marker_info.st_mode) or not stat.S_ISREG(marker_info.st_mode):
                return False
            marker_value = marker.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        if secret_digest(marker_value) != runtime.profile_marker_sha256:
            return False
        try:
            _remove_without_following_symlinks(candidate)
        except OSError:
            return False
        return True


class LifecycleManager:
    """Two-phase cleanup: stop owned runtime, then release logical resources."""

    def __init__(
        self,
        config: GateholdConfig,
        store: GateholdStore,
        *,
        process_adapter: ProcessLifecycleAdapter | None = None,
        simulator_adapter: SimulatorLifecycleAdapter | None = None,
        port_adapter: PortLifecycleAdapter | None = None,
        profile_adapter: ProfileLifecycleAdapter | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.process_adapter = process_adapter or PsutilProcessLifecycle()
        self.simulator_adapter = simulator_adapter or SimctlLifecycle()
        self.port_adapter = port_adapter or LoopbackPortLifecycle()
        self.profile_adapter = profile_adapter or SafeProfileLifecycle(config.browser_profiles_dir)

    def prepare_simulator(self, *, lease_id: str, now: float) -> bool:
        with self.store.transaction() as connection:
            lease = self.store.get_lease(connection, lease_id)
            if lease is None or lease.state is not LeaseState.ACTIVE:
                raise RuntimeError("active lease is required")
            udid = lease.resources.simulator
            if udid is None:
                return False
            runtime = self.store.get_runtime_ownership(connection, lease_id)
            if runtime is None:
                raise RuntimeError("runtime ownership record is unavailable")
            if runtime.simulator_udid not in {None, udid}:
                raise RuntimeError("simulator ownership UDID does not match lease")
            if runtime.simulator_state == "external":
                if runtime.simulator_owned:
                    raise RuntimeError("external simulator ownership is inconsistent")
                return False
            if runtime.simulator_state == "owned":
                if (
                    not runtime.simulator_owned
                    or runtime.simulator_boot_intent_at is None
                    or runtime.simulator_owned_at is None
                    or runtime.simulator_udid != udid
                ):
                    raise RuntimeError("owned simulator provenance is incomplete")
                return True
            if runtime.simulator_state == "boot_intent":
                raise RuntimeError("simulator boot ownership is unresolved")
            if runtime.simulator_state == "cleaned":
                raise RuntimeError("simulator lifecycle is already cleaned")
            if runtime.simulator_state != "none" or runtime.terminal_state is not None:
                raise RuntimeError("simulator lifecycle is unavailable")
            request_id = lease.request_id

        if self.simulator_adapter.is_booted(udid):
            with self.store.transaction() as connection:
                runtime = self.store.get_runtime_ownership(connection, lease_id)
                if runtime is None or runtime.terminal_state is not None:
                    raise RuntimeError("simulator lease changed during inspection")
                if not self.store.set_simulator_external(
                    connection,
                    lease_id=lease_id,
                    udid=udid,
                    now=now,
                ):
                    raise RuntimeError("simulator ownership changed during inspection")
                self.store.insert_event(
                    connection,
                    kind="runtime.simulator_external",
                    occurred_at=now,
                    request_id=request_id,
                    lease_id=lease_id,
                    detail={"owned": False, "state": "prebooted"},
                )
            return False

        with self.store.transaction() as connection:
            runtime = self.store.get_runtime_ownership(connection, lease_id)
            if runtime is None or runtime.terminal_state is not None:
                raise RuntimeError("simulator lease changed before boot")
            if not self.store.begin_simulator_boot(
                connection,
                lease_id=lease_id,
                udid=udid,
                now=now,
            ):
                raise RuntimeError("simulator ownership changed before boot")
            self.store.insert_event(
                connection,
                kind="runtime.simulator_boot_intent",
                occurred_at=now,
                request_id=request_id,
                lease_id=lease_id,
                detail={"owned": False, "state": "boot_intent"},
            )

        try:
            self.simulator_adapter.boot(udid)
            boot_confirmed = self.simulator_adapter.is_booted(udid)
        except Exception:
            self._record_simulator_boot_ambiguous(
                lease_id=lease_id,
                request_id=request_id,
                now=now,
            )
            raise RuntimeError("simulator boot ownership is unresolved") from None
        if not boot_confirmed:
            self._record_simulator_boot_ambiguous(
                lease_id=lease_id,
                request_id=request_id,
                now=now,
            )
            raise RuntimeError("simulator boot ownership is unresolved")

        with self.store.transaction() as connection:
            if not self.store.confirm_simulator_owned(
                connection,
                lease_id=lease_id,
                udid=udid,
                now=now,
            ):
                raise RuntimeError("simulator ownership confirmation was rejected")
            self.store.insert_event(
                connection,
                kind="runtime.simulator_owned",
                occurred_at=now,
                request_id=request_id,
                lease_id=lease_id,
                detail={"owned": True, "state": "owned"},
            )
        return True

    def _record_simulator_boot_ambiguous(
        self,
        *,
        lease_id: str,
        request_id: str,
        now: float,
    ) -> None:
        with self.store.transaction() as connection:
            runtime = self.store.get_runtime_ownership(connection, lease_id)
            if runtime is None or runtime.simulator_state != "boot_intent":
                return
            self.store.insert_event(
                connection,
                kind="runtime.simulator_boot_ambiguous",
                occurred_at=now,
                request_id=request_id,
                lease_id=lease_id,
                detail={"owned": False, "state": "boot_intent"},
            )

    def register_process(
        self,
        *,
        lease_id: str,
        pid: int,
        run_token: str,
        now: float,
    ) -> None:
        identity = self.process_adapter.capture(pid)
        if identity is None:
            raise RuntimeError("managed process identity could not be captured")
        if identity.pid != pid or identity.pgid != pid or identity.session_id != pid:
            raise RuntimeError("managed process did not create a private process group")
        with self.store.transaction() as connection:
            lease = self.store.get_lease(connection, lease_id)
            if lease is None or lease.state is not LeaseState.ACTIVE:
                raise RuntimeError("active lease is required")
            self.store.register_runtime_process(
                connection,
                lease_id=lease_id,
                pid=pid,
                pgid=identity.pgid,
                session_id=identity.session_id,
                process_create_time=identity.create_time,
                boot_time=identity.boot_time,
                run_token_sha256=secret_digest(run_token),
                now=now,
            )
            self.store.insert_event(
                connection,
                kind="runtime.registered",
                occurred_at=now,
                request_id=lease.request_id,
                lease_id=lease_id,
                detail={
                    "provenance": "managed_run",
                    "private_process_group": True,
                },
            )

    def cleanup(
        self,
        *,
        lease_id: str,
        reason: str,
        now: float,
        child_exit_code: int | None = None,
    ) -> RuntimeCleanupResult:
        with self.store.transaction() as connection:
            existing = self.store.get_runtime_ownership(connection, lease_id)
            lease = self.store.get_lease(connection, lease_id)
            if existing is None or lease is None:
                return RuntimeCleanupResult(
                    lease_id=lease_id,
                    complete=True,
                    process=ProcessCleanupResult(complete=True),
                    simulator_shutdown=False,
                    resources_finalized=False,
                )
            if existing.state == "cleaned":
                finalized = self.store.finalize_runtime_resources(
                    connection,
                    lease_id=lease_id,
                    now=now,
                )
                return RuntimeCleanupResult(
                    lease_id=lease_id,
                    complete=True,
                    process=ProcessCleanupResult(complete=True),
                    simulator_shutdown=False,
                    resources_finalized=finalized or existing.resources_finalized,
                )
            cleanup_claim_token = new_secret()
            claimed = self.store.claim_runtime_cleanup(
                connection,
                lease_id=lease_id,
                now=now,
                retry_after_seconds=DEFAULT_CLEANUP_RETRY_SECONDS,
                claim_token=cleanup_claim_token,
            )
            if claimed is None:
                return RuntimeCleanupResult(
                    lease_id=lease_id,
                    complete=False,
                    process=ProcessCleanupResult(complete=False),
                    simulator_shutdown=False,
                    resources_finalized=False,
                )
            simulator_udid = lease.resources.simulator

        try:
            process_result = self.process_adapter.cleanup(claimed)
        except Exception:
            process_result = ProcessCleanupResult(complete=False)

        (
            simulator_complete,
            simulator_shutdown,
            simulator_state,
        ) = self._cleanup_simulator(
            runtime=claimed,
            simulator_udid=simulator_udid,
            request_id=lease.request_id,
            now=now,
        )

        profile_complete = True
        if (
            process_result.complete
            and claimed.browser_profile_owned
            and lease.resources.browser_profile is not None
        ):
            profile_complete = self.profile_adapter.remove_owned(
                lease.resources.browser_profile,
                claimed,
            )

        port_complete = True
        if process_result.complete and lease.resources.port is not None:
            port_complete = self.port_adapter.is_available(lease.resources.port)

        result_file_complete = (
            _remove_runtime_result(self.config.runtime_results_dir, lease_id)
            if process_result.complete
            else False
        )
        complete = (
            process_result.complete
            and simulator_complete
            and profile_complete
            and port_complete
            and result_file_complete
        )
        with self.store.transaction() as connection:
            claimed_finish = self.store.finish_runtime_cleanup(
                connection,
                lease_id=lease_id,
                complete=complete,
                now=now,
                claim_token=cleanup_claim_token,
            )
            if not claimed_finish:
                return RuntimeCleanupResult(
                    lease_id=lease_id,
                    complete=False,
                    process=process_result,
                    simulator_shutdown=simulator_shutdown,
                    resources_finalized=False,
                )
            finalized = (
                self.store.finalize_runtime_resources(
                    connection,
                    lease_id=lease_id,
                    now=now,
                )
                if complete
                else False
            )
            self.store.insert_event(
                connection,
                kind="runtime.cleanup",
                occurred_at=now,
                request_id=lease.request_id,
                lease_id=lease_id,
                detail={
                    "reason": reason[:40],
                    "result": "cleaned" if complete else "partial",
                    "child_exit_code": child_exit_code,
                    "terminated": process_result.terminated,
                    "killed": process_result.killed,
                    "skipped_unowned": process_result.skipped_unowned,
                    "simulator_shutdown": simulator_shutdown,
                    "simulator_state": simulator_state,
                    "profile_removed": profile_complete,
                    "port_available": port_complete,
                    "resources_finalized": finalized,
                },
            )
        return RuntimeCleanupResult(
            lease_id=lease_id,
            complete=complete,
            process=process_result,
            simulator_shutdown=simulator_shutdown,
            resources_finalized=finalized,
        )

    def _cleanup_simulator(
        self,
        *,
        runtime: StoredRuntimeOwnership,
        simulator_udid: str | None,
        request_id: str,
        now: float,
    ) -> tuple[bool, bool, str]:
        state = runtime.simulator_state
        if state == "none":
            return (not runtime.simulator_owned, False, state)
        if state in {"external", "cleaned"}:
            valid = (
                not runtime.simulator_owned
                and simulator_udid is not None
                and runtime.simulator_udid == simulator_udid
            )
            return (valid, False, state)
        if state == "boot_intent":
            # Boot may have happened, but ownership was never positively confirmed.
            # Never guess by inspecting current state or issuing shutdown.
            return (False, False, state)
        if (
            state != "owned"
            or not runtime.simulator_owned
            or simulator_udid is None
            or runtime.simulator_udid != simulator_udid
            or runtime.simulator_boot_intent_at is None
            or runtime.simulator_owned_at is None
        ):
            return (False, False, state)

        shutdown = False
        try:
            if self.simulator_adapter.is_booted(simulator_udid):
                self.simulator_adapter.shutdown(simulator_udid)
                shutdown = True
                if self.simulator_adapter.is_booted(simulator_udid):
                    return (False, shutdown, state)
        except Exception:
            return (False, shutdown, state)

        with self.store.transaction() as connection:
            if not self.store.mark_simulator_cleaned(
                connection,
                lease_id=runtime.lease_id,
                udid=simulator_udid,
                now=now,
            ):
                return (False, shutdown, state)
            self.store.insert_event(
                connection,
                kind="runtime.simulator_cleaned",
                occurred_at=now,
                request_id=request_id,
                lease_id=runtime.lease_id,
                detail={"owned": False, "state": "cleaned", "shutdown": shutdown},
            )
        return (True, shutdown, "cleaned")

    def cleanup_pending(self, *, reason: str, now: float) -> int:
        with self.store.reader() as connection:
            lease_ids = self.store.pending_runtime_cleanup_ids(connection)
        completed = 0
        for lease_id in lease_ids:
            result = self.cleanup(lease_id=lease_id, reason=reason, now=now)
            completed += int(result.complete)
        return completed


def _simctl_environment() -> dict[str, str]:
    allowed = ("PATH", "HOME", "TMPDIR", "DEVELOPER_DIR")
    return {name: os.environ[name] for name in allowed if name in os.environ}


def _remove_without_following_symlinks(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        path.unlink()
        return
    for child in path.iterdir():
        _remove_without_following_symlinks(child)
    path.rmdir()


def _remove_runtime_result(root: Path, lease_id: str) -> bool:
    path = root / f"{lease_id}.exit"
    try:
        info = path.lstat()
    except FileNotFoundError:
        return True
    if stat.S_ISLNK(info.st_mode) or stat.S_ISREG(info.st_mode):
        try:
            path.unlink()
        except OSError:
            return False
        return True
    return False
