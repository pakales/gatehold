"""Strict domain models shared by Gatehold's local boundaries."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]
Scope = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SecretToken = Annotated[str, StringConstraints(min_length=32, max_length=256)]


class DomainModel(BaseModel):
    """Base model for strict, typo-resistant boundary objects."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkloadClass(StrEnum):
    LIGHT = "light"
    HEAVY = "heavy"


class ClearanceDecision(StrEnum):
    GRANTED = "GRANTED"
    QUEUED = "QUEUED"
    DETERMINISTIC_HOLD = "DETERMINISTIC_HOLD"
    SEMANTIC_HOLD = "SEMANTIC_HOLD"


class RequestState(StrEnum):
    QUEUED = "queued"
    ADMITTED = "admitted"
    DETERMINISTIC_HOLD = "deterministic_hold"
    SEMANTIC_HOLD = "semantic_hold"
    RELEASED = "released"
    EXPIRED = "expired"


class LeaseState(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


class ConflictKind(StrEnum):
    WORKSTREAM = "workstream"
    SCOPE = "scope"


class ReasonCode(StrEnum):
    CLEAR = "clear"
    WORKSTREAM_CONFLICT = "workstream_conflict"
    SCOPE_CONFLICT = "scope_conflict"
    FIFO_WAIT = "fifo_wait"
    HOST_CPU_PRESSURE = "host_cpu_pressure"
    HOST_MEMORY_PRESSURE = "host_memory_pressure"
    HEAVY_SLOT_LIMIT = "heavy_slot_limit"
    PORT_UNAVAILABLE = "port_unavailable"
    BROWSER_PROFILE_UNAVAILABLE = "browser_profile_unavailable"
    SIMULATOR_UNAVAILABLE = "simulator_unavailable"
    MODEL_OVERLAP = "model_overlap"
    MODEL_UNCERTAIN = "model_uncertain"


class SemanticVerdict(StrEnum):
    CLEAR = "CLEAR"
    HOLD = "HOLD"
    UNCERTAIN = "UNCERTAIN"
    SKIPPED = "SKIPPED"


class SemanticFallback(StrEnum):
    UNCONFIGURED = "unconfigured"
    NO_COMPARABLE_LEASES = "no_comparable_leases"
    REFUSAL = "refusal"
    API_ERROR = "api_error"
    INVALID_OUTPUT = "invalid_output"
    STALE_COMPARISON = "stale_comparison"


class SemanticReason(StrEnum):
    NONE = "none"
    SAME_FEATURE = "same_feature"
    SHARED_STATE = "shared_state"
    INDIRECT_FILE_OVERLAP = "indirect_file_overlap"
    UNCERTAIN = "uncertain"


class SemanticConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ResourceRequest(DomainModel):
    port: bool = False
    browser_profile: bool = False
    simulator: bool = False


class ResourceAllocation(DomainModel):
    port: int | None = Field(default=None, ge=1024, le=65535)
    browser_profile: str | None = Field(default=None, max_length=2048)
    simulator: str | None = Field(default=None, max_length=160)


class ClaimRequest(DomainModel):
    owner_id: Identifier
    workstream: Identifier
    scopes: tuple[Scope, ...] = Field(min_length=1, max_length=64)
    workload: WorkloadClass = WorkloadClass.HEAVY
    ttl_seconds: int = Field(default=900, ge=15, le=86_400)
    resources: ResourceRequest = Field(default_factory=ResourceRequest)
    semantic_summary: str | None = Field(default=None, max_length=2000)

    @field_validator("scopes")
    @classmethod
    def reject_duplicate_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len({item.casefold() for item in value}) != len(value):
            raise ValueError("scopes must not contain duplicates")
        return value


class SemanticCandidate(DomainModel):
    workstream: Identifier
    scopes: tuple[Scope, ...] = Field(min_length=1, max_length=64)
    summary: str | None = Field(default=None, max_length=2000)


class SemanticModelOutput(DomainModel):
    overlap: bool
    confidence: SemanticConfidence
    reason: SemanticReason

    @model_validator(mode="after")
    def validate_reason(self) -> SemanticModelOutput:
        if self.overlap and self.reason in {SemanticReason.NONE, SemanticReason.UNCERTAIN}:
            raise ValueError("overlap requires a concrete overlap reason")
        if not self.overlap and self.reason not in {
            SemanticReason.NONE,
            SemanticReason.UNCERTAIN,
        }:
            raise ValueError("clear output cannot carry an overlap reason")
        return self


class SemanticAssessment(DomainModel):
    verdict: SemanticVerdict
    model: str | None = None
    compared_lease_id: str | None = None
    confidence: SemanticConfidence | None = None
    reason: SemanticReason = SemanticReason.UNCERTAIN
    fallback: SemanticFallback | None = None


class DeterministicConflict(DomainModel):
    kind: ConflictKind
    lease_id: str
    workstream_sha256: Sha256Hex
    scope_sha256: Sha256Hex


class HostSnapshot(DomainModel):
    sampled_at: datetime
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    cpu_limit_percent: float = Field(ge=1, le=100)
    memory_limit_percent: float = Field(ge=1, le=100)
    pressure_ok: bool


class LeaseGrant(DomainModel):
    lease_id: str
    request_id: str
    owner_id: Identifier
    heartbeat_token: SecretToken
    workload: WorkloadClass
    granted_at: datetime
    expires_at: datetime
    resources: ResourceAllocation


class LeaseView(DomainModel):
    lease_id: str
    request_id: str
    owner_sha256: Sha256Hex
    workstream_sha256: Sha256Hex
    scope_sha256: Sha256Hex
    workload: WorkloadClass
    state: LeaseState
    granted_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    resources: ResourceAllocation
    executable_name: str | None = Field(default=None, max_length=255)


class QueueView(DomainModel):
    request_id: str
    owner_sha256: Sha256Hex
    workstream_sha256: Sha256Hex
    scope_sha256: Sha256Hex
    workload: WorkloadClass
    position: int = Field(ge=1)
    enqueued_at: datetime
    reasons: tuple[ReasonCode, ...] = ()
    executable_name: str | None = Field(default=None, max_length=255)


class EstimatedSavings(DomainModel):
    label: Literal["estimate"] = "estimate"
    minutes: float = Field(ge=0)


class Receipt(DomainModel):
    receipt_id: str
    receipt_sha256: Sha256Hex
    input_sha256: Sha256Hex
    generated_at: datetime
    request_id: str
    lease_id: str | None = None
    decision: ClearanceDecision
    owner_sha256: Sha256Hex
    workstream_sha256: Sha256Hex
    scope_sha256: Sha256Hex
    reasons: tuple[ReasonCode, ...]
    semantic_verdict: SemanticVerdict
    semantic_model: str | None = None
    expires_at: datetime | None = None
    executable_name: str | None = Field(default=None, max_length=255)
    estimated_savings: EstimatedSavings | None = None


class ClaimOutcome(DomainModel):
    decision: ClearanceDecision
    request_id: str
    queue_position: int | None = Field(default=None, ge=1)
    queue_token: SecretToken | None = None
    lease: LeaseGrant | None = None
    conflicts: tuple[DeterministicConflict, ...] = ()
    reasons: tuple[ReasonCode, ...]
    semantic: SemanticAssessment
    receipt: Receipt

    @model_validator(mode="after")
    def validate_shape(self) -> ClaimOutcome:
        if self.decision is ClearanceDecision.GRANTED and self.lease is None:
            raise ValueError("granted outcome requires a lease")
        if self.decision is ClearanceDecision.QUEUED:
            if self.queue_position is None or self.queue_token is None:
                raise ValueError("queued outcome requires position and queue token")
        elif self.queue_position is not None or self.queue_token is not None:
            raise ValueError("only queued outcomes expose queue credentials")
        return self


class HeartbeatOutcome(DomainModel):
    lease_id: str
    heartbeat_at: datetime
    expires_at: datetime
    receipt: Receipt


class ReleaseOutcome(DomainModel):
    lease_id: str
    released_at: datetime
    receipt: Receipt


class CapacitySnapshot(DomainModel):
    heavy_limit: int = Field(ge=1, le=2)
    heavy_active: int = Field(ge=0)
    heavy_available: int = Field(ge=0)


EventDetail = dict[str, str | int | float | bool | None]


class GateholdEvent(DomainModel):
    sequence: int = Field(ge=1)
    kind: str = Field(min_length=1, max_length=80)
    occurred_at: datetime
    request_id: str | None = None
    lease_id: str | None = None
    detail: EventDetail = Field(default_factory=dict)


class GateholdSnapshot(DomainModel):
    version: Literal["gatehold.snapshot.v1"] = "gatehold.snapshot.v1"
    generated_at: datetime
    host: HostSnapshot
    capacity: CapacitySnapshot
    active_leases: tuple[LeaseView, ...]
    queue: tuple[QueueView, ...]
    recent_receipts: tuple[Receipt, ...]


class HealthResponse(DomainModel):
    status: Literal["ok"] = "ok"
    version: str
