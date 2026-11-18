import json
import logging
from typing import Any

import pytest
from flask.testing import FlaskClient

import app as app_module

VALID_PAYLOAD: dict[str, Any] = {
    "total_relic_chests": 100,
    "divine_chests": 1,
    "relic_cap": 5,
    "obelisk_level": 64,
    "targets": [1, 0, 0, 0, 0],
}


def _frames(client: FlaskClient) -> list[dict[str, Any]]:
    resp = client.post("/solve", json=VALID_PAYLOAD)
    lines = resp.data.decode().strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


def _raise(exc: BaseException) -> Any:
    def _boom(*_args: object, **_kwargs: object) -> float:
        raise exc

    return _boom


class TestCatastrophicErrors:
    def test_unexpected_exception_yields_an_error_frame(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(app_module, "solve", _raise(RuntimeError("kaboom")))
        errors = [f for f in _frames(client) if f.get("type") == "error"]
        assert len(errors) == 1

    def test_unexpected_exception_does_not_leak_internals(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(app_module, "solve", _raise(RuntimeError("kaboom")))
        body = client.post("/solve", json=VALID_PAYLOAD).data.decode()
        assert "kaboom" not in body

    def test_memory_error_is_caught_like_any_other(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(app_module, "solve", _raise(MemoryError()))
        errors = [f for f in _frames(client) if f.get("type") == "error"]
        assert len(errors) == 1

    def test_stream_is_not_truncated_without_an_error(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(app_module, "solve", _raise(RuntimeError("kaboom")))
        frames = _frames(client)
        assert frames, "stream closed without emitting anything"
        assert frames[-1]["type"] == "error"

    def test_unexpected_exception_is_logged_with_a_traceback(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(app_module, "solve", _raise(RuntimeError("kaboom")))
        with caplog.at_level(logging.ERROR, logger="app"):
            _frames(client)
        records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert records
        assert records[0].exc_info is not None

    def test_a_crash_log_carries_no_request_inputs(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(app_module, "solve", _raise(RuntimeError("kaboom")))
        with caplog.at_level(logging.ERROR, logger="app"):
            client.post("/solve", json=VALID_PAYLOAD)
        records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert records
        for record in records:
            message = record.getMessage()
            for value in (
                VALID_PAYLOAD["total_relic_chests"],
                VALID_PAYLOAD["divine_chests"],
                VALID_PAYLOAD["relic_cap"],
            ):
                assert str(value) not in message, message


class TestOperationalErrors:
    def test_value_error_message_reaches_the_client(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(app_module, "solve", _raise(ValueError("cap too small")))
        errors = [f for f in _frames(client) if f.get("type") == "error"]
        assert errors[0]["error"] == "cap too small"

    def test_timeout_message_reaches_the_client(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(app_module, "solve", _raise(TimeoutError("ran too long")))
        errors = [f for f in _frames(client) if f.get("type") == "error"]
        assert errors[0]["error"] == "ran too long"
