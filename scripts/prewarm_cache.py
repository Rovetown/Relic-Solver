import argparse
import json
import logging
import math
import os
import signal
import time
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path

import redis
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from relic_solver import expected_gems, expected_rerolls, solve
from relic_solver.config import DEFAULT_OBELISK_LEVEL

CAP = -1
_BATCH_SIZE = 1_000
_PREWARM_OBELISK_LEVEL = DEFAULT_OBELISK_LEVEL
_SOLVE_TIMEOUT = 120.0

_log = logging.getLogger(__name__)

_shutdown = False


_TIER_1_PATTERNS: list[tuple[int, ...]] = [
    (1, 0, 0, 0, 0),
    (3, 0, 0, 0, 0),
    (5, 0, 0, 0, 0),
    (10, 0, 0, 0, 0),
    (1, 1, 0, 0, 0),
    (2, 1, 0, 0, 0),
    (3, 2, 0, 0, 0),
    (1, 1, 1, 0, 0),
    (2, 1, 1, 0, 0),
    (1, 1, 1, 1, 0),
    (2, 1, 1, 1, 0),
    (3, 2, 1, 0, 0),
    (5, 3, 2, 1, 0),
    (5, CAP, CAP, CAP, CAP),
    (10, CAP, CAP, CAP, CAP),
]

_TIER_2_PATTERNS: list[tuple[int, ...]] = [
    *_TIER_1_PATTERNS,
    (15, 0, 0, 0, 0),
    (20, 0, 0, 0, 0),
    (30, 0, 0, 0, 0),
    (5, 3, 3, 2, 1),
    (10, 5, 5, 3, 2),
    (15, 10, 8, 5, 3),
    (1, CAP, CAP, CAP, CAP),
    (15, CAP, CAP, CAP, CAP),
    (20, CAP, CAP, CAP, CAP),
    (30, CAP, CAP, CAP, CAP),
]


def _handle_sigint(_signum: int, _frame: object) -> None:
    global _shutdown  # noqa: PLW0603
    if _shutdown:
        return
    _shutdown = True
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    _log.warning("Ctrl+C - shutting down gracefully (press again to force) ...")


def _cache_key(
    chests: int,
    divines: int,
    cap: int,
    targets: tuple[int, ...],
) -> str:
    target_csv = ",".join(str(t) for t in targets)
    return (
        f"solve:{chests}:{divines}:{cap}:{_PREWARM_OBELISK_LEVEL}:{target_csv}"
    )


def _normalize_targets(targets: tuple[int, ...], cap: int) -> tuple[int, ...]:
    return (targets[0], *(min(t, cap) for t in targets[1:]))


def _resolve_pattern(pattern: tuple[int, ...], cap: int) -> tuple[int, ...]:
    return tuple(cap if t == CAP else t for t in pattern)


def _solve_one(
    chests: int,
    divines: int,
    cap: int,
    targets: tuple[int, ...],
) -> tuple[str, str | None, float]:
    normalized = _normalize_targets(targets, cap)
    key = _cache_key(chests, divines, cap, normalized)

    t0 = time.perf_counter()
    try:
        prob = solve(
            chests,
            divines,
            targets,
            relic_cap=cap,
            obelisk_level=_PREWARM_OBELISK_LEVEL,
            max_seconds=_SOLVE_TIMEOUT,
        )
    except TimeoutError:
        return key, None, time.perf_counter() - t0

    duration = time.perf_counter() - t0
    rerolls = expected_rerolls(prob)
    gems = expected_gems(prob)

    value = json.dumps(
        {
            "probability": prob,
            "expected_rerolls": rerolls if not math.isinf(rerolls) else None,
            "expected_gems": gems if not math.isinf(gems) else None,
        },
        separators=(",", ":"),
    )
    return key, value, duration


def _build_grid(tier: int | None) -> list[tuple[int, int, int, tuple[int, ...]]]:
    jobs: list[tuple[int, int, int, tuple[int, ...]]] = []
    seen: set[str] = set()

    def _add(
        caps: range,
        chests_range: range,
        patterns: list[tuple[int, ...]],
    ) -> None:
        for cap in caps:
            resolved = [_resolve_pattern(p, cap) for p in patterns]
            for chests in chests_range:
                for divines in range(51):
                    for targets in resolved:
                        normalized = _normalize_targets(targets, cap)
                        key = _cache_key(chests, divines, cap, normalized)
                        if key not in seen:
                            seen.add(key)
                            jobs.append((chests, divines, cap, targets))

    if tier in (1, None):
        _add(
            caps=range(15, 18),
            chests_range=range(1_000_000, 5_000_001, 500_000),
            patterns=_TIER_1_PATTERNS,
        )

    if tier in (2, None):
        _add(
            caps=range(18, 22),
            chests_range=range(500_000, 5_000_001, 250_000),
            patterns=_TIER_2_PATTERNS,
        )

    return jobs


