import math
from typing import Any, Protocol

import pytest

from relic_solver.config import (
    COST_PER_REROLL,
    DEFAULT_RELIC_CAP,
    DIVINE_CHANCE,
    MAX_RELIC_CAP,
    MIN_RELIC_CAP,
    NUM_RELIC_TYPES,
    RATE_LIMIT_DEFAULT,
    RATE_LIMIT_SOLVE,
    UNLOCK_D2_THRESHOLD,
    UNLOCK_D3_THRESHOLD,
    UNLOCK_D4_THRESHOLD,
    UNLOCK_D5_THRESHOLD,
    get_divine_relic_names,
)
from relic_solver.solver import (
    _get_drop_distribution,
    _meets_target,
    _solve_dict,
    _solve_numpy,
    expected_gems,
    expected_rerolls,
    solve,
)

ZERO_TARGET: tuple[int, ...] = (0, 0, 0, 0, 0)
INITIAL_STATE: tuple[int, ...] = (0, 0, 0, 0)


class BenchmarkFixture(Protocol):
    def __call__(self, target: Any, /, *args: Any, **kwargs: Any) -> Any: ...


class TestConfigRegression:
    def test_divine_chance(self) -> None:
        assert DIVINE_CHANCE == pytest.approx(1 / 25_000)

    def test_num_relic_types(self) -> None:
        assert NUM_RELIC_TYPES == 5

    def test_unlock_thresholds(self) -> None:
        assert UNLOCK_D2_THRESHOLD == 3
        assert UNLOCK_D3_THRESHOLD == 6
        assert UNLOCK_D4_THRESHOLD == 10
        assert UNLOCK_D5_THRESHOLD == 30

    def test_cap_bounds_are_coherent(self) -> None:
        assert MIN_RELIC_CAP <= DEFAULT_RELIC_CAP <= MAX_RELIC_CAP
        assert MIN_RELIC_CAP > 0

    def test_cost_per_reroll(self) -> None:
        assert COST_PER_REROLL == 200

    def test_rate_limits(self) -> None:
        assert RATE_LIMIT_SOLVE == "10/minute"
        assert RATE_LIMIT_DEFAULT == "60/minute"

    def test_divine_relic_names(self) -> None:
        names = get_divine_relic_names()
        assert len(names) == NUM_RELIC_TYPES
        assert names[0] == "Rainbow Floor Chance"
        assert all(isinstance(v, str) for v in names.values())


class TestSolveEdgeCases:
    def test_all_zero_targets_no_chests(self) -> None:
        assert solve(0, 0, ZERO_TARGET) == 1.0

    def test_all_zero_targets_with_chests(self) -> None:
        assert solve(100_000, 50, ZERO_TARGET) == 1.0

    def test_no_chests_nonzero_target(self) -> None:
        assert solve(0, 0, (1, 0, 0, 0, 0)) == 0.0

    def test_single_divine_chest_d1_target_guaranteed(self) -> None:
        assert solve(0, 1, (1, 0, 0, 0, 0)) == 1.0

    def test_single_divine_chest_d2_impossible(self) -> None:
        assert solve(0, 1, (0, 1, 0, 0, 0)) == 0.0

    def test_two_divines_d2_still_impossible(self) -> None:
        assert solve(0, 2, (0, 1, 0, 0, 0)) == 0.0

    def test_three_divines_d2_still_impossible(self) -> None:
        assert solve(0, 3, (0, 1, 0, 0, 0)) == 0.0

    def test_four_divines_d2_becomes_possible(self) -> None:
        result = solve(0, 4, (0, 1, 0, 0, 0))
        assert result > 0.0

    def test_seven_divines_d3_becomes_possible(self) -> None:
        result = solve(0, 7, (0, 0, 1, 0, 0))
        assert result > 0.0

    def test_six_divines_d3_still_impossible(self) -> None:
        assert solve(0, 6, (0, 0, 1, 0, 0)) == 0.0

    def test_eleven_divines_d4_becomes_possible(self) -> None:
        result = solve(0, 11, (0, 0, 0, 1, 0))
        assert result > 0.0

    def test_ten_divines_d4_still_impossible(self) -> None:
        assert solve(0, 10, (0, 0, 0, 1, 0)) == 0.0

    def test_thirtyone_divines_d5_becomes_possible(self) -> None:
        result = solve(0, 31, (0, 0, 0, 0, 1))
        assert result > 0.0

    def test_thirty_divines_d5_still_impossible(self) -> None:
        assert solve(0, 30, (0, 0, 0, 0, 1)) == 0.0

    def test_twentynine_divines_d5_impossible(self) -> None:
        assert solve(0, 29, (0, 0, 0, 0, 1)) == 0.0

    def test_single_regular_chest_d1(self) -> None:
        result = solve(1, 0, (1, 0, 0, 0, 0))
        assert result == pytest.approx(DIVINE_CHANCE, rel=1e-6)

    def test_many_divines_d1_only(self) -> None:
        assert solve(0, 100, (1, 0, 0, 0, 0)) == 1.0

    def test_zero_regular_many_divines_all_d1(self) -> None:
        result = solve(0, 10, (10, 0, 0, 0, 0))
        assert 0.0 < result <= 1.0


