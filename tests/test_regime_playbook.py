"""Tests for the per-regime strategies and for the stop/sizing machinery they drive.

Two groups here, and the second group matters more than it looks.

The playbook tests pin the behaviour the owner asked for: a regime selects a strategy,
and that strategy carries its own risk budget, stop geometry, horizon and burden of
proof.

The characterisation tests pin what `_active_stop` and `size_entry_percentage`
already do. Neither had a single numeric test anywhere in the repo, and they are the
protective stop and the position size. Changing them without first recording their
current behaviour would mean changing the one mechanism that limits losses with no way
to tell whether it still works.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from btc_decision_agent.application.realtime_demo import (
    ProtectiveDecisionEngine,
    RealtimeParams,
    size_entry_percentage,
)
from btc_decision_agent.application.regime_playbook import (
    MAX_ALLOCATION,
    MAX_STOP_FRACTION,
    MIN_ALLOCATION,
    MIN_STOP_FRACTION,
    PLAYBOOK,
    ExecutionPlan,
    Posture,
    meets_burden_of_proof,
    render_playbook_block,
    resolve_plan,
    strategy_for,
)

D = Decimal
NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


class TestCurrentStopBehaviour:
    """Characterisation. Records today's stop geometry before it becomes variable."""

    def _engine(self, **params: object) -> ProtectiveDecisionEngine:
        engine = ProtectiveDecisionEngine(RealtimeParams(**params))  # type: ignore[arg-type]
        return engine

    def _long_at(self, engine: ProtectiveDecisionEngine, entry: str, high: str) -> None:
        from dataclasses import replace as dc_replace

        engine.import_state(
            dc_replace(engine.state, entry_price=D(entry), high_since_entry=D(high))
        )

    def test_no_position_has_no_stop(self) -> None:
        assert self._engine().active_stop(D("80000")) is None

    def test_initial_stop_is_a_fixed_fraction_below_entry(self) -> None:
        engine = self._engine()
        self._long_at(engine, "80000", "80000")
        # Default stop_loss_fraction is 3%.
        assert engine.active_stop(D("80000")) == D("80000") * D("0.97")

    def test_break_even_lock_raises_the_floor_once_slightly_in_profit(self) -> None:
        engine = self._engine()
        # Default break-even activation +0.5%, lock +0.25%.
        self._long_at(engine, "80000", "80400")  # +0.5%
        assert engine.active_stop(D("80400")) == D("80000") * D("1.0025")

    def test_trailing_engages_only_after_the_activation_threshold(self) -> None:
        engine = self._engine()
        # +0.9% high: past break-even (+0.5%) but short of trailing activation (+1%).
        self._long_at(engine, "80000", "80720")
        assert engine.active_stop(D("80720")) == D("80000") * D("1.0025")

    def test_trailing_follows_the_high_once_active(self) -> None:
        engine = self._engine()
        self._long_at(engine, "80000", "88000")  # +10%, well past activation
        # Default trailing 2.5% behind the high.
        assert engine.active_stop(D("88000")) == D("88000") * D("0.975")

    def test_the_stop_never_falls_back_below_its_floor(self) -> None:
        engine = self._engine()
        self._long_at(engine, "80000", "80900")  # trail would be below break-even lock
        stop = engine.active_stop(D("80900"))
        assert stop is not None and stop >= D("80000") * D("1.0025")

    def test_a_wider_stop_fraction_moves_the_initial_stop_down(self) -> None:
        # The property the playbook depends on: stop geometry follows params.
        wide = self._engine(stop_loss_fraction=D("0.10"))
        self._long_at(wide, "80000", "80000")
        assert wide.active_stop(D("80000")) == D("80000") * D("0.90")


