from __future__ import annotations

import socket
import stat
from pathlib import Path

import pytest
from helpers import ConfigFactory

from gatehold.admission import GateholdService
from gatehold.host import StaticHostProbe
from gatehold.models import (
    ClaimRequest,
    ClearanceDecision,
    ReasonCode,
    ResourceRequest,
    WorkloadClass,
)


def _always_available(_port: int) -> bool:
    return True


def _never_available(_port: int) -> bool:
    return False


def _resource_request(
    owner: str,
    *,
    port: bool = False,
    browser_profile: bool = False,
    simulator: bool = False,
) -> ClaimRequest:
    return ClaimRequest(
        owner_id=owner,
        workstream=f"resource lane {owner}",
        scopes=(f"src/{owner}",),
        workload=WorkloadClass.LIGHT,
        resources=ResourceRequest(
            port=port,
            browser_profile=browser_profile,
            simulator=simulator,
        ),
    )


def test_port_leases_are_exclusive_and_reusable_after_release(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("gatehold.resources._port_is_available", _always_available)
    service = GateholdService(
        config_factory(port_start=55_100, port_end=55_100),
        host_probe=StaticHostProbe(),
    )
    first_request = _resource_request("first", port=True)
    second_request = _resource_request("second", port=True)

    first = service.claim(first_request)
    second = service.claim(second_request)

    assert first.lease is not None
    assert first.lease.resources.port == 55_100
    assert second.decision is ClearanceDecision.QUEUED
    assert second.reasons == (ReasonCode.PORT_UNAVAILABLE,)
    assert second.queue_token is not None

    service.release(
        lease_id=first.lease.lease_id,
        owner_id=first_request.owner_id,
        heartbeat_token=first.lease.heartbeat_token,
    )
    resumed = service.claim(
        second_request,
        request_id=second.request_id,
        queue_token=second.queue_token,
    )
    assert resumed.lease is not None
    assert resumed.lease.resources.port == 55_100


def test_multiple_port_leases_choose_distinct_lowest_available_ports(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("gatehold.resources._port_is_available", _always_available)
    service = GateholdService(
        config_factory(port_start=55_200, port_end=55_202),
        host_probe=StaticHostProbe(),
    )

    first = service.claim(_resource_request("first", port=True))
    second = service.claim(_resource_request("second", port=True))

    assert first.lease is not None
    assert second.lease is not None
    assert first.lease.resources.port == 55_200
    assert second.lease.resources.port == 55_201


def test_bound_loopback_port_is_not_allocated(
    config_factory: ConfigFactory,
) -> None:
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    port = int(occupied.getsockname()[1])
    try:
        service = GateholdService(
            config_factory(port_start=port, port_end=port),
            host_probe=StaticHostProbe(),
        )
        outcome = service.claim(_resource_request("owner", port=True))
    finally:
        occupied.close()

    assert outcome.decision is ClearanceDecision.QUEUED
    assert outcome.reasons == (ReasonCode.PORT_UNAVAILABLE,)


def test_browser_profile_is_private_unique_and_redacted_in_snapshot(
    config_factory: ConfigFactory,
) -> None:
    config = config_factory()
    service = GateholdService(config, host_probe=StaticHostProbe())
    first = service.claim(_resource_request("first", browser_profile=True))
    second = service.claim(_resource_request("second", browser_profile=True))

    assert first.lease is not None
    assert second.lease is not None
    first_profile = Path(first.lease.resources.browser_profile or "")
    second_profile = Path(second.lease.resources.browser_profile or "")
    assert first_profile.parent == config.browser_profiles_dir
    assert second_profile.parent == config.browser_profiles_dir
    assert first_profile != second_profile
    assert stat.S_IMODE(first_profile.stat().st_mode) == 0o700
    assert stat.S_IMODE(second_profile.stat().st_mode) == 0o700

    snapshot = service.snapshot()
    exposed_profiles = {lease.resources.browser_profile for lease in snapshot.active_leases}
    assert exposed_profiles == {first_profile.name, second_profile.name}
    assert str(config.state_dir) not in snapshot.model_dump_json()


def test_simulator_leases_are_exclusive_and_reusable_after_expiry(
    config_factory: ConfigFactory,
) -> None:
    from helpers import MutableClock

    clock = MutableClock()
    service = GateholdService(
        config_factory(simulators=("ios-17",)),
        host_probe=StaticHostProbe(),
        now=clock,
    )
    first_request = _resource_request("first", simulator=True)
    first_request = first_request.model_copy(update={"ttl_seconds": 15})
    second_request = _resource_request("second", simulator=True)

    first = service.claim(first_request)
    second = service.claim(second_request)
    assert first.lease is not None
    assert first.lease.resources.simulator == "ios-17"
    assert second.decision is ClearanceDecision.QUEUED
    assert second.reasons == (ReasonCode.SIMULATOR_UNAVAILABLE,)
    assert second.queue_token is not None

    clock.advance(seconds=15)
    assert service.reap_expired() == 1
    resumed = service.claim(
        second_request,
        request_id=second.request_id,
        queue_token=second.queue_token,
    )
    assert resumed.lease is not None
    assert resumed.lease.resources.simulator == "ios-17"


def test_simulator_request_waits_when_no_simulators_are_configured(
    config_factory: ConfigFactory,
) -> None:
    service = GateholdService(
        config_factory(simulators=()),
        host_probe=StaticHostProbe(),
    )

    outcome = service.claim(_resource_request("owner", simulator=True))

    assert outcome.decision is ClearanceDecision.QUEUED
    assert outcome.reasons == (ReasonCode.SIMULATOR_UNAVAILABLE,)


def test_failed_port_or_simulator_allocation_does_not_create_profile(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("gatehold.resources._port_is_available", _never_available)
    config = config_factory(simulators=(), port_start=55_300, port_end=55_300)
    service = GateholdService(config, host_probe=StaticHostProbe())

    outcome = service.claim(
        _resource_request(
            "owner",
            port=True,
            browser_profile=True,
            simulator=True,
        )
    )

    assert outcome.decision is ClearanceDecision.QUEUED
    assert outcome.reasons == (
        ReasonCode.PORT_UNAVAILABLE,
        ReasonCode.SIMULATOR_UNAVAILABLE,
    )
    assert tuple(config.browser_profiles_dir.iterdir()) == ()


def test_profile_directory_is_removed_if_lease_transaction_fails(
    config_factory: ConfigFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = config_factory()
    service = GateholdService(config, host_probe=StaticHostProbe())

    def fail_create_lease(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic create failure")

    monkeypatch.setattr(service.store, "create_lease", fail_create_lease)
    with pytest.raises(RuntimeError, match="synthetic create failure"):
        service.claim(_resource_request("owner", browser_profile=True))

    assert tuple(config.browser_profiles_dir.iterdir()) == ()
