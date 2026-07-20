from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

import pytest
from helpers import ConfigFactory
from openai import OpenAI

from gatehold.admission import GateholdService
from gatehold.host import StaticHostProbe
from gatehold.models import (
    ClaimRequest,
    ClearanceDecision,
    ReasonCode,
    SemanticAssessment,
    SemanticCandidate,
    SemanticConfidence,
    SemanticFallback,
    SemanticModelOutput,
    SemanticReason,
    SemanticVerdict,
    WorkloadClass,
)
from gatehold.semantic import (
    MAX_SEMANTIC_PAYLOAD_BYTES,
    OpenAISemanticComparator,
    UnconfiguredSemanticComparator,
)


@dataclass
class FakeContent:
    type: str
    parsed: SemanticModelOutput | None = None


@dataclass
class FakeOutput:
    type: str
    content: tuple[FakeContent, ...]


@dataclass
class FakeResponse:
    output: tuple[FakeOutput, ...] = ()
    output_parsed: SemanticModelOutput | None = None


class FakeResponses:
    def __init__(
        self,
        *,
        response: FakeResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or FakeResponse()
        self.error = error
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeOpenAI:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def _comparator(
    fake_responses: FakeResponses,
    *,
    model: str = "gpt-5.6-sol-unit",
    timeout_seconds: float = 7.5,
) -> OpenAISemanticComparator:
    fake_client = cast(OpenAI, cast(object, FakeOpenAI(fake_responses)))
    return OpenAISemanticComparator(
        api_key="unit-test-placeholder",
        model=model,
        timeout_seconds=timeout_seconds,
        client=fake_client,
    )


def _clear_model_output() -> SemanticModelOutput:
    return SemanticModelOutput(
        overlap=False,
        confidence=SemanticConfidence.HIGH,
        reason=SemanticReason.NONE,
    )


def test_openai_comparator_uses_one_exact_bounded_structured_request() -> None:
    parsed = _clear_model_output()
    fake = FakeResponses(response=FakeResponse(output_parsed=parsed))
    comparator = _comparator(fake)
    candidate = SemanticCandidate(
        workstream="Auth refresh",
        scopes=("src/auth", "database:billing"),
        summary="Refresh login state",
    )
    active = SemanticCandidate(
        workstream="Billing retry",
        scopes=("src/billing",),
    )

    result = comparator.compare(candidate, active, active_lease_id="lease-123")

    assert result.verdict is SemanticVerdict.CLEAR
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert set(call) == {
        "model",
        "instructions",
        "input",
        "text_format",
        "reasoning",
        "max_output_tokens",
        "store",
        "timeout",
    }
    assert call["model"] == "gpt-5.6-sol-unit"
    assert call["text_format"] is SemanticModelOutput
    assert call["reasoning"] == {"effort": "low"}
    assert call["max_output_tokens"] == 300
    assert call["store"] is False
    assert call["timeout"] == 7.5
    assert "untrusted data" in cast(str, call["instructions"])
    assert "Do not call tools" in cast(str, call["instructions"])

    payload_text = cast(str, call["input"])
    payload = json.loads(payload_text)
    assert payload == {
        "active": {
            "scope_hints": ["<root>/src/billing"],
            "summary_hint": None,
            "workstream_hint": "Billing retry",
        },
        "candidate": {
            "scope_hints": ["<root>/src/auth", "database:billing"],
            "summary_hint": "Refresh login state",
            "workstream_hint": "Auth refresh",
        },
    }
    assert payload_text == json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def test_semantic_payload_redacts_absolute_user_paths_and_is_hard_bounded() -> None:
    private_path = "/Users/example/Secret Repo/src/private/file.py"
    scopes = (private_path, *(f"/Users/example/Secret Repo/src/area-{i}" for i in range(12)))
    summary = f"Review {private_path} before release. " + ("private context " * 100)
    fake = FakeResponses(response=FakeResponse(output_parsed=_clear_model_output()))
    comparator = _comparator(fake)

    comparator.compare(
        SemanticCandidate(
            workstream="Private repository review",
            scopes=scopes,
            summary=summary,
        ),
        SemanticCandidate(
            workstream="Other repository work",
            scopes=(private_path,),
            summary=f"Related location: {private_path}",
        ),
        active_lease_id="lease-private",
    )

    assert len(fake.calls) == 1
    payload_text = cast(str, fake.calls[0]["input"])
    assert len(payload_text.encode("utf-8")) <= MAX_SEMANTIC_PAYLOAD_BYTES
    assert "/Users/" not in payload_text
    assert "example" not in payload_text
    assert private_path not in payload_text
    payload = cast(dict[str, dict[str, object]], json.loads(payload_text))
    for side in ("candidate", "active"):
        wire_candidate = payload[side]
        scope_hints = cast(list[str], wire_candidate["scope_hints"])
        assert 1 <= len(scope_hints) <= 8
        assert all(hint.startswith("<root>/") for hint in scope_hints)
        assert all(len(hint) <= 96 for hint in scope_hints)
        assert len(cast(str, wire_candidate["workstream_hint"])) <= 96
        assert len(cast(str, wire_candidate["summary_hint"])) <= 320


def test_semantic_payload_redacts_email_and_common_secret_shapes() -> None:
    secrets = (
        "person@example.test",
        "sk-testsecret123456",
        "ghp_abcdefghijklmnop",
        "github_pat_abcdefghijklmnop",
        "OPENAI_API_KEY=sk-assignmentsecret123",
    )
    fake = FakeResponses(response=FakeResponse(output_parsed=_clear_model_output()))
    comparator = _comparator(fake)

    comparator.compare(
        SemanticCandidate(
            workstream=f"Review {secrets[0]}",
            scopes=("src/privacy",),
            summary=" ".join(secrets),
        ),
        SemanticCandidate(
            workstream="Privacy review",
            scopes=("src/other",),
            summary=f"Do not expose {secrets[1]}",
        ),
        active_lease_id="lease-secret-redaction",
    )

    payload_text = cast(str, fake.calls[0]["input"])
    for secret in secrets:
        assert secret not in payload_text
    assert "<email>" in payload_text
    assert "<secret>" in payload_text
    assert "OPENAI_API_KEY=<redacted>" in payload_text


@pytest.mark.parametrize(
    ("secret_text", "raw_secret"),
    [
        (
            "aws_access_key_id=" + "AKIA" + "A1B2C3D4E5F6G7H8",
            "AKIA" + "A1B2C3D4E5F6G7H8",
        ),
        (
            "AWS_SECRET_ACCESS_KEY=" + ("aB3/" * 10),
            "aB3/" * 10,
        ),
        (
            "jwt="
            + "eyJhbGciOiJIUzI1NiJ9"
            + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            + ".abcDEF0123456789abcDEF0123456789",
            "eyJhbGciOiJIUzI1NiJ9"
            + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            + ".abcDEF0123456789abcDEF0123456789",
        ),
        (
            "slack_token=" + "xoxb-" + "123456789012-" + "abcdefghijklmnopqrstuvwx",
            "xoxb-" + "123456789012-" + "abcdefghijklmnopqrstuvwx",
        ),
        (
            "api_key=" + "Q7v9mN2pL8xR4sT6uW3zA5cD",
            "Q7v9mN2pL8xR4sT6uW3zA5cD",
        ),
        (
            "Authorization: Bearer " + "T9m2Q7vL4xR8pN6sK3wZ5cD1",
            "T9m2Q7vL4xR8pN6sK3wZ5cD1",
        ),
        (
            "access_token=" + ("0123456789abcdef" * 2),
            "0123456789abcdef" * 2,
        ),
        (
            "STRIPE_SECRET_KEY=" + "S9t4R7i2P8e5K3y6V1a0L4u7",
            "S9t4R7i2P8e5K3y6V1a0L4u7",
        ),
        (
            "GITHUB_TOKEN=" + "G8h3T6o9K2e5N7v4A1l0U6e3",
            "G8h3T6o9K2e5N7v4A1l0U6e3",
        ),
        (
            "CUSTOM_API_KEY=" + "C7u4S9t2O5m8K3e6Y1v0A4l7",
            "C7u4S9t2O5m8K3e6Y1v0A4l7",
        ),
        (
            "stripe_secret_key=" + "S5t8R2i7P4e9K6y3V1a0L5u8",
            "S5t8R2i7P4e9K6y3V1a0L5u8",
        ),
        (
            "GitHub_Token=" + "G4h7T1o8K5e2N9v6A3l0U4e7",
            "G4h7T1o8K5e2N9v6A3l0U4e7",
        ),
        (
            "CUSTOM_API_KEY=" + "K9exampleR4d7Q2m8N6v3T1x5",
            "K9exampleR4d7Q2m8N6v3T1x5",
        ),
        (
            "GITHUB_TOKEN=" + "R7redactedZ9m4Q2v8L6s3T1c5",
            "R7redactedZ9m4Q2v8L6s3T1c5",
        ),
    ],
    ids=[
        "aws-access-key-id",
        "aws-secret-access-key",
        "jwt",
        "slack-token",
        "contextual-api-key",
        "bearer-token",
        "contextual-hex-token",
        "prefixed-stripe-secret-key",
        "prefixed-github-token",
        "prefixed-custom-api-key",
        "lowercase-prefixed-secret-key",
        "mixed-case-prefixed-token",
        "embedded-example-is-not-exempt",
        "embedded-redacted-is-not-exempt",
    ],
)
def test_semantic_payload_redacts_high_confidence_secret_formats(
    secret_text: str,
    raw_secret: str,
) -> None:
    fake = FakeResponses(response=FakeResponse(output_parsed=_clear_model_output()))
    comparator = _comparator(fake)

    comparator.compare(
        SemanticCandidate(
            workstream="Credential boundary review",
            scopes=("src/security",),
            summary=f"Never send {secret_text} to the model",
        ),
        SemanticCandidate(workstream="Other work", scopes=("src/other",)),
        active_lease_id="lease-high-confidence-secret",
    )

    payload_text = cast(str, fake.calls[0]["input"])
    assert raw_secret not in payload_text
    assert "<secret>" in payload_text


@pytest.mark.parametrize(
    "benign_text",
    [
        "Document api_key=placeholder-value-for-local-tests",
        "Document access_token=example-token-value-2026",
        "Set client_secret=not-a-secret-placeholder",
        "Document CUSTOM_API_KEY=placeholder-value-for-local-tests",
        "Document GITHUB_TOKEN=example-token-value-2026",
        "Set STRIPE_SECRET_KEY=not-a-secret-placeholder",
        "Document stripe_secret_key=placeholder-value-for-local-tests",
        "Document GitHub_Token=example-token-value-2026",
        "A JWT starts with eyJ but this has only two.parts",
        "Slack uses an xoxb-short prefix in examples",
        "AWS access key IDs begin with AKIA123 in this format note",
        "Compare commit 0123456789abcdef0123456789abcdef01234567",
        "The release token budget is 4096",
    ],
)
def test_semantic_payload_preserves_benign_secret_like_text(benign_text: str) -> None:
    fake = FakeResponses(response=FakeResponse(output_parsed=_clear_model_output()))

    _comparator(fake).compare(
        SemanticCandidate(
            workstream="Security documentation",
            scopes=("docs/security",),
            summary=benign_text,
        ),
        SemanticCandidate(workstream="Other work", scopes=("src/other",)),
        active_lease_id="lease-benign-secret-like-text",
    )

    payload = cast(dict[str, dict[str, object]], json.loads(cast(str, fake.calls[0]["input"])))
    assert payload["candidate"]["summary_hint"] == benign_text


@pytest.mark.parametrize(
    ("parsed", "expected_verdict", "expected_reason"),
    [
        (
            SemanticModelOutput(
                overlap=True,
                confidence=SemanticConfidence.HIGH,
                reason=SemanticReason.SAME_FEATURE,
            ),
            SemanticVerdict.HOLD,
            SemanticReason.SAME_FEATURE,
        ),
        (
            SemanticModelOutput(
                overlap=False,
                confidence=SemanticConfidence.MEDIUM,
                reason=SemanticReason.NONE,
            ),
            SemanticVerdict.CLEAR,
            SemanticReason.NONE,
        ),
    ],
)
def test_valid_semantic_output_maps_to_bounded_assessment(
    parsed: SemanticModelOutput,
    expected_verdict: SemanticVerdict,
    expected_reason: SemanticReason,
) -> None:
    fake = FakeResponses(
        response=FakeResponse(
            output=(
                FakeOutput(
                    type="message",
                    content=(FakeContent(type="output_text", parsed=parsed),),
                ),
            )
        )
    )

    assessment = _comparator(fake).compare(
        SemanticCandidate(workstream="candidate", scopes=("src/a",)),
        SemanticCandidate(workstream="active", scopes=("src/b",)),
        active_lease_id="lease-1",
    )

    assert assessment.verdict is expected_verdict
    assert assessment.reason is expected_reason
    assert assessment.confidence is parsed.confidence
    assert assessment.compared_lease_id == "lease-1"
    assert assessment.fallback is None


def test_refusal_wins_over_any_output_parsed_value() -> None:
    fake = FakeResponses(
        response=FakeResponse(
            output=(
                FakeOutput(
                    type="message",
                    content=(FakeContent(type="refusal"),),
                ),
            ),
            output_parsed=_clear_model_output(),
        )
    )

    assessment = _comparator(fake).compare(
        SemanticCandidate(workstream="candidate", scopes=("src/a",)),
        SemanticCandidate(workstream="active", scopes=("src/b",)),
        active_lease_id="lease-refused",
    )

    assert assessment.verdict is SemanticVerdict.UNCERTAIN
    assert assessment.reason is SemanticReason.UNCERTAIN
    assert assessment.fallback is SemanticFallback.REFUSAL
    assert assessment.compared_lease_id == "lease-refused"


def test_api_error_falls_back_without_retry() -> None:
    fake = FakeResponses(error=TimeoutError("synthetic timeout"))

    assessment = _comparator(fake).compare(
        SemanticCandidate(workstream="candidate", scopes=("src/a",)),
        SemanticCandidate(workstream="active", scopes=("src/b",)),
        active_lease_id="lease-timeout",
    )

    assert len(fake.calls) == 1
    assert assessment.verdict is SemanticVerdict.UNCERTAIN
    assert assessment.fallback is SemanticFallback.API_ERROR
    assert assessment.model == "gpt-5.6-sol-unit"


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(),
        FakeResponse(
            output=(
                FakeOutput(
                    type="message",
                    content=(FakeContent(type="output_text"),),
                ),
            )
        ),
        FakeResponse(
            output=(
                FakeOutput(
                    type="tool_call",
                    content=(FakeContent(type="output_text", parsed=_clear_model_output()),),
                ),
            )
        ),
    ],
)
def test_missing_or_invalid_output_falls_back_to_uncertain(
    response: FakeResponse,
) -> None:
    assessment = _comparator(FakeResponses(response=response)).compare(
        SemanticCandidate(workstream="candidate", scopes=("src/a",)),
        SemanticCandidate(workstream="active", scopes=("src/b",)),
        active_lease_id="lease-invalid",
    )

    assert assessment.verdict is SemanticVerdict.UNCERTAIN
    assert assessment.reason is SemanticReason.UNCERTAIN
    assert assessment.fallback is SemanticFallback.INVALID_OUTPUT


