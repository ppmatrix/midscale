"""Sliding window rate limiter with in-memory and Redis backends."""

import asyncio
import time
from collections import defaultdict, deque
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Sliding window rate limiter.

    Tracks request timestamps per key (typically client IP) and rejects
    requests that exceed the configured limit within the window.

    Supports both in-memory and Redis backends. Redis is used when a
    ``redis_url`` is provided, enabling rate limit sharing across
    multiple server processes.
    """

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: int = 60,
        redis_url: str = "",
    ):
        self._max = max_requests
        self._window = window_seconds
        self._redis_url = redis_url
        self._clients: dict[str, deque[float]] = defaultdict(deque)
        self._redis = None
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._redis_url:
            try:
                import redis.asyncio as aioredis
                self._redis = await aioredis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=3,
                )
                await self._redis.ping()
                logger.info("rate limiter using redis", url=self._redis_url)
            except Exception as e:
                logger.warning(
                    "redis unavailable for rate limiter, falling back to in-memory",
                    error=str(e),
                )
                self._redis = None
        else:
            logger.info("rate limiter using in-memory storage")
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def check(self, key: str) -> tuple[bool, int]:
        """Check if ``key`` is within the rate limit.

        Returns ``(allowed, retry_after_seconds)``. When ``allowed`` is
        ``False``, ``retry_after`` is the number of seconds the caller
        should wait before retrying.
        """
        if self._redis:
            return await self._check_redis(key)
        return self._check_memory(key)

    def _check_memory(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        window_start = now - self._window
        timestamps = self._clients[key]

        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        if len(timestamps) >= self._max:
            retry_after = int(timestamps[0] + self._window - now)
            return False, max(retry_after, 1)

        timestamps.append(now)
        return True, 0

    async def _check_redis(self, key: str) -> tuple[bool, int]:
        now = time.time()
        window_start = now - self._window
        redis_key = f"midscale:ratelimit:{key}"

        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(redis_key, 0, window_start)
                pipe.zcard(redis_key)
                results = await pipe.execute()
            count = results[1] if results else 0

            if count >= self._max:
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe.zrange(redis_key, 0, 0, withscores=True)
                    oldest = await pipe.execute()
                oldest_score = oldest[0][0][1] if oldest and oldest[0] else now
                retry_after = int(oldest_score + self._window - now)
                return False, max(retry_after, 1)

            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zadd(redis_key, {str(now): now})
                pipe.expire(redis_key, int(self._window * 2))
                await pipe.execute()
            return True, 0
        except Exception as e:
            logger.error("redis rate check failed, allowing request", error=str(e))
            return True, 0

    async def reset(self, key: str) -> None:
        """Clear all rate limit data for ``key``."""
        if self._redis:
            await self._redis.delete(f"midscale:ratelimit:{key}")
        else:
            self._clients.pop(key, None)

    async def _periodic_cleanup(self) -> None:
        """Periodically purge stale in-memory entries."""
        while True:
            await asyncio.sleep(300)
            now = time.monotonic()
            window_start = now - self._window
            stale_keys = [
                k for k, v in self._clients.items()
                if v and v[-1] < window_start
            ]
            for k in stale_keys:
                del self._clients[k]
