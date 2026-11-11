import dataclasses
import logging

import pytest

from app import Settings


class TestForceHttps:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "Yes", "on"])
    def test_recognised_true_values(self, value: str) -> None:
        assert Settings.from_env({"FORCE_HTTPS": value}).force_https is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", ""])
    def test_recognised_false_values(self, value: str) -> None:
        assert Settings.from_env({"FORCE_HTTPS": value}).force_https is False

    def test_absent_defaults_to_false(self) -> None:
        assert Settings.from_env({}).force_https is False

    def test_unrecognised_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="FORCE_HTTPS"):
            Settings.from_env({"FORCE_HTTPS": "maybe"})


class TestCorsOrigin:
    def test_defaults_to_wildcard(self) -> None:
        assert Settings.from_env({}).cors_origin == "*"

    def test_explicit_origin_is_kept(self) -> None:
        env = {"CORS_ORIGIN": "https://iomreliccalc.me"}
        assert Settings.from_env(env).cors_origin == "https://iomreliccalc.me"

    def test_blank_origin_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="CORS_ORIGIN"):
            Settings.from_env({"CORS_ORIGIN": "   "})


class TestRedisUrl:
    def test_absent_is_none(self) -> None:
        assert Settings.from_env({}).redis_url is None

    def test_rediscloud_takes_precedence(self) -> None:
        env = {
            "REDISCLOUD_URL": "redis://cloud:6379/0",
            "REDIS_URL": "redis://local:6379/0",
        }
        assert Settings.from_env(env).redis_url == "redis://cloud:6379/0"

    @pytest.mark.parametrize(
        "url",
        ["redis://host:6379/0", "rediss://host:6379/0"],
    )
    def test_valid_schemes_accepted(self, url: str) -> None:
        assert Settings.from_env({"REDIS_URL": url}).redis_url == url

    def test_wrong_scheme_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="REDIS_URL"):
            Settings.from_env({"REDIS_URL": "http://host:6379"})


class TestLogLevel:
    def test_defaults_to_info(self) -> None:
        assert Settings.from_env({}).log_level == logging.INFO

    def test_named_level_is_used(self) -> None:
        assert Settings.from_env({"LOG_LEVEL": "warning"}).log_level == logging.WARNING

    def test_unknown_level_falls_back_without_raising(self) -> None:
        assert Settings.from_env({"LOG_LEVEL": "LOUD"}).log_level == logging.INFO


class TestImmutability:
    def test_cannot_be_mutated(self) -> None:
        settings = Settings.from_env({})
        with pytest.raises(dataclasses.FrozenInstanceError):
            settings.cors_origin = "https://elsewhere"  # type: ignore[misc]
