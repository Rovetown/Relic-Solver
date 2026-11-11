import math
import time
from collections import defaultdict
from collections.abc import Callable

import numpy as np
import numpy.typing as npt
from scipy.stats import binom

from relic_solver.config import (
    COST_PER_REROLL,
    DEFAULT_RELIC_CAP,
    DIVINE_CHANCE,
    NUM_RELIC_TYPES,
    UNLOCK_D2_THRESHOLD,
    UNLOCK_D3_THRESHOLD,
    UNLOCK_D4_THRESHOLD,
    UNLOCK_D5_THRESHOLD,
)

_UNLOCK_THRESHOLDS: tuple[int, ...] = (
    0,
    UNLOCK_D2_THRESHOLD,
    UNLOCK_D3_THRESHOLD,
    UNLOCK_D4_THRESHOLD,
    UNLOCK_D5_THRESHOLD,
)

_PRUNE_LIMIT = 100_000

_PRUNE_RATIO = 1e-15

_NUM_CAPPED = NUM_RELIC_TYPES - 1


def _get_drop_distribution(
    state: tuple[int, ...],
    total_divines: int,
    relic_cap: int,
) -> dict[int, float]:
    available: list[int] = []

    for idx in range(NUM_RELIC_TYPES):
        if total_divines < _UNLOCK_THRESHOLDS[idx]:
            continue
        if idx == 0 or state[idx - 1] < relic_cap:
            available.append(idx)

    if not available:
        return {0: 1.0}

    prob = 1.0 / len(available)
    return dict.fromkeys(available, prob)


def _meets_target(
    state: tuple[int, ...],
    target: tuple[int, ...],
    total_divines: int,
) -> bool:
    d1 = total_divines - sum(state)
    if d1 < target[0]:
        return False
    return all(s >= t for s, t in zip(state, target[1:], strict=True))


