import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

_DEFAULT_INPUT = Path("reports/test_results.json")
_DEFAULT_OUTPUT = Path("reports/visuals/test_suite")

_GREEN = "#66cc66"
_RED = "#ff6b6b"
_ORANGE = "#ffb84d"
_PINK = "#ff4da6"
_BLUE = "#4da3ff"
_MUTED = "#8b949e"
_BG = "#0d1117"
_AXES_BG = "#161b22"
_GRID = "#30363d"


def _setup_theme() -> None:
    plt.style.use("dark_background")
    plt.rcParams.update(
        {
            "axes.facecolor": _AXES_BG,
            "figure.facecolor": _BG,
            "grid.color": _GRID,
            "axes.edgecolor": _GRID,
            "text.color": "#e6edf3",
            "axes.labelcolor": "#e6edf3",
            "xtick.color": "#e6edf3",
            "ytick.color": "#e6edf3",
            "axes.titlesize": 13,
            "axes.labelsize": 11,
        },
    )


def _save(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Saved {path}")


def plot_test_summary(json_path: Path, output_dir: Path) -> None:
    data: dict[str, object] = json.loads(json_path.read_text(encoding="utf-8"))

    summary: dict[str, int] = data.get("summary", {})  # type: ignore[assignment]
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)
    errored = summary.get("error", 0)
    total = passed + failed + skipped + errored

    tests: list[dict[str, object]] = data.get("tests", [])  # type: ignore[assignment]

    file_durations: dict[str, float] = {}
    for t in tests:
        nodeid = str(t.get("nodeid", ""))
        file = nodeid.split("::")[0] if "::" in nodeid else nodeid
        file_durations[file] = file_durations.get(file, 0.0) + float(
            t.get("duration", 0.0),
        )

    files = sorted(file_durations.keys())
    durations = [file_durations[f] for f in files]
    short_names = [Path(f).name for f in files]

    fig, (ax1, ax2) = plt.subplots(
        1,
        2,
        figsize=(14, max(5, len(files) * 0.5 + 2)),
        constrained_layout=True,
    )
    fig.suptitle(f"Test Suite Results ({total:,} tests)", fontsize=14)

    sizes = [passed, failed, skipped, errored]
    pie_labels = ["Passed", "Failed", "Skipped", "Error"]
    pie_colors = [_GREEN, _RED, _ORANGE, _PINK]
    non_zero = [
        (s, lbl, col)
        for s, lbl, col in zip(sizes, pie_labels, pie_colors, strict=False)
        if s > 0
    ]
    if non_zero:
        sz, lb, cl = zip(*non_zero, strict=False)
        ax1.pie(
            sz,
            labels=lb,
            colors=cl,
            autopct="%1.0f%%",
            startangle=90,
            textprops={"color": "#e6edf3"},
        )
    ax1.set_title("Pass Rate")

    y_pos = np.arange(len(files))
    ax2.barh(y_pos, durations, color=_BLUE, alpha=0.85)
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(short_names, fontsize=9)
    ax2.set_xlabel("Duration (seconds)")
    ax2.set_title("Cumulative Duration per Test File")
    ax2.grid(True, alpha=0.35, axis="x")
    ax2.invert_yaxis()

    _save(fig, output_dir / "test_suite.png")


def run(json_path: Path, output_dir: Path) -> None:
    if not json_path.exists():
        print(
            f"Error: {json_path} not found.\n"
            "Run: uv run pytest --json-report --json-report-file=reports/test_results.json",
            file=sys.stderr,
        )
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    _setup_theme()
    print(f"Generating test suite chart from {json_path} -> {output_dir}/")
    plot_test_summary(json_path, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test suite summary chart from pytest --json-report output.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=_DEFAULT_INPUT,
        metavar="JSON",
        help=f"pytest-json-report output file (default: {_DEFAULT_INPUT})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        metavar="DIR",
        help=f"Output directory for PNGs (default: {_DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    run(args.input, args.output)


if __name__ == "__main__":
    main()
