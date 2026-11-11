import logging

import pytest
import redis

from app.api.deps import get_login_rate_limiter
from app.core.rate_limit import RedisRateLimiter
from app.main import app
from tests.conftest import DEFAULT_PASSWORD

WRONG_PASSWORD = "Wr0ng!Pass"


class InMemoryRateLimiter:
    def __init__(self, limit: int, retry_after: int = 42) -> None:
        self.limit = limit
        self.retry_after_seconds = retry_after
        self.failures: dict[str, int] = {}

    def retry_after(self, key: str) -> int | None:
        return self.retry_after_seconds if self.failures.get(key, 0) >= self.limit else None

    def record_failure(self, key: str) -> None:
        self.failures[key] = self.failures.get(key, 0) + 1


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    def get(self, key: str) -> int | None:
        return self.values.get(key)

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds

    def ttl(self, key: str) -> int:
        return self.expiries.get(key, -1)


class BrokenRedis:
    def get(self, _key: str) -> int:
        raise redis.ConnectionError("redis down")

    def incr(self, _key: str) -> int:
        raise redis.ConnectionError("redis down")


def _login(client, email: str, password: str = DEFAULT_PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


class TestLoginRateLimit:
    @pytest.fixture
    def limited(self, client) -> tuple:
        limiter = InMemoryRateLimiter(limit=3)
        app.dependency_overrides[get_login_rate_limiter] = lambda: limiter
        return client, limiter

    def test_blocks_after_failed_attempts_with_retry_after(self, limited, make_user) -> None:
        client, _ = limited
        user = make_user()
        statuses = [_login(client, user.email, WRONG_PASSWORD).status_code for _ in range(3)]
        blocked = _login(client, user.email)

        assert statuses == [401, 401, 401]
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "42"
        assert blocked.json()["error"] == {
            "code": "rate_limited",
            "message": "Too many login attempts. Please try again later.",
            "details": [],
        }

    def test_successful_logins_are_not_counted(self, limited, make_user) -> None:
        client, limiter = limited
        user = make_user()
        statuses = [_login(client, user.email).status_code for _ in range(10)]
        assert set(statuses) == {200}
        assert limiter.failures == {}

    def test_successes_between_failures_do_not_reset_or_count(self, limited, make_user) -> None:
        client, limiter = limited
        user = make_user()
        _login(client, user.email, WRONG_PASSWORD)
        _login(client, user.email)
        _login(client, user.email, WRONG_PASSWORD)
        assert limiter.failures == {"login:testclient": 2}
        assert _login(client, user.email).status_code == 200

    def test_validation_errors_are_not_counted(self, limited) -> None:
        client, limiter = limited
        for _ in range(5):
            assert client.post("/auth/login", json={}).status_code == 400
        assert limiter.failures == {}

    def test_blocked_ip_is_rejected_before_password_or_body_checks(
        self, limited, make_user
    ) -> None:
        client, _ = limited
        user = make_user()
        for _ in range(3):
            _login(client, user.email, WRONG_PASSWORD)
        assert _login(client, user.email).status_code == 429
        assert client.post("/auth/login", json={}).status_code == 429

    def test_other_endpoints_are_not_limited(self, limited, admin_headers) -> None:
        client, limiter = limited
        for _ in range(5):
            assert client.get("/domains", headers=admin_headers).status_code == 200
        assert limiter.failures == {}


def test_limiter_is_keyed_by_client_ip(client, rate_limiter, make_user) -> None:
    _login(client, make_user().email, WRONG_PASSWORD)
    assert rate_limiter.checked == ["login:testclient"]
    assert rate_limiter.failures == ["login:testclient"]


class TestRedisRateLimiter:
    def test_blocks_once_failures_reach_limit(self) -> None:
        fake = FakeRedis()
        limiter = RedisRateLimiter(fake, limit=2, window_seconds=60)

        assert limiter.retry_after("login:1.2.3.4") is None
        limiter.record_failure("login:1.2.3.4")
        assert limiter.retry_after("login:1.2.3.4") is None
        limiter.record_failure("login:1.2.3.4")
        assert limiter.retry_after("login:1.2.3.4") == 60
        assert fake.expiries == {"ratelimit:login:1.2.3.4": 60}

    def test_checking_does_not_count(self) -> None:
        fake = FakeRedis()
        limiter = RedisRateLimiter(fake, limit=1, window_seconds=60)
        for _ in range(5):
            assert limiter.retry_after("login:a") is None
        assert fake.values == {}

    def test_keys_are_independent(self) -> None:
        limiter = RedisRateLimiter(FakeRedis(), limit=1, window_seconds=60)
        limiter.record_failure("login:a")
        assert limiter.retry_after("login:a") == 60
        assert limiter.retry_after("login:b") is None

    def test_fails_open_when_redis_is_down(self, caplog) -> None:
        limiter = RedisRateLimiter(BrokenRedis(), limit=1, window_seconds=60)
        with caplog.at_level(logging.WARNING, logger="app.rate_limit"):
            limiter.record_failure("login:a")
            assert limiter.retry_after("login:a") is None
        assert any(r.getMessage() == "rate_limit.unavailable" for r in caplog.records)
