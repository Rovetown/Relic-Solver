from dataclasses import replace
from pathlib import Path

import pytest
from flask.testing import FlaskClient

import app as app_module
from tests.integration.conftest import FakeRedis

REPO_ROOT = Path(__file__).resolve().parents[2]


class _BrokenRedis(FakeRedis):
    def ping(self) -> bool:
        raise ConnectionError("connection lost")


class TestRedisAbsent:
    def test_status_is_ok(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, redis_url=None),
        )
        assert client.get("/api/health").get_json()["status"] == "ok"

    def test_redis_reported_absent(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, redis_url=None),
        )
        data = client.get("/api/health").get_json()
        assert data["dependencies"]["redis"] == "absent"


class TestRedisExpectedButMissing:
    def test_status_is_degraded_when_startup_ping_failed(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, redis_url="redis://configured:6379/0"),
        )
        monkeypatch.setattr(app_module, "redis_client", None)
        assert client.get("/api/health").get_json()["status"] == "degraded"

    def test_redis_reported_down_when_startup_ping_failed(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, redis_url="redis://configured:6379/0"),
        )
        monkeypatch.setattr(app_module, "redis_client", None)
        data = client.get("/api/health").get_json()
        assert data["dependencies"]["redis"] == "down"

    def test_status_is_degraded_when_redis_stops_answering(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, redis_url="redis://configured:6379/0"),
        )
        monkeypatch.setattr(app_module, "redis_client", _BrokenRedis())
        assert client.get("/api/health").get_json()["status"] == "degraded"

    def test_degraded_still_answers_200(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, redis_url="redis://configured:6379/0"),
        )
        monkeypatch.setattr(app_module, "redis_client", None)
        assert client.get("/api/health").status_code == 200


class TestRedisUp:
    def test_status_is_ok(
        self,
        client: FlaskClient,
        redis_client: FakeRedis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, redis_url="redis://configured:6379/0"),
        )
        assert client.get("/api/health").get_json()["status"] == "ok"

    def test_redis_reported_up(
        self,
        client: FlaskClient,
        redis_client: FakeRedis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            replace(app_module.settings, redis_url="redis://configured:6379/0"),
        )
        data = client.get("/api/health").get_json()
        assert data["dependencies"]["redis"] == "up"


class TestDockerHealthcheck:
    def _healthcheck(self) -> str:
        text = (REPO_ROOT / "Dockerfile").read_text()
        start = text.index("HEALTHCHECK")
        return text[start : text.index("\n\n", start)]

    def test_does_not_match_on_the_status_word(self) -> None:
        assert "'ok'" not in self._healthcheck()

    def test_keys_off_the_http_status_code(self) -> None:
        assert "200" in self._healthcheck()