class TestCurrentSizingBehaviour:
    """Characterisation of `size_entry_percentage`, which had no tests at all."""

    def test_cash_allocation_alone(self) -> None:
        assert size_entry_percentage(D("1000"), D("0.95")) == D("950.00")

    def test_risk_cap_can_bind_below_the_cash_allocation(self) -> None:
        # equity * risk / stop = 5000 * 0.02 / 0.03 = 3333.33, below 0.95 * 5000.
        quote = size_entry_percentage(
            D("5000"),
            D("0.95"),
            equity=D("5000"),
            risk_per_trade_fraction=D("0.02"),
            stop_loss_fraction=D("0.03"),
        )
        assert quote == D("3333.33")

    def test_a_wider_stop_shrinks_the_position_for_a_fixed_risk_budget(self) -> None:
        """The coupling that shaped the playbook's design.

        Widening the stop to avoid being shaken out of a trend would have quietly cut
        the position instead, so each strategy sets its risk budget together with its
        stop rather than one at a time.
        """
        tight = size_entry_percentage(
            D("100000"), D("0.95"), equity=D("5000"),
            risk_per_trade_fraction=D("0.02"), stop_loss_fraction=D("0.03"),
        )
        wide = size_entry_percentage(
            D("100000"), D("0.95"), equity=D("5000"),
            risk_per_trade_fraction=D("0.02"), stop_loss_fraction=D("0.12"),
        )
        assert wide < tight
        # And raising the risk budget alongside the stop restores the size.
        restored = size_entry_percentage(
            D("100000"), D("0.95"), equity=D("5000"),
            risk_per_trade_fraction=D("0.08"), stop_loss_fraction=D("0.12"),
        )
        assert restored == tight

    def test_below_min_notional_returns_zero_rather_than_a_tiny_order(self) -> None:
        assert size_entry_percentage(D("5"), D("0.95"), min_notional=D("10")) == D("0")

    def test_risk_arguments_are_all_or_nothing(self) -> None:
        with pytest.raises(ValueError, match="must be provided together"):
            size_entry_percentage(D("1000"), D("0.95"), equity=D("1000"))


class TestPlaybookShape:
    def test_every_regime_has_a_strategy(self) -> None:
        assert sorted(PLAYBOOK) == [0, 1, 2, 3]

    def test_the_bull_regime_is_the_most_committed_and_the_bear_the_least(self) -> None:
        bull, bear = PLAYBOOK[3], PLAYBOOK[1]
        assert bull.allocation_at_neutral > bear.allocation_at_neutral
        # A wide stop is the point in a trend: noise must not end the position.
        assert bull.stop_vol_multiple > bear.stop_vol_multiple
        # And a wide stop needs a bigger risk budget or sizing would shrink instead.
        assert bull.risk_per_trade > bear.risk_per_trade
        assert bull.horizon_hours > bear.horizon_hours

    def test_the_burden_of_proof_inverts_in_a_strong_uptrend(self) -> None:
        """The specific failure the owner pointed at: 41% invested in a bull regime.

        In regime 3 staying in cash is what has to be justified, so an agent that is
        merely unsure ends up invested rather than out.
        """
        assert meets_burden_of_proof(regime=3, wants_invested=True, conviction=0.40)
        assert not meets_burden_of_proof(regime=3, wants_invested=False, conviction=0.40)
        # And the reverse in a deep bear.
        assert not meets_burden_of_proof(regime=1, wants_invested=True, conviction=0.60)
        assert meets_burden_of_proof(regime=1, wants_invested=False, conviction=0.40)

    def test_an_unknown_regime_falls_back_to_the_cautious_strategy(self) -> None:
        assert strategy_for(None) is PLAYBOOK[1]
        assert strategy_for(99) is PLAYBOOK[1]


