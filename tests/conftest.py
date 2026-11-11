import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

log = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).parent / "reports"


def _fmt(seconds: float) -> str:
    if seconds < 1e-3:
        return f"{seconds * 1e6:.1f} \u03bcs"
    if seconds < 1.0:
        return f"{seconds * 1e3:.2f} ms"
    return f"{seconds:.3f} s"


def pytest_configure(config: pytest.Config) -> None:
    REPORTS_DIR.mkdir(exist_ok=True)


def _collect_benchmarks(config: pytest.Config) -> list[Any]:
    session = getattr(config, "_benchmarksession", None)
    if session is None or not hasattr(session, "benchmarks"):
        return []
    try:
        return list(session.benchmarks)
    except Exception:  # noqa: BLE001
        log.warning("Failed to collect benchmark results", exc_info=True)
        return []


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    now = datetime.now(tz=UTC)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"test_report_{timestamp}.md"

    passed = terminalreporter.stats.get("passed", [])
    failed = terminalreporter.stats.get("failed", [])
    errors = terminalreporter.stats.get("error", [])
    skipped = terminalreporter.stats.get("skipped", [])

    total = len(passed) + len(failed) + len(errors) + len(skipped)

    lines: list[str] = [
        f"# Test Report -- {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        f"**Exit status:** {exitstatus}  ",
        f"**Root:** {config.rootpath}  ",
        "",
        "## Summary",
        "",
        "| Status | Count |",
        "|--------|------:|",
        f"| Passed | {len(passed)} |",
        f"| Failed | {len(failed)} |",
        f"| Errors | {len(errors)} |",
        f"| Skipped | {len(skipped)} |",
        f"| **Total** | **{total}** |",
        "",
        "## Detailed Results",
        "",
        "| Test | Status | Duration (s) |",
        "|------|--------|-------------:|",
    ]

    for status_key in ("passed", "failed", "error", "skipped"):
        for report in terminalreporter.stats.get(status_key, []):
            if report.when == "call" or (
                report.when == "setup" and status_key == "error"
            ):
                dur = f"{report.duration:.6f}"
                lines.append(
                    f"| `{report.nodeid}` | {status_key.upper()} | {dur} |",
                )

    if failed:
        lines.extend(("", "## Failures", ""))
        for report in failed:
            lines.extend((
                f"### `{report.nodeid}`",
                "",
                f"```\n{report.longreprtext}\n```",
                "",
            ))

    benchmarks = _collect_benchmarks(config)
    if benchmarks:
        durations: dict[str, float] = {}
        for status_key in ("passed", "failed", "error"):
            for report in terminalreporter.stats.get(status_key, []):
                if report.when == "call":
                    durations[report.nodeid] = report.duration

        lines.extend(("", "## Benchmark Results", ""))
        lines.append(
            "| Test | Min | Mean | Max | StdDev"
            " | Median (time/1-reroll) | Rounds | OPS | Total |",
        )
        lines.append(
            "|------|----:|-----:|----:|-------:"
            "|-------:|-------:|----:|------:|",
        )
        for bench in benchmarks:
            s = bench.stats
            ops = f"{s.ops:,.1f}" if s.ops < 1e6 else f"{s.ops:.2e}"
            wall = durations.get(bench.fullname, 0.0)
            lines.append(
                f"| `{bench.name}` "
                f"| {_fmt(s.min)} "
                f"| {_fmt(s.mean)} "
                f"| {_fmt(s.max)} "
                f"| {_fmt(s.stddev)} "
                f"| {_fmt(s.median)} "
                f"| {s.rounds} "
                f"| {ops} "
                f"| {_fmt(wall)} |",
            )

    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    terminalreporter.write_line(
        f"\n>> Report written to: {report_path}",
    )