def _connect_redis() -> redis.Redis[str]:
    url = os.environ.get("REDISCLOUD_URL") or os.environ.get("REDIS_URL")
    if not url:
        raise SystemExit(
            "Set REDISCLOUD_URL or REDIS_URL environment variable",
        )
    rc = redis.Redis.from_url(url, decode_responses=True, socket_timeout=5)
    rc.ping()
    return rc  # type: ignore[return-value]


def _flush_batch(
    rc: redis.Redis[str],
    batch: list[tuple[str, str]],
) -> int:
    if not batch:
        return 0
    pipe = rc.pipeline(transaction=False)
    for key, value in batch:
        pipe.set(key, value)
    pipe.execute()
    return len(batch)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prewarm Redis cache with popular solver combinations.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=cpu_count(),
        help="parallel workers (default: CPU count)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute only, skip Redis writes",
    )
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2],
        default=None,
        help="run only one tier (default: both)",
    )
    args = parser.parse_args()

    console = Console()
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"prewarm_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_path=False,
            ),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    signal.signal(signal.SIGINT, _handle_sigint)

    tier_label = f"tier {args.tier}" if args.tier else "both tiers"
    _log.info("Building grid for %s ...", tier_label)
    jobs = _build_grid(args.tier)
    _log.info("Grid: %s jobs, %d workers", f"{len(jobs):,}", args.workers)

    if args.dry_run:
        _log.info("DRY RUN - no Redis writes")

    rc: redis.Redis[str] | None = None
    if not args.dry_run:
        _log.info("Connecting to Redis ...")
        rc = _connect_redis()
        _log.info("Redis connected - %s existing keys", f"{rc.dbsize():,}")

    completed = 0
    skipped = 0
    errors = 0
    written = 0
    batch: list[tuple[str, str]] = []

    with Progress(
        SpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(),
        MofNCompleteColumn(),
        "[cyan]{task.percentage:>3.0f}%",
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Prewarming", total=len(jobs))

        try:
            with ProcessPoolExecutor(max_workers=args.workers) as executor:
                futures: dict[
                    Future[tuple[str, str | None, float]],
                    tuple[int, int, int, tuple[int, ...]],
                ] = {}

                for job in jobs:
                    if _shutdown:
                        break
                    futures[executor.submit(_solve_one, *job)] = job

                for future in as_completed(futures):
                    if _shutdown:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    job = futures[future]
                    try:
                        key, value, duration = future.result()
                    except Exception:
                        _log.exception(
                            "Worker crashed: chests=%d divines=%d cap=%d"
                            " targets=%s",
                            *job,
                        )
                        errors += 1
                        progress.advance(task_id)
                        continue

                    completed += 1

                    if value is None:
                        skipped += 1
                        _log.warning(
                            "TIMEOUT (%.1fs): chests=%d divines=%d cap=%d"
                            " targets=%s",
                            duration,
                            *job,
                        )
                    elif rc is not None:
                        batch.append((key, value))
                        if len(batch) >= _BATCH_SIZE:
                            written += _flush_batch(rc, batch)
                            batch.clear()

                    progress.advance(task_id)

        except KeyboardInterrupt:
            _log.warning("KeyboardInterrupt - shutting down ...")

    if rc is not None and batch:
        written += _flush_batch(rc, batch)
        batch.clear()

    _log.info("─" * 50)
    _log.info("Completed: %s", f"{completed:,}")
    _log.info("Written:   %s", f"{written:,}")
    _log.info("Skipped:   %s (timeout)", f"{skipped:,}")
    _log.info("Errors:    %s", f"{errors:,}")
    if rc is not None:
        _log.info("Redis keys: %s", f"{rc.dbsize():,}")
    _log.info("Log file:  %s", log_file)
    if _shutdown:
        _log.warning("Interrupted - partial results saved")


if __name__ == "__main__":
    main()
