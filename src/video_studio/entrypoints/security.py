"""HTTP Host/Origin validation and CORS middleware helpers for FastAPI."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from video_studio.config.settings import AppConfig


def is_allowed_host(host: str, allowed_hosts: set[str], suffixes: tuple[str, ...]) -> bool:
    """Return whether an incoming HTTP Host header is permitted.

    Args:
        host: Normalized lowercase hostname without port.
        allowed_hosts: Exact permitted hostnames.
        suffixes: Permitted domain suffixes (e.g. `.ts.net`).

    Returns:
        True when empty, exact-matched, or suffix-matched.
    """
    if not host or host in allowed_hosts:
        return True
    return any(host.endswith(suffix) for suffix in suffixes)


def is_allowed_origin(origin: str, allowed_origins: set[str], suffixes: tuple[str, ...]) -> bool:
    """Return whether an HTTP Origin header is permitted for mutating requests.

    Args:
        origin: Raw Origin header string.
        allowed_origins: Exact permitted origins.
        suffixes: Permitted host suffixes (e.g. `.ts.net`).

    Returns:
        True when empty, exact-matched, or matching an allowed host suffix.
    """
    if not origin:
        return True
    norm = origin.rstrip("/")
    if norm in allowed_origins:
        return True
    origin_host = norm.split("://", 1)[-1].split("/", 1)[0].split(":")[0].lower()
    return any(origin_host.endswith(suffix) for suffix in suffixes)


def build_cors_origin_regex(suffixes: tuple[str, ...]) -> str | None:
    """Build a CORS origin regex matching HTTP(S) origins under allowed host suffixes.

    Args:
        suffixes: Normalized domain suffixes starting with `.`.

    Returns:
        Compiled regex pattern string for CORSMiddleware, or None when disabled.
    """
    if not suffixes:
        return None
    joined = "|".join(re.escape(suffix) for suffix in suffixes)
    return rf"^https?://[^/]+(?:{joined})(?::\d+)?$"


def install_security_middleware(app: FastAPI, cfg: AppConfig) -> None:
    """Register Host/Origin validation and CORS middleware for local-only access.

    Args:
        app: FastAPI application instance.
        cfg: Application configuration.
    """
    suffixes = cfg.http_allowed_host_suffixes
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.http_allowed_origins),
        allow_origin_regex=build_cors_origin_regex(suffixes),
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    allowed_hosts = {cfg.http_host, "127.0.0.1", "localhost", "testserver"}
    allowed_origins = set(cfg.http_allowed_origins)

    @app.middleware("http")
    async def guard_host_and_origin(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Reject non-local Host headers and disallowed cross-origin mutations.

        Args:
            request: Incoming HTTP request.
            call_next: Next ASGI handler.

        Returns:
            HTTP response or 403 error JSON.
        """
        host_header = (request.headers.get("host") or "").split(":")[0].lower()
        if not is_allowed_host(host_header, allowed_hosts, suffixes):
            return JSONResponse({"detail": "Forbidden host"}, status_code=403)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin") or ""
            if not is_allowed_origin(origin, allowed_origins, suffixes):
                return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
        return await call_next(request)
