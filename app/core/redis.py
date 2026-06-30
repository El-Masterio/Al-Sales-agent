"""
app/core/redis.py
=================
Redis connection pool, cache utilities, distributed rate limiter,
and pub/sub manager.

All Redis operations use the same connection pool for efficiency.
Keys follow a namespaced pattern:  sales:{namespace}:{key}
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any

import structlog
from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from app.core.config import settings

logger = structlog.get_logger(__name__)

# =============================================================================
# Connection pool (module singleton)
# =============================================================================

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.redis_url_str,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
            decode_responses=True,
            encoding="utf-8",
        )
    return _pool


def get_redis() -> Redis:
    """Return a Redis client backed by the shared connection pool."""
    return Redis(connection_pool=get_pool())


async def close_pool() -> None:
    """Gracefully disconnect all connections. Call on app shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("redis_pool_closed")


# =============================================================================
# FastAPI dependency
# =============================================================================

async def get_redis_dep() -> AsyncGenerator[Redis, None]:
    """
    FastAPI dependency that yields a Redis client.

        async def route(redis: Redis = Depends(get_redis_dep)):
    """
    client = get_redis()
    try:
        yield client
    finally:
        await client.aclose()


# =============================================================================
# Health check
# =============================================================================

async def check_redis_health() -> dict[str, Any]:
    try:
        client = get_redis()
        pong = await client.ping()
        await client.aclose()
        return {"status": "healthy", "ping": pong}
    except RedisError as exc:
        logger.error("redis_health_check_failed", error=str(exc))
        return {"status": "unhealthy", "error": str(exc)}


# =============================================================================
# Key helpers
# =============================================================================

def _key(namespace: str, *parts: str | int) -> str:
    """Build a namespaced Redis key: sales:{namespace}:{parts...}"""
    return "sales:" + namespace + ":" + ":".join(str(p) for p in parts)


# =============================================================================
# Cache — generic JSON cache with TTL
# =============================================================================

class CacheManager:
    """
    JSON-serialised key/value cache with optional TTL.
    Keys are automatically namespaced.

    Usage:
        cache = CacheManager(redis_client)
        await cache.set("company", company_id, data={"name": "Acme"}, ttl=300)
        data = await cache.get("company", company_id)
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def get(self, namespace: str, *key_parts: str | int) -> Any | None:
        raw = await self._client.get(_key(namespace, *key_parts))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def set(
        self,
        namespace: str,
        *key_parts: str | int,
        data: Any,
        ttl: int | timedelta | None = None,
    ) -> None:
        key = _key(namespace, *key_parts)
        value = json.dumps(data, default=str)
        if ttl is None:
            await self._client.set(key, value)
        else:
            seconds = int(ttl.total_seconds()) if isinstance(ttl, timedelta) else ttl
            await self._client.setex(key, seconds, value)

    async def delete(self, namespace: str, *key_parts: str | int) -> int:
        return await self._client.delete(_key(namespace, *key_parts))

    async def exists(self, namespace: str, *key_parts: str | int) -> bool:
        return bool(await self._client.exists(_key(namespace, *key_parts)))

    async def invalidate_prefix(self, namespace: str, prefix: str) -> int:
        """Delete all keys matching  sales:{namespace}:{prefix}*"""
        pattern = _key(namespace, prefix) + "*"
        keys: list[str] = []
        async for key in self._client.scan_iter(pattern, count=100):
            keys.append(key)
        if keys:
            return await self._client.delete(*keys)
        return 0


# =============================================================================
# Distributed Rate Limiter (sliding window via Redis sorted sets)
# =============================================================================

RATE_LIMIT_SCRIPT = """
local key     = KEYS[1]
local now     = tonumber(ARGV[1])
local window  = tonumber(ARGV[2])
local limit   = tonumber(ARGV[3])
local cutoff  = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, now .. ':' .. math.random(1,1000000))
    redis.call('EXPIRE', key, math.ceil(window / 1000))
    return 1
