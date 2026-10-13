"""Phase 7 hardening: per-IP rate limit, request-size limits, safe response headers.

All state is in-memory and per process (fine for one small instance; use a shared store such as
Redis if you scale out). Nothing here logs request bodies, so coordinates never reach logs.
"""
import time
from collections import deque
from typing import Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

JSON_BODY_LIMIT = 64 * 1024          # /resolve and /trip-plan bodies are tiny
MULTIPART_OVERHEAD = 256 * 1024      # form fields + boundaries on top of the image bytes
MAX_TRACKED_CLIENTS = 10_000


class RateLimiter:
    """Sliding-window limiter: at most `limit` hits per `window` seconds per key. limit<=0 disables it."""

    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self._clock = limit, window, clock
        self._hits: dict[str, deque] = {}

    def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        if self.limit <= 0:
            return True, 0
        now = self._clock()
        q = self._hits.get(key)
        if q is None:
            if len(self._hits) >= MAX_TRACKED_CLIENTS:  # bound memory: forget the stalest client
                stalest = min(self._hits, key=lambda k: self._hits[k][-1] if self._hits[k] else 0)
                del self._hits[stalest]
            q = self._hits[key] = deque()
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False, max(1, int(self.window - (now - q[0])) + 1)
        q.append(now)
        return True, 0


def client_ip(request: Request, trust_proxy: bool) -> str:
    """Behind a proxy (Render/Fly/Railway) the proxy APPENDS the real client to X-Forwarded-For, so the
    rightmost entry is the one we can trust. Only used when TRUST_PROXY=true; otherwise the socket peer."""
    if trust_proxy:
        xff = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def _err(status: int, code: str, message: str, headers: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}}, headers=headers)


def install(app, settings) -> RateLimiter:
    limiter = RateLimiter(settings.rate_limit_per_minute)
    multipart_limit = settings.max_images * settings.max_image_bytes + MULTIPART_OVERHEAD
    app.state.limiter = limiter

    @app.middleware("http")
    async def guard(request: Request, call_next):
        is_api_post = request.method == "POST" and request.url.path.startswith("/api/")
        if is_api_post:
            # 1) size limit from Content-Length (rejects before the body is read)
            try:
                size = int(request.headers.get("content-length", "0"))
            except ValueError:
                return _err(400, "invalid_length", "Invalid Content-Length header")
            ctype = request.headers.get("content-type", "")
            cap = multipart_limit if ctype.startswith("multipart/form-data") else JSON_BODY_LIMIT
            if size > cap:
                return _err(413, "request_too_large", f"Request body exceeds {cap // 1024} KB")
            # 2) per-IP rate limit (health checks and CORS preflights are not counted)
            ok, retry = limiter.check(client_ip(request, settings.trust_proxy))
            if not ok:
                return _err(429, "rate_limited", f"Too many requests. Try again in {retry} s.",
                            headers={"Retry-After": str(retry)})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    return limiter
