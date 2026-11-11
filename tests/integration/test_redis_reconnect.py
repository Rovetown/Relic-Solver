import time
from dataclasses import replace

import pytest
import redis
from flask.testing import FlaskClient

import app as app_module
from tests.integration.conftest import FakeRedis

CONFIGURED = "redis://configured:6379/0"

SOLVE_PAYLOAD = {
    "total_relic_chests": 10,
    "divine_chests": 1,
    "relic_cap": 5,
    "targets": [1, 0, 0, 0, 0],
}


@pytest.fixture(autouse=True)
def reset_redis_state() -> None:
    app_module._redis_next_attempt = 0.0


def _configure(monkeypatch: pytest.MonkeyPatch, url: str | None) -> None:
    monkeypatch.setattr(
        app_module,
        "settings",
        replace(app_module.settings, redis_url=url),
    )


class _Attempts:
    def __init__(self, *, succeed: bool) -> None:
        self.count = 0
        self._succeed = succeed

    def __call__(self, *_args: object, **_kwargs: object) -> FakeRedis:
        self.count += 1
        if not self._succeed:
            raise ConnectionError("refused")
        return FakeRedis()


class TestNoRedisConfigured:
    def test_does_not_try_to_connect(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempts = _Attempts(succeed=True)
        _configure(monkeypatch, None)
        monkeypatch.setattr(redis.Redis, "from_url", attempts)
        app_module._ensure_redis()
        assert attempts.count == 0


class TestReconnectAfterAFailedStart:
    def test_connects_when_redis_returns(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _configure(monkeypatch, CONFIGURED)
        monkeypatch.setattr(app_module, "redis_client", None)
        monkeypatch.setattr(
            redis.Redis,
            "from_url",
            _Attempts(succeed=True),
        )
        app_module._ensure_redis()
        assert app_module.redis_client is not None

    def test_stays_disabled_while_redis_is_down(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _configure(monkeypatch, CONFIGURED)
        monkeypatch.setattr(app_module, "redis_client", None)
        monkeypatch.setattr(
            redis.Redis,
            "from_url",
            _Attempts(succeed=False),
        )
        app_module._ensure_redis()
        assert app_module.redis_client is None

    def test_an_existing_client_is_left_alone(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempts = _Attempts(succeed=True)
        existing = FakeRedis()
        _configure(monkeypatch, CONFIGURED)
        monkeypatch.setattr(app_module, "redis_client", existing)
        monkeypatch.setattr(redis.Redis, "from_url", attempts)
        app_module._ensure_redis()
        assert attempts.count == 0
        assert app_module.redis_client is existing


class TestRetryBackoff:
    def test_second_attempt_is_suppressed_within_the_window(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempts = _Attempts(succeed=False)
        _configure(monkeypatch, CONFIGURED)
        monkeypatch.setattr(app_module, "redis_client", None)
        monkeypatch.setattr(redis.Redis, "from_url", attempts)
        monkeypatch.setattr(time, "monotonic", lambda: 1000.0)

        app_module._ensure_redis()
        app_module._ensure_redis()
        assert attempts.count == 1

    def test_attempt_resumes_after_the_window(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempts = _Attempts(succeed=False)
        _configure(monkeypatch, CONFIGURED)
        monkeypatch.setattr(app_module, "redis_client", None)
        monkeypatch.setattr(redis.Redis, "from_url", attempts)

        now = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: now)
        app_module._ensure_redis()

        now += app_module._REDIS_RETRY_SECONDS + 1
        monkeypatch.setattr(time, "monotonic", lambda: now)
        app_module._ensure_redis()

        assert attempts.count == 2


class _DyingRedis(FakeRedis):
    def get(self, key: str) -> str | None:
        raise ConnectionError("connection lost")


class TestClientThatDiesLater:
    def test_failed_read_drops_the_client(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _configure(monkeypatch, CONFIGURED)
        monkeypatch.setattr(app_module, "redis_client", _DyingRedis())
        monkeypatch.setattr(
            redis.Redis,
            "from_url",
            _Attempts(succeed=False),
        )
        resp = client.post("/solve", json=SOLVE_PAYLOAD)
        resp.get_data()
        assert app_module.redis_client is None

    def test_the_solve_still_succeeds(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _configure(monkeypatch, CONFIGURED)
        monkeypatch.setattr(app_module, "redis_client", _DyingRedis())
        monkeypatch.setattr(
            redis.Redis,
            "from_url",
            _Attempts(succeed=False),
        )
        resp = client.post("/solve", json=SOLVE_PAYLOAD)
        body = resp.get_data(as_text=True)
        assert '"type":"result"' in body
