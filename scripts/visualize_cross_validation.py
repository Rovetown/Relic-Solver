import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import binom as binom_dist

from relic_solver.config import DEFAULT_RELIC_CAP, DIVINE_CHANCE, NUM_RELIC_TYPES
from relic_solver.solver import _solve_dict, _solve_numpy

_DEFAULT_OUTPUT = Path("reports/visuals/cross_validation")

_BLUE = "#4da3ff"
_PURPLE = "#b084f5"
_RED = "#ff6b6b"
_GREEN = "#66cc66"
_MUTED = "#8b949e"
_BG = "#0d1117"
_AXES_BG = "#161b22"
_GRID = "#30363d"

_CASES: list[tuple[str, int, int, tuple[int, ...], int]] = [
    ("trivial_d1",   0,       5,  (1, 0, 0, 0, 0), DEFAULT_RELIC_CAP),
    ("d2_unlock",    0,       4,  (0, 1, 0, 0, 0), DEFAULT_RELIC_CAP),
    ("d3_unlock",    0,       7,  (0, 0, 1, 0, 0), DEFAULT_RELIC_CAP),
    ("d4_unlock",    0,       11, (0, 0, 0, 1, 0), DEFAULT_RELIC_CAP),
    ("d5_unlock",    0,       31, (0, 0, 0, 0, 1), DEFAULT_RELIC_CAP),
    ("mixed_modest", 50_000,  10, (3, 1, 1, 0, 0), DEFAULT_RELIC_CAP),
    ("higher_cap",   10_000,  10, (2, 2, 1, 0, 0), 10),
    ("all_types",    0,       50, (10, 5, 5, 5, 1), DEFAULT_RELIC_CAP),
    ("impossible",   0,       3,  (0, 1, 0, 0, 0), DEFAULT_RELIC_CAP),
    ("all_at_cap",   0,       50, (5, 5, 5, 5, 5), DEFAULT_RELIC_CAP),
    ("single_chest", 1,       0,  (1, 0, 0, 0, 0), DEFAULT_RELIC_CAP),
    ("cap_1",        0,       50, (5, 1, 1, 1, 1), 1),
    ("cap_15",       100_000, 15, (3, 2, 2, 1, 0), 15),
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


def _run_case(
    total_relic_chests: int,
    divine_chests: int,
    target_relics: tuple[int, ...],
    relic_cap: int,
) -> tuple[float, float]:
    target: tuple[int, ...] = (
        target_relics[0],
        *(min(target_relics[i], relic_cap) for i in range(1, NUM_RELIC_TYPES)),
    )

    if total_relic_chests > 0 and DIVINE_CHANCE > 0:
        k_max = max(
            int(binom_dist.ppf(1 - 1e-15, total_relic_chests, DIVINE_CHANCE)),
            0,
        )
        pmf_arr = binom_dist.pmf(range(k_max + 1), total_relic_chests, DIVINE_CHANCE)
        pmf_values: list[float] = [float(v) for v in pmf_arr]
    else:
        k_max = 0
        pmf_values = [1.0]

    d_max = divine_chests + k_max
    if d_max == 0:
        return 0.0, 0.0

    numpy_result = _solve_numpy(
        target=target,
        relic_cap=relic_cap,
        divine_chests=divine_chests,
        d_max=d_max,
        k_max=k_max,
        pmf_values=pmf_values,
        deadline=None,
        max_seconds=None,
        progress_callback=None,
    )
    dict_result = _solve_dict(
        target=target,
        relic_cap=relic_cap,
        divine_chests=divine_chests,
        d_max=d_max,
        k_max=k_max,
        pmf_values=pmf_values,
        deadline=None,
        max_seconds=None,
        progress_callback=None,
    )
    return numpy_result, dict_result


def plot_cross_validation(output_dir: Path) -> None:
    print(f"Running {len(_CASES)} cross-validation cases...")

    labels = [c[0] for c in _CASES]
    numpy_vals: list[float] = []
    dict_vals: list[float] = []

    for label, chests, divines, target, cap in _CASES:
        n, d = _run_case(chests, divines, target, cap)
        numpy_vals.append(n)
        dict_vals.append(d)
        print(f"  {label}: numpy={n:.8f}  dict={d:.8f}")

    numpy_arr = np.array(numpy_vals)
    dict_arr = np.array(dict_vals)
    abs_diff = np.abs(numpy_arr - dict_arr)

    x = np.arange(len(labels))
    width = 0.38

    fig, (ax1, ax2) = plt.subplots(
        1,
        2,
        figsize=(15, 6),
        constrained_layout=True,
    )
    fig.suptitle("Cross-Validation: NumPy vs Dict Solver Agreement", fontsize=14)

    ax1.bar(x - width / 2, numpy_arr, width, label="NumPy", color=_BLUE, alpha=0.85)
    ax1.bar(x + width / 2, dict_arr, width, label="Dict", color=_PURPLE, alpha=0.85)
    ax1.set_ylabel("Probability")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax1.set_title("Probability by Implementation")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.35, axis="y")

    bar_colors = [_GREEN if d < 1e-12 else _RED for d in abs_diff]
    ax2.bar(x, abs_diff, color=bar_colors, alpha=0.85)
    ax2.axhline(
        y=1e-12,
        color=_MUTED,
        linewidth=0.8,
        linestyle="--",
        label="1e-12 tolerance",
    )
    ax2.set_ylabel("Absolute Difference")
    ax2.set_yscale("symlog", linthresh=1e-16)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax2.set_title("Agreement (green = within 1e-12, lower = better)")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.35, axis="y")

    _save(fig, output_dir / "cross_validation.png")


def run(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _setup_theme()
    print(f"Generating cross-validation chart -> {output_dir}/")
    plot_cross_validation(output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NumPy vs dict solver cross-validation chart.",
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
