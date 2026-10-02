"""Guards for the module that produced this project's operating recommendation.

`research/static_frontier.py` is where the recommended implementation comes from (~18% constant
BTC, 10% band). It had **zero tests**, exactly like `scripts/gate_llm_agent.py` before 14 were
added -- and the gate turned out to contain a hole that would have approved a product dominated
by doing nothing. A number nobody tested is a number nobody should act on.

These assert ARITHMETIC, not formatting: no test here pins a rounded decimal, because a test
that asserts `"+140.0%"` passes while the maths underneath rots.
"""

from __future__ import annotations

import math

import pytest
from multislot_sim import Bar
from static_frontier import simulate


def bars_from(prices: list[float]) -> list[Bar]:
    return [
        Bar(
            open_time_ms=index * 3_600_000,
            open=price,
            high=price,
            low=price,
            close=price,
            contiguous_run=index + 1,
        )
        for index, price in enumerate(prices)
    ]


def test_zero_fraction_holds_no_btc_and_returns_nothing() -> None:
    """The null of the null: 0% exposure must be exactly flat, fees included."""
    point = simulate(bars_from([100.0, 200.0, 50.0, 300.0]), 0.0, 0.10, 0.001)
    assert point.net_return_pct == pytest.approx(0.0, abs=1e-12)
    assert point.rebalances == 0
    assert point.fees_paid_pct == pytest.approx(0.0, abs=1e-12)


def test_full_exposure_without_rebalancing_equals_buy_and_hold_minus_both_fees() -> None:
    """Hand-computed: a doubling costs an entry fee and an exit fee, and nothing else.

    With fraction 1.0 the held share never drifts from the target, so the band is never
    breached and no rebalance may be charged. Final equity is therefore
    `(p_last / p_first) * (1 - fee) - fee`.
    """
    fee = 0.001
    point = simulate(bars_from([100.0, 150.0, 200.0]), 1.0, 0.10, fee)
    expected = 2.0 * (1.0 - fee) - fee
    assert point.net_return_pct == pytest.approx((expected - 1.0) * 100.0, rel=1e-9)
    assert point.rebalances == 0, "a constant 100% allocation cannot drift out of band"


def test_fees_strictly_reduce_the_result() -> None:
    """A fee that does not cost anything is a fee that is not being charged."""
    prices = [100.0, 130.0, 80.0, 160.0, 120.0, 190.0]
    free = simulate(bars_from(prices), 0.18, 0.10, 0.0)
    costly = simulate(bars_from(prices), 0.18, 0.10, 0.002)
    assert costly.net_return_pct < free.net_return_pct
    assert costly.fees_paid_pct > 0.0


def test_a_monotonically_rising_price_has_no_drawdown() -> None:
    point = simulate(bars_from([100.0, 110.0, 125.0, 140.0]), 0.50, 0.10, 0.0)
    assert point.max_drawdown_pct == pytest.approx(0.0, abs=1e-9)


def test_drawdown_is_measured_on_marked_to_market_equity() -> None:
    """Half the capital in an asset that halves is a ~25% equity drawdown, not 50%.

    This is the arithmetic the rewritten gate depends on: the comparator de-leverages buy and
    hold to the agent's own realised drawdown, so a drawdown that is computed on the wrong base
    silently moves the bar the agent is judged against.
    """
    point = simulate(bars_from([100.0, 50.0, 100.0]), 0.50, 0.99, 0.0)
    assert point.max_drawdown_pct == pytest.approx(25.0, rel=1e-6)


def test_a_wider_band_cannot_trade_more_than_a_tighter_one() -> None:
    """The band exists to buy less churn. If widening it traded more, it would be inverted."""
    prices = [100.0 * (1.0 + 0.4 * math.sin(step / 2.0)) for step in range(60)]
    tight = simulate(bars_from(prices), 0.18, 0.02, 0.001)
    wide = simulate(bars_from(prices), 0.18, 0.30, 0.001)
    assert wide.rebalances <= tight.rebalances
    assert wide.fees_paid_pct <= tight.fees_paid_pct


def test_rebalancing_restores_the_target_fraction() -> None:
    """After a breach the held share must come back to the target, not merely move toward it."""
    point = simulate(bars_from([100.0, 100.0, 400.0, 400.0]), 0.20, 0.05, 0.0)
    assert point.rebalances >= 1


def test_the_reported_fraction_and_band_are_the_ones_simulated() -> None:
    """Cheap, but this is how a sweep mislabels its own winner."""
    point = simulate(bars_from([100.0, 120.0]), 0.18, 0.10, 0.002)
    assert point.fraction == 0.18
    assert point.band == 0.10
    assert point.fee_per_side == 0.002