def test_model_uncertain_reason_is_treated_as_invalid_clearance_signal() -> None:
    parsed = SemanticModelOutput(
        overlap=False,
        confidence=SemanticConfidence.LOW,
        reason=SemanticReason.UNCERTAIN,
    )
    assessment = _comparator(FakeResponses(response=FakeResponse(output_parsed=parsed))).compare(
        SemanticCandidate(workstream="candidate", scopes=("src/a",)),
        SemanticCandidate(workstream="active", scopes=("src/b",)),
        active_lease_id="lease-uncertain",
    )

    assert assessment.verdict is SemanticVerdict.UNCERTAIN
    assert assessment.confidence is SemanticConfidence.LOW
    assert assessment.fallback is SemanticFallback.INVALID_OUTPUT


def test_unconfigured_comparator_is_explicitly_uncertain() -> None:
    assessment = UnconfiguredSemanticComparator().compare(
        SemanticCandidate(workstream="candidate", scopes=("src/a",)),
        SemanticCandidate(workstream="active", scopes=("src/b",)),
        active_lease_id="lease-unconfigured",
    )

    assert assessment.verdict is SemanticVerdict.UNCERTAIN
    assert assessment.fallback is SemanticFallback.UNCONFIGURED
    assert assessment.model is None


class FixedComparator:
    def __init__(
        self,
        verdict: SemanticVerdict,
        *,
        fallback: SemanticFallback | None = None,
    ) -> None:
        self.verdict = verdict
        self.fallback = fallback
        self.calls = 0

    def compare(
        self,
        candidate: SemanticCandidate,
        active: SemanticCandidate,
        *,
        active_lease_id: str,
    ) -> SemanticAssessment:
        del candidate, active
        self.calls += 1
        reason = (
            SemanticReason.SAME_FEATURE
            if self.verdict is SemanticVerdict.HOLD
            else SemanticReason.NONE
        )
        if self.verdict is SemanticVerdict.UNCERTAIN:
            reason = SemanticReason.UNCERTAIN
        return SemanticAssessment(
            verdict=self.verdict,
            model="fake-comparator",
            compared_lease_id=active_lease_id,
            confidence=SemanticConfidence.HIGH,
            reason=reason,
            fallback=self.fallback,
        )