class TestPlanResolution:
    def test_conviction_finally_changes_the_position_size(self) -> None:
        """Conviction was measured, calibrated and then ignored: 0.70 and 0.85 both
        produced a 95% position."""
        low = resolve_plan(regime=2, posture="NEUTRAL", conviction=0.30, daily_vol_pct=2.0)
        high = resolve_plan(regime=2, posture="NEUTRAL", conviction=0.95, daily_vol_pct=2.0)
        assert high.allocation_fraction > low.allocation_fraction

    def test_posture_scales_size_and_stop_together(self) -> None:
        defensive = resolve_plan(regime=3, posture="DEFENSIVA", conviction=0.6, daily_vol_pct=2.0)
        aggressive = resolve_plan(regime=3, posture="AGRESIVA", conviction=0.6, daily_vol_pct=2.0)
        assert aggressive.allocation_fraction > defensive.allocation_fraction
        assert aggressive.stop_loss_fraction > defensive.stop_loss_fraction
        assert aggressive.risk_per_trade_fraction > defensive.risk_per_trade_fraction

    def test_stops_scale_with_measured_volatility_not_a_fixed_percentage(self) -> None:
        quiet = resolve_plan(regime=3, posture="NEUTRAL", conviction=0.6, daily_vol_pct=1.0)
        violent = resolve_plan(regime=3, posture="NEUTRAL", conviction=0.6, daily_vol_pct=4.0)
        assert violent.stop_loss_fraction > quiet.stop_loss_fraction

    def test_a_bull_regime_gets_a_wider_stop_than_a_bear_at_equal_volatility(self) -> None:
        bull = resolve_plan(regime=3, posture="NEUTRAL", conviction=0.6, daily_vol_pct=2.0)
        bear = resolve_plan(regime=1, posture="NEUTRAL", conviction=0.6, daily_vol_pct=2.0)
        assert bull.stop_loss_fraction > bear.stop_loss_fraction
        assert bull.allocation_fraction > bear.allocation_fraction
        assert bull.horizon_hours > bear.horizon_hours

    def test_everything_stays_inside_the_reviewed_bounds(self) -> None:
        # No regime, posture, conviction or volatility reading may escape the limits.
        candidates: list[int | None] = [*PLAYBOOK, None, 99]
        for regime in candidates:
            for posture in Posture:
                for conviction in (0.0, 0.5, 1.0):
                    for vol in (None, 0.0, 0.1, 2.0, 25.0):
                        plan = resolve_plan(
                            regime=regime,
                            posture=posture.value,
                            conviction=conviction,
                            daily_vol_pct=vol,
                        )
                        assert MIN_ALLOCATION <= plan.allocation_fraction <= MAX_ALLOCATION
                        assert MIN_STOP_FRACTION <= plan.stop_loss_fraction <= MAX_STOP_FRACTION
                        # And it must satisfy the engine's own validation.
                        plan.apply(RealtimeParams())

    def test_an_unknown_posture_degrades_to_neutral(self) -> None:
        plan = resolve_plan(regime=3, posture="TEMERARIA", conviction=0.6, daily_vol_pct=2.0)
        assert plan.posture == "NEUTRAL"

    def test_applying_a_plan_revalidates_through_realtime_params(self) -> None:
        plan = resolve_plan(regime=3, posture="AGRESIVA", conviction=0.9, daily_vol_pct=3.0)
        params = plan.apply(RealtimeParams())
        assert params.allocation_fraction == plan.allocation_fraction
        assert params.stop_loss_fraction == plan.stop_loss_fraction
        assert params.risk_per_trade_fraction == plan.risk_per_trade_fraction

    def test_a_plan_survives_a_round_trip_through_disk(self) -> None:
        # It has to: the stop is recomputed on every event from these fractions, so
        # losing the plan on restart would silently change an open position's stop.
        plan = resolve_plan(regime=3, posture="AGRESIVA", conviction=0.8, daily_vol_pct=2.5)
        assert ExecutionPlan.from_dict(plan.to_dict()) == plan

    def test_the_agent_is_shown_the_strategy_it_operates_inside(self) -> None:
        block = render_playbook_block(3, 2.0)
        assert "alcista fuerte" in block
        assert "EN LIQUIDEZ" in block  # the inverted burden is stated
        for posture in Posture:
            assert posture.value in block
        # It must be told it chooses posture, not numbers.
        assert "POSTURA" in block
