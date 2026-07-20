"""Privacy-safe hashes, credentials, and deterministic receipt construction."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Mapping, Sequence
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

_CHILD_ENVIRONMENT_ALLOWLIST = (
    "PATH",
    "HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "USER",
    "LOGNAME",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "TERM",
    "COLORTERM",
    "NO_COLOR",
    "FORCE_COLOR",
    "CI",
    "DEVELOPER_DIR",
    "SDKROOT",
    "VIRTUAL_ENV",
)
_MAX_PASSED_ENVIRONMENT_NAMES = 32
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_SECRET_ENVIRONMENT_MARKER = re.compile(
    r"(?:^|_)(?:API_?KEY|KEY|TOKEN|PAT|SECRET|PASSWORD|PASSWD|CREDENTIALS?|"
    r"AUTH|COOKIE|SESSION|PRIVATE|JWT)(?:_|$)"
)
# Bounded high-impact list: common credential carriers plus environment hooks
# that can load code or alternate configuration before the requested argv runs.
# Gatehold remains a cooperative governor, not a general environment sandbox.
_FORBIDDEN_CHILD_ENVIRONMENT_NAMES = frozenset(
    {
        "AWS_PROFILE",
        "BASH_ENV",
        "DATABASE_URL",
        "DOCKER_CONFIG",
        "DOTNET_ADDITIONAL_DEPS",
        "DOTNET_STARTUP_HOOKS",
        "GH_PAT",
        "GITHUB_PAT",
        "GITHUB_ENV",
        "GITHUB_OUTPUT",
        "GITHUB_PATH",
        "GITHUB_STATE",
        "GIT_ASKPASS",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_SYSTEM",
        "GIT_EXEC_PATH",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        "GPG_AGENT_INFO",
        "JDK_JAVA_OPTIONS",
        "JAVA_TOOL_OPTIONS",
        "KUBECONFIG",
        "LD_AUDIT",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "MYSQL_PWD",
        "NODE_OPTIONS",
        "NODE_PATH",
        "NPM_CONFIG_GLOBALCONFIG",
        "NPM_CONFIG_SCRIPT_SHELL",
        "NPM_CONFIG_USERCONFIG",
        "PERL5LIB",
        "PERL5OPT",
        "PGPASSFILE",
        "PGPASSWORD",
        "PHPRC",
        "PHP_INI_SCAN_DIR",
        "PIP_CONFIG_FILE",
        "PYTHONBREAKPOINT",
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONPLATLIBDIR",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "PYTHONWARNINGS",
        "REDIS_URL",
        "RUBYLIB",
        "RUBYOPT",
        "SENTRY_DSN",
        "SSH_AUTH_SOCK",
        "SSH_ASKPASS",
        "UV_CONFIG_FILE",
        "ZDOTDIR",
        "_JAVA_OPTIONS",
    }
)
_FORBIDDEN_CHILD_ENVIRONMENT_PREFIXES = ("DYLD_", "GATEHOLD_", "GIT_CONFIG_")


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


def safe_child_environment(
    source: Mapping[str, str],
    *,
    pass_names: Sequence[str] = (),
) -> dict[str, str]:
    """Keep runtime defaults plus explicitly requested non-secret settings."""

    if len(pass_names) > _MAX_PASSED_ENVIRONMENT_NAMES:
        raise ValueError(
            f"--pass-env may be repeated at most {_MAX_PASSED_ENVIRONMENT_NAMES} times"
        )

    environment = {
        name: source[name]
        for name in _CHILD_ENVIRONMENT_ALLOWLIST
        if name in source
    }
    for name in pass_names:
        normalized = name.upper()
        if not _ENVIRONMENT_NAME.fullmatch(name):
            raise ValueError("--pass-env requires a valid environment variable name")
        if (
            normalized in _FORBIDDEN_CHILD_ENVIRONMENT_NAMES
            or normalized.startswith(_FORBIDDEN_CHILD_ENVIRONMENT_PREFIXES)
            or _SECRET_ENVIRONMENT_MARKER.search(normalized)
        ):
            raise ValueError(f"--pass-env may not forward protected variable {name}")
        if name not in source:
            raise ValueError(f"--pass-env variable {name} is not set")
        environment[name] = source[name]
    return environment


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
