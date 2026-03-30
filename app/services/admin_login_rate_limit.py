"""
In-memory failed admin login rate limit (per client IP).

TODO(production): move to Redis-based rate limiting (or edge/WAF) — in-memory resets on
restart and does not coordinate across multiple app containers.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

_WINDOW_SEC = 60.0
_MAX_FAILS = 5

_failed_attempts: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_admin_login_rate_limit(request: Request) -> None:
    """Raise 429 if this IP has too many failed attempts in the sliding window."""
    ip = _client_ip(request)
    now = time.monotonic()
    bucket = _failed_attempts[ip]
    bucket[:] = [t for t in bucket if now - t < _WINDOW_SEC]
    if len(bucket) >= _MAX_FAILS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-in attempts. Wait a minute and try again.",
        )


def record_failed_admin_login(request: Request) -> None:
    _failed_attempts[_client_ip(request)].append(time.monotonic())


def clear_admin_login_failures(request: Request) -> None:
    _failed_attempts.pop(_client_ip(request), None)
