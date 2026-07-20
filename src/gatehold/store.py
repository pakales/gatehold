"""SQLite WAL persistence for leases, FIFO requests, resources, and events."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .config import GateholdConfig
from .models import (
    EventDetail,
    GateholdEvent,
    LeaseState,
    Receipt,
    RequestState,
    ResourceAllocation,
    ResourceRequest,
    SemanticAssessment,
    WorkloadClass,
)

SCHEMA_VERSION = 3
STATE_MARKER_NAME = ".gatehold-state"
STATE_MARKER_CONTENT = b"gatehold-state-v1\n"


@dataclass(frozen=True, slots=True)
class StoredRequest:
    queue_seq: int
    request_id: str
    owner_id: str
    workstream: str
    workstream_key: str
    scopes: tuple[str, ...]
    scope_sha256: str
    workload: WorkloadClass
    ttl_seconds: int
    resources: ResourceRequest
    status: RequestState
    queue_token_sha256: str
    executable_name: str | None
    created_at: float
    updated_at: float
    queue_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoredLease:
    lease_id: str
    request_id: str
    owner_id: str
    workstream: str
    workstream_key: str
    scopes: tuple[str, ...]
    scope_sha256: str
    workload: WorkloadClass
    ttl_seconds: int
    heartbeat_token_sha256: str
    state: LeaseState
    resources: ResourceAllocation
    executable_name: str | None
    created_at: float
    heartbeat_at: float
    expires_at: float


@dataclass(frozen=True, slots=True)
class StoredRuntimeOwnership:
    lease_id: str
    provenance: str
    pid: int | None
    pgid: int | None
    session_id: int | None
    process_create_time: float | None
    boot_time: float | None
    run_token_sha256: str | None
    browser_profile_owned: bool
    profile_device: int | None
    profile_inode: int | None
    profile_marker_sha256: str | None
    simulator_owned: bool
    simulator_state: str
    simulator_udid: str | None
    simulator_boot_intent_at: float | None
    simulator_owned_at: float | None
    simulator_cleaned_at: float | None
    port_process_owned: bool
    state: str
    terminal_state: str | None
    resources_finalized: bool
    registered_at: float
    updated_at: float
    cleanup_started_at: float | None
    cleanup_claim_token: str | None
    cleanup_attempts: int


def _owned_by_current_user(info: os.stat_result) -> bool:
    get_effective_user_id = getattr(os, "geteuid", None)
    return get_effective_user_id is None or info.st_uid == get_effective_user_id()


def _private_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        path.mkdir(parents=True, exist_ok=False, mode=0o700)
        info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError(f"state path must be a real directory: {path}")
    if not _owned_by_current_user(info):
        raise RuntimeError(f"state path must be owned by the current user: {path}")
    path.chmod(0o700)


def _private_file(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"state file must be a regular file: {path}")
    if not _owned_by_current_user(info):
        raise RuntimeError(f"state file must be owned by the current user: {path}")
    path.chmod(0o600)


def _write_state_marker(path: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        written = os.write(descriptor, STATE_MARKER_CONTENT)
        if written != len(STATE_MARKER_CONTENT):
            raise RuntimeError(f"could not write complete state marker: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _valid_state_marker(path: Path) -> bool:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise RuntimeError(f"state marker must be a regular private file: {path}") from error
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or not _owned_by_current_user(info)
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise RuntimeError(f"state marker must be a regular private file: {path}")
        content = os.read(descriptor, len(STATE_MARKER_CONTENT) + 1)
    finally:
        os.close(descriptor)
    if content != STATE_MARKER_CONTENT:
        raise RuntimeError(f"state marker is not recognized: {path}")
    return True


def _legacy_gatehold_database(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"state file must be a regular file: {path}")
    if not _owned_by_current_user(info) or stat.S_IMODE(info.st_mode) != 0o600:
        return False

    required_columns = {
        "leases": {
            "lease_id",
            "request_id",
            "owner_id",
            "workstream",
            "scope_sha256",
            "workload",
            "heartbeat_token_sha256",
            "state",
            "resources_json",
        },
        "runtime_ownership": {
            "lease_id",
            "provenance",
            "browser_profile_owned",
            "simulator_owned",
            "state",
            "resources_finalized",
        },
    }
    uri = f"{path.absolute().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if not required_columns.keys() <= tables:
                return False
            for table, expected_columns in required_columns.items():
                columns = {
                    str(row[1])
                    for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                }
                if not expected_columns <= columns:
                    return False
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return True


def _prepare_state_directory(path: Path, database_path: Path) -> None:
    created = False
    try:
        info = path.lstat()
    except FileNotFoundError:
        path.mkdir(parents=True, exist_ok=False, mode=0o700)
        path.chmod(0o700)
        info = path.lstat()
        created = True

    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError(f"state path must be a real directory: {path}")
    if not _owned_by_current_user(info):
        raise RuntimeError(f"state path must be owned by the current user: {path}")

    mode = stat.S_IMODE(info.st_mode)
    if mode != 0o700:
        raise RuntimeError(
            f"refusing to adopt existing state directory without mode 0o700: {path}"
        )

    marker_path = path / STATE_MARKER_NAME
    if _valid_state_marker(marker_path):
        return
    empty_private_directory = not any(path.iterdir())
    if (
        not created
        and not empty_private_directory
        and not _legacy_gatehold_database(database_path)
    ):
        raise RuntimeError(f"refusing to adopt unrecognized state directory: {path}")
    _write_state_marker(marker_path)


def _utc_from_timestamp(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


class GateholdStore:
    """Small explicit SQLite store with process-safe immediate transactions."""

    def __init__(self, config: GateholdConfig) -> None:
        self.config = config

    def initialize(self) -> None:
        _prepare_state_directory(
            self.config.state_dir,
            self.config.database_path,
        )
        _private_directory(self.config.browser_profiles_dir)
        _private_directory(self.config.runtime_results_dir)
        if os.path.lexists(self.config.database_path):
            _private_file(self.config.database_path)
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS requests (
                    queue_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL UNIQUE,
                    owner_id TEXT NOT NULL,
                    workstream TEXT NOT NULL,
                    workstream_key TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    scope_sha256 TEXT NOT NULL,
                    workload TEXT NOT NULL CHECK (workload IN ('light', 'heavy')),
                    ttl_seconds INTEGER NOT NULL CHECK (ttl_seconds >= 15),
                    resources_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    queue_token_sha256 TEXT NOT NULL,
                    executable_name TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    queue_reasons_json TEXT NOT NULL DEFAULT '[]'
                );

                CREATE INDEX IF NOT EXISTS requests_status_queue_idx
                    ON requests(status, workload, queue_seq);

                CREATE TABLE IF NOT EXISTS leases (
                    lease_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id),
                    owner_id TEXT NOT NULL,
                    workstream TEXT NOT NULL,
                    workstream_key TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    scope_sha256 TEXT NOT NULL,
                    workload TEXT NOT NULL CHECK (workload IN ('light', 'heavy')),
                    ttl_seconds INTEGER NOT NULL CHECK (ttl_seconds >= 15),
                    heartbeat_token_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('active', 'released', 'expired')),
                    resources_json TEXT NOT NULL,
                    executable_name TEXT,
                    created_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS leases_active_expiry_idx
                    ON leases(state, expires_at);

                CREATE INDEX IF NOT EXISTS leases_workstream_idx
                    ON leases(state, workstream_key);

                CREATE TABLE IF NOT EXISTS allocations (
                    resource_type TEXT NOT NULL,
                    resource_key TEXT NOT NULL,
                    lease_id TEXT NOT NULL REFERENCES leases(lease_id),
                    PRIMARY KEY(resource_type, resource_key),
                    UNIQUE(resource_type, lease_id)
                );

                CREATE TABLE IF NOT EXISTS receipts (
                    receipt_id TEXT PRIMARY KEY,
                    generated_at REAL NOT NULL,
                    receipt_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS receipts_generated_idx
                    ON receipts(generated_at DESC);

                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    request_id TEXT,
                    lease_id TEXT,
                    detail_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS semantic_cache (
                    request_id TEXT PRIMARY KEY REFERENCES requests(request_id),
                    active_set_sha256 TEXT NOT NULL,
                    assessment_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile_cleanup (
                    profile_path TEXT PRIMARY KEY,
                    enqueued_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runtime_ownership (
                    lease_id TEXT PRIMARY KEY REFERENCES leases(lease_id),
                    provenance TEXT NOT NULL,
                    pid INTEGER,
                    pgid INTEGER,
                    session_id INTEGER,
                    process_create_time REAL,
                    boot_time REAL,
                    run_token_sha256 TEXT,
                    browser_profile_owned INTEGER NOT NULL CHECK (
                        browser_profile_owned IN (0, 1)
                    ),
                    profile_device INTEGER,
                    profile_inode INTEGER,
                    profile_marker_sha256 TEXT,
                    simulator_owned INTEGER NOT NULL DEFAULT 0 CHECK (
                        simulator_owned IN (0, 1)
                    ),
                    simulator_state TEXT NOT NULL DEFAULT 'none' CHECK (
                        simulator_state IN (
                            'none', 'external', 'boot_intent', 'owned', 'cleaned'
                        )
                    ),
                    simulator_udid TEXT,
                    simulator_boot_intent_at REAL,
                    simulator_owned_at REAL,
                    simulator_cleaned_at REAL,
                    port_process_owned INTEGER NOT NULL DEFAULT 0 CHECK (
                        port_process_owned IN (0, 1)
                    ),
                    state TEXT NOT NULL CHECK (
                        state IN ('active', 'cleaning', 'cleaned', 'partial')
                    ),
                    terminal_state TEXT CHECK (
                        terminal_state IS NULL
                        OR terminal_state IN ('released', 'expired')
                    ),
                    resources_finalized INTEGER NOT NULL DEFAULT 0 CHECK (
                        resources_finalized IN (0, 1)
                    ),
                    registered_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    cleanup_started_at REAL,
                    cleanup_claim_token TEXT,
                    cleanup_attempts INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS runtime_cleanup_idx
                    ON runtime_ownership(state, resources_finalized, updated_at);
                """
            )
            self._migrate_runtime_ownership_v3(connection)
            connection.execute(
                """
                INSERT OR IGNORE INTO runtime_ownership(
                    lease_id, provenance, browser_profile_owned,
                    simulator_owned, port_process_owned, state,
                    resources_finalized, registered_at, updated_at,
                    cleanup_attempts
                )
                SELECT
                    lease_id, 'legacy_unverified', 0, 0, 0, 'active', 0,
                    created_at, created_at, 0
                FROM leases
                """
            )
            connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )
        finally:
            connection.close()
        _private_file(self.config.database_path)

    def _migrate_runtime_ownership_v3(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(runtime_ownership)").fetchall()
        }
        if "simulator_state" not in columns:
            connection.execute(
                """
                ALTER TABLE runtime_ownership
                ADD COLUMN simulator_state TEXT NOT NULL DEFAULT 'none'
                CHECK (
                    simulator_state IN (
                        'none', 'external', 'boot_intent', 'owned', 'cleaned'
                    )
                )
                """
            )
        if "simulator_udid" not in columns:
            connection.execute("ALTER TABLE runtime_ownership ADD COLUMN simulator_udid TEXT")
        if "simulator_boot_intent_at" not in columns:
            connection.execute(
                """
                ALTER TABLE runtime_ownership
                ADD COLUMN simulator_boot_intent_at REAL
                """
            )
        if "simulator_owned_at" not in columns:
            connection.execute("ALTER TABLE runtime_ownership ADD COLUMN simulator_owned_at REAL")
        if "simulator_cleaned_at" not in columns:
            connection.execute("ALTER TABLE runtime_ownership ADD COLUMN simulator_cleaned_at REAL")
        # A legacy boolean alone cannot prove boot ownership. Quarantine it as
        # an unresolved intent instead of guessing that shutdown is authorized.
        connection.execute(
            """
            UPDATE runtime_ownership
            SET simulator_state = 'boot_intent',
                simulator_owned = 0,
                simulator_udid = (
                    SELECT json_extract(leases.resources_json, '$.simulator')
                    FROM leases
                    WHERE leases.lease_id = runtime_ownership.lease_id
                )
            WHERE simulator_owned = 1 AND simulator_state = 'none'
            """
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.config.database_path,
            timeout=10,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def reader(self) -> Generator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def journal_mode(self) -> str:
        with self.reader() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
        if row is None:
            raise RuntimeError("SQLite did not return a journal mode")
        return str(row[0]).casefold()

    def enqueue(
        self,
        connection: sqlite3.Connection,
        *,
        request_id: str,
        owner_id: str,
        workstream: str,
        workstream_key: str,
        scopes: tuple[str, ...],
        scope_sha256: str,
        workload: WorkloadClass,
        ttl_seconds: int,
        resources: ResourceRequest,
        queue_token_sha256: str,
        executable_name: str | None,
        now: float,
    ) -> StoredRequest:
        connection.execute(
            """
            INSERT INTO requests(
                request_id, owner_id, workstream, workstream_key, scopes_json,
                scope_sha256, workload, ttl_seconds, resources_json, status,
                queue_token_sha256, executable_name, created_at, updated_at,
                queue_reasons_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]')
            """,
            (
                request_id,
                owner_id,
                workstream,
                workstream_key,
                json.dumps(scopes, separators=(",", ":"), ensure_ascii=False),
                scope_sha256,
                workload.value,
                ttl_seconds,
                resources.model_dump_json(),
                RequestState.QUEUED.value,
                queue_token_sha256,
                executable_name,
                now,
                now,
            ),
        )
        stored = self.get_request(connection, request_id)
        if stored is None:
            raise RuntimeError("enqueued request could not be read")
        return stored

    def get_request(self, connection: sqlite3.Connection, request_id: str) -> StoredRequest | None:
        row = connection.execute(
            "SELECT * FROM requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        return self._request_from_row(row) if row is not None else None

    def set_request_state(
        self,
        connection: sqlite3.Connection,
        *,
        request_id: str,
        state: RequestState,
        now: float,
        queue_reasons: tuple[str, ...] = (),
    ) -> None:
        connection.execute(
            """
            UPDATE requests
            SET status = ?, updated_at = ?, queue_reasons_json = ?
            WHERE request_id = ?
            """,
            (
                state.value,
                now,
                json.dumps(queue_reasons, separators=(",", ":")),
                request_id,
            ),
        )

    def touch_queued_request(
        self,
        connection: sqlite3.Connection,
        *,
        request_id: str,
        now: float,
    ) -> None:
        connection.execute(
            """
            UPDATE requests
            SET updated_at = ?
            WHERE request_id = ? AND status = ?
            """,
            (now, request_id, RequestState.QUEUED.value),
        )

    def expire_queued_requests(
        self,
        connection: sqlite3.Connection,
        *,
        now: float,
        stale_after_seconds: int,
    ) -> tuple[StoredRequest, ...]:
        cutoff = now - stale_after_seconds
        rows = connection.execute(
            """
            SELECT * FROM requests
            WHERE status = ? AND updated_at <= ?
            ORDER BY queue_seq
            """,
            (RequestState.QUEUED.value, cutoff),
        ).fetchall()
        expired = tuple(self._request_from_row(row) for row in rows)
        for request in expired:
            self.set_request_state(
                connection,
                request_id=request.request_id,
                state=RequestState.EXPIRED,
                now=now,
            )
            self.insert_event(
                connection,
                kind="request.expired",
                occurred_at=now,
                request_id=request.request_id,
                detail={"workload": request.workload.value},
            )
        return expired

    def active_leases(
        self, connection: sqlite3.Connection, *, now: float
    ) -> tuple[StoredLease, ...]:
        rows = connection.execute(
            """
            SELECT leases.* FROM leases
            JOIN runtime_ownership USING(lease_id)
            WHERE leases.state = ?
              AND (
                    leases.expires_at > ?
                    OR runtime_ownership.terminal_state IS NOT NULL
              )
            ORDER BY leases.created_at, leases.lease_id
            """,
            (LeaseState.ACTIVE.value, now),
        ).fetchall()
        return tuple(self._lease_from_row(row) for row in rows)

    def get_lease(self, connection: sqlite3.Connection, lease_id: str) -> StoredLease | None:
        row = connection.execute("SELECT * FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
        return self._lease_from_row(row) if row is not None else None

    def active_heavy_count(self, connection: sqlite3.Connection, *, now: float) -> int:
        row = connection.execute(
            """
            SELECT COUNT(*) FROM leases
            JOIN runtime_ownership USING(lease_id)
            WHERE leases.state = ? AND leases.workload = ?
              AND (
                    leases.expires_at > ?
                    OR runtime_ownership.terminal_state IS NOT NULL
              )
            """,
            (LeaseState.ACTIVE.value, WorkloadClass.HEAVY.value, now),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def first_queued_heavy(self, connection: sqlite3.Connection) -> str | None:
        row = connection.execute(
            """
            SELECT request_id FROM requests
            WHERE status = ? AND workload = ?
            ORDER BY queue_seq
            LIMIT 1
            """,
            (RequestState.QUEUED.value, WorkloadClass.HEAVY.value),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def earlier_queued_requests(
        self,
        connection: sqlite3.Connection,
        *,
        queue_seq: int,
    ) -> tuple[StoredRequest, ...]:
        rows = connection.execute(
            """
            SELECT * FROM requests
            WHERE status = ? AND queue_seq < ?
            ORDER BY queue_seq
            """,
            (RequestState.QUEUED.value, queue_seq),
        ).fetchall()
        return tuple(self._request_from_row(row) for row in rows)

    def queue_position(self, connection: sqlite3.Connection, request_id: str) -> int:
        row = connection.execute(
            """
            SELECT COUNT(*) + 1
            FROM requests
            WHERE status = ?
              AND queue_seq < (SELECT queue_seq FROM requests WHERE request_id = ?)
            """,
            (RequestState.QUEUED.value, request_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("could not calculate queue position")
        return int(row[0])

    def allocation_keys(self, connection: sqlite3.Connection, resource_type: str) -> set[str]:
        rows = connection.execute(
            "SELECT resource_key FROM allocations WHERE resource_type = ?",
            (resource_type,),
        ).fetchall()
        return {str(row[0]) for row in rows}

    def create_lease(
        self,
        connection: sqlite3.Connection,
        *,
        lease_id: str,
        request: StoredRequest,
        heartbeat_token_sha256: str,
        resources: ResourceAllocation,
        profile_device: int | None,
        profile_inode: int | None,
        profile_marker_sha256: str | None,
        now: float,
        expires_at: float,
    ) -> StoredLease:
        connection.execute(
            """
            INSERT INTO leases(
                lease_id, request_id, owner_id, workstream, workstream_key,
                scopes_json, scope_sha256, workload, ttl_seconds,
                heartbeat_token_sha256, state, resources_json, executable_name,
                created_at, heartbeat_at, expires_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lease_id,
                request.request_id,
                request.owner_id,
                request.workstream,
                request.workstream_key,
                json.dumps(request.scopes, separators=(",", ":"), ensure_ascii=False),
                request.scope_sha256,
                request.workload.value,
                request.ttl_seconds,
                heartbeat_token_sha256,
                LeaseState.ACTIVE.value,
                resources.model_dump_json(),
                request.executable_name,
                now,
                now,
                expires_at,
            ),
        )
        allocations: list[tuple[str, str, str]] = []
        if resources.port is not None:
            allocations.append(("port", str(resources.port), lease_id))
        if resources.browser_profile is not None:
            allocations.append(("browser_profile", resources.browser_profile, lease_id))
        if resources.simulator is not None:
            allocations.append(("simulator", resources.simulator, lease_id))
        connection.executemany(
            """
            INSERT INTO allocations(resource_type, resource_key, lease_id)
            VALUES(?, ?, ?)
            """,
            allocations,
        )
        connection.execute(
            """
            INSERT INTO runtime_ownership(
                lease_id, provenance, browser_profile_owned, profile_device,
                profile_inode, profile_marker_sha256, simulator_owned,
                port_process_owned, state, resources_finalized, registered_at,
                updated_at, cleanup_attempts
            ) VALUES(?, 'allocation', ?, ?, ?, ?, 0, 0, 'active', 0, ?, ?, 0)
            """,
            (
                lease_id,
                int(resources.browser_profile is not None),
                profile_device,
                profile_inode,
                profile_marker_sha256,
                now,
                now,
            ),
        )
        self.set_request_state(
            connection,
            request_id=request.request_id,
            state=RequestState.ADMITTED,
            now=now,
        )
        stored = self.get_lease(connection, lease_id)
        if stored is None:
            raise RuntimeError("created lease could not be read")
        return stored

    def extend_lease(
        self,
        connection: sqlite3.Connection,
        *,
        lease_id: str,
        heartbeat_at: float,
        expires_at: float,
    ) -> None:
        connection.execute(
            """
            UPDATE leases
            SET heartbeat_at = ?, expires_at = ?
            WHERE lease_id = ? AND state = ?
            """,
            (heartbeat_at, expires_at, lease_id, LeaseState.ACTIVE.value),
        )

    def release_lease(
        self,
        connection: sqlite3.Connection,
        *,
        lease: StoredLease,
        state: LeaseState,
        now: float,
    ) -> None:
        if state not in {LeaseState.RELEASED, LeaseState.EXPIRED}:
            raise ValueError("release state must be released or expired")
        runtime = self.get_runtime_ownership(connection, lease.lease_id)
        if runtime is None:
            raise RuntimeError("runtime ownership record is unavailable")
        if runtime.terminal_state is not None and runtime.terminal_state != state.value:
            raise RuntimeError("lease cleanup terminal state is already fixed")
        connection.execute(
            """
            UPDATE runtime_ownership
            SET terminal_state = COALESCE(terminal_state, ?), updated_at = ?
            WHERE lease_id = ?
            """,
            (state.value, now, lease.lease_id),
        )
        connection.execute(
            "UPDATE leases SET expires_at = ? WHERE lease_id = ?",
            (min(now, lease.expires_at), lease.lease_id),
        )

    def expire_leases(
        self, connection: sqlite3.Connection, *, now: float
    ) -> tuple[StoredLease, ...]:
        rows = connection.execute(
            """
            SELECT leases.* FROM leases
            JOIN runtime_ownership USING(lease_id)
            WHERE leases.state = ? AND leases.expires_at <= ?
              AND runtime_ownership.terminal_state IS NULL
            ORDER BY leases.expires_at, leases.lease_id
            """,
            (LeaseState.ACTIVE.value, now),
        ).fetchall()
        expired = tuple(self._lease_from_row(row) for row in rows)
        for lease in expired:
            self.release_lease(
                connection,
                lease=lease,
                state=LeaseState.EXPIRED,
                now=now,
            )
            self.insert_event(
                connection,
                kind="lease.expired",
                occurred_at=now,
                request_id=lease.request_id,
                lease_id=lease.lease_id,
                detail={"workload": lease.workload.value},
            )
        return expired

    def get_runtime_ownership(
        self,
        connection: sqlite3.Connection,
        lease_id: str,
    ) -> StoredRuntimeOwnership | None:
        row = connection.execute(
            "SELECT * FROM runtime_ownership WHERE lease_id = ?",
            (lease_id,),
        ).fetchone()
        return self._runtime_from_row(row) if row is not None else None

    def register_runtime_process(
        self,
        connection: sqlite3.Connection,
        *,
        lease_id: str,
        pid: int,
        pgid: int,
        session_id: int,
        process_create_time: float | None,
        boot_time: float,
        run_token_sha256: str,
        now: float,
    ) -> None:
        row = connection.execute(
            """
            UPDATE runtime_ownership
            SET provenance = 'managed_run', pid = ?, pgid = ?, session_id = ?,
                process_create_time = ?, boot_time = ?, run_token_sha256 = ?,
                port_process_owned = (
                    SELECT CASE
                        WHEN json_extract(resources_json, '$.port') IS NULL THEN 0
                        ELSE 1
                    END
                    FROM leases WHERE leases.lease_id = runtime_ownership.lease_id
                ),
                state = 'active', updated_at = ?
            WHERE lease_id = ?
            RETURNING lease_id
            """,
            (
                pid,
                pgid,
                session_id,
                process_create_time,
                boot_time,
                run_token_sha256,
                now,
                lease_id,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("runtime ownership record is unavailable")

    def set_simulator_external(
        self,
        connection: sqlite3.Connection,
        *,
        lease_id: str,
        udid: str,
        now: float,
    ) -> bool:
        row = connection.execute(
            """
            UPDATE runtime_ownership
            SET simulator_owned = 0, simulator_state = 'external',
                simulator_udid = ?, updated_at = ?
            WHERE lease_id = ? AND simulator_state = 'none'
              AND ? = (
                  SELECT json_extract(resources_json, '$.simulator')
                  FROM leases
                  WHERE leases.lease_id = runtime_ownership.lease_id
              )
            RETURNING lease_id
            """,
            (udid, now, lease_id, udid),
        ).fetchone()
        return row is not None

    def begin_simulator_boot(
        self,
        connection: sqlite3.Connection,
        *,
        lease_id: str,
        udid: str,
        now: float,
    ) -> bool:
        row = connection.execute(
            """
            UPDATE runtime_ownership
            SET simulator_owned = 0, simulator_state = 'boot_intent',
                simulator_udid = ?, simulator_boot_intent_at = ?, updated_at = ?
            WHERE lease_id = ? AND simulator_state = 'none'
              AND ? = (
                  SELECT json_extract(resources_json, '$.simulator')
                  FROM leases
                  WHERE leases.lease_id = runtime_ownership.lease_id
              )
            RETURNING lease_id
            """,
            (udid, now, now, lease_id, udid),
        ).fetchone()
        return row is not None

    def confirm_simulator_owned(
        self,
        connection: sqlite3.Connection,
        *,
        lease_id: str,
        udid: str,
        now: float,
    ) -> bool:
        row = connection.execute(
            """
            UPDATE runtime_ownership
            SET simulator_owned = 1, simulator_state = 'owned',
                simulator_owned_at = ?, updated_at = ?
            WHERE lease_id = ? AND simulator_state = 'boot_intent'
              AND simulator_udid = ?
              AND ? = (
                  SELECT json_extract(resources_json, '$.simulator')
                  FROM leases
                  WHERE leases.lease_id = runtime_ownership.lease_id
              )
            RETURNING lease_id
            """,
            (now, now, lease_id, udid, udid),
        ).fetchone()
        return row is not None

    def mark_simulator_cleaned(
        self,
        connection: sqlite3.Connection,
        *,
        lease_id: str,
        udid: str,
        now: float,
    ) -> bool:
        row = connection.execute(
            """
            UPDATE runtime_ownership
            SET simulator_owned = 0, simulator_state = 'cleaned',
                simulator_cleaned_at = ?, updated_at = ?
            WHERE lease_id = ? AND simulator_state = 'owned'
              AND simulator_udid = ?
              AND ? = (
                  SELECT json_extract(resources_json, '$.simulator')
                  FROM leases
                  WHERE leases.lease_id = runtime_ownership.lease_id
              )
            RETURNING lease_id
            """,
            (now, now, lease_id, udid, udid),
        ).fetchone()
        return row is not None

    def claim_runtime_cleanup(
        self,
        connection: sqlite3.Connection,
        *,
        lease_id: str,
        now: float,
        retry_after_seconds: float,
        claim_token: str,
    ) -> StoredRuntimeOwnership | None:
        stale_cleaning_before = now - retry_after_seconds
        row = connection.execute(
            """
            UPDATE runtime_ownership
            SET state = 'cleaning', cleanup_started_at = ?, updated_at = ?,
                cleanup_claim_token = ?, cleanup_attempts = cleanup_attempts + 1
            WHERE lease_id = ?
              AND (
                    state IN ('active', 'partial')
                    OR (state = 'cleaning' AND updated_at <= ?)
              )
            RETURNING *
            """,
            (now, now, claim_token, lease_id, stale_cleaning_before),
        ).fetchone()
        return self._runtime_from_row(row) if row is not None else None

    def finish_runtime_cleanup(
        self,
        connection: sqlite3.Connection,
        *,
        lease_id: str,
        complete: bool,
        now: float,
        claim_token: str,
    ) -> bool:
        cursor = connection.execute(
            """
            UPDATE runtime_ownership
            SET state = ?, updated_at = ?, cleanup_claim_token = NULL
            WHERE lease_id = ? AND cleanup_claim_token = ?
            """,
            ("cleaned" if complete else "partial", now, lease_id, claim_token),
        )
        return cursor.rowcount == 1

    def pending_runtime_cleanup_ids(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            """
            SELECT runtime_ownership.lease_id
            FROM runtime_ownership
            JOIN leases USING(lease_id)
            WHERE leases.state = ?
              AND runtime_ownership.terminal_state IS NOT NULL
              AND (
                  runtime_ownership.state != 'cleaned'
                  OR runtime_ownership.resources_finalized = 0
              )
            ORDER BY runtime_ownership.registered_at, runtime_ownership.lease_id
            """,
            (LeaseState.ACTIVE.value,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def finalize_runtime_resources(
        self,
        connection: sqlite3.Connection,
        *,
        lease_id: str,
        now: float,
    ) -> bool:
        runtime = self.get_runtime_ownership(connection, lease_id)
        lease = self.get_lease(connection, lease_id)
        if (
            runtime is None
            or lease is None
            or runtime.state != "cleaned"
            or runtime.resources_finalized
            or runtime.terminal_state is None
            or lease.state is not LeaseState.ACTIVE
        ):
            return False
        connection.execute("DELETE FROM allocations WHERE lease_id = ?", (lease_id,))
        terminal_state = LeaseState(runtime.terminal_state)
        connection.execute(
            "UPDATE leases SET state = ? WHERE lease_id = ?",
            (terminal_state.value, lease_id),
        )
        request_state = (
            RequestState.RELEASED if terminal_state is LeaseState.RELEASED else RequestState.EXPIRED
        )
        self.set_request_state(
            connection,
            request_id=lease.request_id,
            state=request_state,
            now=now,
        )
        connection.execute(
            """
            UPDATE runtime_ownership
            SET resources_finalized = 1, updated_at = ?
            WHERE lease_id = ?
            """,
            (now, lease_id),
        )
        return True

    def persist_receipt(self, connection: sqlite3.Connection, receipt: Receipt) -> None:
        connection.execute(
            """
            INSERT INTO receipts(receipt_id, generated_at, receipt_json)
            VALUES(?, ?, ?)
            """,
            (
                receipt.receipt_id,
                receipt.generated_at.timestamp(),
                receipt.model_dump_json(),
            ),
        )

    def get_semantic_cache(
        self,
        connection: sqlite3.Connection,
        *,
        request_id: str,
        active_set_sha256: str,
    ) -> SemanticAssessment | None:
        row = connection.execute(
            """
            SELECT assessment_json FROM semantic_cache
            WHERE request_id = ? AND active_set_sha256 = ?
            """,
            (request_id, active_set_sha256),
        ).fetchone()
        if row is None:
            return None
        return SemanticAssessment.model_validate_json(str(row[0]))

    def set_semantic_cache(
        self,
        connection: sqlite3.Connection,
        *,
        request_id: str,
        active_set_sha256: str,
        assessment: SemanticAssessment,
        now: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO semantic_cache(
                request_id, active_set_sha256, assessment_json, updated_at
            ) VALUES(?, ?, ?, ?)
            ON CONFLICT(request_id) DO UPDATE SET
                active_set_sha256=excluded.active_set_sha256,
                assessment_json=excluded.assessment_json,
                updated_at=excluded.updated_at
            """,
            (
                request_id,
                active_set_sha256,
                assessment.model_dump_json(),
                now,
            ),
        )

    def pending_profile_cleanup(self) -> tuple[str, ...]:
        with self.reader() as connection:
            rows = connection.execute(
                "SELECT profile_path FROM profile_cleanup ORDER BY enqueued_at"
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def complete_profile_cleanup(self, profile_path: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM profile_cleanup WHERE profile_path = ?",
                (profile_path,),
            )

    def recent_receipts(self, *, limit: int = 20) -> tuple[Receipt, ...]:
        with self.reader() as connection:
            rows = connection.execute(
                """
                SELECT receipt_json FROM receipts
                ORDER BY generated_at DESC, receipt_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(Receipt.model_validate_json(str(row[0])) for row in rows)

    def insert_event(
        self,
        connection: sqlite3.Connection,
        *,
        kind: str,
        occurred_at: float,
        request_id: str | None = None,
        lease_id: str | None = None,
        detail: EventDetail | None = None,
    ) -> int:
        safe_detail = detail or {}
        if len(safe_detail) > 20:
            raise ValueError("event detail is too large")
        row = connection.execute(
            """
            INSERT INTO events(kind, occurred_at, request_id, lease_id, detail_json)
            VALUES(?, ?, ?, ?, ?)
            RETURNING sequence
            """,
            (
                kind[:80],
                occurred_at,
                request_id,
                lease_id,
                json.dumps(safe_detail, sort_keys=True, separators=(",", ":")),
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("event sequence was not returned")
        return int(row[0])

    def events_after(self, sequence: int, *, limit: int = 100) -> tuple[GateholdEvent, ...]:
        with self.reader() as connection:
            rows = connection.execute(
                """
                SELECT * FROM events
                WHERE sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (sequence, limit),
            ).fetchall()
        return tuple(
            GateholdEvent(
                sequence=int(row["sequence"]),
                kind=str(row["kind"]),
                occurred_at=_utc_from_timestamp(float(row["occurred_at"])),
                request_id=cast(str | None, row["request_id"]),
                lease_id=cast(str | None, row["lease_id"]),
                detail=cast(EventDetail, json.loads(str(row["detail_json"]))),
            )
            for row in rows
        )

    def snapshot_requests(self) -> tuple[StoredRequest, ...]:
        with self.reader() as connection:
            rows = connection.execute(
                """
                SELECT * FROM requests
                WHERE status = ?
                ORDER BY queue_seq
                """,
                (RequestState.QUEUED.value,),
            ).fetchall()
        return tuple(self._request_from_row(row) for row in rows)

    def snapshot_leases(self, *, now: float) -> tuple[StoredLease, ...]:
        with self.reader() as connection:
            return self.active_leases(connection, now=now)

    def _request_from_row(self, row: sqlite3.Row) -> StoredRequest:
        scopes_raw: object = json.loads(str(row["scopes_json"]))
        reasons_raw: object = json.loads(str(row["queue_reasons_json"]))
        if not isinstance(scopes_raw, list):
            raise RuntimeError("invalid persisted request scopes")
        scopes_objects = cast(list[object], scopes_raw)
        if not all(isinstance(value, str) for value in scopes_objects):
            raise RuntimeError("invalid persisted request scopes")
        if not isinstance(reasons_raw, list):
            raise RuntimeError("invalid persisted queue reasons")
        reasons_objects = cast(list[object], reasons_raw)
        if not all(isinstance(value, str) for value in reasons_objects):
            raise RuntimeError("invalid persisted queue reasons")
        scopes_value = cast(list[str], scopes_objects)
        reasons_value = cast(list[str], reasons_objects)
        return StoredRequest(
            queue_seq=int(row["queue_seq"]),
            request_id=str(row["request_id"]),
            owner_id=str(row["owner_id"]),
            workstream=str(row["workstream"]),
            workstream_key=str(row["workstream_key"]),
            scopes=tuple(scopes_value),
            scope_sha256=str(row["scope_sha256"]),
            workload=WorkloadClass(str(row["workload"])),
            ttl_seconds=int(row["ttl_seconds"]),
            resources=ResourceRequest.model_validate_json(str(row["resources_json"])),
            status=RequestState(str(row["status"])),
            queue_token_sha256=str(row["queue_token_sha256"]),
            executable_name=cast(str | None, row["executable_name"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            queue_reasons=tuple(reasons_value),
        )

    def _lease_from_row(self, row: sqlite3.Row) -> StoredLease:
        scopes_raw: object = json.loads(str(row["scopes_json"]))
        if not isinstance(scopes_raw, list):
            raise RuntimeError("invalid persisted lease scopes")
        scopes_objects = cast(list[object], scopes_raw)
        if not all(isinstance(value, str) for value in scopes_objects):
            raise RuntimeError("invalid persisted lease scopes")
        scopes_value = cast(list[str], scopes_objects)
        return StoredLease(
            lease_id=str(row["lease_id"]),
            request_id=str(row["request_id"]),
            owner_id=str(row["owner_id"]),
            workstream=str(row["workstream"]),
            workstream_key=str(row["workstream_key"]),
            scopes=tuple(scopes_value),
            scope_sha256=str(row["scope_sha256"]),
            workload=WorkloadClass(str(row["workload"])),
            ttl_seconds=int(row["ttl_seconds"]),
            heartbeat_token_sha256=str(row["heartbeat_token_sha256"]),
            state=LeaseState(str(row["state"])),
            resources=ResourceAllocation.model_validate_json(str(row["resources_json"])),
            executable_name=cast(str | None, row["executable_name"]),
            created_at=float(row["created_at"]),
            heartbeat_at=float(row["heartbeat_at"]),
            expires_at=float(row["expires_at"]),
        )

    def _runtime_from_row(self, row: sqlite3.Row) -> StoredRuntimeOwnership:
        return StoredRuntimeOwnership(
            lease_id=str(row["lease_id"]),
            provenance=str(row["provenance"]),
            pid=int(row["pid"]) if row["pid"] is not None else None,
            pgid=int(row["pgid"]) if row["pgid"] is not None else None,
            session_id=(int(row["session_id"]) if row["session_id"] is not None else None),
            process_create_time=(
                float(row["process_create_time"])
                if row["process_create_time"] is not None
                else None
            ),
            boot_time=(float(row["boot_time"]) if row["boot_time"] is not None else None),
            run_token_sha256=cast(str | None, row["run_token_sha256"]),
            browser_profile_owned=bool(row["browser_profile_owned"]),
            profile_device=(
                int(row["profile_device"]) if row["profile_device"] is not None else None
            ),
            profile_inode=(int(row["profile_inode"]) if row["profile_inode"] is not None else None),
            profile_marker_sha256=cast(str | None, row["profile_marker_sha256"]),
            simulator_owned=bool(row["simulator_owned"]),
            simulator_state=str(row["simulator_state"]),
            simulator_udid=cast(str | None, row["simulator_udid"]),
            simulator_boot_intent_at=(
                float(row["simulator_boot_intent_at"])
                if row["simulator_boot_intent_at"] is not None
                else None
            ),
            simulator_owned_at=(
                float(row["simulator_owned_at"]) if row["simulator_owned_at"] is not None else None
            ),
            simulator_cleaned_at=(
                float(row["simulator_cleaned_at"])
                if row["simulator_cleaned_at"] is not None
                else None
            ),
            port_process_owned=bool(row["port_process_owned"]),
            state=str(row["state"]),
            terminal_state=cast(str | None, row["terminal_state"]),
            resources_finalized=bool(row["resources_finalized"]),
            registered_at=float(row["registered_at"]),
            updated_at=float(row["updated_at"]),
            cleanup_started_at=(
                float(row["cleanup_started_at"]) if row["cleanup_started_at"] is not None else None
            ),
            cleanup_claim_token=cast(str | None, row["cleanup_claim_token"]),
            cleanup_attempts=int(row["cleanup_attempts"]),
        )


def secure_state_permissions(config: GateholdConfig) -> dict[str, str]:
    """Return safe permission metadata for diagnostics without secret values."""

    result: dict[str, str] = {}
    for label, path in {
        "state_dir": config.state_dir,
        "database": config.database_path,
        "profiles": config.browser_profiles_dir,
    }.items():
        if path.exists():
            result[label] = oct(stat.S_IMODE(os.lstat(path).st_mode))
    return result
