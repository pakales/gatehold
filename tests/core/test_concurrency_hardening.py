"""Regression tests for semantic races, cost bounds, and profile cleanup."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gatehold.admission import GateholdService
from gatehold.config import GateholdConfig
from gatehold.host import StaticHostProbe
from gatehold.models import (
    ClaimRequest,
    ClearanceDecision,
    ResourceRequest,
    SemanticAssessment,
    SemanticCandidate,
    SemanticConfidence,
    SemanticReason,
    SemanticVerdict,
    WorkloadClass,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 20, 8, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def _request(
    owner: str,
    workstream: str,
    scope: str,
    *,
    workload: WorkloadClass = WorkloadClass.LIGHT,
    ttl_seconds: int = 60,
    browser_profile: bool = False,
) -> ClaimRequest:
    return ClaimRequest(
        owner_id=owner,
        workstream=workstream,
        scopes=(scope,),
        workload=workload,
        ttl_seconds=ttl_seconds,
        resources=ResourceRequest(browser_profile=browser_profile),
    )


def _clear(active_lease_id: str) -> SemanticAssessment:
    return SemanticAssessment(
        verdict=SemanticVerdict.CLEAR,
        model="fake",
        compared_lease_id=active_lease_id,
        confidence=SemanticConfidence.HIGH,
        reason=SemanticReason.NONE,
    )


def test_model_latency_does_not_consume_new_lease_ttl(tmp_path: Path) -> None:
    clock = MutableClock()
    config = GateholdConfig(state_dir=tmp_path / "state")
    local = GateholdService(config, host_probe=StaticHostProbe(), now=clock)
    anchor = local.claim(_request("anchor", "anchor", "src/anchor"))
    assert anchor.lease is not None

    class AdvancingComparator:
        def compare(
            self,
            candidate: SemanticCandidate,
            active: SemanticCandidate,
            *,
            active_lease_id: str,
        ) -> SemanticAssessment:
            del candidate, active
            clock.advance(12)
            return _clear(active_lease_id)

    service = GateholdService(
        config,
        host_probe=StaticHostProbe(),
        semantic_comparator=AdvancingComparator(),
        now=clock,
    )
    result = service.claim(_request("candidate", "candidate", "src/candidate", ttl_seconds=15))

    assert result.lease is not None
    assert result.lease.granted_at == clock.value
    assert result.lease.expires_at - result.lease.granted_at == timedelta(seconds=15)


def test_new_active_lease_during_semantic_call_is_compared_before_grant(
    tmp_path: Path,
) -> None:
    config = GateholdConfig(state_dir=tmp_path / "state")
    local = GateholdService(config, host_probe=StaticHostProbe())
    anchor = local.claim(_request("anchor", "anchor", "src/anchor"))
    assert anchor.lease is not None

    class InjectingComparator:
        def __init__(self) -> None:
            self.injected_lease_id: str | None = None

        def compare(
            self,
            candidate: SemanticCandidate,
            active: SemanticCandidate,
            *,
            active_lease_id: str,
        ) -> SemanticAssessment:
            del candidate, active
            if self.injected_lease_id is None:
                injected = local.claim(_request("injected", "hidden duplicate", "src/disjoint-new"))
                assert injected.lease is not None
                self.injected_lease_id = injected.lease.lease_id
                return _clear(active_lease_id)
            if active_lease_id == self.injected_lease_id:
                return SemanticAssessment(
                    verdict=SemanticVerdict.HOLD,
                    model="fake",
                    compared_lease_id=active_lease_id,
                    confidence=SemanticConfidence.HIGH,
                    reason=SemanticReason.SAME_FEATURE,
                )
            return _clear(active_lease_id)

    comparator = InjectingComparator()
    service = GateholdService(
        config,
        host_probe=StaticHostProbe(),
        semantic_comparator=comparator,
    )
    result = service.claim(_request("candidate", "candidate", "src/disjoint-candidate"))

    assert comparator.injected_lease_id is not None
    assert result.decision is ClearanceDecision.SEMANTIC_HOLD
    assert result.lease is None
    assert result.semantic.compared_lease_id == comparator.injected_lease_id


def test_unchanged_active_set_reuses_semantic_cache_across_queue_polls(
    tmp_path: Path,
) -> None:
    config = GateholdConfig(
        state_dir=tmp_path / "state",
        cpu_limit_percent=50,
    )
    local = GateholdService(config, host_probe=StaticHostProbe())
    anchor = local.claim(_request("anchor", "anchor", "src/anchor"))
    assert anchor.lease is not None

    class CountingComparator:
        def __init__(self) -> None:
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
            return _clear(active_lease_id)

    comparator = CountingComparator()
    service = GateholdService(
        config,
        host_probe=StaticHostProbe(cpu_percent=95),
        semantic_comparator=comparator,
    )
    request = _request(
        "waiting",
        "waiting",
        "src/waiting",
        workload=WorkloadClass.HEAVY,
    )
    outcome = service.claim(request)
    assert outcome.decision is ClearanceDecision.QUEUED
    assert outcome.queue_token is not None

    for _ in range(3):
        outcome = service.claim(
            request,
            request_id=outcome.request_id,
            queue_token=outcome.queue_token,
        )
        assert outcome.decision is ClearanceDecision.QUEUED

    assert comparator.calls == 1


def test_release_unlinks_replaced_profile_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    config = GateholdConfig(state_dir=tmp_path / "state")
    service = GateholdService(config, host_probe=StaticHostProbe())
    request = _request(
        "owner",
        "profile",
        "src/profile",
        browser_profile=True,
    )
    outcome = service.claim(request)
    assert outcome.lease is not None
    profile = Path(outcome.lease.resources.browser_profile or "")
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    shutil.rmtree(profile)
    profile.symlink_to(external, target_is_directory=True)
    service.release(
        lease_id=outcome.lease.lease_id,
        owner_id=request.owner_id,
        heartbeat_token=outcome.lease.heartbeat_token,
    )

    assert not profile.exists()
    assert marker.read_text(encoding="utf-8") == "keep"