end
return 0
"""


class RateLimiter:
    """
    Sliding-window rate limiter backed by Redis sorted sets.

    Usage:
        limiter = RateLimiter(redis_client)
        allowed = await limiter.is_allowed("email_send", campaign_id, limit=50, window_seconds=3600)
    """

    def __init__(self, client: Redis) -> None:
        self._client = client
        self._script = self._client.register_script(RATE_LIMIT_SCRIPT)

    async def is_allowed(
        self,
        action: str,
        identifier: str | int,
        limit: int,
        window_seconds: int,
    ) -> bool:
        """
        Returns True if the action is within rate limit, False if throttled.
        window_seconds: sliding window size
        limit: max allowed requests within the window
        """
        if not settings.RATE_LIMIT_ENABLED:
            return True
        key = _key("rate", action, str(identifier))
        import time
        now_ms = int(time.time() * 1000)
        window_ms = window_seconds * 1000
        try:
            result = await self._script(
                keys=[key],
                args=[now_ms, window_ms, limit],
            )
            return bool(result)
        except RedisError as exc:
            # Fail open — don't block traffic if Redis is down
            logger.warning("rate_limiter_redis_error", error=str(exc))
            return True

    async def get_remaining(
        self,
        action: str,
        identifier: str | int,
        limit: int,
        window_seconds: int,
    ) -> int:
        """Return how many requests remain in the current window."""
        key = _key("rate", action, str(identifier))
        import time
        cutoff = int(time.time() * 1000) - (window_seconds * 1000)
        await self._client.zremrangebyscore(key, "-inf", cutoff)
        used = await self._client.zcard(key)
        return max(0, limit - used)


# =============================================================================
# Pub/Sub — for real-time dashboard updates via WebSocket
# =============================================================================

class PubSubManager:
    """
    Thin wrapper around Redis pub/sub for broadcasting real-time events.

    Publisher (in a service):
        await pubsub.publish("lead_status_changed", {"company_id": ..., "status": ...})

    Subscriber (in WebSocket handler):
        async for message in pubsub.subscribe("lead_status_changed"):
            await ws.send_json(message)
    """

    CHANNELS = {
        "lead_status_changed",
        "email_sent",
        "email_opened",
        "reply_received",
        "meeting_booked",
        "campaign_stats_updated",
        "task_completed",
    }

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        if channel not in self.CHANNELS:
            logger.warning("pubsub_unknown_channel", channel=channel)
        await self._client.publish(
            _key("pubsub", channel),
            json.dumps(data, default=str),
        )

    @contextlib.asynccontextmanager
    async def subscribe(self, *channels: str) -> AsyncGenerator[PubSub, None]:
        """
        Context manager yielding an active PubSub subscription.

        async with pubsub_manager.subscribe("lead_status_changed") as sub:
            async for message in sub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
        """
        ps: PubSub = self._client.pubsub()
        keys = [_key("pubsub", ch) for ch in channels]
        await ps.subscribe(*keys)
        try:
            yield ps
        finally:
            await ps.unsubscribe(*keys)
            await ps.aclose()


# =============================================================================
# Distributed locks — prevent duplicate task execution
# =============================================================================

class DistributedLock:
    """
    Simple Redis-based distributed lock using SET NX EX.

    Usage:
        lock = DistributedLock(redis_client)
        async with lock.acquire("research_company", company_id, ttl=300):
            # Only one worker runs this block at a time
            await research_company(company_id)
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    @contextlib.asynccontextmanager
    async def acquire(
        self,
        action: str,
        identifier: str | int,
        ttl: int = 60,
        raise_on_locked: bool = False,
    ) -> AsyncGenerator[bool, None]:
        key = _key("lock", action, str(identifier))
        acquired = await self._client.set(key, "1", nx=True, ex=ttl)
        if not acquired and raise_on_locked:
            raise RuntimeError(f"Could not acquire lock for {action}:{identifier}")
        try:
            yield bool(acquired)
        finally:
            if acquired:
                await self._client.delete(key)

    async def is_locked(self, action: str, identifier: str | int) -> bool:
        key = _key("lock", action, str(identifier))
        return bool(await self._client.exists(key))


# =============================================================================
# Convenience: module-level instances (requires calling get_redis() first)
# =============================================================================

def get_cache(client: Redis | None = None) -> CacheManager:
    return CacheManager(client or get_redis())


def get_rate_limiter(client: Redis | None = None) -> RateLimiter:
    return RateLimiter(client or get_redis())


def get_pubsub(client: Redis | None = None) -> PubSubManager:
    return PubSubManager(client or get_redis())


def get_lock(client: Redis | None = None) -> DistributedLock:
    return DistributedLock(client or get_redis())