def _service_request(owner: str, workstream: str, scope: str) -> ClaimRequest:
    return ClaimRequest(
        owner_id=owner,
        workstream=workstream,
        scopes=(scope,),
        workload=WorkloadClass.LIGHT,
    )


def test_valid_model_hold_can_only_add_a_hold(
    config_factory: ConfigFactory,
) -> None:
    comparator = FixedComparator(SemanticVerdict.HOLD)
    service = GateholdService(
        config_factory(),
        host_probe=StaticHostProbe(),
        semantic_comparator=comparator,
    )
    first = service.claim(_service_request("a", "auth", "src/auth"))
    assert first.lease is not None

    second = service.claim(_service_request("b", "billing", "src/billing"))

    assert comparator.calls == 1
    assert second.decision is ClearanceDecision.SEMANTIC_HOLD
    assert second.reasons == (ReasonCode.MODEL_OVERLAP,)
    assert second.conflicts == ()


def test_model_error_preserves_deterministic_clear_result(
    config_factory: ConfigFactory,
) -> None:
    comparator = FixedComparator(
        SemanticVerdict.UNCERTAIN,
        fallback=SemanticFallback.API_ERROR,
    )
    service = GateholdService(
        config_factory(),
        host_probe=StaticHostProbe(),
        semantic_comparator=comparator,
    )
    first = service.claim(_service_request("a", "auth", "src/auth"))
    assert first.lease is not None

    second = service.claim(_service_request("b", "billing", "src/billing"))

    assert comparator.calls == 1
    assert second.decision is ClearanceDecision.GRANTED
    assert second.semantic.verdict is SemanticVerdict.UNCERTAIN
    assert second.semantic.fallback is SemanticFallback.API_ERROR


