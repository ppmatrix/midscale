"""Middleware for rate limiting and API metrics tracking."""

import time
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.services.metrics import API_REQUESTS, RATE_LIMIT_BLOCKED
from app.services.rate_limiter import RateLimiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting per client IP with separate limits per endpoint type.

    Uses limiters stored on ``app.state.rate_limiters`` (a dict with
    keys ``auth``, ``default``, ``register``, ``heartbeat``,
    ``websocket``, ``admin``). These are set during the application
    lifespan.

    Returns ``429 Too Many Requests`` with ``Retry-After``,
    ``X-RateLimit-Limit``, and ``X-RateLimit-Reset`` headers.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        client_ip = request.client.host if request.client else "127.0.0.1"
        path = request.url.path
        method = request.method

        limiter = self._get_limiter(request, path)

        if limiter is not None:
            allowed, retry_after = await limiter.check(client_ip)
            if not allowed:
                API_REQUESTS.labels(
                    method=method,
                    endpoint=path,
                    status="429",
                ).inc()
                RATE_LIMIT_BLOCKED.labels(limiter=self._classify_path(path), path=path).inc()
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later."},
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limiter._max),
                        "X-RateLimit-Reset": str(int(time.time() + retry_after)),
                    },
                )

        response = await call_next(request)
        API_REQUESTS.labels(
            method=method,
            endpoint=path,
            status=str(response.status_code),
        ).inc()
        return response

    def _get_limiter(self, request: Request, path: str) -> Optional[RateLimiter]:
        """Retrieve the appropriate rate limiter for ``path``."""
        limiters = getattr(request.app.state, "rate_limiters", None)
        if not limiters:
            return None

        category = self._classify_path(path)
        return limiters.get(category) or limiters.get("default")

    @staticmethod
    def _classify_path(path: str) -> str:
        if path.startswith("/api/v1/auth/"):
            return "auth"
        if "/register" in path:
            return "register"
        if "/heartbeat" in path:
            return "heartbeat"
        if path.startswith("/ws"):
            return "websocket"
        if path.startswith("/api/v1/routes/") or path.startswith("/api/v1/audit"):
            return "admin"
        return "default"
