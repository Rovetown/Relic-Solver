import argparse
import csv
import json
import os
import sys
from os.path import dirname, join
from pathlib import Path

import redis
from dotenv import load_dotenv

dotenv_path = join(dirname(__file__), '../.env')

load_dotenv(dotenv_path)

def _get_redis_client() -> redis.Redis[str]:
    url = os.environ.get("REDISCLOUD_URL")
    if not url:
        print(
            "Error: set REDISCLOUD_URL or REDIS_URL to your Redis connection string.",
            file=sys.stderr,
        )
        print(
            "  heroku config:get REDISCLOUD_URL --app iomreliccalc",
            file=sys.stderr,
        )
        sys.exit(1)
    client: redis.Redis[str] = redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_timeout=10,
    )
    client.ping()
    return client


def _write_csv(
    rows: list[dict[str, object]],
    fieldnames: list[str],
    output: Path | None,
) -> None:
    if output is not None:
        with output.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} rows to {output}")
    else:
        writer = csv.DictWriter(
            sys.stdout,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_json(data: object, output: Path | None) -> None:
    text = json.dumps(data, indent=2)
    if output is not None:
        output.write_text(text, encoding="utf-8")
        n = len(data) if isinstance(data, list) else 1  # type: ignore[arg-type]
        print(f"Wrote {n} entries to {output}")
    else:
        print(text)


_ANALYTICS_FIELDS = ["ts", "chests", "divines", "cap", "d1", "d2", "d3", "d4", "d5", "prob", "ms"]
_CACHE_FIELDS = ["chests", "divines", "cap", "d2", "d3", "d4", "d5"]


def export_analytics(
    client: redis.Redis[str],
    *,
    limit: int | None,
    output: Path | None,
    fmt: str,
) -> None:
    raw = client.lrange("analytics:solves", 0, -1)
    if not raw:
        print(
            "No analytics entries found. Entries are written each time a user"
            " clicks 'Run Solver' (with analytics consent).",
            file=sys.stderr,
        )
        return

    entries = [json.loads(r) for r in raw]
    if limit is not None:
        entries = entries[:limit]

    if fmt == "json":
        _write_json(entries, output)
        return

    rows: list[dict[str, object]] = []
    for e in entries:
        targets: list[int] = e.get("targets", [0, 0, 0, 0, 0])
        rows.append({
            "ts": e.get("ts", ""),
            "chests": e.get("chests", ""),
            "divines": e.get("divines", ""),
            "cap": e.get("cap", ""),
            "d1": targets[0] if len(targets) > 0 else "",
            "d2": targets[1] if len(targets) > 1 else "",
            "d3": targets[2] if len(targets) > 2 else "",
            "d4": targets[3] if len(targets) > 3 else "",
            "d5": targets[4] if len(targets) > 4 else "",
            "prob": e.get("prob", ""),
            "ms": e.get("ms", ""),
        })
    _write_csv(rows, _ANALYTICS_FIELDS, output)


def export_cache_keys(
    client: redis.Redis[str],
    *,
    output: Path | None,
    fmt: str,
) -> None:
    rows: list[dict[str, object]] = []
    for key in client.scan_iter("solve:*"):
        parts = key.split(":")
        if len(parts) != 5:
            continue
        target_parts = parts[4].split(",")
        rows.append({
            "chests": parts[1],
            "divines": parts[2],
            "cap": parts[3],
            "d2": target_parts[0] if len(target_parts) > 0 else "",
            "d3": target_parts[1] if len(target_parts) > 1 else "",
            "d4": target_parts[2] if len(target_parts) > 2 else "",
            "d5": target_parts[3] if len(target_parts) > 3 else "",
        })

    if not rows:
        print("No cached solve results found in Redis.", file=sys.stderr)
        return

    if fmt == "json":
        _write_json(rows, output)
        return

    _write_csv(rows, _CACHE_FIELDS, output)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export solver analytics from Redis to CSV or JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["analytics", "cache"],
        default="analytics",
        help=(
            "analytics: timestamped per-request data (analytics:solves list); "
            "cache: unique input combinations from solve:* cache keys (default: analytics)"
        ),
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["csv", "json"],
        default="csv",
        dest="fmt",
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Return only the N most recent entries (analytics mode only)",
    )
    args = parser.parse_args()

    load_dotenv()
    client = _get_redis_client()

    if args.mode == "cache":
        export_cache_keys(client, output=args.output, fmt=args.fmt)
    else:
        export_analytics(client, limit=args.limit, output=args.output, fmt=args.fmt)


if __name__ == "__main__":
    main()
