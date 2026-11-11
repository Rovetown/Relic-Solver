import argparse
import csv
import sys
from pathlib import Path


def merge_csvs(input_files: list[Path], output: Path) -> None:
    fieldnames: list[str] | None = None
    all_rows: list[dict[str, str]] = []

    for path in input_files:
        if not path.exists():
            print(f"Warning: {path} not found, skipping", file=sys.stderr)
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if fieldnames is None:
                fieldnames = list(reader.fieldnames or [])
            for row in reader:
                all_rows.append(row)

    if not all_rows or not fieldnames:
        print("No data to merge.", file=sys.stderr)
        return

    seen: set[tuple[str, ...]] = set()
    unique_rows: list[dict[str, str]] = []
    for row in all_rows:
        key = tuple(row.get(f, "") for f in fieldnames)
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(unique_rows)

    n_dupes = len(all_rows) - len(unique_rows)
    print(
        f"Merged {len(all_rows)} rows from {len(input_files)} file(s) "
        f"-> {len(unique_rows)} unique rows "
        f"({n_dupes} duplicate{'s' if n_dupes != 1 else ''} removed) "
        f"-> {output}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge CSV files and remove exact duplicate rows.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Input CSV files (used together with --dir or alone)",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Directory to glob CSV files from",
    )
    parser.add_argument(
        "--pattern",
        default="*.csv",
        metavar="GLOB",
        help='Glob pattern for --dir mode (default: "*.csv")',
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        metavar="FILE",
        help="Output CSV file",
    )
    args = parser.parse_args()

    input_files: list[Path] = list(args.files)

    if args.dir is not None:
        if not args.dir.is_dir():
            print(f"Error: {args.dir} is not a directory", file=sys.stderr)
            sys.exit(1)
        input_files.extend(sorted(args.dir.glob(args.pattern)))

    if not input_files:
        print(
            "Error: no input files. Pass file paths directly or use --dir + --pattern.",
            file=sys.stderr,
        )
        sys.exit(1)

    resolved_output = args.output.resolve()
    input_files = [f for f in input_files if f.resolve() != resolved_output]

    merge_csvs(input_files, args.output)


if __name__ == "__main__":
    main()
