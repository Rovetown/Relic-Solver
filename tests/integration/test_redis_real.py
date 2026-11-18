import json
import os
from collections.abc import Generator
from urllib.parse import urlparse

import pytest
import redis
from flask.testing import FlaskClient

import app as app_module
from app import app as flask_app
from app import limiter

pytestmark = pytest.mark.redis

SOLVE_PAYLOAD = {
    "total_relic_chests": 10,
    "divine_chests": 1,
    "relic_cap": 5,
    "obelisk_level": 64,
    "targets": [1, 0, 0, 0, 0],
}

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "redis"}


def _local_redis_url() -> str | None:
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    host = urlparse(url).hostname
    return url if host in _LOCAL_HOSTS else None


@pytest.fixture
def real_redis() -> Generator[redis.Redis[str]]:
    url = _local_redis_url()
    if url is None:
        pytest.skip("no local REDIS_URL set")

    client: redis.Redis[str] = redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_timeout=2,
    )
    try:
        client.ping()
    except redis.exceptions.RedisError:
        pytest.skip(f"Redis at {url} is not answering")

    client.flushdb()
    flask_app.config["TESTING"] = True
    limiter.enabled = False
    original = app_module.redis_client
    app_module.redis_client = client
    original_hits, original_misses = app_module._cache_hits, app_module._cache_misses
    app_module._cache_hits = app_module._cache_misses = 0

    yield client

    app_module.redis_client = original
    app_module._cache_hits, app_module._cache_misses = original_hits, original_misses
    limiter.enabled = True
    client.flushdb()
    client.close()


@pytest.fixture
def client(real_redis: redis.Redis[str]) -> Generator[FlaskClient]:
    with flask_app.test_client() as c:
        yield c


class TestCacheRoundTrip:
    def test_first_solve_stores_a_result(
        self,
        client: FlaskClient,
        real_redis: redis.Redis[str],
    ) -> None:
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        assert len(list(real_redis.keys("solve:*"))) == 1

    def test_stored_value_is_valid_json(
        self,
        client: FlaskClient,
        real_redis: redis.Redis[str],
    ) -> None:
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        raw = real_redis.get(next(iter(real_redis.keys("solve:*"))))
        assert raw is not None
        assert "probability" in json.loads(raw)

    def test_second_solve_is_served_from_cache(
        self,
        client: FlaskClient,
    ) -> None:
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        body = client.post("/solve", json=SOLVE_PAYLOAD).get_data(as_text=True)
        assert '"cached":true' in body.replace(" ", "")

    def test_cache_hit_carries_an_etag(self, client: FlaskClient) -> None:
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        resp = client.post("/solve", json=SOLVE_PAYLOAD)
        resp.get_data()
        assert resp.headers.get("ETag")

    def test_matching_etag_returns_304(self, client: FlaskClient) -> None:
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        first = client.post("/solve", json=SOLVE_PAYLOAD)
        first.get_data()
        etag = first.headers["ETag"]
        second = client.post(
            "/solve",
            json=SOLVE_PAYLOAD,
            headers={"If-None-Match": etag},
        )
        assert second.status_code == 304


class TestPersistentCounters:
    def test_miss_then_hit_are_counted(
        self,
        client: FlaskClient,
        real_redis: redis.Redis[str],
    ) -> None:
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        assert real_redis.get("stats:cache_misses") == "1"
        assert real_redis.get("stats:cache_hits") == "1"

    def test_health_reports_the_real_counters(self, client: FlaskClient) -> None:
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        cache = client.get("/api/health").get_json()["cache"]
        assert cache["total_hits"] == 1
        assert cache["total_misses"] == 1

    def test_health_hit_rate_is_computed_from_them(
        self,
        client: FlaskClient,
    ) -> None:
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        assert client.get("/api/health").get_json()["cache"]["hit_rate"] == 0.5

    def test_health_reports_redis_up(self, client: FlaskClient) -> None:
        data = client.get("/api/health").get_json()
        assert data["dependencies"]["redis"] == "up"
        assert data["status"] == "ok"


class TestUsageList:
    def test_a_solve_is_recorded(
        self,
        client: FlaskClient,
        real_redis: redis.Redis[str],
    ) -> None:
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        assert real_redis.llen("analytics:solves") == 1

    def test_the_row_carries_no_identifier(
        self,
        client: FlaskClient,
        real_redis: redis.Redis[str],
    ) -> None:
        client.post("/solve", json=SOLVE_PAYLOAD).get_data()
        row = json.loads(real_redis.lindex("analytics:solves", 0) or "{}")
        assert set(row) == {
            "ts",
            "chests",
            "divines",
            "cap",
            "ob",
            "targets",
            "prob",
            "ms",
        }


class TestLimiterStorage:
    def test_limit_is_enforced_through_redis(
        self,
        real_redis: redis.Redis[str],
    ) -> None:
        url = _local_redis_url()
        assert url is not None
        storage = app_module._limiter_storage_uri()
        if not storage.startswith(("redis://", "rediss://")):
            pytest.skip("limiter not configured against Redis in this environment")

        limiter.enabled = True
        limiter.reset()
        try:
            with flask_app.test_client() as c:
                last = None
                for _ in range(12):
                    last = c.post("/solve", json=SOLVE_PAYLOAD)
                    last.get_data()
                    if last.status_code == 429:
                        break
            assert last is not None
            assert last.status_code == 429
        finally:
            limiter.reset()
            limiter.enabled = False
