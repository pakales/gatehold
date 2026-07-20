"""Deterministic Gatehold admission engine and lease lifecycle."""

from __future__ import annotations

import hmac
import stat
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlite3 import Connection
from uuid import uuid4

from .config import GateholdConfig
from .conflicts import canonical_workstream, scope_sets_overlap
from .host import HostProbe, PsutilHostProbe
from .lifecycle import (
    LifecycleManager,
    PortLifecycleAdapter,
    ProcessLifecycleAdapter,
    ProfileLifecycleAdapter,
    RuntimeCleanupResult,
    SimulatorLifecycleAdapter,
)
from .models import (
    CapacitySnapshot,
    ClaimOutcome,
    ClaimRequest,
    ClearanceDecision,
    ConflictKind,
    DeterministicConflict,
    GateholdEvent,
    GateholdSnapshot,
    HeartbeatOutcome,
    LeaseGrant,
    LeaseState,
    LeaseView,
    QueueView,
    ReasonCode,
    ReleaseOutcome,
    RequestState,
    ResourceAllocation,
    SemanticAssessment,
    SemanticCandidate,
    SemanticFallback,
    SemanticReason,
    SemanticVerdict,
    WorkloadClass,
)
from .privacy import (
    executable_name as sanitize_executable_name,
)
from .privacy import (
    make_receipt,
    new_secret,
    scope_digest,
    secret_digest,
    sha256_text,
    verify_secret,
)
from .resources import ResourceAllocator
from .semantic import SemanticComparator
from .store import GateholdStore, StoredLease, StoredRequest

ESTIMATED_COLLISION_SAVINGS_MINUTES = 15.0


class GateholdError(RuntimeError):
    """Base error safe for concise local CLI reporting."""


class UnknownRequestError(GateholdError):
    pass


class UnknownLeaseError(GateholdError):
    pass


class CredentialError(GateholdError):
    pass


class LeaseNotActiveError(GateholdError):
    pass


class RequestNotQueuedError(GateholdError):
    pass


