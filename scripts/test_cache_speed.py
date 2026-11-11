import json
import time

import app as app_module

_TEST_INPUTS = [
    {
        "total_relic_chests": 2_000_000,
        "divine_chests": 10,
        "relic_cap": 15,
        "targets": [3, 1, 1, 0, 0],
    },
    {
        "total_relic_chests": 3_000_000,
        "divine_chests": 20,
        "relic_cap": 16,
        "targets": [5, 0, 0, 0, 0],
    },
    {
        "total_relic_chests": 1_000_000,
        "divine_chests": 5,
        "relic_cap": 15,
        "targets": [1, 1, 0, 0, 0],
    },
    {
        "total_relic_chests": 1_500_000,
        "divine_chests": 30,
        "relic_cap": 17,
        "targets": [5, 3, 2, 1, 0],
    },
    {
        "total_relic_chests": 4_000_000,
        "divine_chests": 40,
        "relic_cap": 15,
        "targets": [10, 0, 0, 0, 0],
    },
]


def _parse_ndjson_result(raw: bytes) -> dict[str, object]:
    for line in raw.decode().strip().split("\n"):
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("type") == "result":
            return msg
    return {}


def _cache_key_for(inp: dict[str, object]) -> str:
    chests = inp["total_relic_chests"]
    divines = inp["divine_chests"]
    cap: int = inp["relic_cap"]  # type: ignore[assignment]
    targets = tuple(inp["targets"])  # type: ignore[arg-type]
    normalized = (targets[0], *(min(t, cap) for t in targets[1:]))
    csv = ",".join(str(t) for t in normalized)
    return f"solve:{chests}:{divines}:{cap}:{csv}"


def _timed_solve(
    client: object,
    inp: dict[str, object],
) -> tuple[float, dict[str, object]]:
    t0 = time.perf_counter()
    resp = client.post(  # type: ignore[union-attr]
        "/solve",
        json=inp,
        content_type="application/json",
    )
    raw = resp.data
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return elapsed_ms, _parse_ndjson_result(raw)


def main() -> None:
    rc = app_module.redis_client
    if rc is None:
        raise SystemExit(
            "Redis not connected -- set REDISCLOUD_URL or REDIS_URL",
        )

    app_module.limiter.enabled = False
    client = app_module.app.test_client()

    print(f"\nRedis connected -- {rc.dbsize()} existing keys")
    print(f"Testing {len(_TEST_INPUTS)} input combinations\n")

    print("Flushing test keys ...")
    for inp in _TEST_INPUTS:
        key = _cache_key_for(inp)
        existed = rc.delete(key)
        tag = "(was cached)" if existed else "(not in cache)"
        print(f"  {key}  {tag}")
    print()

    print("=" * 72)
    print("  COLD RUN (uncached -- solver computes from scratch)")
    print("=" * 72)
    cold_times: list[float] = []

    for inp in _TEST_INPUTS:
        elapsed_ms, result = _timed_solve(client, inp)
        cold_times.append(elapsed_ms)

        solve_ms = result.get("solve_time_ms", "?")
        cached = result.get("cached", False)
        prob = result.get("probability", "?")
        print(
            f"  targets={str(inp['targets']):<20s} cap={inp['relic_cap']}"
            f"  -> {elapsed_ms:>9.1f}ms  solve={solve_ms}ms"
            f"  cached={cached}  p={prob}",
        )

    print()
    print("=" * 72)
    print("  HOT RUN (cached -- Redis lookup)")
    print("=" * 72)
    hot_times: list[float] = []

    for inp in _TEST_INPUTS:
        elapsed_ms, result = _timed_solve(client, inp)
        hot_times.append(elapsed_ms)

        cached = result.get("cached", False)
        prob = result.get("probability", "?")
        print(
            f"  targets={str(inp['targets']):<20s} cap={inp['relic_cap']}"
            f"  -> {elapsed_ms:>9.1f}ms"
            f"  cached={cached}  p={prob}",
        )

    print()
    print("=" * 72)
    print("  COMPARISON")
    print("=" * 72)
    header = f"  {'Targets':<20s} {'Cold (ms)':>10s} {'Hot (ms)':>10s} {'Speedup':>10s}"
    sep = f"  {'-' * 20} {'-' * 10} {'-' * 10} {'-' * 10}"
    print(header)
    print(sep)
    for inp, cold, hot in zip(_TEST_INPUTS, cold_times, hot_times, strict=False):
        speedup = cold / hot if hot > 0 else float("inf")
        print(
            f"  {str(inp['targets']):<20s}"
            f" {cold:>10.1f} {hot:>10.1f} {speedup:>9.0f}x",
        )
    print(sep)
    avg_cold = sum(cold_times) / len(cold_times)
    avg_hot = sum(hot_times) / len(hot_times)
    avg_speedup = avg_cold / avg_hot if avg_hot > 0 else float("inf")
    print(
        f"  {'AVERAGE':<20s}"
        f" {avg_cold:>10.1f} {avg_hot:>10.1f} {avg_speedup:>9.0f}x",
    )

    print(f"\nRedis keys after test: {rc.dbsize()}")


if __name__ == "__main__":
    main()
