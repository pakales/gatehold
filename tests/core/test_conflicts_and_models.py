from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from gatehold.config import GateholdConfig
from gatehold.conflicts import (
    canonical_scope,
    canonical_workstream,
    scope_sets_overlap,
    scopes_overlap,
)
from gatehold.models import (
    ClaimOutcome,
    ClaimRequest,
    ClearanceDecision,
    ReasonCode,
    ResourceAllocation,
    SemanticAssessment,
    SemanticConfidence,
    SemanticFallback,
    SemanticModelOutput,
    SemanticReason,
    SemanticVerdict,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Release   Audit ", "release audit"),
        ("AUTH\tMigration", "auth migration"),
        ("Straße", "strasse"),
    ],
)
def test_canonical_workstream_collapses_whitespace_and_case(raw: str, expected: str) -> None:
    assert canonical_workstream(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("src//gatehold/../gatehold/models.py/", "src/gatehold/models.py"),
        (r"src\gatehold\.\models.py", "src/gatehold/models.py"),
        ("/Users/Example/Repo/../Repo/App", "/users/example/repo/app"),
        ("*", "*"),
        (".", "/"),
        ("/", "/"),
        ("database:Billing", "database:billing"),
    ],
)
def test_canonical_scope_is_lexical_and_stable(raw: str, expected: str) -> None:
    assert canonical_scope(raw) == expected


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("*", "anything"),
        ("src", "src/gatehold/models.py"),
        ("src/gatehold", r"SRC\gatehold\models.py"),
        ("/repo/app", "/repo/app/components"),
        ("database:billing", "DATABASE:billing"),
        ("/repo/src", "repo/src/models.py"),
    ],
)
def test_scopes_overlap_for_same_or_ancestor_scope(left: str, right: str) -> None:
    assert scopes_overlap(left, right)
    assert scopes_overlap(right, left)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("src/auth", "src/billing"),
        ("app/api", "app/page.tsx"),
        ("database:billing", "database:users"),
        ("database:billing", "database"),
        ("foo/bar", "foo/barn"),
    ],
)
def test_scopes_do_not_overlap_for_siblings_or_distinct_named_keys(left: str, right: str) -> None:
    assert not scopes_overlap(left, right)
    assert not scopes_overlap(right, left)


def test_scope_set_overlap_checks_every_pair() -> None:
    assert scope_sets_overlap(("docs", "src/auth"), ("tests", "src/auth/login.py"))
    assert not scope_sets_overlap(("docs", "src/auth"), ("tests", "src/billing"))


def test_claim_request_is_strict_and_normalizes_boundary_strings() -> None:
    request = ClaimRequest.model_validate(
        {
            "owner_id": "  agent-1  ",
            "workstream": "  Login polish ",
            "scopes": ["  src/auth  "],
        }
    )
    assert request.owner_id == "agent-1"
    assert request.workstream == "Login polish"
    assert request.scopes == ("src/auth",)


def test_claim_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="unexpected"):
        ClaimRequest.model_validate(
            {
                "owner_id": "agent-1",
                "workstream": "login",
                "scopes": ["src/auth"],
                "unexpected": "rejected",
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"owner_id": "", "workstream": "work", "scopes": ["src"]},
        {"owner_id": "owner\nspoof", "workstream": "work", "scopes": ["src"]},
        {"owner_id": "owner", "workstream": "work", "scopes": []},
        {"owner_id": "owner", "workstream": "work", "scopes": ["src", "SRC"]},
        {
            "owner_id": "owner",
            "workstream": "work",
            "scopes": ["src"],
            "ttl_seconds": 14,
        },
        {
            "owner_id": "owner",
            "workstream": "work",
            "scopes": ["src"],
            "ttl_seconds": 86_401,
        },
        {
            "owner_id": "owner",
            "workstream": "work",
            "scopes": ["src"],
            "semantic_summary": "x" * 2_001,
        },
    ],
)
def test_claim_request_rejects_invalid_boundary_payloads(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ClaimRequest.model_validate(payload)


def test_claim_request_enforces_scope_count_and_item_bounds() -> None:
    with pytest.raises(ValidationError):
        ClaimRequest(
            owner_id="owner",
            workstream="work",
            scopes=tuple(f"src/{index}" for index in range(65)),
        )
    with pytest.raises(ValidationError):
        ClaimRequest(
            owner_id="owner",
            workstream="work",
            scopes=("x" * 1_025,),
        )


def test_config_rejects_non_loopback_bind_and_invalid_capacity(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="127.0.0.1"):
        GateholdConfig(state_dir=tmp_path, host="127.0.0.2")
    with pytest.raises(ValidationError):
        GateholdConfig(state_dir=tmp_path, max_heavy_slots=3)
    with pytest.raises(ValidationError, match="port_end"):
        GateholdConfig(state_dir=tmp_path, port_start=60_000, port_end=59_999)


def test_resource_allocation_rejects_invalid_port_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ResourceAllocation(port=1)
    with pytest.raises(ValidationError):
        ResourceAllocation.model_validate({"port": 55_000, "token": "secret"})


@pytest.mark.parametrize(
    "payload",
    [
        {
            "overlap": True,
            "confidence": SemanticConfidence.HIGH,
            "reason": SemanticReason.NONE,
        },
        {
            "overlap": True,
            "confidence": SemanticConfidence.HIGH,
            "reason": SemanticReason.UNCERTAIN,
        },
        {
            "overlap": False,
            "confidence": SemanticConfidence.HIGH,
            "reason": SemanticReason.SHARED_STATE,
        },
    ],
)
def test_semantic_model_output_rejects_incoherent_reason(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SemanticModelOutput.model_validate(payload)


def test_semantic_model_output_accepts_clear_overlap_and_uncertain_shapes() -> None:
    assert (
        SemanticModelOutput(
            overlap=False,
            confidence=SemanticConfidence.MEDIUM,
            reason=SemanticReason.NONE,
        ).reason
        is SemanticReason.NONE
    )
    assert (
        SemanticModelOutput(
            overlap=False,
            confidence=SemanticConfidence.LOW,
            reason=SemanticReason.UNCERTAIN,
        ).reason
        is SemanticReason.UNCERTAIN
    )
    assert (
        SemanticModelOutput(
            overlap=True,
            confidence=SemanticConfidence.HIGH,
            reason=SemanticReason.SAME_FEATURE,
        ).reason
        is SemanticReason.SAME_FEATURE
    )


def test_claim_outcome_shape_cannot_claim_grant_without_lease() -> None:
    assessment = SemanticAssessment(
        verdict=SemanticVerdict.SKIPPED,
        fallback=SemanticFallback.NO_COMPARABLE_LEASES,
    )
    with pytest.raises(ValidationError, match="granted outcome requires a lease"):
        ClaimOutcome.model_validate(
            {
                "decision": ClearanceDecision.GRANTED,
                "request_id": "request",
                "reasons": [ReasonCode.CLEAR],
                "semantic": assessment,
                "receipt": {
                    "receipt_id": "receipt",
                    "receipt_sha256": "a" * 64,
                    "input_sha256": "b" * 64,
                    "generated_at": "2026-07-20T09:00:00Z",
                    "request_id": "request",
                    "decision": ClearanceDecision.GRANTED,
                    "owner_sha256": "c" * 64,
                    "workstream_sha256": "d" * 64,
                    "scope_sha256": "e" * 64,
                    "reasons": [ReasonCode.CLEAR],
                    "semantic_verdict": SemanticVerdict.SKIPPED,
                },
            }
        )
