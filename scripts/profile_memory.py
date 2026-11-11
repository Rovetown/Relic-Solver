import argparse
import tracemalloc

from relic_solver.solver import solve


def _format_bytes(size: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024  # type: ignore[assignment]
    return f"{size:.1f} TiB"


def run(heavy: bool = False) -> None:
    if heavy:
        label = "Heavy (2M chests, cap=21, all relics)"
        args = (2_000_000, 100, (100, 21, 21, 21, 21))
        kwargs = {"relic_cap": 21}
    else:
        label = "Standard (150K chests, cap=5)"
        args = (150_000, 10, (3, 1, 1, 0, 0))
        kwargs = {}

    print(f"Profiling: {label}")
    print("-" * 50)

    tracemalloc.start()
    prob = solve(*args, **kwargs)  # type: ignore[arg-type]
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"Probability:    {prob:.6f}")
    print(f"Current memory: {_format_bytes(current)}")
    print(f"Peak memory:    {_format_bytes(peak)}")

    tracemalloc.start()
    solve(*args, **kwargs)  # type: ignore[arg-type]
    snapshot = tracemalloc.take_snapshot()
    tracemalloc.stop()

    top_stats = snapshot.statistics("lineno")
    print("\nTop 10 allocations:")
    for stat in top_stats[:10]:
        print(f"  {stat}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Solver memory profiler")
    parser.add_argument("--heavy", action="store_true", help="Use worst-case inputs")
    run(parser.parse_args().heavy)
