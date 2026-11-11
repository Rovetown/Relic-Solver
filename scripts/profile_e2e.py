import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
from relic_solver import expected_gems, expected_rerolls, solve  # noqa: E402

_CASES: list[tuple[str, int, int, int, list[int]]] = [
    ("Trivial (D1=1)",        0,         5,  15, [1, 0, 0, 0, 0]),
    ("Light (D1=5)",          3_000_000, 20, 16, [5, 0, 0, 0, 0]),
    ("Medium (3,1,1,0,0)",    2_000_000, 10, 15, [3, 1, 1, 0, 0]),
    ("Heavy (5,3,2,1,0)",     1_500_000, 30, 17, [5, 3, 2, 1, 0]),
    ("Very heavy (10,0,0,0)", 4_000_000, 40, 15, [10, 0, 0, 0, 0]),
]

_REDIS_ITERATIONS = 50
_SERIAL_ITERATIONS = 1000


_SEPARATOR = "=" * 74


def _median_ms(samples: list[float]) -> float:
    return statistics.median(samples) * 1000


def _stats_ms(samples: list[float]) -> str:
    med = statistics.median(samples) * 1000
    if len(samples) > 1:
        sd = statistics.stdev(samples) * 1000
        return f"{med:>8.2f} ± {sd:.2f} ms"
    return f"{med:>8.2f} ms"


def _parse_ndjson_result(raw: bytes) -> dict[str, object]:
    for line in raw.decode().strip().split("\n"):
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("type") == "result":
            return msg
    return {}


def _profile_redis(rc: object) -> None:
    print(f"\n{_SEPARATOR}")
    print("  LAYER 1: Raw Redis Latency")
    print(_SEPARATOR)

    ping_times: list[float] = []
    for _ in range(_REDIS_ITERATIONS):
        t0 = time.perf_counter()
        rc.ping()  # type: ignore[union-attr]
        ping_times.append(time.perf_counter() - t0)
    print(f"  PING          {_stats_ms(ping_times)}")

    test_key = "profile:test"
    test_val = json.dumps({"probability": 0.999, "expected_rerolls": 1.001, "expected_gems": 200})
    rc.set(test_key, test_val)  # type: ignore[union-attr]

    get_times: list[float] = []
    for _ in range(_REDIS_ITERATIONS):
        t0 = time.perf_counter()
        rc.get(test_key)  # type: ignore[union-attr]
        get_times.append(time.perf_counter() - t0)
    print(f"  GET           {_stats_ms(get_times)}")

    set_times: list[float] = []
    for _ in range(_REDIS_ITERATIONS):
        t0 = time.perf_counter()
        rc.set(test_key, test_val)  # type: ignore[union-attr]
        set_times.append(time.perf_counter() - t0)
    print(f"  SET           {_stats_ms(set_times)}")

    miss_times: list[float] = []
    for _ in range(_REDIS_ITERATIONS):
        t0 = time.perf_counter()
        rc.get("profile:nonexistent")  # type: ignore[union-attr]
        miss_times.append(time.perf_counter() - t0)
    print(f"  GET (miss)    {_stats_ms(miss_times)}")

    rc.delete(test_key)  # type: ignore[union-attr]

    print(f"\n  Network baseline (PING median): {_median_ms(ping_times):.2f} ms")


def _profile_serialization() -> None:
    print(f"\n{_SEPARATOR}")
    print("  LAYER 2: JSON Serialization")
    print(_SEPARATOR)

    payload = {
        "probability": 0.9999999992669946,
        "expected_rerolls": 1.0000000007330054,
        "expected_gems": 200,
    }

    ser_times: list[float] = []
    for _ in range(_SERIAL_ITERATIONS):
        t0 = time.perf_counter()
        json.dumps(payload, separators=(",", ":"))
        ser_times.append(time.perf_counter() - t0)
    print(f"  json.dumps    {_stats_ms(ser_times)}")

    raw = json.dumps(payload, separators=(",", ":"))
    deser_times: list[float] = []
    for _ in range(_SERIAL_ITERATIONS):
        t0 = time.perf_counter()
        json.loads(raw)
        deser_times.append(time.perf_counter() - t0)
    print(f"  json.loads    {_stats_ms(deser_times)}")

    ndjson_times: list[float] = []
    for _ in range(_SERIAL_ITERATIONS):
        t0 = time.perf_counter()
        json.dumps(payload, separators=(",", ":")) + "\n"
        ndjson_times.append(time.perf_counter() - t0)
    print(f"  NDJSON line   {_stats_ms(ndjson_times)}")


