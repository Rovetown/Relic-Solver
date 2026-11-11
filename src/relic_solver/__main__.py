from relic_solver.solver import solve


def main() -> None:
    prob = solve(150_000, 10, (3, 1, 1, 0, 0))
    print(f"Probability: {prob}")


if __name__ == "__main__":
    main()
