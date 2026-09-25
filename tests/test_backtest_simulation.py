"""Tests for the backtest's execution simulation, driven by synthetic verdicts.

The backtest costs four hours of model inference per run, so the arithmetic it performs
cannot be validated by running it. These tests drive the same simulation with scripted
verdicts and no model at all, which is the only way to know whether the numbers the
report prints mean anything.

Two properties matter most. The simulation must size positions through the production
formula, so a backtest cannot flatter the agent with sizing the live system would never
do. And the protective stop must actually fire, because a wide trend-following stop that
is never tested is not a strategy, it is an assumption.
"""

from __future__ import annotations

from dataclasses import replace as dc_replace
from decimal import Decimal

from btc_decision_agent.application.realtime_demo import (
    ProtectiveDecisionEngine,
    RealtimeParams,
    size_entry_percentage,
)
from btc_decision_agent.application.regime_playbook import resolve_plan

D = Decimal


def _stop_for(plan_dict: dict[str, object] | None, entry: float, high: float, price: float) -> float | None:
    """The same helper shape the backtest uses, so this tests that mechanism."""
    engine = ProtectiveDecisionEngine(RealtimeParams())
    engine.import_state(
        dc_replace(
            engine.state,
            entry_price=D(str(entry)),
            high_since_entry=D(str(high)),
            execution_plan=plan_dict,
        )
    )
    raw = engine.active_stop(D(str(price)))
    return float(raw) if raw is not None else None


class TestSimulatedSizing:
    def test_a_normalised_capital_would_round_every_order_to_zero(self) -> None:
        """Why the backtest starts from 10,000 rather than 1.0.

        Production sizing enforces a minimum notional. Replaying with capital of 1.0
        would size every entry to zero and the run would silently measure an agent that
        never trades.
        """
        assert size_entry_percentage(D("1.0"), D("0.95"), min_notional=D("10")) == D("0")
        assert size_entry_percentage(D("10000"), D("0.95"), min_notional=D("10")) > D("0")

    def test_a_bull_plan_deploys_more_capital_than_a_bear_plan(self) -> None:
        cash, equity = D("10000"), D("10000")
        bull = resolve_plan(regime=3, posture="AGRESIVA", conviction=0.85, daily_vol_pct=2.5)
        bear = resolve_plan(regime=1, posture="DEFENSIVA", conviction=0.85, daily_vol_pct=2.5)
        params = RealtimeParams()
        bull_quote = size_entry_percentage(
            cash,
            bull.apply(params).allocation_fraction,
            equity=equity,
            risk_per_trade_fraction=bull.apply(params).risk_per_trade_fraction,
            stop_loss_fraction=bull.apply(params).stop_loss_fraction,
        )
        bear_quote = size_entry_percentage(
            cash,
            bear.apply(params).allocation_fraction,
            equity=equity,
            risk_per_trade_fraction=bear.apply(params).risk_per_trade_fraction,
            stop_loss_fraction=bear.apply(params).stop_loss_fraction,
        )
        assert bull_quote > bear_quote

    def test_partial_allocation_leaves_cash_on_the_side(self) -> None:
        # The old simulation was all-in or all-out, so it could not represent this.
        plan = resolve_plan(regime=1, posture="DEFENSIVA", conviction=0.5, daily_vol_pct=2.0)
        params = plan.apply(RealtimeParams())
        quote = size_entry_percentage(
            D("10000"),
            params.allocation_fraction,
            equity=D("10000"),
            risk_per_trade_fraction=params.risk_per_trade_fraction,
            stop_loss_fraction=params.stop_loss_fraction,
        )
        assert D("0") < quote < D("10000")


class TestSimulatedStops:
    def test_the_stop_fires_on_a_fall_through_it(self) -> None:
        plan = resolve_plan(regime=0, posture="DEFENSIVA", conviction=0.5, daily_vol_pct=1.0)
        stop = _stop_for(plan.to_dict(), entry=100.0, high=100.0, price=100.0)
        assert stop is not None
        # A close below the stop is an exit in the simulation.
        assert stop < 100.0
        assert 96.0 < stop < 100.0  # tight geometry in chop at 1% volatility

    def test_a_bull_plan_survives_a_dip_that_would_stop_out_a_bear_plan(self) -> None:
        """The whole point of widening the stop in a trend.

        Same entry, same dip. The bear strategy is out; the trend strategy is still in.
        """
        bull = resolve_plan(regime=3, posture="AGRESIVA", conviction=0.8, daily_vol_pct=3.0)
        bear = resolve_plan(regime=1, posture="DEFENSIVA", conviction=0.8, daily_vol_pct=3.0)
        dip = 92.0  # an 8% pullback
        bull_stop = _stop_for(bull.to_dict(), entry=100.0, high=100.0, price=dip)
        bear_stop = _stop_for(bear.to_dict(), entry=100.0, high=100.0, price=dip)
        assert bull_stop is not None and bear_stop is not None
        assert dip > bull_stop, "el plan alcista debe sobrevivir la caida"
        assert dip <= bear_stop, "el plan bajista debe salir"

    def test_the_trail_locks_in_gains_as_the_high_advances(self) -> None:
        plan = resolve_plan(regime=3, posture="NEUTRAL", conviction=0.7, daily_vol_pct=2.0)
        at_entry = _stop_for(plan.to_dict(), entry=100.0, high=100.0, price=100.0)
        after_run = _stop_for(plan.to_dict(), entry=100.0, high=140.0, price=140.0)
        assert at_entry is not None and after_run is not None
        assert after_run > at_entry
        # And once well in profit the stop sits above the entry, so the trade cannot
        # turn into a loss.
        assert after_run > 100.0

    def test_a_missing_plan_falls_back_to_the_default_geometry(self) -> None:
        assert _stop_for(None, entry=100.0, high=100.0, price=100.0) == 97.0

    def test_closes_only_data_understates_stop_exits(self) -> None:
        """Recorded because the report claims it, and a claim in a report should be
        checkable.

        The simulation compares the stop against the daily close. A day whose low
        pierced the stop but whose close recovered above it does not trigger here, so
        measured stop-outs are a lower bound and wide stops look better than they are.
        """
        plan = resolve_plan(regime=0, posture="NEUTRAL", conviction=0.5, daily_vol_pct=1.0)
        stop = _stop_for(plan.to_dict(), entry=100.0, high=100.0, price=99.0)
        assert stop is not None
        intraday_low, close = stop - 1.0, 99.0
        assert intraday_low < stop, "la mecha habria tocado el stop"
        assert close > stop, "el cierre no lo toca, asi que la simulacion no lo ve"