def _profile_solver() -> None:
    print(f"\n{_SEPARATOR}")
    print("  LAYER 3: Raw Solver Compute")
    print(_SEPARATOR)

    for label, chests, divines, cap, targets in _CASES:
        t0 = time.perf_counter()
        prob = solve(chests, divines, tuple(targets), relic_cap=cap)
        elapsed = time.perf_counter() - t0

        t1 = time.perf_counter()
        _ = expected_rerolls(prob)
        _ = expected_gems(prob)
        post_ms = (time.perf_counter() - t1) * 1000

        print(
            f"  {label:<25s}  solve={elapsed * 1000:>9.1f} ms"
            f"  post={post_ms:.3f} ms  p={prob:.6e}",
        )


def _profile_flask(client: object, rc: object) -> None:
    print(f"\n{_SEPARATOR}")
    print("  LAYER 4a: Flask Full Request - CACHE MISS")
    print(_SEPARATOR)

    miss_results: list[tuple[str, float, float]] = []

    for label, chests, divines, cap, targets in _CASES:
        inp = {
            "total_relic_chests": chests,
            "divine_chests": divines,
            "relic_cap": cap,
            "targets": targets,
        }
        normalized = (targets[0], *(min(t, cap) for t in targets[1:]))
        csv = ",".join(str(t) for t in normalized)
        key = f"solve:{chests}:{divines}:{cap}:{csv}"
        rc.delete(key)  # type: ignore[union-attr]

        t0 = time.perf_counter()
        resp = client.post("/solve", json=inp, content_type="application/json")  # type: ignore[union-attr]
        raw = resp.data
        elapsed = time.perf_counter() - t0

        result = _parse_ndjson_result(raw)
        solve_ms = result.get("solve_time_ms", 0)

        overhead = elapsed * 1000 - float(solve_ms)  # type: ignore[arg-type]
        miss_results.append((label, elapsed * 1000, overhead))

        print(
            f"  {label:<25s}  total={elapsed * 1000:>9.1f} ms"
            f"  solver={solve_ms} ms"
            f"  overhead={overhead:>6.1f} ms",
        )

    print(f"\n{_SEPARATOR}")
    print("  LAYER 4b: Flask Full Request - CACHE HIT")
    print(_SEPARATOR)

    hit_results: list[tuple[str, float]] = []

    for label, chests, divines, cap, targets in _CASES:
        inp = {
            "total_relic_chests": chests,
            "divine_chests": divines,
            "relic_cap": cap,
            "targets": targets,
        }
        times: list[float] = []
        for _ in range(5):
            t0 = time.perf_counter()
            resp = client.post("/solve", json=inp, content_type="application/json")  # type: ignore[union-attr]
            _ = resp.data
            times.append(time.perf_counter() - t0)

        med = _median_ms(times)
        hit_results.append((label, med))

        result = _parse_ndjson_result(resp.data)  # type: ignore[possibly-undefined]
        cached = result.get("cached", False)
        print(
            f"  {label:<25s}  median={med:>8.2f} ms"
            f"  cached={cached}",
        )

    print(f"\n{_SEPARATOR}")
    print("  SUMMARY: Time Breakdown")
    print(_SEPARATOR)
    print(
        f"  {'Case':<25s} {'Miss (ms)':>10s} {'Solver (ms)':>12s}"
        f" {'Overhead':>10s} {'Hit (ms)':>10s}",
    )
    print(f"  {'-' * 25} {'-' * 10} {'-' * 12} {'-' * 10} {'-' * 10}")

    for (label, miss_total, miss_overhead), (_, hit_med) in zip(
        miss_results,
        hit_results, strict=False,
    ):
        solver_ms = miss_total - miss_overhead
        print(
            f"  {label:<25s} {miss_total:>10.1f} {solver_ms:>12.1f}"
            f" {miss_overhead:>10.1f} {hit_med:>10.2f}",
        )


def main() -> None:
    rc = app_module.redis_client
    if rc is None:
        print("ERROR: Redis not connected - set REDISCLOUD_URL or REDIS_URL")
        raise SystemExit(1)

    app_module.limiter.enabled = False
    client = app_module.app.test_client()

    print(f"Redis connected - {rc.dbsize()} existing keys")
    print(f"Profiling {len(_CASES)} input combinations\n")

    _profile_redis(rc)
    _profile_serialization()
    _profile_solver()
    _profile_flask(client, rc)

    print(f"\n{_SEPARATOR}")
    print("  VERDICT")
    print(_SEPARATOR)
    print(
        "  Compare 'Overhead' column against raw Redis GET median.\n"
        "  The difference is Flask routing + middleware + response construction.\n"
        "  If solver time dominates cache misses, Steps 5/6 are worthwhile.\n"
        "  If overhead dominates, optimize Flask layer instead.",
    )


if __name__ == "__main__":
    main()