def _solve_dict(
    *,
    target: tuple[int, ...],
    relic_cap: int,
    divine_chests: int,
    d_max: int,
    k_max: int,
    pmf_values: list[float],
    deadline: float | None,
    max_seconds: float | None,
    progress_callback: Callable[[int, int], None] | None,
) -> float:
    initial: tuple[int, ...] = (0,) * _NUM_CAPPED
    active: dict[tuple[int, ...], float] = {initial: 1.0}
    absorbed = 0.0
    result = 0.0

    dist_cache: dict[tuple[int, int], dict[int, float]] = {}
    progress_interval = max(d_max // 100, 1)

    target_d1 = target[0]
    target_tail = target[1:]

    for step in range(1, d_max + 1):
        next_active: defaultdict[tuple[int, ...], float] = defaultdict(float)
        step_absorbed = 0.0

        for state, prob in active.items():
            total = step - 1

            capped_bits = 0
            if state[0] >= relic_cap:
                capped_bits |= 1
            if state[1] >= relic_cap:
                capped_bits |= 2
            if state[2] >= relic_cap:
                capped_bits |= 4
            if state[3] >= relic_cap:
                capped_bits |= 8

            cache_key = (total, capped_bits)
            if cache_key not in dist_cache:
                dist_cache[cache_key] = _get_drop_distribution(
                    state,
                    total_divines=total,
                    relic_cap=relic_cap,
                )

            for relic_idx, drop_prob in dist_cache[cache_key].items():
                contrib = prob * drop_prob
                if relic_idx == 0:
                    new_state = state
                else:
                    si = relic_idx - 1
                    if si == 0:
                        new_state = (state[0] + 1, state[1], state[2], state[3])
                    elif si == 1:
                        new_state = (state[0], state[1] + 1, state[2], state[3])
                    elif si == 2:
                        new_state = (state[0], state[1], state[2] + 1, state[3])
                    else:
                        new_state = (state[0], state[1], state[2], state[3] + 1)

                d1 = step - sum(new_state)
                if d1 >= target_d1 and all(
                    s >= t for s, t in zip(new_state, target_tail, strict=True)
                ):
                    step_absorbed += contrib
                else:
                    next_active[new_state] += contrib

        absorbed += step_absorbed
        active = dict(next_active)

        if step >= divine_chests:
            k = step - divine_chests
            result += pmf_values[k] * absorbed

        if progress_callback is not None and step % progress_interval == 0:
            progress_callback(step, d_max)

        if deadline is not None and time.monotonic() > deadline:
            msg = (
                f"Computation exceeded {max_seconds}s limit "
                f"(step {step}/{d_max}, {len(active)} active states). "
                f"Try reducing the cap or target values."
            )
            raise TimeoutError(msg)

        if not active:
            k_start = max(step + 1 - divine_chests, 0)
            if k_start <= k_max:
                result += sum(pmf_values[k_start:]) * absorbed
            break

        if len(active) > _PRUNE_LIMIT:
            cutoff = max(active.values()) * _PRUNE_RATIO
            active = {s: p for s, p in active.items() if p >= cutoff}

    return min(result, 1.0)


def _solve_numpy(
    *,
    target: tuple[int, ...],
    relic_cap: int,
    divine_chests: int,
    d_max: int,
    k_max: int,
    pmf_values: list[float],
    deadline: float | None,
    max_seconds: float | None,
    progress_callback: Callable[[int, int], None] | None,
) -> float:
    dim = relic_cap + 1
    target_d1 = target[0]
    target_tail = target[1:]

    d2g, d3g, d4g, d5g = np.mgrid[0:dim, 0:dim, 0:dim, 0:dim]
    state_sums: npt.NDArray[np.int64] = d2g + d3g + d4g + d5g

    meets_d2 = d2g >= target_tail[0]
    meets_d3 = d3g >= target_tail[1]
    meets_d4 = d4g >= target_tail[2]
    meets_d5 = d5g >= target_tail[3]
    meets_tail: npt.NDArray[np.bool_] = meets_d2 & meets_d3 & meets_d4 & meets_d5

    capped_d2 = d2g >= relic_cap
    capped_d3 = d3g >= relic_cap
    capped_d4 = d4g >= relic_cap
    capped_d5 = d5g >= relic_cap

    tier_weights: list[npt.NDArray[np.float64]] = []
    for tier in range(NUM_RELIC_TYPES):
        n_avail = np.ones((dim, dim, dim, dim), dtype=np.float64)
        if tier >= 1:
            n_avail += np.where(~capped_d2, 1.0, 0.0)
        if tier >= 2:
            n_avail += np.where(~capped_d3, 1.0, 0.0)
        if tier >= 3:
            n_avail += np.where(~capped_d4, 1.0, 0.0)
        if tier >= 4:
            n_avail += np.where(~capped_d5, 1.0, 0.0)
        tier_weights.append(1.0 / n_avail)

    thresholds = _UNLOCK_THRESHOLDS

    prob_arr: npt.NDArray[np.float64] = np.zeros(
        (dim, dim, dim, dim),
        dtype=np.float64,
    )
    prob_arr[0, 0, 0, 0] = 1.0

    absorbed = 0.0
    result = 0.0
    progress_interval = max(d_max // 100, 1)
    pmf_arr = np.array(pmf_values, dtype=np.float64)

    for step in range(1, d_max + 1):
        total = step - 1

        if total >= thresholds[4]:
            tier = 4
        elif total >= thresholds[3]:
            tier = 3
        elif total >= thresholds[2]:
            tier = 2
        elif total >= thresholds[1]:
            tier = 1
        else:
            tier = 0

        weighted = prob_arr * tier_weights[tier]

        new_prob = weighted.copy()

        if tier >= 1:
            new_prob[1:, :, :, :] += weighted[:-1, :, :, :]

        if tier >= 2:
            new_prob[:, 1:, :, :] += weighted[:, :-1, :, :]

        if tier >= 3:
            new_prob[:, :, 1:, :] += weighted[:, :, :-1, :]

        if tier >= 4:
            new_prob[:, :, :, 1:] += weighted[:, :, :, :-1]


        d1_arr = step - state_sums
        absorb_mask = (d1_arr >= target_d1) & meets_tail

        step_absorbed = float(np.sum(new_prob[absorb_mask]))
        new_prob[absorb_mask] = 0.0

        absorbed += step_absorbed
        prob_arr = new_prob

        if step >= divine_chests:
            k = step - divine_chests
            result += float(pmf_arr[k]) * absorbed

        if progress_callback is not None and step % progress_interval == 0:
            progress_callback(step, d_max)

        if deadline is not None and time.monotonic() > deadline:
            msg = (
                f"Computation exceeded {max_seconds}s limit "
                f"(step {step}/{d_max}). "
                f"Try reducing the cap or target values."
            )
            raise TimeoutError(msg)

        total_remaining = float(np.sum(prob_arr))
        if total_remaining < 1e-30:
            k_start = max(step + 1 - divine_chests, 0)
            if k_start <= k_max:
                result += float(np.sum(pmf_arr[k_start:])) * absorbed
            break

    return min(result, 1.0)


def solve(
    total_relic_chests: int,
    divine_chests: int,
    target_relics: tuple[int, ...],
    *,
    relic_cap: int = DEFAULT_RELIC_CAP,
    progress_callback: Callable[[int, int], None] | None = None,
    max_seconds: float | None = None,
) -> float:
    if len(target_relics) != NUM_RELIC_TYPES:
        msg = f"Expected {NUM_RELIC_TYPES} target values, got {len(target_relics)}"
        raise ValueError(msg)
    if total_relic_chests < 0:
        raise ValueError("total_relic_chests must be non-negative")
    if divine_chests < 0:
        raise ValueError("divine_chests must be non-negative")

    target: tuple[int, ...] = (
        target_relics[0],
        *(min(target_relics[i], relic_cap) for i in range(1, NUM_RELIC_TYPES)),
    )

    initial: tuple[int, ...] = (0,) * _NUM_CAPPED

    if _meets_target(initial, target, total_divines=0):
        return 1.0

    divine_chance = DIVINE_CHANCE
    if total_relic_chests > 0 and divine_chance > 0:
        k_max = max(
            int(binom.ppf(1 - 1e-15, total_relic_chests, divine_chance)),
            0,
        )
        _pmf_arr = binom.pmf(range(k_max + 1), total_relic_chests, divine_chance)
        pmf_values: list[float] = [float(v) for v in _pmf_arr]
    else:
        k_max = 0
        pmf_values = [1.0]

    d_max = divine_chests + k_max

    if d_max == 0:
        return 0.0

    deadline = (time.monotonic() + max_seconds) if max_seconds is not None else None

    return _solve_numpy(
        target=target,
        relic_cap=relic_cap,
        divine_chests=divine_chests,
        d_max=d_max,
        k_max=k_max,
        pmf_values=pmf_values,
        deadline=deadline,
        max_seconds=max_seconds,
        progress_callback=progress_callback,
    )


def expected_rerolls(probability: float) -> float:
    if probability <= 0.0:
        return math.inf
    return 1.0 / probability


def expected_gems(probability: float) -> float:
    rerolls = expected_rerolls(probability)
    if math.isinf(rerolls):
        return math.inf
    return math.ceil(round(rerolls, 9)) * COST_PER_REROLL
