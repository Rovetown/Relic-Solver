from collections.abc import Generator

import pytest
from flask.testing import FlaskClient

import app as app_module
from app import app as flask_app
from app import limiter

VALID_PAYLOAD = {
    "total_relic_chests": 10,
    "divine_chests": 1,
    "relic_cap": 5,
    "obelisk_level": 64,
    "targets": [1, 0, 0, 0, 0],
}


@pytest.fixture
def failing_client() -> Generator[FlaskClient]:
    flask_app.config["TESTING"] = True
    flask_app.config["PROPAGATE_EXCEPTIONS"] = False
    limiter.enabled = False
    original = app_module.redis_client
    app_module.redis_client = None
    with flask_app.test_client() as c:
        yield c
    app_module.redis_client = original
    flask_app.config["PROPAGATE_EXCEPTIONS"] = None
    limiter.enabled = True


@pytest.fixture
def limited_client() -> Generator[FlaskClient]:
    flask_app.config["TESTING"] = True
    limiter.enabled = True
    limiter.reset()
    original = app_module.redis_client
    app_module.redis_client = None
    with flask_app.test_client() as c:
        yield c
    app_module.redis_client = original
    limiter.reset()
    limiter.enabled = False


class TestApiErrorsAreJson:
    def test_unknown_api_route_returns_json(self, client: FlaskClient) -> None:
        resp = client.get("/api/nope")
        assert resp.status_code == 404
        assert resp.is_json
        assert resp.get_json()["error"]

    def test_oversized_body_returns_json(self, client: FlaskClient) -> None:
        payload = {**VALID_PAYLOAD, "padding": "x" * 9000}
        resp = client.post("/solve", json=payload)
        assert resp.status_code == 413
        assert resp.is_json
        assert resp.get_json()["error"]

    def test_wrong_method_returns_json(self, client: FlaskClient) -> None:
        resp = client.get("/solve")
        assert resp.status_code == 405
        assert resp.is_json

    def test_error_response_carries_the_request_id(
        self,
        client: FlaskClient,
    ) -> None:
        resp = client.get("/api/nope")
        assert resp.headers["X-Request-Id"]


class TestRateLimitResponse:
    def test_rate_limited_solve_returns_json(
        self,
        limited_client: FlaskClient,
    ) -> None:
        last = None
        for _ in range(12):
            last = limited_client.post("/solve", json=VALID_PAYLOAD)
            last.get_data()
            if last.status_code == 429:
                break
        assert last is not None
        assert last.status_code == 429
        assert last.is_json
        assert last.get_json()["error"]


class TestInternalErrorResponse:
    def test_returns_json_500(
        self,
        failing_client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _boom() -> str:
            raise RuntimeError("internal detail")

        monkeypatch.setattr(app_module, "_redis_state", _boom)
        resp = failing_client.get("/api/health")
        assert resp.status_code == 500
        assert resp.is_json

    def test_does_not_leak_the_exception_text(
        self,
        failing_client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _boom() -> str:
            raise RuntimeError("internal detail")

        monkeypatch.setattr(app_module, "_redis_state", _boom)
        resp = failing_client.get("/api/health")
        assert "internal detail" not in resp.get_data(as_text=True)


class TestBrowserRoutesKeepHtml:
    def test_unknown_page_returns_html(self, client: FlaskClient) -> None:
        resp = client.get("/definitely-not-a-page")
        assert resp.status_code == 404
        assert not resp.is_json

    def test_unknown_page_renders_the_branded_404(
        self,
        client: FlaskClient,
    ) -> None:
        body = client.get("/definitely-not-a-page").get_data(as_text=True)
        assert "Relic Solver" in body
        assert "style.min.css" in body
        assert 'href="/"' in body

    def test_branded_404_is_not_indexable(self, client: FlaskClient) -> None:
        body = client.get("/definitely-not-a-page").get_data(as_text=True)
        assert 'name="robots"' in body
        assert "noindex" in body
