"""Read-only loopback FastAPI surface for sanitized live status and events."""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.middleware.base import RequestResponseEndpoint

from . import __version__
from .admission import GateholdService
from .models import GateholdSnapshot, HealthResponse

_LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def create_app(
    service: GateholdService,
    *,
    daemon_token: str,
    dashboard_origins: Iterable[str] = (),
    reap_interval_seconds: float = 2,
) -> FastAPI:
    allowed_origins = frozenset(_normalize_dashboard_origin(origin) for origin in dashboard_origins)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        del app
        await asyncio.to_thread(service.reap_expired)
        reaper = asyncio.create_task(_expiry_reaper(service, reap_interval_seconds))
        try:
            yield
        finally:
            reaper.cancel()
            with suppress(asyncio.CancelledError):
                await reaper

    app = FastAPI(
        title="Gatehold local status",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def local_guard(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not _local_host_header(request.headers.get("host", "")):
            return JSONResponse(status_code=403, content={"detail": "loopback host required"})

        origin = request.headers.get("origin")
        browser_allowed = False
        if origin is not None:
            try:
                normalized_origin = _normalize_origin(origin)
            except ValueError:
                return JSONResponse(status_code=403, content={"detail": "origin denied"})
            browser_allowed = normalized_origin in allowed_origins
            if not browser_allowed:
                return JSONResponse(status_code=403, content={"detail": "origin denied"})

        if request.method == "OPTIONS":
            requested_method = request.headers.get("access-control-request-method", "")
            if not browser_allowed or requested_method.upper() != "GET":
                return JSONResponse(status_code=405, content={"detail": "GET only"})
            response: Response = Response(status_code=204)
        else:
            if (
                request.url.path.startswith("/v1/")
                and not browser_allowed
                and not _valid_bearer(request, daemon_token)
            ):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "bearer token required"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            response = await call_next(request)

        if origin is not None and browser_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Last-Event-ID"
            response.headers["Vary"] = "Origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/healthz", response_model=HealthResponse)
    def health() -> HealthResponse:  # pyright: ignore[reportUnusedFunction]
        return HealthResponse(status="ok", version=__version__)

    @app.get("/v1/snapshot", response_model=GateholdSnapshot)
    def snapshot(  # pyright: ignore[reportUnusedFunction]
        recent: int = Query(default=20, ge=0, le=100),
    ) -> GateholdSnapshot:
        return service.snapshot(recent_receipts=recent)

    @app.get("/v1/events", response_model=None)
    async def events(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        after: int = Query(default=0, ge=0),
        once: bool = Query(default=False),
    ) -> Response:
        last_event_id = request.headers.get("last-event-id")
        if last_event_id and after == 0:
            try:
                after = max(0, int(last_event_id))
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Last-Event-ID must be an integer"},
                )
        return StreamingResponse(
            _event_stream(service, request, after=after, once=once),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return app


async def _expiry_reaper(service: GateholdService, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        with suppress(Exception):
            await asyncio.to_thread(service.reap_expired)


async def _event_stream(
    service: GateholdService,
    request: Request,
    *,
    after: int,
    once: bool,
) -> AsyncGenerator[str]:
    sequence = after
    while True:
        events = await asyncio.to_thread(service.events_after, sequence, limit=100)
        for event in events:
            sequence = event.sequence
            yield (
                f"id: {event.sequence}\nevent: {event.kind}\ndata: {event.model_dump_json()}\n\n"
            )
        if once or await request.is_disconnected():
            return
        if not events:
            yield ": keep-alive\n\n"
        await asyncio.sleep(1)


def _valid_bearer(request: Request, expected: str) -> bool:
    header = request.headers.get("authorization", "")
    scheme, separator, token = header.partition(" ")
    return (
        bool(separator) and scheme.casefold() == "bearer" and hmac.compare_digest(token, expected)
    )


def _local_host_header(value: str) -> bool:
    if not value or any(character in value for character in "\r\n/@"):
        return False
    try:
        hostname = urlsplit(f"//{value}").hostname
    except ValueError:
        return False
    return hostname in _LOCAL_HOSTS


def _normalize_origin(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("origin must contain only scheme, host, and optional port")
    return normalized


def _is_loopback_origin(origin: str) -> bool:
    return urlsplit(origin).hostname in _LOCAL_HOSTS


def _normalize_dashboard_origin(value: str) -> str:
    origin = _normalize_origin(value)
    if not _is_loopback_origin(origin) and urlsplit(origin).scheme != "https":
        raise ValueError("non-loopback dashboard origins must use https")
    return origin
