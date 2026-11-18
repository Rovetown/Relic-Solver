import argparse
import sys
from pathlib import Path

import pandas as pd

_DEFAULT_INPUT = Path("reports/analytics_merged.csv")


def _section(label: str, lines: list[str]) -> None:
    lines.append(f"--- {label} ---")


def _row(label: str, value: object, lines: list[str], indent: int = 2) -> None:
    lines.append(f"{' ' * indent}{label:<10} {value}")


def _numeric_block(
    series: pd.Series[float],
    label: str,
    lines: list[str],
    *,
    percentiles: list[int] | None = None,
    show_mode: bool = False,
) -> None:
    _section(label, lines)
    _row("mean", f"{series.mean():,.1f}", lines)
    _row("median", f"{series.median():,.1f}", lines)
    _row("min", f"{series.min():,.0f}", lines)
    _row("max", f"{series.max():,.0f}", lines)
    for p in percentiles or []:
        _row(f"p{p}", f"{series.quantile(p / 100):,.1f}", lines)
    if show_mode and not series.empty:
        _row("mode", f"{int(series.mode().iloc[0])}", lines)
    lines.append("")


def compute_stats(df: pd.DataFrame, output: Path | None) -> None:
    lines: list[str] = []
    n = len(df)
    lines.append(f"=== Aggregate Statistics ({n:,} rows) ===")
    lines.append("")

    if "chests" in df.columns:
        _numeric_block(df["chests"], "chests", lines, percentiles=[95])

    if "divines" in df.columns:
        _numeric_block(df["divines"], "divines", lines)

    if "cap" in df.columns:
        _section("cap", lines)
        mode_val = int(df["cap"].mode().iloc[0])
        lines.append(f"  mode       {mode_val}")
        lines.append("  distribution:")
        for val, count in df["cap"].value_counts().sort_index().items():
            bar = "#" * min(int(count / n * 40), 40)
            lines.append(f"    {int(val):>2}: {count:>6,}  ({count / n * 100:5.1f}%)  {bar}")
        lines.append("")

    if "ob" in df.columns:
        _section("obelisk level", lines)
        lines.append("  distribution:")
        for val, count in df["ob"].value_counts().sort_index().items():
            bar = "#" * min(int(count / n * 40), 40)
            lines.append(f"    {int(val):>3}: {count:>6,}  ({count / n * 100:5.1f}%)  {bar}")
        lines.append("")

    target_cols = [c for c in ["d1", "d2", "d3", "d4", "d5"] if c in df.columns]
    if target_cols:
        _section("targets", lines)
        for col in target_cols:
            s = df[col]
            nonzero_pct = (s > 0).mean() * 100
            lines.append(
                f"  {col}: mean={s.mean():.2f}  "
                f"nonzero={nonzero_pct:.1f}%  "
                f"max={int(s.max())}",
            )
        lines.append("")

    if "prob" in df.columns:
        _section("probability", lines)
        s = df["prob"]
        _row("mean", f"{s.mean():.4%}", lines)
        _row("median", f"{s.median():.4%}", lines)
        _row("min", f"{s.min():.4%}", lines)
        _row("max", f"{s.max():.4%}", lines)
        zero_pct = (s == 0).mean() * 100
        lines.append(f"  impossible (prob=0): {zero_pct:.1f}% of solves")
        lines.append("")

    if "ms" in df.columns:
        _numeric_block(df["ms"], "solve time (ms)", lines, percentiles=[95, 99])

    group_cols = [c for c in ["cap", "d1", "d2", "d3", "d4", "d5"] if c in df.columns]
    if group_cols:
        _section("top 10 input combinations", lines)
        top = (
            df.groupby(group_cols)
            .size()
            .sort_values(ascending=False)
            .head(10)
        )
        for combo, count in top.items():
            parts = combo if isinstance(combo, tuple) else (combo,)
            label = "  ".join(f"{k}={int(v)}" for k, v in zip(group_cols, parts, strict=False))
            lines.append(f"  {count:>5,}x  {label}")
        lines.append("")

    text = "\n".join(lines)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(f"Stats saved to {output}")
    else:
        print(text)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate statistics from exported solver CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=_DEFAULT_INPUT,
        help=f"Input CSV file (default: {_DEFAULT_INPUT})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        metavar="FILE",
        help="Save stats report to FILE instead of printing to stdout",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(
            f"Error: {args.input} not found.\n"
            "Run 'just getdata && just datamerge' first, or pass a CSV path directly.",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_csv(args.input)
    if df.empty:
        print(f"Error: {args.input} is empty.", file=sys.stderr)
        sys.exit(1)

    compute_stats(df, args.output)


if __name__ == "__main__":
    main()
