from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gatehold.models import (
    ClearanceDecision,
    EstimatedSavings,
    ReasonCode,
    SemanticAssessment,
    SemanticFallback,
    SemanticReason,
    SemanticVerdict,
)
from gatehold.privacy import (
    executable_name,
    make_receipt,
    new_secret,
    safe_child_environment,
    scope_digest,
    secret_digest,
    verify_secret,
)


def _semantic() -> SemanticAssessment:
    return SemanticAssessment(
        verdict=SemanticVerdict.SKIPPED,
        reason=SemanticReason.UNCERTAIN,
        fallback=SemanticFallback.NO_COMPARABLE_LEASES,
    )


def test_receipt_contains_hashes_and_never_raw_owner_workstream_or_scopes() -> None:
    owner = "person@example.test"
    workstream = "Private Customer Billing Migration"
    scopes = (
        "/Users/example/Secret Repo/src/billing",
        "database:private-ledger",
    )

    receipt = make_receipt(
        generated_at=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
        request_id="request-123",
        lease_id="lease-123",
        decision=ClearanceDecision.GRANTED,
        owner_id=owner,
        workstream=workstream,
        scopes=scopes,
        reasons=(ReasonCode.CLEAR,),
        semantic=_semantic(),
        expires_at=datetime(2026, 7, 20, 9, 15, tzinfo=UTC),
        command_executable="python3",
    )
    serialized = receipt.model_dump_json()

    assert owner not in serialized
    assert workstream not in serialized
    assert all(scope not in serialized for scope in scopes)
    assert receipt.owner_sha256 == secret_digest(owner)
    assert receipt.scope_sha256 == scope_digest(scopes)
    assert receipt.executable_name == "python3"


def test_receipt_input_digest_ignores_transient_issuance_fields() -> None:
    base_time = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
    common: dict[str, object] = {
        "request_id": "request-stable",
        "decision": ClearanceDecision.GRANTED,
        "owner_id": "owner",
        "workstream": "work",
        "scopes": ("src/work",),
        "reasons": (ReasonCode.CLEAR,),
        "semantic": _semantic(),
        "command_executable": "pytest",
    }
    first = make_receipt(
        generated_at=base_time,
        lease_id="lease-a",
        expires_at=base_time + timedelta(minutes=10),
        **common,  # type: ignore[arg-type]
    )
    second = make_receipt(
        generated_at=base_time + timedelta(seconds=1),
        lease_id="lease-b",
        expires_at=base_time + timedelta(minutes=20),
        **common,  # type: ignore[arg-type]
    )

    assert first.input_sha256 == second.input_sha256
    assert first.receipt_sha256 != second.receipt_sha256
    assert first.receipt_id != second.receipt_id


def test_receipt_input_digest_changes_with_decision_content() -> None:
    now = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
    clear = make_receipt(
        generated_at=now,
        request_id="request",
        lease_id=None,
        decision=ClearanceDecision.QUEUED,
        owner_id="owner",
        workstream="work",
        scopes=("src/work",),
        reasons=(ReasonCode.HOST_CPU_PRESSURE,),
        semantic=_semantic(),
    )
    changed_scope = make_receipt(
        generated_at=now,
        request_id="request",
        lease_id=None,
        decision=ClearanceDecision.QUEUED,
        owner_id="owner",
        workstream="work",
        scopes=("src/other",),
        reasons=(ReasonCode.HOST_CPU_PRESSURE,),
        semantic=_semantic(),
    )
    changed_reason = make_receipt(
        generated_at=now,
        request_id="request",
        lease_id=None,
        decision=ClearanceDecision.QUEUED,
        owner_id="owner",
        workstream="work",
        scopes=("src/work",),
        reasons=(ReasonCode.HOST_MEMORY_PRESSURE,),
        semantic=_semantic(),
    )

    assert len({clear.input_sha256, changed_scope.input_sha256, changed_reason.input_sha256}) == 3


def test_scope_digest_is_order_independent_and_lexically_canonical() -> None:
    first = scope_digest(("SRC/Auth/", r"src\billing"))
    second = scope_digest(("src/billing", "src/auth"))
    with_duplicate = scope_digest(("src/auth", "src/auth", "src/billing"))

    assert first == second == with_duplicate


def test_credentials_are_random_hashed_and_constant_time_verifiable() -> None:
    first = new_secret()
    second = new_secret()

    assert len(first) >= 32
    assert len(second) >= 32
    assert first.startswith("gh_")
    assert second.startswith("gh_")
    assert first != second
    assert secret_digest(first) != first
    assert verify_secret(first, secret_digest(first))
    assert not verify_secret(second, secret_digest(first))


def test_generated_secret_cannot_look_like_a_cli_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def option_like_secret(_byte_count: int) -> str:
        return f"-{'a' * 42}"

    monkeypatch.setattr(
        "gatehold.privacy.secrets.token_urlsafe",
        option_like_secret,
    )

    token = new_secret()

    assert token == f"gh_-{'a' * 42}"
    assert not token.startswith("-")


