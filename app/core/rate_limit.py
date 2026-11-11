import logging
from typing import Any, Protocol

import redis

logger = logging.getLogger("app.rate_limit")


class RateLimiter(Protocol):
    def hit(self, key: str) -> int | None: ...


class RedisRateLimiter:
    def __init__(self, client: Any, *, limit: int, window_seconds: int) -> None:
        self.client = client
        self.limit = limit
        self.window_seconds = window_seconds

    @classmethod
    def from_url(cls, url: str, *, limit: int, window_seconds: int) -> "RedisRateLimiter":
        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        return cls(client, limit=limit, window_seconds=window_seconds)

    def hit(self, key: str) -> int | None:
        redis_key = f"ratelimit:{key}"
        try:
            count = int(self.client.incr(redis_key))
            if count == 1:
                self.client.expire(redis_key, self.window_seconds)
            if count <= self.limit:
                return None
            ttl = int(self.client.ttl(redis_key))
        except redis.RedisError:
            logger.warning("rate_limit.unavailable", extra={"key": key})
            return None
        return ttl if ttl > 0 else self.window_seconds
