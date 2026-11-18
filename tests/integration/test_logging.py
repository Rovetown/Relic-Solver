import io
import logging
import sys
from collections.abc import Generator

import pytest
from flask.testing import FlaskClient

import app as app_module
from app import app as flask_app


@pytest.fixture
def restore_logging() -> Generator[None]:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    root.handlers[:] = original_handlers
    root.level = original_level


class TestLogLevel:
    def test_info_is_enabled_on_the_app_logger(self) -> None:
        assert app_module._log.isEnabledFor(logging.INFO)

    def test_debug_is_disabled_by_default(self) -> None:
        assert not app_module._log.isEnabledFor(logging.DEBUG)

    def test_level_is_read_from_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        restore_logging: None,
    ) -> None:
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        app_module.configure_logging()
        assert not app_module._log.isEnabledFor(logging.INFO)
        assert app_module._log.isEnabledFor(logging.WARNING)

    def test_invalid_level_falls_back_to_info(
        self,
        monkeypatch: pytest.MonkeyPatch,
        restore_logging: None,
    ) -> None:
        monkeypatch.setenv("LOG_LEVEL", "LOUD")
        app_module.configure_logging()
        assert app_module._log.isEnabledFor(logging.INFO)


class TestLogDestination:
    def test_root_handler_writes_to_stdout(
        self,
        restore_logging: None,
    ) -> None:
        app_module.configure_logging()
        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        handler = handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stdout

    def test_repeated_configuration_does_not_stack_handlers(
        self,
        restore_logging: None,
    ) -> None:
        app_module.configure_logging()
        app_module.configure_logging()
        assert len(logging.getLogger().handlers) == 1


class TestRequestId:
    def _capture(self) -> tuple[io.StringIO, logging.Handler]:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(app_module.LOG_FORMAT))
        handler.addFilter(app_module.RequestIdFilter())
        return stream, handler

    def test_record_outside_a_request_uses_a_placeholder(
        self,
        restore_logging: None,
    ) -> None:
        stream, handler = self._capture()
        logger = logging.getLogger("test.norequest")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.info("no request here")
        assert "req=-" in stream.getvalue()

    def test_record_inside_a_request_uses_the_request_id(
        self,
        restore_logging: None,
    ) -> None:
        stream, handler = self._capture()
        logger = logging.getLogger("test.inrequest")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        with flask_app.test_request_context("/"):
            flask_app.preprocess_request()
            logger.info("inside a request")
            from flask import g

            expected = g.request_id
        assert f"req={expected}" in stream.getvalue()

    def test_request_ids_differ_between_requests(
        self,
        client: FlaskClient,
    ) -> None:
        first = client.get("/api/health").headers["X-Request-Id"]
        second = client.get("/api/health").headers["X-Request-Id"]
        assert first != second

    def test_response_exposes_the_request_id(
        self,
        client: FlaskClient,
    ) -> None:
        resp = client.get("/api/health")
        assert resp.headers["X-Request-Id"]


class TestWorkerThreadCorrelation:
    def test_worker_logs_carry_the_originating_request_id(
        self,
        client: FlaskClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        payload = {
            "total_relic_chests": 10,
            "divine_chests": 1,
            "relic_cap": 5,
            "obelisk_level": 64,
            "targets": [1, 0, 0, 0, 0],
        }
        with caplog.at_level(logging.INFO, logger="app"):
            resp = client.post("/solve", json=payload)
            assert resp.data
        expected = resp.headers["X-Request-Id"]

        complete = [r for r in caplog.records if "Solve complete" in r.getMessage()]
        assert complete, "no completion record was logged"
        assert getattr(complete[0], "request_id", None) == expected