def _system_now() -> datetime:
    return datetime.now(tz=UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


class GateholdService:
    """Transactional admission service; no command execution lives here."""

    def __init__(
        self,
        config: GateholdConfig,
        *,
        host_probe: HostProbe | None = None,
        semantic_comparator: SemanticComparator | None = None,
        process_lifecycle: ProcessLifecycleAdapter | None = None,
        simulator_lifecycle: SimulatorLifecycleAdapter | None = None,
        port_lifecycle: PortLifecycleAdapter | None = None,
        profile_lifecycle: ProfileLifecycleAdapter | None = None,
        now: Callable[[], datetime] = _system_now,
    ) -> None:
        self.config = config
        self.store = GateholdStore(config)
        self.store.initialize()
        self.host_probe = host_probe or PsutilHostProbe()
        self.semantic_comparator = semantic_comparator
        self.resource_allocator = ResourceAllocator(config, self.store)
        self.lifecycle = LifecycleManager(
            config,
            self.store,
            process_adapter=process_lifecycle,
            simulator_adapter=simulator_lifecycle,
            port_adapter=port_lifecycle,
            profile_adapter=profile_lifecycle,
        )
        self._now = now

    def claim(
        self,
        request: ClaimRequest,
        *,
        request_id: str | None = None,
        queue_token: str | None = None,
        executable_name: str | None = None,
    ) -> ClaimOutcome:
        try:
            return self._claim(
                request,
                request_id=request_id,
                queue_token=queue_token,
                executable_name=executable_name,
            )
        finally:
            self._drain_cleanup(reason="reconcile")

    def _claim(
        self,
        request: ClaimRequest,
        *,
        request_id: str | None,
        queue_token: str | None,
        executable_name: str | None,
    ) -> ClaimOutcome:
        now = _as_utc(self._now())
        timestamp = now.timestamp()
        stored_executable = sanitize_executable_name(executable_name) if executable_name else None
        is_resume = request_id is not None or queue_token is not None
        if is_resume and (request_id is None or queue_token is None):
            raise CredentialError("request_id and queue_token are required together")

        if request_id is None:
            request_id = str(uuid4())
            queue_token = new_secret()
            with self.store.transaction() as connection:
                self._expire_stale(connection, now=timestamp)
                stored_request = self.store.enqueue(
                    connection,
                    request_id=request_id,
                    owner_id=request.owner_id,
                    workstream=request.workstream,
                    workstream_key=canonical_workstream(request.workstream),
                    scopes=request.scopes,
                    scope_sha256=scope_digest(request.scopes),
                    workload=request.workload,
                    ttl_seconds=request.ttl_seconds,
                    resources=request.resources,
                    queue_token_sha256=secret_digest(queue_token),
                    executable_name=stored_executable,
                    now=timestamp,
                )
                self.store.insert_event(
                    connection,
                    kind="request.queued",
                    occurred_at=timestamp,
                    request_id=request_id,
                    detail={"workload": request.workload.value},
                )
        else:
            if queue_token is None:
                raise CredentialError("queue token is required")
            with self.store.transaction() as connection:
                self._expire_stale(connection, now=timestamp)
                stored_request = self.store.get_request(connection, request_id)
                if stored_request is None:
                    raise UnknownRequestError("unknown request")
                if not verify_secret(queue_token, stored_request.queue_token_sha256):
                    raise CredentialError("invalid queue token")
                if stored_request.status is not RequestState.QUEUED:
                    raise RequestNotQueuedError(
                        f"request is {stored_request.status.value}, not queued"
                    )
                self._validate_resume(request, stored_request)
                self.store.touch_queued_request(
                    connection,
                    request_id=stored_request.request_id,
                    now=timestamp,
                )

        # A deterministic conflict is authoritative and avoids a paid model call.
        with self.store.transaction() as connection:
            self._expire_stale(connection, now=timestamp)
            stored_request = self._require_queued_request(connection, request_id)
            queued_conflicts, queued_reasons = self._queued_conflicts(
                connection,
                stored_request,
            )
            if queued_conflicts:
                semantic = self._skipped_semantic(SemanticFallback.NO_COMPARABLE_LEASES)
                return self._hold_outcome(
                    connection,
                    request=stored_request,
                    decision=ClearanceDecision.DETERMINISTIC_HOLD,
                    state=RequestState.DETERMINISTIC_HOLD,
                    reasons=queued_reasons,
                    conflicts=queued_conflicts,
                    semantic=semantic,
                    now=now,
                )
            active = self.store.active_leases(connection, now=timestamp)
            conflicts, reasons = self._deterministic_conflicts(stored_request, active)
            if conflicts:
                semantic = self._skipped_semantic(SemanticFallback.NO_COMPARABLE_LEASES)
                return self._hold_outcome(
                    connection,
                    request=stored_request,
                    decision=ClearanceDecision.DETERMINISTIC_HOLD,
                    state=RequestState.DETERMINISTIC_HOLD,
                    reasons=reasons,
                    conflicts=conflicts,
                    semantic=semantic,
                    now=now,
                )
            semantic_targets = active

        for generation in range(3):
            semantic = self._compare_semantics_cached(
                request_id=request_id,
                request=request,
                active=semantic_targets,
            )
            # Model latency must never consume a new lease's TTL.
            final_now = _as_utc(self._now())
            final_timestamp = final_now.timestamp()
            host = self.host_probe.sample(
                cpu_limit_percent=self.config.cpu_limit_percent,
                memory_limit_percent=self.config.memory_limit_percent,
                now=final_now,
            )

            with self.store.transaction() as connection:
                self._expire_stale(connection, now=final_timestamp)
                stored_request = self._require_queued_request(connection, request_id)
                queued_conflicts, queued_reasons = self._queued_conflicts(
                    connection,
                    stored_request,
                )
                if queued_conflicts:
                    return self._hold_outcome(
                        connection,
                        request=stored_request,
                        decision=ClearanceDecision.DETERMINISTIC_HOLD,
                        state=RequestState.DETERMINISTIC_HOLD,
                        reasons=queued_reasons,
                        conflicts=queued_conflicts,
                        semantic=semantic,
                        now=final_now,
                    )
                active = self.store.active_leases(connection, now=final_timestamp)
                conflicts, reasons = self._deterministic_conflicts(stored_request, active)
                if conflicts:
                    return self._hold_outcome(
                        connection,
                        request=stored_request,
                        decision=ClearanceDecision.DETERMINISTIC_HOLD,
                        state=RequestState.DETERMINISTIC_HOLD,
                        reasons=reasons,
                        conflicts=conflicts,
                        semantic=semantic,
                        now=final_now,
                    )

                compared_ids = {lease.lease_id for lease in semantic_targets}
                current_ids = {lease.lease_id for lease in active}
                if current_ids - compared_ids:
                    semantic_targets = active
                    if generation < 2:
                        continue
                    semantic = SemanticAssessment(
                        verdict=SemanticVerdict.UNCERTAIN,
                        model=semantic.model,
                        reason=SemanticReason.UNCERTAIN,
                        fallback=SemanticFallback.STALE_COMPARISON,
                    )
                    return self._queued_outcome(
                        connection,
                        request=stored_request,
                        queue_token=queue_token,
                        reasons=(ReasonCode.MODEL_UNCERTAIN,),
                        semantic=semantic,
                        now=final_now,
                    )

                if semantic.verdict is SemanticVerdict.HOLD:
                    compared_is_active = any(
                        lease.lease_id == semantic.compared_lease_id for lease in active
                    )
                    if compared_is_active:
                        return self._hold_outcome(
                            connection,
                            request=stored_request,
                            decision=ClearanceDecision.SEMANTIC_HOLD,
                            state=RequestState.SEMANTIC_HOLD,
                            reasons=(ReasonCode.MODEL_OVERLAP,),
                            conflicts=(),
                            semantic=semantic,
                            now=final_now,
                        )
                    semantic = SemanticAssessment(
                        verdict=SemanticVerdict.UNCERTAIN,
                        model=semantic.model,
                        compared_lease_id=semantic.compared_lease_id,
                        reason=SemanticReason.UNCERTAIN,
                        fallback=SemanticFallback.STALE_COMPARISON,
                    )

                queue_reasons = self._capacity_reasons(
                    connection=connection,
                    request=stored_request,
                    host_cpu=host.cpu_percent,
                    host_memory=host.memory_percent,
                    now=final_timestamp,
                )
                if queue_reasons:
                    return self._queued_outcome(
                        connection,
                        request=stored_request,
                        queue_token=queue_token,
                        reasons=queue_reasons,
                        semantic=semantic,
                        now=final_now,
                    )

                lease_id = str(uuid4())
                allocation_attempt = self.resource_allocator.try_allocate(
                    connection,
                    request=stored_request.resources,
                    lease_id=lease_id,
                )
                if allocation_attempt.allocation is None:
                    return self._queued_outcome(
                        connection,
                        request=stored_request,
                        queue_token=queue_token,
                        reasons=allocation_attempt.reasons,
                        semantic=semantic,
                        now=final_now,
                    )

                heartbeat_token = new_secret()
                expires_at = final_now + timedelta(seconds=stored_request.ttl_seconds)
                try:
                    lease = self.store.create_lease(
                        connection,
                        lease_id=lease_id,
                        request=stored_request,
                        heartbeat_token_sha256=secret_digest(heartbeat_token),
                        resources=allocation_attempt.allocation,
                        profile_device=(
                            allocation_attempt.profile_provenance.device
                            if allocation_attempt.profile_provenance is not None
                            else None
                        ),
                        profile_inode=(
                            allocation_attempt.profile_provenance.inode
                            if allocation_attempt.profile_provenance is not None
                            else None
                        ),
                        profile_marker_sha256=(
                            allocation_attempt.profile_provenance.marker_sha256
                            if allocation_attempt.profile_provenance is not None
                            else None
                        ),
                        now=final_timestamp,
                        expires_at=expires_at.timestamp(),
                    )
                except BaseException:
                    if allocation_attempt.created_profile is not None:
                        with suppress(OSError):
                            (
                                allocation_attempt.created_profile / ".gatehold-profile-owner"
                            ).unlink()
                        with suppress(OSError):
                            allocation_attempt.created_profile.rmdir()
                    raise
                self.store.insert_event(
                    connection,
                    kind="lease.granted",
                    occurred_at=final_timestamp,
                    request_id=stored_request.request_id,
                    lease_id=lease.lease_id,
                    detail={
                        "workload": lease.workload.value,
                        "has_port": lease.resources.port is not None,
                        "has_browser_profile": (lease.resources.browser_profile is not None),
                        "has_simulator": lease.resources.simulator is not None,
                    },
                )
                grant = LeaseGrant(
                    lease_id=lease.lease_id,
                    request_id=lease.request_id,
                    owner_id=lease.owner_id,
                    heartbeat_token=heartbeat_token,
                    workload=lease.workload,
                    granted_at=final_now,
                    expires_at=expires_at,
                    resources=lease.resources,
                )
                receipt = make_receipt(
                    generated_at=final_now,
                    request_id=stored_request.request_id,
                    lease_id=lease.lease_id,
                    decision=ClearanceDecision.GRANTED,
                    owner_id=stored_request.owner_id,
                    workstream=stored_request.workstream,
                    scopes=stored_request.scopes,
                    reasons=(ReasonCode.CLEAR,),
                    semantic=semantic,
                    expires_at=expires_at,
                    command_executable=stored_request.executable_name,
                )
                self.store.persist_receipt(connection, receipt)
                return ClaimOutcome(
                    decision=ClearanceDecision.GRANTED,
                    request_id=stored_request.request_id,
                    lease=grant,
                    reasons=(ReasonCode.CLEAR,),
                    semantic=semantic,
                    receipt=receipt,
                )
        raise RuntimeError("semantic admission generation exhausted")

    def cancel_queue(
        self,
        *,
        request_id: str,
        queue_token: str,
    ) -> bool:
        """Expire an authenticated queued request without touching any lease."""

        try:
            now = _as_utc(self._now())
            timestamp = now.timestamp()
            with self.store.transaction() as connection:
                self._expire_stale(connection, now=timestamp)
                request = self.store.get_request(connection, request_id)
                if request is None:
                    raise UnknownRequestError("unknown request")
                if not verify_secret(queue_token, request.queue_token_sha256):
                    raise CredentialError("invalid queue token")
                if request.status is RequestState.EXPIRED:
                    return False
                if request.status is not RequestState.QUEUED:
                    raise RequestNotQueuedError(f"request is {request.status.value}, not queued")
                self.store.set_request_state(
                    connection,
                    request_id=request.request_id,
                    state=RequestState.EXPIRED,
                    now=timestamp,
                )
                self.store.insert_event(
                    connection,
                    kind="request.cancelled",
                    occurred_at=timestamp,
                    request_id=request.request_id,
                    detail={"workload": request.workload.value},
                )
                return True
        finally:
            self._drain_cleanup(reason="queue_abandon")

    def prepare_managed_simulator(self, *, lease_id: str) -> bool:
        now = _as_utc(self._now())
        return self.lifecycle.prepare_simulator(
            lease_id=lease_id,
            now=now.timestamp(),
        )

    def register_managed_process(
        self,
        *,
        lease_id: str,
        pid: int,
        run_token: str,
    ) -> None:
        now = _as_utc(self._now())
        self.lifecycle.register_process(
            lease_id=lease_id,
            pid=pid,
            run_token=run_token,
            now=now.timestamp(),
        )

    def cleanup_runtime(
        self,
        *,
        lease_id: str,
        reason: str,
        child_exit_code: int | None = None,
    ) -> RuntimeCleanupResult:
        now = _as_utc(self._now())
        result = self.lifecycle.cleanup(
            lease_id=lease_id,
            reason=reason,
            now=now.timestamp(),
            child_exit_code=child_exit_code,
        )
        self._drain_profile_cleanup()
        return result

    def heartbeat(
        self,
        *,
        lease_id: str,
        owner_id: str,
        heartbeat_token: str,
        ttl_seconds: int | None = None,
    ) -> HeartbeatOutcome:
        try:
            return self._heartbeat(
                lease_id=lease_id,
                owner_id=owner_id,
                heartbeat_token=heartbeat_token,
                ttl_seconds=ttl_seconds,
            )
        finally:
            self._drain_cleanup(reason="reconcile")

    def _heartbeat(
        self,
        *,
        lease_id: str,
        owner_id: str,
        heartbeat_token: str,
        ttl_seconds: int | None,
    ) -> HeartbeatOutcome:
        now = _as_utc(self._now())
        timestamp = now.timestamp()
        with self.store.transaction() as connection:
            self._expire_stale(connection, now=timestamp)
            lease = self.store.get_lease(connection, lease_id)
            self._authorize_lease(lease, owner_id, heartbeat_token)
            if lease is None:
                raise UnknownLeaseError("unknown lease")
            runtime = self.store.get_runtime_ownership(connection, lease.lease_id)
            if runtime is None or runtime.terminal_state is not None:
                raise LeaseNotActiveError("lease cleanup is pending")
            ttl = ttl_seconds if ttl_seconds is not None else lease.ttl_seconds
            if ttl < 15 or ttl > 86_400:
                raise ValueError("ttl_seconds must be between 15 and 86400")
            expires_at = now + timedelta(seconds=ttl)
            self.store.extend_lease(
                connection,
                lease_id=lease.lease_id,
                heartbeat_at=timestamp,
                expires_at=expires_at.timestamp(),
            )
            self.store.insert_event(
                connection,
                kind="lease.heartbeat",
                occurred_at=timestamp,
                request_id=lease.request_id,
                lease_id=lease.lease_id,
                detail={"ttl_seconds": ttl},
            )
            semantic = self._skipped_semantic(SemanticFallback.NO_COMPARABLE_LEASES)
            receipt = make_receipt(
                generated_at=now,
                request_id=lease.request_id,
                lease_id=lease.lease_id,
                decision=ClearanceDecision.GRANTED,
                owner_id=lease.owner_id,
                workstream=lease.workstream,
                scopes=lease.scopes,
                reasons=(ReasonCode.CLEAR,),
                semantic=semantic,
                expires_at=expires_at,
                command_executable=lease.executable_name,
            )
            self.store.persist_receipt(connection, receipt)
            return HeartbeatOutcome(
                lease_id=lease.lease_id,
                heartbeat_at=now,
                expires_at=expires_at,
                receipt=receipt,
            )

    def release(
        self,
        *,
        lease_id: str,
        owner_id: str,
        heartbeat_token: str,
    ) -> ReleaseOutcome:
        try:
            return self._release(
                lease_id=lease_id,
                owner_id=owner_id,
                heartbeat_token=heartbeat_token,
            )
        finally:
            self._drain_cleanup(reason="explicit_release")

    def _release(
        self,
        *,
        lease_id: str,
        owner_id: str,
        heartbeat_token: str,
    ) -> ReleaseOutcome:
        now = _as_utc(self._now())
        timestamp = now.timestamp()
        with self.store.transaction() as connection:
            self._expire_stale(connection, now=timestamp)
            lease = self.store.get_lease(connection, lease_id)
            self._authorize_lease(lease, owner_id, heartbeat_token)
            if lease is None:
                raise UnknownLeaseError("unknown lease")
            self.store.release_lease(
                connection,
                lease=lease,
                state=LeaseState.RELEASED,
                now=timestamp,
            )
            self.store.insert_event(
                connection,
                kind="lease.released",
                occurred_at=timestamp,
                request_id=lease.request_id,
                lease_id=lease.lease_id,
                detail={"workload": lease.workload.value},
            )
            semantic = self._skipped_semantic(SemanticFallback.NO_COMPARABLE_LEASES)
            receipt = make_receipt(
                generated_at=now,
                request_id=lease.request_id,
                lease_id=lease.lease_id,
                decision=ClearanceDecision.GRANTED,
                owner_id=lease.owner_id,
                workstream=lease.workstream,
                scopes=lease.scopes,
                reasons=(ReasonCode.CLEAR,),
                semantic=semantic,
                command_executable=lease.executable_name,
            )
            self.store.persist_receipt(connection, receipt)
            return ReleaseOutcome(
                lease_id=lease.lease_id,
                released_at=now,
                receipt=receipt,
            )

    def reap_expired(self) -> int:
        now = _as_utc(self._now())
        with self.store.transaction() as connection:
            expired_leases, expired_requests = self._expire_stale(
                connection,
                now=now.timestamp(),
            )
            count = len(expired_leases) + len(expired_requests)
        self._drain_cleanup(reason="lease_expired")
        return count

    def snapshot(self, *, recent_receipts: int = 20) -> GateholdSnapshot:
        now = _as_utc(self._now())
        timestamp = now.timestamp()
        with self.store.transaction() as connection:
            self._expire_stale(connection, now=timestamp)
        self._drain_cleanup(reason="recovery")
        active = self.store.snapshot_leases(now=timestamp)
        queued = self.store.snapshot_requests()
        host = self.host_probe.sample(
            cpu_limit_percent=self.config.cpu_limit_percent,
            memory_limit_percent=self.config.memory_limit_percent,
            now=now,
        )
        heavy_active = sum(lease.workload is WorkloadClass.HEAVY for lease in active)
        leases = tuple(self._lease_view(lease) for lease in active)
        queue = tuple(
            QueueView(
                request_id=request.request_id,
                owner_sha256=sha256_text(request.owner_id),
                workstream_sha256=sha256_text(request.workstream_key),
                scope_sha256=request.scope_sha256,
                workload=request.workload,
                position=index,
                enqueued_at=datetime.fromtimestamp(request.created_at, tz=UTC),
                reasons=tuple(ReasonCode(reason) for reason in request.queue_reasons),
                executable_name=request.executable_name,
            )
            for index, request in enumerate(queued, start=1)
        )
        return GateholdSnapshot(
            generated_at=now,
            host=host,
            capacity=CapacitySnapshot(
                heavy_limit=self.config.max_heavy_slots,
                heavy_active=heavy_active,
                heavy_available=max(0, self.config.max_heavy_slots - heavy_active),
            ),
            active_leases=leases,
            queue=queue,
            recent_receipts=self.store.recent_receipts(limit=recent_receipts),
        )

    def events_after(self, sequence: int, *, limit: int = 100) -> tuple[GateholdEvent, ...]:
        return self.store.events_after(sequence, limit=limit)

    def _validate_resume(self, supplied: ClaimRequest, stored: StoredRequest) -> None:
        matches = (
            supplied.owner_id == stored.owner_id
            and canonical_workstream(supplied.workstream) == stored.workstream_key
            and scope_digest(supplied.scopes) == stored.scope_sha256
            and supplied.workload is stored.workload
            and supplied.resources == stored.resources
        )
        if not matches:
            raise CredentialError("resume request does not match queued request")

    def _require_queued_request(self, connection: Connection, request_id: str) -> StoredRequest:
        stored = self.store.get_request(connection, request_id)
        if stored is None:
            raise UnknownRequestError("unknown request")
        if stored.status is not RequestState.QUEUED:
            raise RequestNotQueuedError(f"request is {stored.status.value}, not queued")
        return stored

    def _deterministic_conflicts(
        self,
        request: StoredRequest,
        active: tuple[StoredLease, ...],
    ) -> tuple[tuple[DeterministicConflict, ...], tuple[ReasonCode, ...]]:
        conflicts: list[DeterministicConflict] = []
        reasons: list[ReasonCode] = []
        for lease in active:
            kind: ConflictKind | None = None
            reason: ReasonCode | None = None
            if lease.workstream_key == request.workstream_key:
                kind = ConflictKind.WORKSTREAM
                reason = ReasonCode.WORKSTREAM_CONFLICT
            elif scope_sets_overlap(request.scopes, lease.scopes):
                kind = ConflictKind.SCOPE
                reason = ReasonCode.SCOPE_CONFLICT
            if kind is not None and reason is not None:
                conflicts.append(
                    DeterministicConflict(
                        kind=kind,
                        lease_id=lease.lease_id,
                        workstream_sha256=sha256_text(lease.workstream_key),
                        scope_sha256=lease.scope_sha256,
                    )
                )
                if reason not in reasons:
                    reasons.append(reason)
        return tuple(conflicts), tuple(reasons)

    def _queued_conflicts(
        self,
        connection: Connection,
        request: StoredRequest,
    ) -> tuple[tuple[DeterministicConflict, ...], tuple[ReasonCode, ...]]:
        conflicts: list[DeterministicConflict] = []
        reasons: list[ReasonCode] = []
        for queued in self.store.earlier_queued_requests(
            connection,
            queue_seq=request.queue_seq,
        ):
            kind: ConflictKind | None = None
            reason: ReasonCode | None = None
            if queued.workstream_key == request.workstream_key:
                kind = ConflictKind.WORKSTREAM
                reason = ReasonCode.WORKSTREAM_CONFLICT
            elif scope_sets_overlap(request.scopes, queued.scopes):
                kind = ConflictKind.SCOPE
                reason = ReasonCode.SCOPE_CONFLICT
            if kind is None or reason is None:
                continue
            conflicts.append(
                DeterministicConflict(
                    kind=kind,
                    lease_id=f"queued-request:{queued.request_id}",
                    workstream_sha256=sha256_text(queued.workstream_key),
                    scope_sha256=queued.scope_sha256,
                )
            )
            if reason not in reasons:
                reasons.append(reason)
        return tuple(conflicts), tuple(reasons)

    def _compare_semantics(
        self,
        request: ClaimRequest,
        active: tuple[StoredLease, ...],
    ) -> SemanticAssessment:
        if not active:
            return self._skipped_semantic(SemanticFallback.NO_COMPARABLE_LEASES)
        if self.semantic_comparator is None:
            return self._skipped_semantic(SemanticFallback.UNCONFIGURED)
        candidate = SemanticCandidate(
            workstream=request.workstream,
            scopes=request.scopes,
            summary=request.semantic_summary,
        )
        latest = self._skipped_semantic(SemanticFallback.NO_COMPARABLE_LEASES)
        for lease in active:
            assessment = self.semantic_comparator.compare(
                candidate,
                SemanticCandidate(
                    workstream=lease.workstream,
                    scopes=lease.scopes,
                ),
                active_lease_id=lease.lease_id,
            )
            if assessment.verdict is SemanticVerdict.HOLD:
                return assessment
            latest = assessment
        return latest

    def _compare_semantics_cached(
        self,
        *,
        request_id: str,
        request: ClaimRequest,
        active: tuple[StoredLease, ...],
    ) -> SemanticAssessment:
        active_ids = "\n".join(sorted(lease.lease_id for lease in active))
        summary_sha256 = sha256_text(request.semantic_summary or "")
        active_set_sha256 = sha256_text(
            f"semantic-cache-v2\0{summary_sha256}\0{active_ids}"
        )
        with self.store.reader() as connection:
            cached = self.store.get_semantic_cache(
                connection,
                request_id=request_id,
                active_set_sha256=active_set_sha256,
            )
        if cached is not None:
            return cached
        assessment = self._compare_semantics(request, active)
        now = _as_utc(self._now()).timestamp()
        with self.store.transaction() as connection:
            stored = self.store.get_request(connection, request_id)
            if stored is not None and stored.status is RequestState.QUEUED:
                self.store.set_semantic_cache(
                    connection,
                    request_id=request_id,
                    active_set_sha256=active_set_sha256,
                    assessment=assessment,
                    now=now,
                )
        return assessment

    def _capacity_reasons(
        self,
        *,
        connection: Connection,
        request: StoredRequest,
        host_cpu: float,
        host_memory: float,
        now: float,
    ) -> tuple[ReasonCode, ...]:
        if request.workload is WorkloadClass.LIGHT:
            return ()
        reasons: list[ReasonCode] = []
        self.store.expire_queued_requests(
            connection,
            now=now,
            stale_after_seconds=self.config.queue_ttl_seconds,
        )
        first = self.store.first_queued_heavy(connection)
        if first != request.request_id:
            reasons.append(ReasonCode.FIFO_WAIT)
        heavy_active = self.store.active_heavy_count(connection, now=now)
        if heavy_active >= self.config.max_heavy_slots:
            reasons.append(ReasonCode.HEAVY_SLOT_LIMIT)
        if host_cpu >= self.config.cpu_limit_percent:
            reasons.append(ReasonCode.HOST_CPU_PRESSURE)
        if host_memory >= self.config.memory_limit_percent:
            reasons.append(ReasonCode.HOST_MEMORY_PRESSURE)
        return tuple(reasons)

    def _expire_stale(
        self,
        connection: Connection,
        *,
        now: float,
    ) -> tuple[tuple[StoredLease, ...], tuple[StoredRequest, ...]]:
        expired_leases = self.store.expire_leases(connection, now=now)
        expired_requests = self.store.expire_queued_requests(
            connection,
            now=now,
            stale_after_seconds=self.config.queue_ttl_seconds,
        )
        return expired_leases, expired_requests

    def _hold_outcome(
        self,
        connection: Connection,
        *,
        request: StoredRequest,
        decision: ClearanceDecision,
        state: RequestState,
        reasons: tuple[ReasonCode, ...],
        conflicts: tuple[DeterministicConflict, ...],
        semantic: SemanticAssessment,
        now: datetime,
    ) -> ClaimOutcome:
        self.store.set_request_state(
            connection,
            request_id=request.request_id,
            state=state,
            now=now.timestamp(),
        )
        event_kind = (
            "request.deterministic_hold"
            if decision is ClearanceDecision.DETERMINISTIC_HOLD
            else "request.semantic_hold"
        )
        self.store.insert_event(
            connection,
            kind=event_kind,
            occurred_at=now.timestamp(),
            request_id=request.request_id,
            detail={"reason_count": len(reasons)},
        )
        receipt = make_receipt(
            generated_at=now,
            request_id=request.request_id,
            lease_id=None,
            decision=decision,
            owner_id=request.owner_id,
            workstream=request.workstream,
            scopes=request.scopes,
            reasons=reasons,
            semantic=semantic,
            command_executable=request.executable_name,
            estimated_savings_minutes=ESTIMATED_COLLISION_SAVINGS_MINUTES,
        )
        self.store.persist_receipt(connection, receipt)
        return ClaimOutcome(
            decision=decision,
            request_id=request.request_id,
            conflicts=conflicts,
            reasons=reasons,
            semantic=semantic,
            receipt=receipt,
        )

    def _queued_outcome(
        self,
        connection: Connection,
        *,
        request: StoredRequest,
        queue_token: str | None,
        reasons: tuple[ReasonCode, ...],
        semantic: SemanticAssessment,
        now: datetime,
    ) -> ClaimOutcome:
        if queue_token is None:
            raise CredentialError("queue token is unavailable")
        self.store.set_request_state(
            connection,
            request_id=request.request_id,
            state=RequestState.QUEUED,
            now=now.timestamp(),
            queue_reasons=tuple(reason.value for reason in reasons),
        )
        position = self.store.queue_position(connection, request.request_id)
        self.store.insert_event(
            connection,
            kind="request.waiting",
            occurred_at=now.timestamp(),
            request_id=request.request_id,
            detail={"position": position, "reason_count": len(reasons)},
        )
        receipt_reasons = reasons
        if semantic.verdict is SemanticVerdict.UNCERTAIN:
            receipt_reasons = tuple(dict.fromkeys((*reasons, ReasonCode.MODEL_UNCERTAIN)))
        receipt = make_receipt(
            generated_at=now,
            request_id=request.request_id,
            lease_id=None,
            decision=ClearanceDecision.QUEUED,
            owner_id=request.owner_id,
            workstream=request.workstream,
            scopes=request.scopes,
            reasons=receipt_reasons,
            semantic=semantic,
            command_executable=request.executable_name,
        )
        self.store.persist_receipt(connection, receipt)
        return ClaimOutcome(
            decision=ClearanceDecision.QUEUED,
            request_id=request.request_id,
            queue_position=position,
            queue_token=queue_token,
            reasons=reasons,
            semantic=semantic,
            receipt=receipt,
        )

    def _authorize_lease(
        self,
        lease: StoredLease | None,
        owner_id: str,
        heartbeat_token: str,
    ) -> None:
        if lease is None:
            raise UnknownLeaseError("unknown lease")
        if lease.state is not LeaseState.ACTIVE:
            raise LeaseNotActiveError(f"lease is {lease.state.value}")
        if not hmac.compare_digest(lease.owner_id, owner_id):
            raise CredentialError("invalid lease credentials")
        if not verify_secret(heartbeat_token, lease.heartbeat_token_sha256):
            raise CredentialError("invalid lease credentials")

    def _lease_view(self, lease: StoredLease) -> LeaseView:
        profile_handle = (
            Path(lease.resources.browser_profile).name
            if lease.resources.browser_profile is not None
            else None
        )
        return LeaseView(
            lease_id=lease.lease_id,
            request_id=lease.request_id,
            owner_sha256=sha256_text(lease.owner_id),
            workstream_sha256=sha256_text(lease.workstream_key),
            scope_sha256=lease.scope_sha256,
            workload=lease.workload,
            state=lease.state,
            granted_at=datetime.fromtimestamp(lease.created_at, tz=UTC),
            heartbeat_at=datetime.fromtimestamp(lease.heartbeat_at, tz=UTC),
            expires_at=datetime.fromtimestamp(lease.expires_at, tz=UTC),
            resources=ResourceAllocation(
                port=lease.resources.port,
                browser_profile=profile_handle,
                simulator=lease.resources.simulator,
            ),
            executable_name=lease.executable_name,
        )

    def _skipped_semantic(self, fallback: SemanticFallback) -> SemanticAssessment:
        return SemanticAssessment(
            verdict=SemanticVerdict.SKIPPED,
            reason=SemanticReason.UNCERTAIN,
            fallback=fallback,
        )

    def _drain_profile_cleanup(self) -> None:
        root = self.config.browser_profiles_dir
        for raw_path in self.store.pending_profile_cleanup():
            candidate = Path(raw_path)
            if candidate.parent != root or not candidate.name.startswith("profile-"):
                # Never act on a path outside Gatehold's dedicated profile root.
                continue
            try:
                _remove_without_following_symlinks(candidate)
            except FileNotFoundError:
                pass
            except OSError:
                continue
            self.store.complete_profile_cleanup(raw_path)

    def _drain_cleanup(self, *, reason: str) -> None:
        now = _as_utc(self._now())
        self.lifecycle.cleanup_pending(
            reason=reason,
            now=now.timestamp(),
        )
        self._drain_profile_cleanup()


def _remove_without_following_symlinks(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        path.unlink()
        return
    for child in path.iterdir():
        _remove_without_following_symlinks(child)
    path.rmdir()
