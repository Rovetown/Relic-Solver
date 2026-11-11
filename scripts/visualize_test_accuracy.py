import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from relic_solver.solver import solve

_DEFAULT_OUTPUT = Path("reports/visuals/accuracy")

_BLUE = "#4da3ff"
_RED = "#ff6b6b"
_GREEN = "#66cc66"
_MUTED = "#8b949e"
_BG = "#0d1117"
_AXES_BG = "#161b22"
_GRID = "#30363d"

_CASES: list[tuple[str, int, int, tuple[int, ...], int, float]] = [
    ("all_zero_target",      0,       0,   (0, 0, 0, 0, 0), 5, 1.0),
    ("zero_target_chests",   100_000, 50,  (0, 0, 0, 0, 0), 5, 1.0),
    ("d1_guaranteed_1div",   0,       1,   (1, 0, 0, 0, 0), 5, 1.0),
    ("d1_guaranteed_100div", 0,       100, (1, 0, 0, 0, 0), 5, 1.0),
    ("no_chests_d1",         0,       0,   (1, 0, 0, 0, 0), 5, 0.0),
    ("d2_impossible_1div",   0,       1,   (0, 1, 0, 0, 0), 5, 0.0),
    ("d2_impossible_2div",   0,       2,   (0, 1, 0, 0, 0), 5, 0.0),
    ("d2_impossible_3div",   0,       3,   (0, 1, 0, 0, 0), 5, 0.0),
    ("d3_impossible_6div",   0,       6,   (0, 0, 1, 0, 0), 5, 0.0),
    ("d4_impossible_10div",  0,       10,  (0, 0, 0, 1, 0), 5, 0.0),
    ("d5_impossible_30div",  0,       30,  (0, 0, 0, 0, 1), 5, 0.0),
    ("single_chest_d1",      1,       0,   (1, 0, 0, 0, 0), 5, 1.0 / 25_000),
]


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


def plot_accuracy(output_dir: Path) -> None:
    labels = [c[0] for c in _CASES]
    expected = np.array([c[5] for c in _CASES])
    computed = np.array(
        [solve(c[1], c[2], c[3], relic_cap=c[4]) for c in _CASES],
    )

    abs_err = np.abs(computed - expected)

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(12, 9),
        gridspec_kw={"height_ratios": [3, 2]},
        constrained_layout=True,
    )
    fig.suptitle("Solver Accuracy: Computed vs Known Expected Values", fontsize=14)

    ax1.scatter(expected, computed, c=_BLUE, s=60, alpha=0.9, zorder=3, label="Test cases")
    lim = max(float(expected.max()), float(computed.max())) * 1.05
    ax1.plot([0, lim], [0, lim], "--", color=_RED, linewidth=1.5, label="Perfect agreement (y = x)")
    ax1.set_xscale("symlog", linthresh=1e-5)
    ax1.set_yscale("symlog", linthresh=1e-5)
    ax1.set_xlabel("Expected Probability")
    ax1.set_ylabel("Computed Probability")
    ax1.set_title("All points should lie on the diagonal")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.35)

    x = np.arange(len(labels))
    bar_colors = [_GREEN if e < 1e-10 else _RED for e in abs_err]
    ax2.bar(x, abs_err, color=bar_colors, alpha=0.85)
    ax2.axhline(y=1e-10, color=_MUTED, linewidth=0.8, linestyle=":", label="1e-10 tolerance")

    if any(e > 0 for e in abs_err):
        ax2.set_yscale("symlog", linthresh=1e-16)

    ax2.set_ylabel("Absolute Error")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax2.set_title("Absolute Error per Case (green = within 1e-10)")
    ax2.grid(True, alpha=0.35, axis="y")
    ax2.legend(fontsize=8)

    _save(fig, output_dir / "test_accuracy.png")


def run(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _setup_theme()
    print(f"Generating accuracy chart -> {output_dir}/")
    plot_accuracy(output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Solver accuracy chart against known exact expected values.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
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
    run(args.output)


if __name__ == "__main__":
    main()
