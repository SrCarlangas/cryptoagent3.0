"""Shared market perception for the local exposure agent.

This module is the single definition of what the agent sees. Training and the live
runtime both call `market_features`, so a feature can never be computed one way
offline and another way online. That symmetry is the whole point of the module.

Two design rules come directly out of the Task 1 diagnosis
(data/validation/exposure-diagnosis.md):

1. Inputs are COMPLETED daily closes plus the current price, never partial days.
   At any instant the agent sees the days that have already closed and the price
   right now. A backtest that fed it today's close before today ended would be
   inventing information the live agent cannot have.

2. No spread and no order-flow features. Those existed only in the live feed and
   were filled with historical proxies at training time, which is train/serve
   skew. They are still enforced live, but as deterministic data-quality gates
   outside the model, not as inputs the policy can learn to depend on.

Every feature is scale-free (log ratios, returns, volatilities) so a policy
trained across a 10x price range stays valid at any price level.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

FEATURE_SCHEMA_VERSION = "exposure-daily-trend/1.0.0"

MIN_DAILY_HISTORY = 200
"""Completed daily closes required before the agent may act.

Set by the longest lookback in the feature set: the 200-day average and the
200-day high/low channel. Below this the perception is undefined and the caller
must abstain rather than substitute a shorter window, because a 200-day trend
feature computed over 40 days is a different feature wearing the same name.
"""

MARKET_FEATURE_NAMES: tuple[str, ...] = (
    "log_price_over_ma7",
    "log_price_over_ma30",
    "log_price_over_ma50",
    "log_price_over_ma100",
    "log_price_over_ma200",
    "log_ma7_over_ma30",
    "log_ma30_over_ma100",
    "log_ma100_over_ma200",
    "ma7_slope_7d",
    "ma30_slope_30d",
    "return_1d",
    "return_7d",
    "return_30d",
    "return_90d",
    "volatility_30d",
    "volatility_90d",
    "volatility_ratio_30_90",
    "log_price_over_high_200d",
    "log_price_over_low_200d",
)

_VOLATILITY_FLOOR = 1e-9
"""Below this, a volatility ratio is meaningless and is reported as neutral.

A stalled or synthetic-flat series drives both volatilities toward zero, and the
ratio of two near-zero numbers is arbitrary noise. Returning 1.0 there keeps the
feature neutral instead of handing the policy a garbage value to act on.
"""

_MA_WINDOWS: tuple[int, ...] = (7, 30, 50, 100, 200)
_RETURN_WINDOWS: tuple[int, ...] = (1, 7, 30, 90)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _moving_average(closes: Sequence[float], window: int) -> float:
    if window > len(closes):
        raise ValueError(f"moving average window {window} exceeds history {len(closes)}")
    return _mean(closes[-window:])


def _log_return_stdev(closes: Sequence[float], window: int) -> float:
    """Sample standard deviation of daily log returns over `window` days."""
    if window + 1 > len(closes):
        raise ValueError(f"volatility window {window} exceeds history {len(closes)}")
    segment = closes[-(window + 1) :]
    returns = [math.log(later / earlier) for earlier, later in pairwise(segment)]
    average = _mean(returns)
    variance = sum((value - average) ** 2 for value in returns) / max(len(returns) - 1, 1)
    return math.sqrt(max(variance, 0.0))


def market_features(daily_closes: Sequence[float], price: float) -> list[float]:
    """Project completed daily closes plus the current price into the fixed schema.

    `daily_closes` is ordered oldest to newest and must contain only days that
    have already closed. `price` is the current price, which in training is the
    close of the intraday bar being decided on and live is the latest trade.

    Raises ValueError when history is insufficient or any input is not positive
    and finite. Raising is deliberate: a silent fallback would let the runtime act
    on a feature vector whose meaning differs from the trained one.
    """
    if len(daily_closes) < MIN_DAILY_HISTORY:
        raise ValueError(
            f"exposure features need {MIN_DAILY_HISTORY} completed daily closes, "
            f"received {len(daily_closes)}"
        )
    if not math.isfinite(price) or price <= 0.0:
        raise ValueError("price must be positive and finite")
    for value in daily_closes:
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("daily closes must be positive and finite")

    averages = {window: _moving_average(daily_closes, window) for window in _MA_WINDOWS}

    # Slopes are measured on the averages themselves, so they describe the
    # direction of the trend rather than the noise of a single day.
    ma7_previous = _mean(daily_closes[-14:-7])
    ma30_previous = _mean(daily_closes[-60:-30])

    window_200 = daily_closes[-200:]
    high_200 = max(window_200)
    low_200 = min(window_200)

    volatility_30 = _log_return_stdev(daily_closes, 30)
    volatility_90 = _log_return_stdev(daily_closes, 90)

    values: list[float] = [
        *(math.log(price / averages[window]) for window in _MA_WINDOWS),
        math.log(averages[7] / averages[30]),
        math.log(averages[30] / averages[100]),
        math.log(averages[100] / averages[200]),
        math.log(averages[7] / ma7_previous),
        math.log(averages[30] / ma30_previous),
        *(math.log(price / daily_closes[-window]) for window in _RETURN_WINDOWS),
        volatility_30,
        volatility_90,
        (
            volatility_30 / volatility_90
            if volatility_90 > _VOLATILITY_FLOOR and volatility_30 > _VOLATILITY_FLOOR
            else 1.0
        ),
        # Positive when price is making new 200-day highs, negative below the
        # channel top. Named for what it measures rather than for "drawdown",
        # which would imply it is never positive.
        math.log(price / high_200),
        math.log(price / low_200),
    ]
    if len(values) != len(MARKET_FEATURE_NAMES):
        raise ValueError("exposure feature vector length does not match the schema")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("non-finite exposure feature")
    return values


def market_features_from_decimal(
    daily_closes: Sequence[Decimal], price: Decimal
) -> list[float]:
    """Decimal-boundary wrapper for the live runtime.

    Execution keeps Decimal end to end; the policy is float arithmetic. Converting
    at exactly one place keeps that boundary explicit and auditable.
    """
    return market_features([float(value) for value in daily_closes], float(price))


__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "MARKET_FEATURE_NAMES",
    "MIN_DAILY_HISTORY",
    "market_features",
    "market_features_from_decimal",
]