class TestSolveValidation:
    def test_target_too_few_elements(self) -> None:
        with pytest.raises(ValueError, match="Expected 5"):
            solve(100, 0, (1, 2, 3))

    def test_target_too_many_elements(self) -> None:
        with pytest.raises(ValueError, match="Expected 5"):
            solve(100, 0, (1, 2, 3, 4, 5, 6))

    def test_negative_regular_chests(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            solve(-1, 0, ZERO_TARGET)

    def test_negative_divine_chests(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            solve(0, -1, ZERO_TARGET)

    def test_empty_target_raises(self) -> None:
        with pytest.raises(ValueError, match="Expected 5"):
            solve(100, 0, ())

    def test_timeout_raises(self) -> None:
        with pytest.raises(TimeoutError, match="exceeded"):
            solve(100_000, 10, (3, 1, 1, 0, 0), max_seconds=1e-7)


class TestSolveInputEdgeCases:
    def test_negative_target_trivially_met(self) -> None:
        assert solve(0, 0, (-1, 0, 0, 0, 0)) == 1.0

    def test_negative_d2_target_trivially_met(self) -> None:
        assert solve(0, 0, (0, -1, 0, 0, 0)) == 1.0

    def test_all_negative_targets(self) -> None:
        assert solve(0, 0, (-5, -3, -2, -1, -1)) == 1.0

    def test_relic_cap_zero(self) -> None:
        result = solve(0, 1, (1, 5, 5, 5, 5), relic_cap=0)
        assert result == 1.0

    def test_relic_cap_one(self) -> None:
        result = solve(0, 50, (5, 1, 1, 1, 1), relic_cap=1)
        assert result > 0.0

    def test_float_targets_work(self) -> None:
        p_float = solve(50_000, 10, (3.0, 1.0, 1.0, 0.0, 0.0))  # type: ignore[arg-type]
        p_int = solve(50_000, 10, (3, 1, 1, 0, 0))
        assert p_float == pytest.approx(p_int)

    def test_relic_cap_very_large(self) -> None:
        result = solve(0, 50, (10, 5, 5, 5, 1), relic_cap=30)
        assert 0.0 < result <= 1.0


class TestSolveImpossibleCases:
    def test_d5_needs_30_but_only_5_chests(self) -> None:
        assert solve(5, 0, (0, 0, 0, 0, 1)) == 0.0

    def test_target_d1_100_with_10_chests(self) -> None:
        assert solve(10, 0, (100, 0, 0, 0, 0)) == 0.0

    def test_all_capped_types_at_cap_few_chests(self) -> None:
        assert solve(10, 0, (5, 5, 5, 5, 5), relic_cap=5) == 0.0

    def test_high_d1_very_few_divines(self) -> None:
        result = solve(100, 0, (50, 0, 0, 0, 0))
        assert result == pytest.approx(0.0, abs=1e-10)

    def test_d2_target_exceeds_max_divines(self) -> None:
        result = solve(1000, 0, (0, 5, 0, 0, 0), relic_cap=10)
        assert result == pytest.approx(0.0, abs=1e-10)


class TestSolveRealisticScenarios:
    def test_early_game_d1_only(self) -> None:
        result = solve(50_000, 5, (1, 0, 0, 0, 0))
        assert result > 0.999

    def test_mid_game_modest_targets(self) -> None:
        result = solve(150_000, 10, (3, 1, 1, 0, 0))
        assert 0.90 < result < 0.99

    def test_high_chest_count(self) -> None:
        result = solve(500_000, 20, (5, 2, 2, 1, 0))
        assert result > 0.999

    def test_very_high_chest_count(self) -> None:
        result = solve(2_000_000, 50, (10, 5, 5, 5, 5), relic_cap=10)
        assert result > 0.999

    def test_divine_only_no_regular(self) -> None:
        result = solve(0, 50, (10, 5, 5, 5, 1))
        assert result > 0.999

    def test_low_regular_some_divine(self) -> None:
        result = solve(10_000, 3, (2, 0, 0, 0, 0))
        assert 0.0 < result <= 1.0

    @pytest.mark.parametrize("cap", [5, 10, 15, 21])
    def test_various_caps(self, cap: int) -> None:
        result = solve(100_000, 15, (3, 2, 2, 1, 0), relic_cap=cap)
        assert 0.0 < result <= 1.0

    @pytest.mark.parametrize(
        "chests",
        [0, 100, 1_000, 10_000, 50_000, 100_000, 500_000, 1_000_000, 2_000_000],
    )
    def test_scaling_chest_counts_valid_result(self, chests: int) -> None:
        result = solve(chests, 5, (1, 0, 0, 0, 0))
        assert 0.0 <= result <= 1.0


class TestSolveMonotonicity:
    def test_more_regular_chests_higher_probability(self) -> None:
        target = (2, 1, 0, 0, 0)
        p_lo = solve(10_000, 5, target)
        p_mid = solve(50_000, 5, target)
        p_hi = solve(150_000, 5, target)
        assert p_lo <= p_mid + 1e-12
        assert p_mid <= p_hi + 1e-12

    def test_more_divine_chests_higher_probability(self) -> None:
        target = (3, 1, 1, 0, 0)
        p_lo = solve(50_000, 2, target)
        p_mid = solve(50_000, 10, target)
        p_hi = solve(50_000, 30, target)
        assert p_lo <= p_mid + 1e-12
        assert p_mid <= p_hi + 1e-12

    def test_higher_target_lower_probability(self) -> None:
        p_easy = solve(50_000, 10, (1, 0, 0, 0, 0))
        p_medium = solve(50_000, 10, (3, 1, 1, 0, 0))
        p_hard = solve(50_000, 10, (5, 3, 3, 2, 1))
        assert p_easy >= p_medium - 1e-12
        assert p_medium >= p_hard - 1e-12

    def test_solve_is_deterministic(self) -> None:
        args = (100_000, 10, (3, 1, 1, 0, 0))
        assert solve(*args) == solve(*args)

    def test_result_always_in_unit_interval(self) -> None:
        scenarios = [
            (0, 0, (1, 0, 0, 0, 0)),
            (100, 5, (2, 1, 0, 0, 0)),
            (50_000, 10, (3, 1, 1, 0, 0)),
            (1_000, 0, (1, 0, 0, 0, 0)),
            (500_000, 20, (5, 3, 3, 2, 1)),
        ]
        for reg, div, tgt in scenarios:
            result = solve(reg, div, tgt)
            assert 0.0 <= result <= 1.0, f"OOB for ({reg}, {div}, {tgt}): {result}"


class TestSolveCapClamping:
    def test_target_above_cap_is_equivalent(self) -> None:
        cap = 5
        p_above = solve(100_000, 20, (3, 10, 0, 0, 0), relic_cap=cap)
        p_at = solve(100_000, 20, (3, 5, 0, 0, 0), relic_cap=cap)
        assert p_above == pytest.approx(p_at)

    def test_all_types_above_cap_clamped(self) -> None:
        cap = 5
        p_above = solve(0, 50, (5, 99, 99, 99, 99), relic_cap=cap)
        p_at = solve(0, 50, (5, 5, 5, 5, 5), relic_cap=cap)
        assert p_above == pytest.approx(p_at)

    def test_d1_is_uncapped(self) -> None:
        result = solve(0, 100, (50, 0, 0, 0, 0))
        assert 0.0 < result <= 1.0


class TestGetDropDistribution:
    def test_initial_state_d1_only(self) -> None:
        dist = _get_drop_distribution(INITIAL_STATE, total_divines=0, relic_cap=5)
        assert dist == {0: 1.0}

    def test_at_threshold_d2(self) -> None:
        dist = _get_drop_distribution(
            (0, 0, 0, 0), total_divines=UNLOCK_D2_THRESHOLD, relic_cap=5,
        )
        assert set(dist.keys()) == {0, 1}
        assert all(v == pytest.approx(0.5) for v in dist.values())

    def test_at_threshold_d3(self) -> None:
        dist = _get_drop_distribution(
            (0, 0, 0, 0), total_divines=UNLOCK_D3_THRESHOLD, relic_cap=5,
        )
        assert set(dist.keys()) == {0, 1, 2}
        assert all(v == pytest.approx(1 / 3) for v in dist.values())

    def test_at_threshold_d4(self) -> None:
        dist = _get_drop_distribution(
            (0, 0, 0, 0), total_divines=UNLOCK_D4_THRESHOLD, relic_cap=5,
        )
        assert set(dist.keys()) == {0, 1, 2, 3}
        assert all(v == pytest.approx(0.25) for v in dist.values())

    def test_at_threshold_d5(self) -> None:
        dist = _get_drop_distribution(
            (0, 0, 0, 0), total_divines=UNLOCK_D5_THRESHOLD, relic_cap=5,
        )
        assert set(dist.keys()) == {0, 1, 2, 3, 4}
        assert all(v == pytest.approx(0.2) for v in dist.values())

    def test_just_below_d2_threshold(self) -> None:
        dist = _get_drop_distribution(
            (0, 0, 0, 0), total_divines=UNLOCK_D2_THRESHOLD - 1, relic_cap=5,
        )
        assert dist == {0: 1.0}

    def test_capped_type_excluded(self) -> None:
        dist = _get_drop_distribution((5, 0, 0, 0), total_divines=8, relic_cap=5)
        assert 1 not in dist
        assert 0 in dist
        assert 2 in dist

    def test_multiple_capped_types(self) -> None:
        dist = _get_drop_distribution((5, 5, 0, 0), total_divines=16, relic_cap=5)
        assert 1 not in dist
        assert 2 not in dist
        assert 0 in dist
        assert 3 in dist

    def test_all_capped_except_d1(self) -> None:
        dist = _get_drop_distribution((5, 5, 5, 5), total_divines=41, relic_cap=5)
        assert dist == {0: 1.0}

    def test_distribution_sums_to_one(self) -> None:
        cases = [
            ((0, 0, 0, 0), 0),
            ((0, 0, 0, 0), 3),
            ((2, 2, 0, 0), 14),
            ((5, 5, 5, 0), 45),
            ((5, 5, 0, 0), 16),
            ((5, 5, 5, 5), 70),
        ]
        for state, total in cases:
            dist = _get_drop_distribution(state, total_divines=total, relic_cap=5)
            assert sum(dist.values()) == pytest.approx(1.0), (
                f"Bad sum for {state}, total={total}"
            )

    def test_higher_cap_never_fewer_types(self) -> None:
        state = (4, 4, 4, 0)
        types_cap5 = set(
            _get_drop_distribution(state, total_divines=22, relic_cap=5).keys(),
        )
        types_cap10 = set(
            _get_drop_distribution(state, total_divines=22, relic_cap=10).keys(),
        )
        assert types_cap5 <= types_cap10


class TestMeetsTarget:
    def test_exact_match(self) -> None:
        assert _meets_target((2, 1, 0, 0), (3, 2, 1, 0, 0), total_divines=6) is True

    def test_all_above(self) -> None:
        assert _meets_target((3, 2, 1, 1), (3, 2, 1, 0, 0), total_divines=12) is True

    def test_one_below(self) -> None:
        assert _meets_target((1, 1, 0, 0), (3, 2, 1, 0, 0), total_divines=5) is False

    def test_zeros(self) -> None:
        assert _meets_target(INITIAL_STATE, ZERO_TARGET, total_divines=0) is True

    def test_zero_state_positive_target(self) -> None:
        assert _meets_target(INITIAL_STATE, (1, 0, 0, 0, 0), total_divines=0) is False

    def test_single_dimension_fail(self) -> None:
        assert (
            _meets_target((5, 5, 5, 0), (10, 5, 5, 5, 1), total_divines=25) is False
        )


class TestExpectedRerolls:
    def test_certain(self) -> None:
        assert expected_rerolls(1.0) == 1.0

    def test_half(self) -> None:
        assert expected_rerolls(0.5) == 2.0

    def test_tenth(self) -> None:
        assert expected_rerolls(0.1) == pytest.approx(10.0)

    def test_zero_is_inf(self) -> None:
        assert expected_rerolls(0.0) == math.inf

    def test_very_small(self) -> None:
        assert expected_rerolls(1e-10) == pytest.approx(1e10)

    def test_one_in_25000(self) -> None:
        assert expected_rerolls(1 / 25_000) == pytest.approx(25_000.0)


class TestExpectedGems:
    def test_certain_probability(self) -> None:
        assert expected_gems(1.0) == 200

    def test_half_probability(self) -> None:
        assert expected_gems(0.5) == 400

    def test_zero_probability_is_inf(self) -> None:
        assert expected_gems(0.0) == math.inf

    def test_rounds_up_fractional_rerolls(self) -> None:
        assert expected_gems(0.3) == 800

    @pytest.mark.parametrize(
        "prob",
        [1.0, 0.5, 0.3, 0.1, 0.01, 0.001, 0.25, 0.125, 0.9, 0.99],
    )
    def test_always_multiple_of_cost(self, prob: float) -> None:
        gems = expected_gems(prob)
        if not math.isinf(gems):
            assert gems % COST_PER_REROLL == 0, (
                f"p={prob}: gems={gems} not a multiple of {COST_PER_REROLL}"
            )

    @pytest.mark.parametrize(
        "prob",
        [1.0, 0.5, 0.3, 0.1, 0.01, 0.001, 0.25, 0.125],
    )
    def test_gems_at_least_raw_cost(self, prob: float) -> None:
        raw = expected_rerolls(prob) * COST_PER_REROLL
        gems = expected_gems(prob)
        assert gems >= raw or math.isinf(gems)

    def test_exact_integer_rerolls_no_extra_rounding(self) -> None:
        assert expected_gems(0.25) == 800


class TestProgressCallback:
    def test_callback_receives_valid_values(self) -> None:
        calls: list[tuple[int, int]] = []

        def cb(current: int, total: int) -> None:
            calls.append((current, total))

        solve(50_000, 10, (2, 1, 0, 0, 0), progress_callback=cb)
        assert len(calls) > 0
        for cur, tot in calls:
            assert 1 <= cur <= tot

    def test_no_callback_does_not_crash(self) -> None:
        result = solve(1_000, 2, (1, 0, 0, 0, 0), progress_callback=None)
        assert 0.0 <= result <= 1.0


class TestSolveToGemsPipeline:
    def test_trivial_target_cheap(self) -> None:
        p = solve(0, 0, ZERO_TARGET)
        assert expected_gems(p) == COST_PER_REROLL

    def test_impossible_target_inf_gems(self) -> None:
        p = solve(0, 0, (1, 0, 0, 0, 0))
        assert expected_gems(p) == math.inf

    def test_realistic_pipeline(self) -> None:
        p = solve(150_000, 10, (3, 1, 1, 0, 0))
        gems = expected_gems(p)
        assert 0 < gems < math.inf
        assert gems % COST_PER_REROLL == 0


class TestPackageAPI:
    def test_public_imports(self) -> None:
        from relic_solver import expected_gems, expected_rerolls, solve

        assert callable(solve)
        assert callable(expected_rerolls)
        assert callable(expected_gems)

    def test_version_accessible(self) -> None:
        from relic_solver import __version__

        assert isinstance(__version__, str)
        assert "." in __version__


def _prepare_solver_args(
    total_relic_chests: int,
    divine_chests: int,
    target_relics: tuple[int, ...],
    relic_cap: int = DEFAULT_RELIC_CAP,
) -> dict[str, Any]:
    from scipy.stats import binom as binom_dist

    target: tuple[int, ...] = (
        target_relics[0],
        *(min(target_relics[i], relic_cap) for i in range(1, NUM_RELIC_TYPES)),
    )

    divine_chance = DIVINE_CHANCE
    if total_relic_chests > 0 and divine_chance > 0:
        k_max = max(
            int(binom_dist.ppf(1 - 1e-15, total_relic_chests, divine_chance)),
            0,
        )
        _pmf_arr = binom_dist.pmf(
            range(k_max + 1),
            total_relic_chests,
            divine_chance,
        )
        pmf_values: list[float] = [float(v) for v in _pmf_arr]
    else:
        k_max = 0
        pmf_values = [1.0]

    d_max = divine_chests + k_max

    return {
        "target": target,
        "relic_cap": relic_cap,
        "divine_chests": divine_chests,
        "d_max": d_max,
        "k_max": k_max,
        "pmf_values": pmf_values,
        "deadline": None,
        "max_seconds": None,
        "progress_callback": None,
    }


class TestCrossValidation:
    @pytest.mark.parametrize(
        ("total_relic_chests", "divine_chests", "target_relics", "relic_cap"),
        [
            (0, 5, (1, 0, 0, 0, 0), 5),
            (0, 4, (0, 1, 0, 0, 0), 5),
            (0, 7, (0, 0, 1, 0, 0), 5),
            (0, 11, (0, 0, 0, 1, 0), 5),
            (0, 31, (0, 0, 0, 0, 1), 5),
            (50_000, 10, (3, 1, 1, 0, 0), 5),
            (10_000, 10, (2, 2, 1, 0, 0), 10),
            (0, 50, (10, 5, 5, 5, 1), 5),
            (0, 3, (0, 1, 0, 0, 0), 5),
            (0, 50, (5, 5, 5, 5, 5), 5),
            (1, 0, (1, 0, 0, 0, 0), 5),
            (0, 50, (5, 1, 1, 1, 1), 1),
            (100_000, 15, (3, 2, 2, 1, 0), 15),
        ],
        ids=[
            "trivial_d1",
            "d2_unlock",
            "d3_unlock",
            "d4_unlock",
            "d5_unlock",
            "mixed_modest",
            "higher_cap",
            "all_types",
            "impossible",
            "all_at_cap",
            "single_chest",
            "cap_1",
            "cap_15",
        ],
    )
    def test_numpy_matches_dict(
        self,
        total_relic_chests: int,
        divine_chests: int,
        target_relics: tuple[int, ...],
        relic_cap: int,
    ) -> None:
        args = _prepare_solver_args(
            total_relic_chests,
            divine_chests,
            target_relics,
            relic_cap,
        )
        if args["d_max"] == 0:
            pytest.skip("d_max=0 - trivial case handled before dispatch")

        result_dict = _solve_dict(**args)
        result_numpy = _solve_numpy(**args)

        assert result_numpy == pytest.approx(result_dict, abs=1e-12), (
            f"Mismatch: numpy={result_numpy}, dict={result_dict}"
        )


class TestBenchmarks:
    def test_bench_zero_chests(self, benchmark: BenchmarkFixture) -> None:
        benchmark(solve, 0, 5, (1, 0, 0, 0, 0))

    def test_bench_1k_chests(self, benchmark: BenchmarkFixture) -> None:
        benchmark(solve, 1_000, 5, (1, 0, 0, 0, 0))

    def test_bench_10k_chests(self, benchmark: BenchmarkFixture) -> None:
        benchmark(solve, 10_000, 5, (2, 1, 0, 0, 0))

    def test_bench_50k_chests(self, benchmark: BenchmarkFixture) -> None:
        benchmark(solve, 50_000, 10, (3, 1, 1, 0, 0))

    def test_bench_100k_chests(self, benchmark: BenchmarkFixture) -> None:
        benchmark(solve, 100_000, 10, (3, 2, 1, 0, 0))

    def test_bench_500k_chests(self, benchmark: BenchmarkFixture) -> None:
        benchmark(solve, 500_000, 15, (5, 2, 2, 1, 0))

    def test_bench_1m_chests(self, benchmark: BenchmarkFixture) -> None:
        benchmark(solve, 1_000_000, 20, (5, 3, 3, 2, 1))

    def test_bench_2m_chests(self, benchmark: BenchmarkFixture) -> None:
        benchmark(
            solve,
            2_000_000,
            30,
            (8, 4, 4, 3, 1),
            relic_cap=10,
        )

    def test_bench_divine_only_50(self, benchmark: BenchmarkFixture) -> None:
        benchmark(solve, 0, 50, (10, 5, 5, 5, 1))

    def test_bench_max_cap_worst_case(self, benchmark: BenchmarkFixture) -> None:
        benchmark(
            solve,
            2_000_000,
            100,
            (100, MAX_RELIC_CAP, MAX_RELIC_CAP, MAX_RELIC_CAP, MAX_RELIC_CAP),
            relic_cap=MAX_RELIC_CAP,
        )


class TestBackendBenchmarks:
    def test_bench_numpy_backend_100k(self, benchmark: BenchmarkFixture) -> None:
        args = _prepare_solver_args(100_000, 10, (3, 2, 1, 0, 0))
        benchmark(lambda: _solve_numpy(**args))

    def test_bench_dict_backend_100k(self, benchmark: BenchmarkFixture) -> None:
        args = _prepare_solver_args(100_000, 10, (3, 2, 1, 0, 0))
        benchmark(lambda: _solve_dict(**args))

    def test_bench_numpy_backend_cap15(self, benchmark: BenchmarkFixture) -> None:
        args = _prepare_solver_args(1_000_000, 20, (5, 3, 3, 2, 1), relic_cap=15)
        benchmark(lambda: _solve_numpy(**args))
