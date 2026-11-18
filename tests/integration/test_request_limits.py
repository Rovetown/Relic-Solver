import pytest
from flask.testing import FlaskClient

from app import app as flask_app
from relic_solver.config import MAX_REQUEST_BYTES

VALID_PAYLOAD = {
    "total_relic_chests": 100,
    "divine_chests": 1,
    "relic_cap": 5,
    "obelisk_level": 64,
    "targets": [1, 0, 0, 0, 0],
}


class TestPayloadCeiling:
    def test_limit_is_configured(self) -> None:
        assert flask_app.config["MAX_CONTENT_LENGTH"] == MAX_REQUEST_BYTES

    def test_ceiling_leaves_room_for_a_real_request(self) -> None:
        assert MAX_REQUEST_BYTES >= 1024

    def test_oversized_body_is_rejected(self, client: FlaskClient) -> None:
        payload = {**VALID_PAYLOAD, "padding": "x" * (MAX_REQUEST_BYTES + 1)}
        resp = client.post("/solve", json=payload)
        assert resp.status_code == 413

    def test_oversized_body_does_not_reach_the_solver(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[object] = []
        monkeypatch.setattr(
            "app.solve",
            lambda *a, **k: calls.append(a) or 1.0,  # type: ignore[func-returns-value]
        )
        payload = {**VALID_PAYLOAD, "padding": "x" * (MAX_REQUEST_BYTES + 1)}
        client.post("/solve", json=payload)
        assert not calls

    def test_normal_body_is_still_accepted(self, client: FlaskClient) -> None:
        resp = client.post("/solve", json=VALID_PAYLOAD)
        assert resp.status_code == 200
