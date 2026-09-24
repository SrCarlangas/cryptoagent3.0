"""Behavioural sanity checks for the exposure agent on synthetic data.

Real BTC data cannot tell me whether the learning rule works, because there the
right answer is unknown and any result is arguable. These synthetic worlds have a
known right answer, so they can falsify the implementation:

1. Persistent uptrend      -> the agent should end up long and stay long.
2. Persistent downtrend    -> the agent should end up flat.
3. Regime switch up/down   -> the agent should be long in the first half and flat
                              in the second, which requires the gate to actually
                              separate regimes.
4. Fee sensitivity         -> raising the fee must REDUCE the number of switches.
                              This is the emergent-hysteresis claim: nothing in the
                              code says "wait for a band", so if churn does not
                              fall when trading gets expensive, the cost-aware
                              reward is not doing its job.

Read-only. Exits non-zero if any expectation fails.
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass

from btc_decision_agent.application.exposure_training import (
    TrainingConfig,
    build_daily_perception,
    evaluate_agent,
    train_agent,
)

HOUR_MS = 3_600_000


@dataclass(frozen=True)
class SyntheticBar:
    open_time_ms: int
    close: float


def make_bars(segments: list[tuple[int, float]], *, noise: float, seed: int) -> list[SyntheticBar]:
    """Build hourly bars from (hours, hourly_drift) segments with lognormal noise."""
    rng = random.Random(seed)
    bars: list[SyntheticBar] = []
    price = 10_000.0
    clock = 0
    for hours, drift in segments:
        for _ in range(hours):
            price *= math.exp(drift + rng.gauss(0.0, noise))
            bars.append(SyntheticBar(clock, price))
            clock += HOUR_MS
    return bars


WARMUP_DAYS = 200
"""The agent cannot act until 200 daily closes exist, so every synthetic world
must budget that much history before the behaviour under test begins. Skipping
this is what made the first version of this script report a false failure: the
agent had ~10 usable training steps and was forced flat through most of the
evaluation window."""


def run(
    bars: list[SyntheticBar],
    config: TrainingConfig,
    *,
    train_until_day: int,
    evaluate_from_day: int | None = None,
) -> tuple[float, int, bool, list[float], int]:
    """Train on the actionable part of history, then evaluate on a later slice."""
    perception = build_daily_perception(bars)
    train_start = WARMUP_DAYS * 24
    train_end = train_until_day * 24
    eval_start = (evaluate_from_day if evaluate_from_day is not None else WARMUP_DAYS) * 24
    policy, history = train_agent(bars, perception, train_start, train_end, config)
    result = evaluate_agent(bars, perception, policy, eval_start, len(bars), config)
    return (
        result.net_return_pct,
        result.buys + result.sells,
        result.final_long,
        result.regime_usage,
        history[-1].steps,
    )


def main() -> int:
    failures: list[str] = []
    config = TrainingConfig(cadence_hours=24, epochs=8, regimes=3, seed=7)

    # 200 warmup days + 600 days of the behaviour under test.
    up = make_bars([(800 * 24, 0.0004)], noise=0.004, seed=1)
    down = make_bars([(800 * 24, -0.0004)], noise=0.004, seed=2)
    # Warmup and 300 up days, then 300 down days. Evaluation starts in the up leg.
    switch = make_bars([(500 * 24, 0.0004), (300 * 24, -0.0005)], noise=0.004, seed=3)

    trend_return, trend_flips, trend_long, _usage, trend_steps = run(
        up, config, train_until_day=600
    )
    print(
        f"uptrend      return {trend_return:+10.2f}%  switches {trend_flips:3d}  "
        f"ends_long={trend_long}  train_steps={trend_steps}"
    )
    if not trend_long:
        failures.append("agent did not hold exposure through a persistent uptrend")

    bear_return, bear_flips, bear_long, _usage, bear_steps = run(
        down, config, train_until_day=600
    )
    print(
        f"downtrend    return {bear_return:+10.2f}%  switches {bear_flips:3d}  "
        f"ends_long={bear_long}  train_steps={bear_steps}"
    )
    if bear_long:
        failures.append("agent held exposure through a persistent downtrend")
    if bear_return < -50.0:
        failures.append(f"agent lost {bear_return:.1f}% in a downtrend it should have sat out")

    # Train across the turn so both regimes are seen, evaluate from the up leg.
    switch_return, switch_flips, switch_long, usage, switch_steps = run(
        switch, config, train_until_day=700, evaluate_from_day=250
    )
    print(
        f"regime flip  return {switch_return:+10.2f}%  switches {switch_flips:3d}  "
        f"ends_long={switch_long}  train_steps={switch_steps}  "
        f"regime_usage={[round(v, 3) for v in usage]}"
    )
    if switch_long:
        failures.append("agent still long after the regime turned down")

    # Fee sensitivity needs a CHOPPY world. In a clean uptrend the agent converges
    # to buy-and-hold at any fee level, so the test would pass trivially with one
    # switch on both sides and prove nothing. Alternating 20-day legs create a real
    # temptation to trade, so the fee is what decides whether acting is worth it.
    oscillating: list[tuple[int, float]] = []
    for leg in range(40):
        oscillating.append((20 * 24, 0.0006 if leg % 2 == 0 else -0.0006))
    noisy = make_bars(oscillating, noise=0.012, seed=11)
    cheap = run(
        noisy,
        TrainingConfig(cadence_hours=24, epochs=8, regimes=3, seed=7, fee_per_side=0.0001),
        train_until_day=600,
    )
    dear = run(
        noisy,
        TrainingConfig(cadence_hours=24, epochs=8, regimes=3, seed=7, fee_per_side=0.01),
        train_until_day=600,
    )
    print(f"fee 1bps     switches {cheap[1]:3d}   return {cheap[0]:+.2f}%   (choppy market)")
    print(f"fee 100bps   switches {dear[1]:3d}   return {dear[0]:+.2f}%   (choppy market)")
    if dear[1] >= cheap[1]:
        failures.append(
            f"raising fees did not reduce switching ({cheap[1]} -> {dear[1]}); "
            "cost-aware reward is not producing emergent hysteresis"
        )
    if cheap[1] < 4:
        failures.append(
            f"cheap-fee agent only switched {cheap[1]} times in a choppy market, so "
            "the fee comparison is not discriminating and proves nothing"
        )

    print()
    if failures:
        for item in failures:
            print(f"FAIL: {item}")
        return 1
    print("ALL BEHAVIOURAL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
