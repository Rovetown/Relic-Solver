import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

_DEFAULT_BENCH_DIR = Path(".benchmarks")
_DEFAULT_OUTPUT = Path("reports/visuals/benchmarks")

_BLUE = "#4da3ff"
_PURPLE = "#b084f5"
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


def _find_latest_benchmark(bench_dir: Path) -> Path | None:
    json_files = sorted(
        bench_dir.rglob("*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return json_files[-1] if json_files else None


def plot_benchmarks(json_path: Path, output_dir: Path) -> None:
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    benchmarks: list[dict[str, object]] = raw.get("benchmarks", [])

    if not benchmarks:
        print(f"Error: no benchmark entries found in {json_path}.", file=sys.stderr)
        sys.exit(1)

    benchmarks.sort(key=lambda b: float(b["stats"]["mean"]))  # type: ignore[index]

    def _label(b: dict[str, object]) -> str:
        name = str(b.get("name", ""))
        fullname = str(b.get("fullname", ""))
        if "::" in fullname:
            name = fullname.rsplit("::", 1)[-1]
        return name.removeprefix("test_bench_").replace("_", " ")

    names = [_label(b) for b in benchmarks]
    stats = [b["stats"] for b in benchmarks]  # type: ignore[index]

    means = np.array([float(s["mean"]) * 1000 for s in stats])   # type: ignore[index]
    stddevs = np.array([float(s["stddev"]) * 1000 for s in stats])  # type: ignore[index]
    mins = np.array([float(s["min"]) * 1000 for s in stats])   # type: ignore[index]
    maxs = np.array([float(s["max"]) * 1000 for s in stats])   # type: ignore[index]

    fig_height = max(5, len(names) * 0.45)
    fig, ax = plt.subplots(figsize=(13, fig_height), constrained_layout=True)
    fig.suptitle(f"Benchmark Results -- {json_path.stem}", fontsize=14)

    y_pos = np.arange(len(names))
    ax.barh(
        y_pos,
        means,
        xerr=stddevs,
        height=0.6,
        color=_BLUE,
        alpha=0.85,
        capsize=4,
        error_kw={"ecolor": _PURPLE, "capthick": 1.5},
    )

    x_offset = float(means.max()) * 0.01
    for i, (mean, mn, mx) in enumerate(zip(means, mins, maxs, strict=False)):
        ax.text(
            mean + stddevs[i] + x_offset,
            i,
            f"{mean:.2f} ms  (min {mn:.2f}, max {mx:.2f})",
            va="center",
            fontsize=8,
            color="#e6edf3",
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel("Mean Time (ms)")
    ax.set_title("Sorted fastest to slowest -- error bars show stddev")
    ax.grid(True, alpha=0.35, axis="x")
    ax.invert_yaxis()

    _save(fig, output_dir / "benchmarks.png")


def run(input_path: Path, output_dir: Path) -> None:
    if input_path.is_dir():
        json_path = _find_latest_benchmark(input_path)
        if json_path is None:
            print(
                f"Error: no benchmark JSON files found under {input_path}.\n"
                "Run 'just bench-save baseline' first.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Using most recent benchmark file: {json_path}")
    else:
        json_path = input_path
        if not json_path.exists():
            print(f"Error: {json_path} not found.", file=sys.stderr)
            sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    _setup_theme()
    print(f"Generating benchmark chart -> {output_dir}/")
    plot_benchmarks(json_path, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Solver benchmark timing chart from pytest-benchmark JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=_DEFAULT_BENCH_DIR,
        metavar="PATH",
        help=(
            "Benchmark JSON file or .benchmarks/ directory "
            f"(default: {_DEFAULT_BENCH_DIR}, auto-selects latest)"
        ),
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
