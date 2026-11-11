from collections.abc import Generator
from dataclasses import replace

import pytest
from flask.testing import FlaskClient

import app as app_module
from app import app as flask_app
from app import limiter


class _FakePipeline:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store
        self._commands: list[tuple[str, tuple[str, ...]]] = []

    def dbsize(self) -> _FakePipeline:
        self._commands.append(("dbsize", ()))
        return self

    def get(self, key: str) -> _FakePipeline:
        self._commands.append(("get", (key,)))
        return self

    def execute(self) -> list[object]:
        results: list[object] = []
        for cmd, args in self._commands:
            if cmd == "dbsize":
                results.append(len(self._store))
            elif cmd == "get":
                results.append(self._store.get(args[0]))
        return results


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def incr(self, key: str) -> int:
        val = int(self._store.get(key, "0")) + 1
        self._store[key] = str(val)
        return val

    def dbsize(self) -> int:
        return len(self._store)

    def ping(self) -> bool:
        return True

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self._store)


@pytest.fixture
def client() -> Generator[FlaskClient]:
    flask_app.config["TESTING"] = True
    limiter.enabled = False
    original_redis = app_module.redis_client
    original_settings = app_module.settings
    app_module.redis_client = None
    app_module.settings = replace(original_settings, redis_url=None)
    with flask_app.test_client() as c:
        yield c
    app_module.redis_client = original_redis
    app_module.settings = original_settings
    limiter.enabled = True


@pytest.fixture
def redis_client(client: FlaskClient) -> Generator[FakeRedis]:
    fake = FakeRedis()
    original = app_module.redis_client
    original_hits = app_module._cache_hits
    original_misses = app_module._cache_misses
    app_module.redis_client = fake
    app_module._cache_hits = 0
    app_module._cache_misses = 0
    yield fake
    app_module.redis_client = original
    app_module._cache_hits = original_hits
    app_module._cache_misses = original_misses
