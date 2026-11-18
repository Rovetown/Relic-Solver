import re
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from relic_solver.config import SOLVE_MAX_SECONDS, WORKER_TIMEOUT_SECONDS

REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_PAYLOAD = {
    "total_relic_chests": 100,
    "divine_chests": 1,
    "relic_cap": 5,
    "obelisk_level": 64,
    "targets": [1, 0, 0, 0, 0],
}


def _timeout_flag(text: str, flag: str) -> int | None:
    match = re.search(rf"{re.escape(flag)}[= ](\d+)", text)
    return int(match.group(1)) if match else None


class TestDeadlineOrdering:
    def test_solver_finishes_before_the_worker_is_killed(self) -> None:
        assert SOLVE_MAX_SECONDS < WORKER_TIMEOUT_SECONDS

    def test_the_gap_is_wide_enough_to_report_the_timeout(self) -> None:
        assert WORKER_TIMEOUT_SECONDS - SOLVE_MAX_SECONDS >= 10


class TestSolverIsGivenTheDeadline:
    def test_solve_receives_the_configured_max_seconds(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict[str, Any] = {}

        def _capture(*_args: object, **kwargs: object) -> float:
            seen.update(kwargs)
            return 1.0

        monkeypatch.setattr("app.solve", _capture)
        client.post("/solve", json=VALID_PAYLOAD)
        assert seen["max_seconds"] == SOLVE_MAX_SECONDS


class TestProcfile:
    def test_timeout_matches_config(self) -> None:
        procfile = (REPO_ROOT / "Procfile").read_text()
        assert _timeout_flag(procfile, "--timeout") == WORKER_TIMEOUT_SECONDS

    def test_graceful_timeout_is_set(self) -> None:
        procfile = (REPO_ROOT / "Procfile").read_text()
        assert _timeout_flag(procfile, "--graceful-timeout") is not None


def _dockerfile_cmd() -> str:
    for line in (REPO_ROOT / "Dockerfile").read_text().splitlines():
        if line.startswith("CMD"):
            return line
    raise AssertionError("Dockerfile has no CMD line")


class TestDockerfile:
    def test_timeout_matches_config(self) -> None:
        assert _timeout_flag(_dockerfile_cmd(), "--timeout") == WORKER_TIMEOUT_SECONDS

    def test_graceful_timeout_is_set(self) -> None:
        assert _timeout_flag(_dockerfile_cmd(), "--graceful-timeout") is not None
