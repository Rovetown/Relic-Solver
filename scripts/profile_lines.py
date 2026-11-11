from line_profiler import profile

from relic_solver.config import (
    UNLOCK_D2_THRESHOLD,
    UNLOCK_D3_THRESHOLD,
    UNLOCK_D4_THRESHOLD,
    UNLOCK_D5_THRESHOLD,
)


@profile  # type: ignore[untyped-decorator]
def solve_profiled() -> float:
    from relic_solver.solver import solve

    return solve(150_000, 10, (3, 1, 1, 0, 0))


if __name__ == "__main__":
    prob = solve_profiled()
    print(f"\nProbability: {prob:.6f}")
    print(
        "\nTo profile the solver internals directly, run:\n"
        "  uv run kernprof -lv -m relic_solver\n"
        "\nOr add @profile to specific functions in solver.py temporarily.",
    )
    print(
        f"\nUnlock thresholds: D2={UNLOCK_D2_THRESHOLD}, "
        f"D3={UNLOCK_D3_THRESHOLD}, D4={UNLOCK_D4_THRESHOLD}, "
        f"D5={UNLOCK_D5_THRESHOLD}",
    )