def test_safe_child_environment_preserves_only_required_runtime_settings() -> None:
    environment = {
        "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
        "HOME": "/Users/example",
        "TMPDIR": "/private/tmp/example",
        "LANG": "lt_LT.UTF-8",
        "TERM": "xterm-256color",
        "CI": "true",
        "DEVELOPER_DIR": "/Applications/Xcode.app/Contents/Developer",
        "SDKROOT": "iphoneos",
        "VIRTUAL_ENV": "/repo/.venv",
        "UNRELATED_FEATURE_FLAG": "must-not-propagate",
    }

    child_environment = safe_child_environment(environment)

    assert child_environment == {
        "PATH": environment["PATH"],
        "HOME": environment["HOME"],
        "TMPDIR": environment["TMPDIR"],
        "LANG": environment["LANG"],
        "TERM": environment["TERM"],
        "CI": environment["CI"],
        "DEVELOPER_DIR": environment["DEVELOPER_DIR"],
        "SDKROOT": environment["SDKROOT"],
        "VIRTUAL_ENV": environment["VIRTUAL_ENV"],
    }


def test_safe_child_environment_passes_bounded_non_secret_tool_settings() -> None:
    environment = {
        "PATH": "/usr/bin:/bin",
        "UV_CACHE_DIR": "/Users/example/Library/Caches/uv",
        "NPM_CONFIG_CACHE": "/Users/example/Library/Caches/npm",
        "NODE_ENV": "test",
        "AWS_REGION": "eu-west-1",
        "GITHUB_REPOSITORY": "example/repository",
        "PGHOST": "127.0.0.1",
        "PGPORT": "5432",
    }

    child_environment = safe_child_environment(
        environment,
        pass_names=(
            "UV_CACHE_DIR",
            "NPM_CONFIG_CACHE",
            "NODE_ENV",
            "AWS_REGION",
            "GITHUB_REPOSITORY",
            "PGHOST",
            "PGPORT",
        ),
    )

    assert child_environment == environment


@pytest.mark.parametrize(
    "secret_name",
    [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "GITHUB_TOKEN",
        "GITHUB_PAT",
        "GH_PAT",
        "GITHUB_ENV",
        "GH_TOKEN",
        "NPM_TOKEN",
        "DATABASE_URL",
        "PGPASSWORD",
        "STRIPE_SECRET_KEY",
        "SSH_AUTH_SOCK",
        "CUSTOM_INTERNAL_SECRET",
    ],
)
def test_safe_child_environment_strips_cloud_and_common_secrets(
    secret_name: str,
) -> None:
    child_environment = safe_child_environment(
        {
            "PATH": "/usr/bin:/bin",
            secret_name: "test-only-secret",
        }
    )

    assert child_environment == {"PATH": "/usr/bin:/bin"}


@pytest.mark.parametrize(
    "protected_name",
    [
        "OPENAI_API_KEY",
        "GATEHOLD_HEARTBEAT_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GH_PAT",
        "GITHUB_PAT",
        "DATABASE_URL",
        "PGPASSWORD",
        "PGPASSFILE",
        "MYSQL_PWD",
        "SSH_AUTH_SOCK",
        "BASH_ENV",
        "NODE_OPTIONS",
        "NODE_PATH",
        "PYTHONPATH",
        "PYTHONBREAKPOINT",
        "PYTHONUSERBASE",
        "RUBYOPT",
        "PERL5OPT",
        "JAVA_TOOL_OPTIONS",
        "_JAVA_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "LD_AUDIT",
        "DOTNET_STARTUP_HOOKS",
        "PHPRC",
        "NPM_CONFIG_USERCONFIG",
        "NPM_CONFIG_SCRIPT_SHELL",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "GIT_SSH_COMMAND",
        "GIT_CONFIG_KEY_0",
        "PIP_CONFIG_FILE",
        "UV_CONFIG_FILE",
        "ZDOTDIR",
        "DYLD_INSERT_LIBRARIES",
    ],
)
def test_safe_child_environment_rejects_explicit_protected_passthrough(
    protected_name: str,
) -> None:
    with pytest.raises(ValueError, match="may not forward protected variable"):
        safe_child_environment(
            {protected_name: "test-only-secret"},
            pass_names=(protected_name,),
        )


@pytest.mark.parametrize("invalid_name", ["", "WITH-DASH", " LEADING", "A" * 129])
def test_safe_child_environment_rejects_invalid_passthrough_names(
    invalid_name: str,
) -> None:
    with pytest.raises(ValueError, match="valid environment variable name"):
        safe_child_environment(
            {invalid_name: "value"},
            pass_names=(invalid_name,),
        )


def test_safe_child_environment_rejects_missing_or_excessive_passthrough() -> None:
    with pytest.raises(ValueError, match="MISSING is not set"):
        safe_child_environment({}, pass_names=("MISSING",))
    with pytest.raises(ValueError, match="at most 32"):
        safe_child_environment(
            {},
            pass_names=tuple(f"SAFE_{index}" for index in range(33)),
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/usr/local/bin/python3", "python3"),
        (r"C:\tools\gatehold.exe", r"C:\tools\gatehold.exe"),
        ("  pytest  ", "pytest"),
    ],
)
def test_executable_name_keeps_only_bounded_basename(raw: str, expected: str) -> None:
    assert executable_name(raw) == expected


def test_executable_name_rejects_empty_and_bounds_length() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        executable_name("   ")
    assert len(executable_name("/bin/" + "x" * 300)) == 255


def test_savings_field_is_explicitly_labeled_estimate() -> None:
    savings = EstimatedSavings(minutes=12.5)

    assert savings.label == "estimate"
    assert savings.model_dump() == {"label": "estimate", "minutes": 12.5}
