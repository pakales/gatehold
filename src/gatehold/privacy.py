"""Privacy-safe hashes, credentials, and deterministic receipt construction."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .conflicts import canonical_scope, canonical_workstream
from .models import (
    ClearanceDecision,
    EstimatedSavings,
    ReasonCode,
    Receipt,
    SemanticAssessment,
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def scope_digest(scopes: tuple[str, ...] | list[str]) -> str:
    canonical = sorted({canonical_scope(scope) for scope in scopes})
    return sha256_text(json.dumps(canonical, separators=(",", ":"), ensure_ascii=False))


def new_secret() -> str:
    """Return a high-entropy secret that is also safe as a CLI option value."""

    return f"gh_{secrets.token_urlsafe(32)}"


def secret_digest(secret: str) -> str:
    return sha256_text(secret)


def verify_secret(secret: str, expected_digest: str) -> bool:
    return hmac.compare_digest(secret_digest(secret), expected_digest)


def executable_name(argv0: str) -> str:
    """Reduce a command to a basename suitable for durable storage."""

    value = Path(argv0).name.strip()
    if not value:
        raise ValueError("command executable must not be empty")
    return value[:255]


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def make_receipt(
    *,
    generated_at: datetime,
    request_id: str,
    lease_id: str | None,
    decision: ClearanceDecision,
    owner_id: str,
    workstream: str,
    scopes: tuple[str, ...] | list[str],
    reasons: tuple[ReasonCode, ...],
    semantic: SemanticAssessment,
    expires_at: datetime | None = None,
    command_executable: str | None = None,
    estimated_savings_minutes: float | None = None,
) -> Receipt:
    """Build a receipt containing hashes and bounded enums, never raw scopes."""

    generated_at = generated_at.astimezone(UTC)
    safe_payload: dict[str, Any] = {
        "schema": "gatehold.receipt.v1",
        "generated_at": generated_at.isoformat(),
        "request_id": request_id,
        "lease_id": lease_id,
        "decision": decision.value,
        "owner_sha256": sha256_text(owner_id),
        "workstream_sha256": sha256_text(canonical_workstream(workstream)),
        "scope_sha256": scope_digest(scopes),
        "reasons": [reason.value for reason in reasons],
        "semantic_verdict": semantic.verdict.value,
        "semantic_model": semantic.model,
        "expires_at": expires_at.astimezone(UTC).isoformat() if expires_at else None,
        "executable_name": command_executable,
        "estimated_savings": (
            {"label": "estimate", "minutes": estimated_savings_minutes}
            if estimated_savings_minutes is not None
            else None
        ),
    }
    input_payload = {
        key: value
        for key, value in safe_payload.items()
        if key not in {"generated_at", "lease_id", "expires_at"}
    }
    input_sha256 = hashlib.sha256(_canonical_json(input_payload)).hexdigest()
    receipt_sha256 = hashlib.sha256(_canonical_json(safe_payload)).hexdigest()
    return Receipt(
        receipt_id=str(uuid4()),
        receipt_sha256=receipt_sha256,
        input_sha256=input_sha256,
        generated_at=generated_at,
        request_id=request_id,
        lease_id=lease_id,
        decision=decision,
        owner_sha256=safe_payload["owner_sha256"],
        workstream_sha256=safe_payload["workstream_sha256"],
        scope_sha256=safe_payload["scope_sha256"],
        reasons=reasons,
        semantic_verdict=semantic.verdict,
        semantic_model=semantic.model,
        expires_at=expires_at,
        executable_name=command_executable,
        estimated_savings=(
            EstimatedSavings(minutes=estimated_savings_minutes)
            if estimated_savings_minutes is not None
            else None
        ),
    )