def test_model_clear_cannot_override_deterministic_host_capacity(
    config_factory: ConfigFactory,
) -> None:
    comparator = FixedComparator(SemanticVerdict.CLEAR)
    service = GateholdService(
        config_factory(cpu_limit_percent=50),
        host_probe=StaticHostProbe(cpu_percent=99),
        semantic_comparator=comparator,
    )
    first = service.claim(_service_request("a", "auth", "src/auth"))
    assert first.lease is not None
    heavy = ClaimRequest(
        owner_id="b",
        workstream="billing",
        scopes=("src/billing",),
        workload=WorkloadClass.HEAVY,
    )

    second = service.claim(heavy)

    assert comparator.calls == 1
    assert second.decision is ClearanceDecision.QUEUED
    assert ReasonCode.HOST_CPU_PRESSURE in second.reasons


def test_semantic_cache_is_bound_to_summary_digest_without_persisting_summary(
    config_factory: ConfigFactory,
) -> None:
    summaries: list[str | None] = []

    class SummaryRecordingComparator:
        def compare(
            self,
            candidate: SemanticCandidate,
            active: SemanticCandidate,
            *,
            active_lease_id: str,
        ) -> SemanticAssessment:
            del active
            summaries.append(candidate.summary)
            return SemanticAssessment(
                verdict=SemanticVerdict.CLEAR,
                model="fake-summary-cache",
                compared_lease_id=active_lease_id,
                confidence=SemanticConfidence.HIGH,
                reason=SemanticReason.NONE,
            )

    config = config_factory(cpu_limit_percent=50)
    service = GateholdService(
        config,
        host_probe=StaticHostProbe(cpu_percent=99),
        semantic_comparator=SummaryRecordingComparator(),
    )
    active = service.claim(_service_request("a", "auth", "src/auth"))
    assert active.lease is not None
    first_summary = "semantic-summary-alpha-unique"
    second_summary = "semantic-summary-beta-unique"
    queued_request = ClaimRequest(
        owner_id="b",
        workstream="billing",
        scopes=("src/billing",),
        workload=WorkloadClass.HEAVY,
        semantic_summary=first_summary,
    )

    queued = service.claim(queued_request)
    assert queued.decision is ClearanceDecision.QUEUED
    assert queued.queue_token is not None
    changed_request = queued_request.model_copy(
        update={"semantic_summary": second_summary}
    )
    resumed = service.claim(
        changed_request,
        request_id=queued.request_id,
        queue_token=queued.queue_token,
    )
    cached_resume = service.claim(
        changed_request,
        request_id=queued.request_id,
        queue_token=queued.queue_token,
    )

    assert resumed.decision is ClearanceDecision.QUEUED
    assert cached_resume.decision is ClearanceDecision.QUEUED
    assert summaries == [first_summary, second_summary]
    with service.store.reader() as connection:
        row = connection.execute(
            """
            SELECT active_set_sha256
            FROM semantic_cache
            WHERE request_id = ?
            """,
            (queued.request_id,),
        ).fetchone()
    assert row is not None
    assert len(str(row["active_set_sha256"])) == 64
    for path in config.state_dir.glob("gatehold.sqlite3*"):
        persisted = path.read_bytes()
        assert first_summary.encode() not in persisted
        assert second_summary.encode() not in persisted


