from __future__ import annotations

# pyright: reportPrivateUsage=false
import stat
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self, cast

import pytest
from fastapi.testclient import TestClient
from helpers import ConfigFactory
from httpx import Response

from gatehold.admission import GateholdService
from gatehold.api import (
    _local_host_header,
    _normalize_dashboard_origin,
    _normalize_origin,
    create_app,
)
from gatehold.host import StaticHostProbe
from gatehold.models import ClaimRequest, ResourceRequest, WorkloadClass
from gatehold.security import ensure_daemon_token, read_daemon_token


class LocalTestClient(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: object | None = None,
    ) -> Response: ...

    def options(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...


def _service(config_factory: ConfigFactory) -> GateholdService:
    return GateholdService(
        config_factory(),
        host_probe=StaticHostProbe(),
        semantic_comparator=None,
    )


def _client(
    service: GateholdService,
    *,
    daemon_token: str = "t" * 48,
    dashboard_origins: tuple[str, ...] = (),
) -> LocalTestClient:
    app = create_app(
        service,
        daemon_token=daemon_token,
        dashboard_origins=dashboard_origins,
        reap_interval_seconds=60,
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    return cast(LocalTestClient, cast(object, client))


def test_health_is_loopback_only_but_does_not_require_bearer(
    config_factory: ConfigFactory,
) -> None:
    with _client(_service(config_factory)) as client:
        allowed = client.get("/healthz")
        denied = client.get("/healthz", headers={"host": "example.test"})

    assert allowed.status_code == 200
    assert allowed.json()["status"] == "ok"
    assert allowed.headers["cache-control"] == "no-store"
    assert allowed.headers["referrer-policy"] == "no-referrer"
    assert denied.status_code == 403
    assert denied.json() == {"detail": "loopback host required"}


def test_originless_snapshot_requires_exact_bearer_token(
    config_factory: ConfigFactory,
) -> None:
    token = "local-daemon-token-" + ("x" * 32)
    with _client(_service(config_factory), daemon_token=token) as client:
        missing = client.get("/v1/snapshot")
        wrong = client.get(
            "/v1/snapshot",
            headers={"authorization": "Bearer " + ("y" * 40)},
        )
        accepted = client.get(
            "/v1/snapshot",
            headers={"authorization": f"bEaReR {token}"},
        )

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["version"] == "gatehold.snapshot.v1"
    assert token not in accepted.text


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "https://localhost",
    ],
)
def test_exact_configured_loopback_origin_can_read_snapshot_without_bearer(
    origin: str,
    config_factory: ConfigFactory,
) -> None:
    with _client(
        _service(config_factory),
        dashboard_origins=(origin,),
    ) as client:
        response = client.get("/v1/snapshot", headers={"origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-methods"] == "GET"
    assert response.headers["vary"] == "Origin"


def test_unconfigured_loopback_origin_is_denied(
    config_factory: ConfigFactory,
) -> None:
    origin = "http://127.0.0.1:3000"
    with _client(_service(config_factory)) as client:
        response = client.get("/v1/snapshot", headers={"origin": origin})

    assert response.status_code == 403
    assert response.json() == {"detail": "origin denied"}


def test_exact_https_dashboard_origin_is_allowed_and_http_remote_is_rejected(
    config_factory: ConfigFactory,
) -> None:
    service = _service(config_factory)
    with _client(
        service,
        dashboard_origins=("https://dashboard.example.test",),
    ) as client:
        allowed = client.get(
            "/v1/snapshot",
            headers={"origin": "https://dashboard.example.test"},
        )
        denied = client.get(
            "/v1/snapshot",
            headers={
                "origin": "https://evil.example.test",
                "authorization": "Bearer " + ("t" * 48),
            },
        )

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied.json() == {"detail": "origin denied"}
    with pytest.raises(ValueError, match="must use https"):
        _client(service, dashboard_origins=("http://dashboard.example.test",))


def test_preflight_allows_only_get_from_allowed_browser_origin(
    config_factory: ConfigFactory,
) -> None:
    origin = "http://localhost:3000"
    with _client(
        _service(config_factory),
        dashboard_origins=(origin,),
    ) as client:
        allowed = client.options(
            "/v1/snapshot",
            headers={
                "origin": origin,
                "access-control-request-method": "GET",
            },
        )
        denied_method = client.options(
            "/v1/snapshot",
            headers={
                "origin": origin,
                "access-control-request-method": "POST",
            },
        )
        missing_origin = client.options(
            "/v1/snapshot",
            headers={"access-control-request-method": "GET"},
        )

    assert allowed.status_code == 204
    assert allowed.headers["access-control-allow-origin"] == origin
    assert denied_method.status_code == 405
    assert missing_origin.status_code == 405


def test_api_has_no_mutating_claim_route_or_public_schema(
    config_factory: ConfigFactory,
) -> None:
    service = _service(config_factory)
    origin = "http://localhost:3000"
    headers = {"origin": origin}
    with _client(service, dashboard_origins=(origin,)) as client:
        claim = client.post("/v1/claim", headers=headers, json={"owner": "attacker"})
        snapshot_post = client.post("/v1/snapshot", headers=headers)
        schema = client.get("/openapi.json")

    assert claim.status_code == 404
    assert snapshot_post.status_code == 405
    assert schema.status_code == 404
    assert service.snapshot().active_leases == ()
    assert service.snapshot().queue == ()


def test_snapshot_query_is_strictly_bounded(
    config_factory: ConfigFactory,
) -> None:
    headers = {"authorization": "Bearer " + ("t" * 48)}
    with _client(_service(config_factory)) as client:
        negative = client.get("/v1/snapshot?recent=-1", headers=headers)
        excessive = client.get("/v1/snapshot?recent=101", headers=headers)
        valid = client.get("/v1/snapshot?recent=0", headers=headers)

    assert negative.status_code == 422
    assert excessive.status_code == 422
    assert valid.status_code == 200
    assert valid.json()["recent_receipts"] == []


def test_api_snapshot_exposes_hashes_and_profile_handle_not_raw_private_values(
    config_factory: ConfigFactory,
) -> None:
    service = _service(config_factory)
    request = ClaimRequest(
        owner_id="private-owner",
        workstream="Secret release lane",
        scopes=("/Users/example/Secret Repo/src/private",),
        workload=WorkloadClass.LIGHT,
        resources=ResourceRequest(browser_profile=True),
    )
    claimed = service.claim(request)
    assert claimed.lease is not None
    full_profile = claimed.lease.resources.browser_profile
    assert full_profile is not None
    headers = {"authorization": "Bearer " + ("t" * 48)}

    with _client(service) as client:
        response = client.get("/v1/snapshot", headers=headers)

    assert response.status_code == 200
    serialized = response.text
    assert "private-owner" not in serialized
    assert "Secret release lane" not in serialized
    assert "/Users/example" not in serialized
    assert full_profile not in serialized
    assert Path(full_profile).name in serialized
    lease = response.json()["active_leases"][0]
    assert len(lease["owner_sha256"]) == 64
    assert len(lease["workstream_sha256"]) == 64
    assert len(lease["scope_sha256"]) == 64


def test_once_event_stream_is_bounded_and_contains_no_raw_work_content(
    config_factory: ConfigFactory,
) -> None:
    service = _service(config_factory)
    request = ClaimRequest(
        owner_id="private-owner",
        workstream="Private release work",
        scopes=("/Users/example/Secret Repo/src/private",),
        workload=WorkloadClass.LIGHT,
    )
    service.claim(request)
    headers = {"authorization": "Bearer " + ("t" * 48)}

    with _client(service) as client:
        response = client.get("/v1/events?once=true", headers=headers)
        invalid_cursor = client.get(
            "/v1/events?once=true",
            headers={**headers, "last-event-id": "not-an-integer"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: request.queued" in response.text
    assert "event: lease.granted" in response.text
    assert "private-owner" not in response.text
    assert "Private release work" not in response.text
    assert "/Users/example" not in response.text
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json() == {"detail": "Last-Event-ID must be an integer"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("127.0.0.1", True),
        ("127.0.0.1:47820", True),
        ("localhost", True),
        ("localhost:47820", True),
        ("example.test", False),
        ("127.0.0.1@example.test", False),
        ("127.0.0.1/evil", False),
        ("127.0.0.1\r\nx-forwarded-host: example.test", False),
        ("", False),
    ],
)
def test_host_header_parser_rejects_spoofing(value: str, expected: bool) -> None:
    assert _local_host_header(value) is expected


@pytest.mark.parametrize(
    "origin",
    [
        "ftp://localhost",
        "https://user@dashboard.example.test",
        "https://dashboard.example.test/path",
        "https://dashboard.example.test?query=1",
        "https://dashboard.example.test#fragment",
        "dashboard.example.test",
    ],
)
def test_origin_parser_rejects_non_origin_values(origin: str) -> None:
    with pytest.raises(ValueError):
        _normalize_origin(origin)


def test_dashboard_origin_is_normalized_without_trailing_slash() -> None:
    assert (
        _normalize_dashboard_origin("https://dashboard.example.test/")
        == "https://dashboard.example.test"
    )


def test_daemon_token_is_created_once_with_private_permissions(tmp_path: Path) -> None:
    token_path = tmp_path / "state" / "daemon.token"

    first = ensure_daemon_token(token_path)
    second = ensure_daemon_token(token_path)

    assert first == second == read_daemon_token(token_path)
    assert len(first) >= 32
    assert stat.S_IMODE(token_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_daemon_token_rejects_symlink_and_short_file(tmp_path: Path) -> None:
    target = tmp_path / "outside-token"
    target.write_text("x" * 48, encoding="utf-8")
    symlink = tmp_path / "daemon.token"
    symlink.symlink_to(target)
    with pytest.raises(RuntimeError, match="regular file"):
        read_daemon_token(symlink)

    short = tmp_path / "short.token"
    short.write_text("too-short", encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid"):
        read_daemon_token(short)
