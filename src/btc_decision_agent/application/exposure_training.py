"""Training and honest economic evaluation for the local exposure agent.

Two properties matter more here than anything else.

On-policy rollout
    The agent's reward depends on the position it is currently holding, because
    acting costs a fee only when it changes that position. So the agent cannot be
    trained on shuffled independent samples; it is walked through history carrying
    the book its own past decisions produced. This is what makes it an agent
    learning a policy rather than a classifier learning labels.

No look-ahead
    A decision taken on the close of bar i is FILLED at the close of bar i+1, and
    the reward it earns is measured from that fill forward. The agent never trades
    at a price it used to decide. Reward periods tile exactly, so no price move is
    counted twice.

Daily perception is rebuilt the way the live runtime will see it: at any bar, the
agent may use only the daily closes of days that have already ended.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from btc_decision_agent.application.exposure_agent import (
    PortfolioState,
    RegimeMixturePolicy,
    TradeDecision,
    action_rewards,
    compose_features,
)
from btc_decision_agent.application.exposure_features import (
    MIN_DAILY_HISTORY,
    market_features,
)

HOUR_MS = 3_600_000
DAY_MS = 86_400_000


@dataclass(frozen=True)
class TrainingConfig:
    fee_per_side: float = 0.001
    cadence_hours: int = 24
    """How often the agent re-decides during training, and the reward horizon.

    These are deliberately the same number so reward periods tile the timeline
    without overlapping. Live inference may run far more often: the policy is a
    function of slowly-moving daily features, so evaluating it every second does
    not change what it computes.
    """
    regimes: int = 4
    learning_rate: float = 0.05
    l2: float = 1e-5
    epochs: int = 4
    seed: int = 20260924
    explore: bool = True


@dataclass
class RolloutResult:
    steps: int
    net_return_pct: float
    max_drawdown_pct: float
    buys: int
    sells: int
    exposure_share: float
    """Fraction of elapsed hours spent holding BTC."""
    mean_reward: float
    final_long: bool
    skipped_gap_steps: int
    skipped_history_steps: int
    regime_usage: list[float] = field(default_factory=list)
    decision_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DailyPerception:
    """Daily closes plus, for each hourly bar, how many of them were complete."""

    closes: list[float]
    available_at_bar: list[int]
    sparse_days: int
    total_days: int


def build_daily_perception(bars: Sequence[Any]) -> DailyPerception:
    """Derive daily closes and the causal availability count per hourly bar.

    A day's close is the close of its last hourly bar. At a bar belonging to day D
    the agent may use days strictly before D, which is exactly what a live agent
    knows: today has not finished yet.

    Documented dataset gaps mean some days hold fewer than 24 bars, and a fully
    missing day simply does not appear. The daily series is therefore indexed by
    trading days present, not by calendar offset; `sparse_days` reports how often
    that approximation applies so it is never silent.
    """
    day_closes: list[float] = []
    day_bar_counts: list[int] = []
    day_index_of_bar: list[int] = []
    current_day: int | None = None

    for bar in bars:
        day = int(bar.open_time_ms) // DAY_MS
        if current_day is None or day != current_day:
            day_closes.append(float(bar.close))
            day_bar_counts.append(1)
            current_day = day
        else:
            day_closes[-1] = float(bar.close)
            day_bar_counts[-1] += 1
        # Days strictly before this bar's day are complete.
        day_index_of_bar.append(len(day_closes) - 1)

    # day_index_of_bar[i] is already the count of days strictly BEFORE bar i's day,
    # because the current day sits at that index and indices are zero-based.
    return DailyPerception(
        closes=day_closes,
        available_at_bar=list(day_index_of_bar),
        sparse_days=sum(1 for count in day_bar_counts if count < 20),
        total_days=len(day_closes),
    )


def rollout(
    bars: Sequence[Any],
    perception: DailyPerception,
    policy: RegimeMixturePolicy,
    start: int,
    end: int,
    config: TrainingConfig,
    *,
    learn: bool,
    rng: random.Random | None = None,
    capital: float = 1.0,
) -> RolloutResult:
    """Walk the agent through [start, end) carrying its own book.

    When `learn` is true the policy is updated from each resolved step and actions
    may be sampled for exploration. When false the policy is frozen and acts by
    argmax, which is the deterministic behaviour production will show.
    """
    if not 0 <= start < end <= len(bars):
        raise ValueError("invalid rollout window")

    cadence = config.cadence_hours
    fee = config.fee_per_side
    cash = capital
    units = 0.0
    entry_price: float | None = None
    holding_hours = 0
    buys = sells = 0
    steps = 0
    skipped_gap = 0
    skipped_history = 0
    reward_total = 0.0
    regime_totals = [0.0] * policy.regimes
    decision_counts = {item.value: 0 for item in TradeDecision}
    peak = capital
    max_drawdown = 0.0
    exposed_hours = 0
    last_mark_index = start

    def equity_at(index: int) -> float:
        return cash + units * float(bars[index].close)

    index = start
    while index < end:
        available = perception.available_at_bar[index]
        position_long = units > 0.0

        # Mark to market across every bar since the previous decision so drawdown
        # reflects what the book actually lived through, not just decision points.
        for mark in range(last_mark_index, min(index + 1, end)):
            value = equity_at(mark)
            peak = max(peak, value)
            if peak > 0.0:
                max_drawdown = max(max_drawdown, (peak - value) / peak)
            if units > 0.0:
                exposed_hours += 1
        last_mark_index = min(index + 1, end)

        if available < MIN_DAILY_HISTORY:
            skipped_history += 1
            index += cadence
            continue

        fill_index = index + 1
        reward_index = index + 1 + cadence
        if fill_index >= end or reward_index >= end:
            break
        # Never bridge a documented gap: the fill and reward bars must be exactly
        # where the clock says they should be.
        if (
            bars[fill_index].open_time_ms != bars[index].open_time_ms + HOUR_MS
            or bars[reward_index].open_time_ms
            != bars[fill_index].open_time_ms + cadence * HOUR_MS
        ):
            skipped_gap += 1
            index += cadence
            continue

        decision_price = float(bars[index].close)
        market = market_features(perception.closes[:available], decision_price)
        state = PortfolioState(
            position_long=position_long,
            unrealized_log_return=(
                math.log(decision_price / entry_price)
                if position_long and entry_price is not None and entry_price > 0.0
                else 0.0
            ),
            holding_hours=holding_hours,
            round_trip_cost_bps=fee * 2.0 * 10_000.0,
        )
        features = compose_features(market, state)

        outcome = policy.decide(
            features, state, explore_with=rng if (learn and config.explore) else None
        )
        for k, share in enumerate(outcome.regime_responsibilities):
            regime_totals[k] += share
        decision_counts[outcome.decision.value] += 1

        fill_price = float(bars[fill_index].close)
        reward_price = float(bars[reward_index].close)
        forward_log_return = math.log(reward_price / fill_price)

        if learn:
            rewards = action_rewards(
                forward_log_return, position_long=position_long, fee_per_side=fee
            )
            reward_total += policy.update(features, rewards)

        # Apply the chosen exposure at the fill price.
        if outcome.decision == TradeDecision.BUY:
            units = (cash * (1.0 - fee)) / fill_price
            cash = 0.0
            entry_price = fill_price
            holding_hours = 0
            buys += 1
        elif outcome.decision == TradeDecision.SELL:
            cash = units * fill_price * (1.0 - fee)
            units = 0.0
            entry_price = None
            holding_hours = 0
            sells += 1
        elif units > 0.0:
            holding_hours += cadence

        steps += 1
        index += cadence

    # Mark the tail and liquidate any open position at the final close.
    for mark in range(last_mark_index, end):
        value = equity_at(mark)
        peak = max(peak, value)
        if peak > 0.0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)
        if units > 0.0:
            exposed_hours += 1

    final_long = units > 0.0
    final_equity = cash + (
        units * float(bars[end - 1].close) * (1.0 - fee) if final_long else 0.0
    )
    elapsed_hours = max(end - start, 1)
    total_share = sum(regime_totals) or 1.0
    return RolloutResult(
        steps=steps,
        net_return_pct=(final_equity / capital - 1.0) * 100.0,
        max_drawdown_pct=max_drawdown * 100.0,
        buys=buys,
        sells=sells,
        exposure_share=exposed_hours / elapsed_hours,
        mean_reward=reward_total / steps if steps else 0.0,
        final_long=final_long,
        skipped_gap_steps=skipped_gap,
        skipped_history_steps=skipped_history,
        regime_usage=[value / total_share for value in regime_totals],
        decision_counts=decision_counts,
    )


def train_agent(
    bars: Sequence[Any],
    perception: DailyPerception,
    start: int,
    end: int,
    config: TrainingConfig,
) -> tuple[RegimeMixturePolicy, list[RolloutResult]]:
    """Train by repeated on-policy passes over the training window."""
    policy = RegimeMixturePolicy(
        regimes=config.regimes,
        learning_rate=config.learning_rate,
        l2=config.l2,
        init_seed=config.seed,
    )
    rng = random.Random(config.seed)
    history: list[RolloutResult] = []
    for _epoch in range(config.epochs):
        history.append(
            rollout(
                bars, perception, policy, start, end, config, learn=True, rng=rng
            )
        )
    return policy, history


def evaluate_agent(
    bars: Sequence[Any],
    perception: DailyPerception,
    policy: RegimeMixturePolicy,
    start: int,
    end: int,
    config: TrainingConfig,
) -> RolloutResult:
    """Frozen, deterministic evaluation: no learning, no exploration."""
    return rollout(
        bars, perception, policy, start, end, config, learn=False, rng=None
    )


def buy_and_hold_reference(
    bars: Sequence[Any], start: int, end: int, fee_per_side: float
) -> dict[str, float]:
    """Reported for context only.

    Per the user's instruction this is no longer an approval criterion; the agent
    is judged on how much it earns, not on whether it clears this line. It is kept
    because a return number without the passive alternative next to it is hard to
    interpret.
    """
    units = (1.0 * (1.0 - fee_per_side)) / float(bars[start].close)
    peak = 1.0
    max_drawdown = 0.0
    for index in range(start, end):
        value = units * float(bars[index].close)
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) / peak)
    final = units * float(bars[end - 1].close) * (1.0 - fee_per_side)
    return {
        "net_return_pct": (final - 1.0) * 100.0,
        "max_drawdown_pct": max_drawdown * 100.0,
    }


def result_to_dict(result: RolloutResult) -> dict[str, Any]:
    return asdict(result)


__all__ = [
    "DailyPerception",
    "RolloutResult",
    "TrainingConfig",
    "build_daily_perception",
    "buy_and_hold_reference",
    "evaluate_agent",
    "result_to_dict",
    "rollout",
    "train_agent",
]