def test_stale_model_hold_cannot_hold_after_compared_lease_is_released(
    config_factory: ConfigFactory,
) -> None:
    service = GateholdService(config_factory(), host_probe=StaticHostProbe())
    first_request = _service_request("a", "auth", "src/auth")
    first = service.claim(first_request)
    assert first.lease is not None
    heartbeat_token = first.lease.heartbeat_token

    class ReleasingHoldComparator:
        def compare(
            self,
            candidate: SemanticCandidate,
            active: SemanticCandidate,
            *,
            active_lease_id: str,
        ) -> SemanticAssessment:
            del candidate, active
            service.release(
                lease_id=active_lease_id,
                owner_id=first_request.owner_id,
                heartbeat_token=heartbeat_token,
            )
            return SemanticAssessment(
                verdict=SemanticVerdict.HOLD,
                model="fake-stale",
                compared_lease_id=active_lease_id,
                confidence=SemanticConfidence.HIGH,
                reason=SemanticReason.SAME_FEATURE,
            )

    service.semantic_comparator = ReleasingHoldComparator()
    second = service.claim(_service_request("b", "billing", "src/billing"))

    assert second.decision is ClearanceDecision.GRANTED
    assert second.semantic.verdict is SemanticVerdict.UNCERTAIN
    assert second.semantic.fallback is SemanticFallback.STALE_COMPARISON
