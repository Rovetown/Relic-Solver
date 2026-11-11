import subprocess  # nosec B404 - runs first-party scripts, not user input
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_CSV_HEADER = "ts,chests,divines,cap,d1,d2,d3,d4,d5,prob,ms"


def _synthetic_rows() -> list[str]:
    rows = []
    for i in range(30):
        cap = (i % 4) * 5 + 5
        rows.append(
            f"{1_700_000_000 + i * 60},"
            f"{i * 1000},{i % 7},{cap},"
            f"{i % 3},{i % 5},{i % 4},{i % 3},{i % 2},"
            f"{(i + 1) / 40:.4f},{12.5 + i:.1f}",
        )
    return rows


@pytest.fixture
def analytics_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "analytics_merged.csv"
    csv_path.write_text(
        "\n".join([_CSV_HEADER, *_synthetic_rows()]) + "\n",
        encoding="utf-8",
    )
    return csv_path


@pytest.mark.parametrize(
    "script",
    [
        "scripts/aggregate_stats.py",
    ],
)
def test_script_runs_against_analytics_csv(
    script: str,
    analytics_csv: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    result = subprocess.run(  # nosec B603 - fixed argv, no shell, no user input
        [sys.executable, script, str(analytics_csv), "-o", str(out)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, (
        f"{script} exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert out.exists(), f"{script} produced no output at {out}"
