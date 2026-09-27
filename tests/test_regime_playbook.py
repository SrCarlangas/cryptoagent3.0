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

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from btc_decision_agent.application import regime_playbook
from btc_decision_agent.application.realtime_demo import (
    ProtectiveDecisionEngine,
    RealtimeParams,
    size_entry_percentage,
)
from btc_decision_agent.application.regime_playbook import (
    _POSTURE_SIZE,
    LEGACY_BREAK_EVEN_ACTIVATION,
    LEGACY_BREAK_EVEN_LOCK,
    MAX_ALLOCATION,
    MAX_RISK_FRACTION,
    MAX_STOP_FRACTION,
    MIN_ALLOCATION,
    MIN_RISK_FRACTION,
    MIN_STOP_FRACTION,
    PLAYBOOK,
    TREND_SIDE_ABOVE,
    TREND_SIDE_BELOW,
    ExecutionPlan,
    Posture,
    RegimeTracker,
    _clamp,
    corroborated_regime,
    render_playbook_block,
    resolve_plan,
    resolve_target_allocation,
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

    def test_the_default_exposure_inverts_between_bear_and_bull(self) -> None:
        """The specific failure the owner pointed at: 41% invested in a bull regime."""
        from btc_decision_agent.application.llm_tools import (
            EXPOSURE_CASH,
            EXPOSURE_INVESTED,
        )

        assert PLAYBOOK[3].default_exposure == EXPOSURE_INVESTED
        assert PLAYBOOK[2].default_exposure == EXPOSURE_INVESTED
        assert PLAYBOOK[1].default_exposure == EXPOSURE_CASH
        assert PLAYBOOK[0].default_exposure == EXPOSURE_CASH

    def test_the_default_exposure_is_doctrine_and_not_a_control(self) -> None:
        """What used to be here, and why it is gone.

        A conviction threshold per regime let the playbook REVERSE the direction the agent
        asked for. Three tests pinned that behaviour and they have been deleted rather than
        weakened, because the behaviour was removed deliberately.

        Measured on 60 recorded decisions the override cost 39 points, +60.65% against
        +99.70% without it, and nearly doubled the round trips, 27 against 14. Of 15
        direction changes, 9 were imposed against what the agent had asked for.

        It was added because the agent had been OBSERVED sitting out a +185% advance at
        0.50 conviction. That observation was real and the diagnosis was wrong: the run
        behind it had a break-even ratchet closing every position that went 0.5% green and
        a memory scoring 168 hour decisions on tomorrow's price. The caution was partly a
        correct response to an execution layer that could not hold a position.

        The default survives as DOCTRINE shown to the agent in its prompt. Nothing reads it
        to reverse a decision, so nothing asserts that it does.
        """
        from btc_decision_agent.application.llm_tools import (
            EXPOSURE_CASH,
            EXPOSURE_INVESTED,
        )

        assert PLAYBOOK[3].default_exposure == EXPOSURE_INVESTED
        assert PLAYBOOK[1].default_exposure == EXPOSURE_CASH
        # And the threshold that used to enforce it no longer exists anywhere. A parameter
        # that is read by nothing is the defect this whole file has been chasing.
        assert not hasattr(PLAYBOOK[3], "min_conviction_to_deviate")
        assert not hasattr(regime_playbook, "resolve_exposure")

    def test_the_regime_still_owns_every_magnitude(self) -> None:
        """What makes full direction authority safe rather than reckless.

        The agent may ask to be invested in a deep bear. The regime decides that this buys
        a fifth of the capital behind a tight stop, so the decision is honoured and the
        damage is still bounded.
        """
        bear = resolve_plan(regime=1, posture="AGRESIVA", conviction=1.0, daily_vol_pct=2.0)
        bull = resolve_plan(regime=3, posture="AGRESIVA", conviction=1.0, daily_vol_pct=2.0)
        assert bear.allocation_fraction < bull.allocation_fraction / 2
        assert bear.stop_loss_fraction < bull.stop_loss_fraction
        assert bear.horizon_hours < bull.horizon_hours
        # The ceiling scales with posture like the stop does, so the comparison has to
        # use the scaled figure. Checked against the plan's own recorded risk too.
        ceiling = PLAYBOOK[1].risk_per_trade * _POSTURE_SIZE[Posture.AGRESIVA]
        assert bear.allocation_fraction * bear.stop_loss_fraction <= ceiling
        assert bear.risk_per_trade_fraction <= ceiling

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
                        # MIN_ALLOCATION is no longer a hard floor. The risk ceiling may
                        # push the allocation below it, and that is the intended
                        # precedence: between a floor on position size and a ceiling on
                        # risk, the ceiling wins. Dust is handled by the exchange minimum
                        # notional in plan_adjustment, not by inflating a position past the
                        # risk the regime allows.
                        assert D("0") < plan.allocation_fraction <= MAX_ALLOCATION
                        implied = plan.allocation_fraction * plan.stop_loss_fraction
                        if plan.allocation_fraction < MIN_ALLOCATION:
                            assert implied <= MAX_RISK_FRACTION
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
        assert "EN LIQUIDEZ" in block  # the regime's doctrine is stated
        # And the two things the agent has to know to carry its own authority: that the
        # direction is its call, and the horizon its decision will be judged on. The old
        # version showed it a conviction threshold to clear, which both invited anchoring
        # and is no longer true.
        assert "LA DIRECCION LA DECIDES TU" in block
        assert f"{PLAYBOOK[3].horizon_hours} h" in block
        assert "no por lo que pase manana" in block
        for posture in Posture:
            assert posture.value in block
        # It must be told it chooses posture, not numbers.
        assert "POSTURA" in block


class TestMemoryMigration:
    """A column added after release has to be applied to databases that predate it.

    This crashed the live agent into a restart loop and no existing test could have
    caught it: every fixture builds a fresh database where CREATE TABLE already carries
    the column. The failure only appears against a database that does not.
    """

    def _legacy_database(self, path) -> None:  # type: ignore[no-untyped-def]
        import sqlite3

        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decided_at TEXT NOT NULL, event_id TEXT, features TEXT NOT NULL,
                regime INTEGER, quant_p_long REAL, target_exposure TEXT NOT NULL,
                exposure_before TEXT NOT NULL, derived_order TEXT NOT NULL,
                conviction REAL, expected_move_pct REAL, reason TEXT, thinking TEXT,
                price_at_decision TEXT NOT NULL, acted INTEGER NOT NULL DEFAULT 0,
                resolved INTEGER NOT NULL DEFAULT 0, resolved_at TEXT,
                price_at_resolution TEXT, realized_pct REAL,
                UNIQUE(decided_at, event_id));
            """
        )
        conn.execute(
            "INSERT INTO decisions (decided_at,event_id,features,regime,target_exposure,"
            "exposure_before,derived_order,price_at_decision) "
            "VALUES ('2026-01-01','e1','[]',0,'INVERTIDO','EN LIQUIDEZ','HOLD','80000')"
        )
        conn.commit()
        conn.close()

    def test_opening_a_database_without_the_column_migrates_it(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        import sqlite3

        from btc_decision_agent.application.llm_memory import AgentMemory

        path = tmp_path / "legacy.sqlite3"
        self._legacy_database(path)
        columns = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(decisions)")}
        assert "posture" not in columns

        memory = AgentMemory(path)  # must not raise
        columns = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(decisions)")}
        assert "posture" in columns
        # The existing row survives the migration.
        assert memory.stats()["decisiones_totales"] == 1

    def test_the_migration_is_idempotent(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from btc_decision_agent.application.llm_memory import AgentMemory

        path = tmp_path / "legacy.sqlite3"
        self._legacy_database(path)
        AgentMemory(path)
        AgentMemory(path)
        assert AgentMemory(path).stats()["decisiones_totales"] == 1

    def test_a_posture_can_be_written_after_migrating(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        import sqlite3

        from btc_decision_agent.application.llm_memory import AgentMemory

        path = tmp_path / "legacy.sqlite3"
        self._legacy_database(path)
        memory = AgentMemory(path)
        memory.record(
            decided_at=NOW,
            event_id="e2",
            features=[0.0] * 19,
            regime=3,
            quant_p_long=0.8,
            target_exposure="INVERTIDO",
            exposure_before="EN LIQUIDEZ",
            derived_order="BUY",
            conviction=0.8,
            expected_move_pct=2.0,
            reason="x",
            thinking="",
            price=D("80000"),
            acted=True,
            posture="AGRESIVA",
        )
        stored = sqlite3.connect(path).execute(
            "SELECT posture FROM decisions WHERE event_id='e2'"
        ).fetchone()
        assert stored == ("AGRESIVA",)


class TestExposureAdjustment:
    """Scaling a position instead of only opening and closing it.

    The measured failure this fixes: over 98 replayed decisions the agent entered while
    cautious (79% of entries DEFENSIVA, which halves the position) and then turned
    aggressive while already holding (58% of holding decisions AGRESIVA, asking for 95%),
    and there were ZERO scaling orders in the whole run. Participation froze at 51%
    against a 95% target and the run captured +27.6% of a +184% advance.
    """

    def _adjust(self, **kwargs):  # type: ignore[no-untyped-def]
        from btc_decision_agent.application.regime_playbook import plan_adjustment

        defaults = dict(
            target_allocation=D("0.95"),
            btc_qty=D("0"),
            price=D("100"),
            usdt_free=D("10000"),
            risk_per_trade_fraction=D("0.117"),
            stop_loss_fraction=D("0.10"),
            min_notional=D("10"),
            base_step=D("0.00001"),
        )
        defaults.update(kwargs)
        return plan_adjustment(**defaults)  # type: ignore[arg-type]

    def test_a_flat_book_buys_up_to_the_target(self) -> None:
        adjustment = self._adjust()
        assert adjustment.action == "COMPRAR"
        assert adjustment.quote_usdt == D("9500.00")

    def test_a_held_position_is_topped_up_when_conviction_rises(self) -> None:
        """The exact case that produced the gap: holding 50%, plan asks for 95%."""
        adjustment = self._adjust(btc_qty=D("50"), usdt_free=D("5000"))
        assert adjustment.current_share == D("0.5")
        assert adjustment.action == "COMPRAR"
        # 45pp of a 10,000 equity.
        assert adjustment.quote_usdt == D("4500.00")

    def test_an_over_large_position_is_trimmed_rather_than_closed(self) -> None:
        adjustment = self._adjust(
            target_allocation=D("0.50"), btc_qty=D("90"), usdt_free=D("1000")
        )
        assert adjustment.action == "VENDER"
        assert adjustment.base_qty > 0
        # It trims, it does not liquidate.
        assert adjustment.base_qty < D("90")

    def test_the_dead_band_absorbs_small_drift(self) -> None:
        # Holding 90% against a 95% target: five points is not worth a commission.
        adjustment = self._adjust(btc_qty=D("90"), usdt_free=D("1000"))
        assert adjustment.action == "MANTENER"
        assert "banda" in adjustment.reason

    def test_the_dead_band_does_not_block_a_real_posture_change(self) -> None:
        # Defensive to aggressive in the bull regime is roughly 45pp and must act.
        adjustment = self._adjust(btc_qty=D("50"), usdt_free=D("5000"))
        assert adjustment.acts

    def test_the_risk_cap_still_binds_the_target(self) -> None:
        """A wide stop must not quietly become a large bet."""
        adjustment = self._adjust(
            btc_qty=D("0"),
            usdt_free=D("10000"),
            risk_per_trade_fraction=D("0.02"),
            stop_loss_fraction=D("0.20"),
        )
        # Risk cap is 0.02 / 0.20 = 10% of equity, well under the 95% asked for.
        assert adjustment.target_share == D("0.1")
        assert adjustment.quote_usdt == D("1000.00")

    def test_it_never_buys_more_cash_than_it_has(self) -> None:
        adjustment = self._adjust(btc_qty=D("60"), usdt_free=D("100"))
        assert adjustment.quote_usdt <= D("100")

    def test_an_adjustment_below_the_minimum_notional_is_skipped(self) -> None:
        adjustment = self._adjust(
            target_allocation=D("0.95"),
            btc_qty=D("0"),
            usdt_free=D("12"),
            min_notional=D("100"),
        )
        assert adjustment.action == "MANTENER"
        assert "minimo nocional" in adjustment.reason

    def test_a_zero_target_still_arrives_as_a_full_exit(self) -> None:
        adjustment = self._adjust(
            target_allocation=D("0"), btc_qty=D("100"), usdt_free=D("0")
        )
        assert adjustment.action == "VENDER"
        assert adjustment.base_qty == D("100")

    def test_an_empty_book_does_nothing(self) -> None:
        adjustment = self._adjust(btc_qty=D("0"), usdt_free=D("0"))
        assert adjustment.action == "MANTENER"

    def test_the_sell_quantity_respects_the_lot_step(self) -> None:
        adjustment = self._adjust(
            target_allocation=D("0.50"),
            btc_qty=D("90"),
            usdt_free=D("1000"),
            base_step=D("1"),
        )
        assert adjustment.base_qty == adjustment.base_qty.to_integral_value()

    def test_target_is_a_share_of_equity_not_of_free_cash(self) -> None:
        """Asking for 95% is only well defined against equity once a position exists.

        Against free cash the same number would mean something different at every
        moment, which is why scaling could not be expressed before.
        """
        flat = self._adjust(btc_qty=D("0"), usdt_free=D("10000"))
        half = self._adjust(btc_qty=D("50"), usdt_free=D("5000"))
        assert flat.target_share == half.target_share == D("0.95")
        # And the two requests differ only by what is already held.
        assert flat.quote_usdt - half.quote_usdt == D("5000.00")

    def test_the_dead_band_never_prevents_opening_a_position(self) -> None:
        """Caught by a test before it ever ran.

        With the risk cap holding the target at 10% and a 15 point band, the gap from
        flat is 10pp and the agent would have stayed permanently flat: unable to open,
        because opening looked like drift. Opening and fully closing are changes of
        state, not drift.
        """
        adjustment = self._adjust(
            btc_qty=D("0"),
            usdt_free=D("10000"),
            risk_per_trade_fraction=D("0.02"),
            stop_loss_fraction=D("0.20"),
        )
        assert adjustment.action == "COMPRAR"
        assert adjustment.quote_usdt == D("1000.00")

    def test_a_full_exit_is_never_blocked_by_the_dead_band(self) -> None:
        # Holding only 5% and the plan says out: the band must not trap the remainder.
        adjustment = self._adjust(
            target_allocation=D("0"), btc_qty=D("5"), usdt_free=D("9500")
        )
        assert adjustment.action == "VENDER"
        assert adjustment.base_qty == D("5")


class TestFillAccountingWhenScaling:
    """What a fill does to the cost basis, the high watermark and the stop.

    This is the protective stop's input, so it gets tests before it gets changes. The
    bug being prevented: treating a top-up as a fresh entry rewrites entry_price to the
    new higher fill and resets high_since_entry, which tightens the stop across the whole
    position at the exact moment of scaling into a trend and discards the trailing high.
    """

    def _engine(self) -> ProtectiveDecisionEngine:
        return ProtectiveDecisionEngine(RealtimeParams())

    def _open(self, engine: ProtectiveDecisionEngine, price: str, qty: str) -> None:
        from btc_decision_agent.application.execution import OrderSide

        engine.on_fill(OrderSide.BUY, D(price), D(qty), NOW)

    def test_a_fresh_entry_sets_the_cost_basis_to_its_fill(self) -> None:
        engine = self._engine()
        self._open(engine, "100", "1")
        assert engine.state.entry_price == D("100")
        assert engine.state.high_since_entry == D("100")
        assert engine.state.position_base_qty == D("1")

    def test_a_top_up_averages_the_cost_basis(self) -> None:
        engine = self._engine()
        self._open(engine, "100", "1")
        self._open(engine, "140", "1")
        # (100 * 1 + 140 * 1) / 2
        assert engine.state.entry_price == D("120")
        assert engine.state.position_base_qty == D("2")

    def test_a_top_up_preserves_the_trailing_high_watermark(self) -> None:
        """The destructive part of treating a top-up as a new entry."""
        from dataclasses import replace as dc_replace

        engine = self._engine()
        self._open(engine, "100", "1")
        # The trade ran to 200 before the agent added at 140.
        engine.import_state(dc_replace(engine.state, high_since_entry=D("200")))
        self._open(engine, "140", "1")
        assert engine.state.high_since_entry == D("200")

    def test_a_top_up_keeps_the_stop_aware_of_the_real_profit(self) -> None:
        """Averaging the basis and keeping the high leaves MORE profit protected.

        Averaged, the position is entered at 120 with a high of 140, so the trade is up
        17% and the trailing stop engages at 140 * (1 - 2.5%) = 136.50.

        Treated as a fresh entry at 140 the high equals the entry, the trail has not
        activated, and the stop would be 140 * (1 - 3%) = 135.80. Lower, because it has
        forgotten that the trade is in profit at all.
        """
        engine = self._engine()
        self._open(engine, "100", "1")
        self._open(engine, "140", "1")
        after = engine.active_stop(D("140"))
        assert after is not None
        assert engine.state.entry_price == D("120")
        assert after == D("140") * D("0.975")
        # Strictly better protection than the fresh-entry treatment would have given.
        assert after > D("140") * D("0.97")

    def test_a_trim_keeps_the_cost_basis_and_the_position(self) -> None:
        from btc_decision_agent.application.execution import OrderSide

        engine = self._engine()
        self._open(engine, "100", "2")
        engine.on_fill(OrderSide.SELL, D("150"), D("1"), NOW)
        # Selling half does not change what was paid for the other half.
        assert engine.state.entry_price == D("100")
        assert engine.state.position_base_qty == D("1")
        assert engine.active_stop(D("150")) is not None

    def test_a_trim_keeps_the_strategy_the_position_was_opened_under(self) -> None:
        from dataclasses import replace as dc_replace

        from btc_decision_agent.application.execution import OrderSide

        engine = self._engine()
        self._open(engine, "100", "2")
        plan = resolve_plan(regime=3, posture="AGRESIVA", conviction=0.8, daily_vol_pct=3.0)
        engine.import_state(dc_replace(engine.state, execution_plan=plan.to_dict()))
        engine.on_fill(OrderSide.SELL, D("150"), D("1"), NOW)
        assert engine.state.execution_plan == plan.to_dict()
        assert engine.effective_params.stop_loss_fraction == plan.stop_loss_fraction

    def test_selling_everything_still_closes_the_position(self) -> None:
        from btc_decision_agent.application.execution import OrderSide

        engine = self._engine()
        self._open(engine, "100", "2")
        engine.on_fill(OrderSide.SELL, D("150"), D("2"), NOW)
        assert engine.state.entry_price is None
        assert engine.state.position_base_qty is None
        assert engine.state.execution_plan is None
        assert engine.active_stop(D("150")) is None

    def test_a_scaling_fill_marks_the_resting_stop_as_absent(self) -> None:
        """The resting order no longer covers the position, so it must be replaced.

        Recorded as absent rather than left in place, because the forced sync that
        follows every fill is what puts a correctly sized one on the exchange.
        """
        from dataclasses import replace as dc_replace

        engine = self._engine()
        self._open(engine, "100", "1")
        engine.import_state(
            dc_replace(
                engine.state,
                protective_order_id="orden-vieja",
                protective_stop_price=D("97"),
            )
        )
        self._open(engine, "140", "1")
        assert engine.state.protective_order_id is None
        assert engine.state.protective_stop_price is None


class TestBreakEvenRatchetIsGovernedByThePlaybook:
    """The omission that overrode the whole playbook, and the tests that missed it.

    `ExecutionPlan.apply` substituted the allocation, the stop, the trailing stop, the
    trailing activation and the risk budget, but not the two break-even fields. So every
    regime and every posture inherited the engine defaults: as soon as a trade was 0.5%
    in profit the stop ratcheted to 0.25% above entry.

    BTC covers 0.5% in an hour routinely, so this turned every position that went green
    into a trade closed on the first quarter-percent pullback for +0.05% after fees. It
    also pre-empted the trailing stop, whose activation sits at 2 to 3%, which is why the
    per-regime trailing geometry the playbook computed never executed.

    Measured on 100 replayed decisions, pushing the ratchet out of reach cut stop exits
    from 10 to 5 and raised the share of hours actually holding a position by 70%.

    The whole suite of 202 tests passed throughout, because every one of them built plans
    through `resolve_plan` or `from_dict` and none asserted anything about the fields
    `apply` forgot. These tests assert the fields and the resulting behaviour instead.
    """

    def _engine(self, plan: ExecutionPlan) -> ProtectiveDecisionEngine:
        from dataclasses import replace as dc_replace

        engine = ProtectiveDecisionEngine(plan.apply(RealtimeParams()))
        engine.import_state(dc_replace(engine.state, execution_plan=plan.to_dict()))
        return engine

    def _long_at(self, engine: ProtectiveDecisionEngine, entry: str, high: str) -> None:
        from dataclasses import replace as dc_replace

        engine.import_state(
            dc_replace(engine.state, entry_price=D(entry), high_since_entry=D(high))
        )

    def _bull_plan(self) -> ExecutionPlan:
        return resolve_plan(
            regime=3, posture=Posture.AGRESIVA.value, conviction=0.85, daily_vol_pct=2.0
        )

    def test_apply_substitutes_the_break_even_pair(self) -> None:
        # The regression test for the actual defect. Every field `_active_stop` reads has
        # to come from the plan, or the plan is advisory.
        plan = self._bull_plan()
        applied = plan.apply(RealtimeParams())
        assert applied.break_even_activation_fraction == plan.break_even_activation_fraction
        assert applied.break_even_lock_fraction == plan.break_even_lock_fraction
        assert applied.break_even_activation_fraction != LEGACY_BREAK_EVEN_ACTIVATION

    def test_a_trend_trade_is_not_closed_by_a_quarter_percent_pullback(self) -> None:
        # The behaviour the regime 3 doctrine promises the agent: noise does not shake it
        # out of a trend. Under the old geometry the stop here was entry + 0.25%.
        plan = self._bull_plan()
        engine = self._engine(plan)
        self._long_at(engine, "80000", "80800")  # +1%, past the legacy activation
        stop = engine.active_stop(D("80800"))
        assert stop is not None
        assert stop < D("80000"), "a 1% gain must not lift the stop above the entry"
        assert stop == D("80000") * (D("1") - plan.stop_loss_fraction)

    def test_the_ratchet_still_engages_once_the_profit_is_material(self) -> None:
        # It is a backstop, not a scalper's leash. It must still exist.
        plan = self._bull_plan()
        engine = self._engine(plan)
        activation = D("1") + plan.break_even_activation_fraction
        self._long_at(engine, "80000", format(D("80000") * activation, "f"))
        stop = engine.active_stop(D("80000") * activation)
        assert stop is not None and stop > D("80000")

    @pytest.mark.parametrize("regime", [0, 1, 2, 3])
    @pytest.mark.parametrize("volatility", [0.5, 1.0, 2.0, 3.5, 6.0, 12.0])
    @pytest.mark.parametrize("posture", list(Posture))
    def test_the_floor_is_never_tighter_than_the_trail_already_is(
        self, regime: int, volatility: float, posture: Posture
    ) -> None:
        """The invariant that keeps the ratchet from becoming the exposure policy again.

        At the moment the ratchet engages the high sits at entry * (1 + activation), so the
        trailing stop is already at entry * (1 + activation) * (1 - trail). A floor above
        that is tighter than the trail, which is exactly how a 0.25% floor came to govern a
        strategy advertising a 5% stop. Checked against the CLAMPED numbers, because
        clamping is what breaks the relationship the multiples were chosen to satisfy.
        """
        plan = resolve_plan(
            regime=regime, posture=posture.value, conviction=0.7, daily_vol_pct=volatility
        )
        ceiling = (D("1") + plan.break_even_activation_fraction) * (
            D("1") - plan.trailing_stop_fraction
        ) - D("1")
        assert plan.break_even_lock_fraction <= ceiling

    def test_a_bull_regime_tolerates_more_give_back_than_a_bear(self) -> None:
        bull = resolve_plan(
            regime=3, posture=Posture.NEUTRAL.value, conviction=0.7, daily_vol_pct=2.0
        )
        bear = resolve_plan(
            regime=1, posture=Posture.NEUTRAL.value, conviction=0.7, daily_vol_pct=2.0
        )
        assert bull.break_even_activation_fraction > bear.break_even_activation_fraction

    def test_a_plan_persisted_before_this_change_keeps_its_original_geometry(self) -> None:
        """Loosening a stop underneath an open position is the costly direction of surprise.

        An older build persisted plans without these fields. Resolving absence to the new
        regime geometry would widen the stop on a position that was opened under the old
        one, so absence resolves to the legacy values instead.
        """
        raw = self._bull_plan().to_dict()
        del raw["break_even_activation_fraction"]
        del raw["break_even_lock_fraction"]
        restored = ExecutionPlan.from_dict(raw)
        assert restored.break_even_activation_fraction == LEGACY_BREAK_EVEN_ACTIVATION
        assert restored.break_even_lock_fraction == LEGACY_BREAK_EVEN_LOCK

    def test_the_pair_survives_a_round_trip_through_disk(self) -> None:
        import json

        plan = self._bull_plan()
        restored = ExecutionPlan.from_dict(json.loads(json.dumps(plan.to_dict())))
        assert restored == plan

    def test_the_agent_is_told_the_floor_it_is_actually_operating_under(self) -> None:
        # The prompt promised a wide stop while the engine ran a 0.25% leash. Whatever
        # governs the exit has to be visible to the thing being judged on the outcome.
        block = render_playbook_block(3, 2.0)
        assert "piso en +" in block


class TestTheTrailMatchesTheHorizonItProtects:
    """A unit error, not a tuning: the multiples are unchanged.

    A strategy declared how long it meant to hold and then measured its trailing exit
    against a SINGLE DAY's volatility, so the exit rule knew nothing about the horizon it
    was supposed to protect. 2.8 sigma means one thing over 24 hours and something else
    entirely over 168.

    Measured on 60 replayed bull-window decisions, once the break-even floor was fixed the
    daily-scaled leash became the binding constraint: 19 stop exits on 17 entries, a
    position open 50.6% of hours. Scaled to the horizon it is 7 exits and 81.0% of hours.
    """

    def test_a_one_day_horizon_is_unchanged_by_the_scaling(self) -> None:
        # The check that this follows from the declared horizons rather than from a window's
        # returns: the regime whose horizon is a single day must be untouched.
        assert PLAYBOOK[1].horizon_hours == 24
        plan = resolve_plan(regime=1, posture="NEUTRAL", conviction=0.5, daily_vol_pct=2.0)
        expected = PLAYBOOK[1].trail_vol_multiple * D("0.02")
        assert plan.trailing_stop_fraction == pytest.approx(expected)

    def test_a_longer_horizon_widens_the_leash_by_root_time(self) -> None:
        plan = resolve_plan(regime=2, posture="NEUTRAL", conviction=0.5, daily_vol_pct=2.0)
        # 96 hours is four days, so sqrt(4) = 2.
        expected = PLAYBOOK[2].trail_vol_multiple * D("0.02") * D("2")
        assert plan.trailing_stop_fraction == pytest.approx(expected)

    def test_a_trend_regime_tolerates_a_deeper_pullback_than_a_bear(self) -> None:
        bull = resolve_plan(regime=3, posture="NEUTRAL", conviction=0.5, daily_vol_pct=2.0)
        bear = resolve_plan(regime=1, posture="NEUTRAL", conviction=0.5, daily_vol_pct=2.0)
        assert bull.trailing_stop_fraction > bear.trailing_stop_fraction * 5

    def test_the_trend_leash_is_looser_than_its_own_initial_stop(self) -> None:
        """Which is what demotes the trail from strategy to insurance.

        With the leash tighter than the initial stop, the trail governed every exit in a
        regime whose whole doctrine is to hold through noise for 168 hours. Looser, the
        initial stop bounds the loss and the trail only takes over once the position is
        genuinely in profit.
        """
        plan = resolve_plan(regime=3, posture="NEUTRAL", conviction=0.5, daily_vol_pct=2.0)
        assert plan.trailing_stop_fraction > plan.stop_loss_fraction


class TestRiskIsDerivedNotACompetingKnob:
    """Three knobs for two degrees of freedom, and the third won silently.

    Sizing is `min(cash * allocation, equity * risk / stop)`. The risk ceiling was a fixed
    fraction of equity while the stop scales with volatility, so `risk / stop` FELL as
    volatility rose and cut the position hardest exactly when volatility expanded, which in
    a strong advance is most of the way up.

    Measured on the bull window run it overrode the declared allocation in 11 of 60
    decisions: day 1550 regime 2 asked for 75% and got 35%, day 1555 regime 3 asked for 90%
    and got 66%. Averaged over its 19 decisions regime 2 targeted 34.5% against a declared
    allocation of 65 to 75%.
    """

    def _effective_target(self, plan: ExecutionPlan) -> Decimal:
        """What size_entry_percentage will actually allow."""
        return min(
            plan.allocation_fraction, plan.risk_per_trade_fraction / plan.stop_loss_fraction
        )

    @pytest.mark.parametrize("regime", [0, 1, 2, 3])
    @pytest.mark.parametrize("volatility", [0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 12.0])
    @pytest.mark.parametrize("posture", list(Posture))
    def test_the_risk_cap_never_silently_overrides_the_allocation(
        self, regime: int, volatility: float, posture: Posture
    ) -> None:
        plan = resolve_plan(
            regime=regime, posture=posture.value, conviction=0.6, daily_vol_pct=volatility
        )
        assert self._effective_target(plan) == pytest.approx(plan.allocation_fraction)

    @pytest.mark.parametrize("volatility", [0.5, 2.0, 6.0, 12.0])
    def test_the_risk_taken_never_exceeds_the_regimes_ceiling(self, volatility: float) -> None:
        for regime, strategy in PLAYBOOK.items():
            for posture in Posture:
                plan = resolve_plan(
                    regime=regime,
                    posture=posture.value,
                    conviction=1.0,
                    daily_vol_pct=volatility,
                )
                ceiling = min(
                    strategy.risk_per_trade * _POSTURE_SIZE[posture], MAX_RISK_FRACTION
                )
                # MIN_RISK_FRACTION can lift a very small figure, which is a floor on the
                # recorded number rather than on the position, since the cap cannot bind
                # below the allocation in that direction.
                assert plan.risk_per_trade_fraction <= max(ceiling, MIN_RISK_FRACTION)

    def test_violent_volatility_reduces_the_allocation_visibly(self) -> None:
        # The behaviour that replaces the silent override: the ALLOCATION comes down, which
        # is the number recorded, displayed and shown to the agent.
        calm = resolve_plan(regime=3, posture="NEUTRAL", conviction=0.5, daily_vol_pct=2.0)
        violent = resolve_plan(regime=3, posture="NEUTRAL", conviction=0.5, daily_vol_pct=6.0)
        assert violent.allocation_fraction < calm.allocation_fraction
        assert self._effective_target(violent) == pytest.approx(violent.allocation_fraction)

    def test_ordinary_volatility_leaves_the_declared_allocation_intact(self) -> None:
        # A ceiling that binds in ordinary conditions is not a ceiling, it is the policy.
        for regime in (0, 1, 2, 3):
            plan = resolve_plan(
                regime=regime, posture="NEUTRAL", conviction=0.5, daily_vol_pct=2.0
            )
            expected = _clamp(
                PLAYBOOK[regime].allocation_at_neutral, MIN_ALLOCATION, MAX_ALLOCATION
            )
            assert plan.allocation_fraction == pytest.approx(expected)


class TestARegimeLabelHasToPersistBeforeItTakesEffect:
    """The burden of proof was anchored to a label that oscillates.

    Measured over 300 days at a 5 day step, the regime label changed on 37% of transitions
    and 31% of transitions INVERTED the default exposure, because regime 0 defaults to cash
    and regime 3 defaults to invested and the sequence alternates between them. Of 15
    direction changes in that run, 9 were imposed by the playbook AGAINST what the agent
    asked for: it wanted to be invested in regime 0 on 12 of 17 decisions and was forced to
    cash on 8 of them, then forced back in when the label returned to 3.

    The rule is not a tuned parameter: a new label has to persist for the horizon of the
    strategy it would replace, and those horizons are the ones each strategy already
    declares. A strategy is not abandoned faster than it said it meant to hold.
    """

    def _tracker(self, regime: int, at: datetime) -> RegimeTracker:
        return RegimeTracker(regime=1).observe(regime, at)

    def test_the_first_observation_takes_effect_immediately(self) -> None:
        tracker = RegimeTracker(regime=1).observe(3, NOW)
        assert tracker.regime == 3

    def test_a_single_contrary_reading_does_not_displace_a_trend(self) -> None:
        # Regime 3 declares a 168 hour horizon, so one 5 day reading of regime 0 is not
        # enough to abandon it. This is the exact oscillation that generated the round trips.
        tracker = self._tracker(3, NOW)
        tracker = tracker.observe(0, NOW + timedelta(days=5))
        assert tracker.regime == 3
        assert tracker.pending == 0
        tracker = tracker.observe(3, NOW + timedelta(days=10))
        assert tracker.regime == 3
        assert tracker.pending is None

    def test_a_persistent_change_does_take_effect(self) -> None:
        tracker = self._tracker(3, NOW)
        tracker = tracker.observe(0, NOW + timedelta(days=5))
        tracker = tracker.observe(0, NOW + timedelta(days=13))  # 8 days > 168 h
        assert tracker.regime == 0

    def test_leaving_the_deep_bear_is_immediate_by_comparison(self) -> None:
        """The asymmetry falls out of the horizons rather than being added on top.

        Regime 1's horizon is 24 hours, so its strategy is abandoned after a single day of a
        contrary label. Being slow to leave a trend and quick to leave a panic is the
        behaviour the horizons already describe.
        """
        tracker = self._tracker(1, NOW)
        tracker = tracker.observe(3, NOW + timedelta(hours=12))
        assert tracker.regime == 1, "aun no ha cumplido las 24 h"
        tracker = tracker.observe(3, NOW + timedelta(hours=40))
        assert tracker.regime == 3

    def test_an_alternating_label_never_displaces_the_regime_in_force(self) -> None:
        tracker = self._tracker(3, NOW)
        for step in range(1, 13):
            tracker = tracker.observe(0 if step % 2 else 3, NOW + timedelta(days=5 * step))
        assert tracker.regime == 3

    def test_an_unknown_label_leaves_the_regime_in_force(self) -> None:
        tracker = self._tracker(3, NOW)
        tracker = tracker.observe(None, NOW + timedelta(days=5))
        tracker = tracker.observe(99, NOW + timedelta(days=10))
        assert tracker.regime == 3

    def test_it_survives_a_restart(self) -> None:
        """Otherwise a restart resets the clock and the label flips freely again.

        Same reason execution_plan is persisted: the elapsed time a pending label has
        accumulated IS state, and losing it reinstates the behaviour this prevents.
        """
        import json

        tracker = self._tracker(3, NOW).observe(0, NOW + timedelta(days=5))
        restored = RegimeTracker.from_dict(json.loads(json.dumps(tracker.to_dict())))
        assert restored == tracker
        # And the pending label still cannot take effect early.
        assert restored.observe(0, NOW + timedelta(days=6)).regime == 3
        assert restored.observe(0, NOW + timedelta(days=14)).regime == 0

    def test_an_absent_checkpoint_starts_from_the_cautious_regime(self) -> None:
        assert RegimeTracker.from_dict(None).regime == 1
        assert RegimeTracker.from_dict({}).regime == 1

    def test_the_wait_is_the_horizon_of_the_strategy_being_left(self) -> None:
        # Stated as a property so a change to any horizon keeps this honest.
        for leaving, arriving in ((3, 0), (2, 1), (0, 3), (1, 2)):
            required = timedelta(hours=PLAYBOOK[leaving].horizon_hours)
            # The clock starts when the contrary label is FIRST seen, so the deadline is
            # measured from that moment and not from when the regime took effect.
            first_seen = NOW + timedelta(seconds=1)
            in_force = RegimeTracker(regime=1).observe(leaving, NOW)
            pending = in_force.observe(arriving, first_seen)
            assert pending.regime == leaving, (leaving, arriving)
            assert pending.observe(arriving, first_seen + required).regime == arriving
            assert (
                pending.observe(arriving, first_seen + required - timedelta(hours=1)).regime
                == leaving
            ), (leaving, arriving)


class TestADisagreementMovesTheSizeNotTheDirection:
    """The third attempt at the same question, after two binary answers both failed.

    The override let the regime REVERSE the agent. On 60 recorded decisions from a cautious
    agent that cost 39 points and nearly doubled the round trips. It was removed, and the run
    that followed came in worse: replaying THAT run's decisions with the override restored
    gives +90.93% against +61.18%. So the rule helped a confident agent and hurt a cautious
    one, which means neither answer generalises and picking between them on one window is
    fitting to the window.

    A disagreement now moves the size, weighted by the agent's own stated departure from
    indifference. No new parameter: the weight is 2 * (conviction - 0.5).
    """

    ALLOCATION = D("0.90")

    def _target(self, regime: int, wants_invested: bool, conviction: float) -> Decimal:
        target, _ = resolve_target_allocation(
            regime=regime,
            wants_invested=wants_invested,
            conviction=conviction,
            allocation=self.ALLOCATION,
        )
        return target

    def test_agreement_changes_nothing(self) -> None:
        # The common case has to be untouched, or this is a rewrite rather than a blend.
        assert self._target(3, True, 0.85) == self.ALLOCATION
        assert self._target(1, False, 0.55) == D("0")
        for conviction in (0.0, 0.5, 1.0):
            _, weight = resolve_target_allocation(
                regime=3,
                wants_invested=True,
                conviction=conviction,
                allocation=self.ALLOCATION,
            )
            assert weight == D("1")

    def test_indifference_cedes_to_the_regime(self) -> None:
        # 0.50 is the agent saying it does not know, so the regime's doctrine stands.
        assert self._target(3, False, 0.50) == self.ALLOCATION
        assert self._target(0, True, 0.50) == D("0")

    def test_total_conviction_carries_it_entirely(self) -> None:
        assert self._target(3, False, 1.0) == D("0")
        assert self._target(0, True, 1.0) == self.ALLOCATION

    def test_half_conviction_splits_the_difference(self) -> None:
        # 2 * (0.75 - 0.5) = 0.5
        assert self._target(3, False, 0.75) == self.ALLOCATION / 2

    def test_a_conviction_below_indifference_carries_no_weight(self) -> None:
        """Not abs(). The first version gave 0.40 the same weight as 0.60.

        A model less than half convinced of its own stated exposure must not move the book as
        much as one more than half convinced. Values under 0.5 appear in the record: 0.30,
        0.40 and 0.45 all occur.
        """
        for conviction in (0.0, 0.30, 0.40, 0.45, 0.50):
            assert self._target(3, False, conviction) == self.ALLOCATION
            _, weight = resolve_target_allocation(
                regime=3,
                wants_invested=False,
                conviction=conviction,
                allocation=self.ALLOCATION,
            )
            assert weight == D("0")

    @pytest.mark.parametrize("regime", [0, 1, 2, 3])
    @pytest.mark.parametrize("wants_invested", [True, False])
    @pytest.mark.parametrize("conviction", [0.0, 0.3, 0.5, 0.6, 0.75, 0.9, 1.0])
    def test_the_result_always_lies_between_the_two_views(
        self, regime: int, wants_invested: bool, conviction: float
    ) -> None:
        """Which is what makes it impossible for the blend to be worse than both extremes."""
        target = self._target(regime, wants_invested, conviction)
        assert D("0") <= target <= self.ALLOCATION

    def test_it_is_monotone_in_conviction(self) -> None:
        # More conviction must never move the book less toward what the agent asked for.
        previous = self._target(3, False, 0.0)
        for conviction in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
            current = self._target(3, False, conviction)
            assert current <= previous
            previous = current

    def test_a_regime_flip_now_costs_a_trim_instead_of_a_round_trip(self) -> None:
        """The original complaint about the override, measured as a property.

        The label oscillated between regime 3, whose default is invested, and regime 0, whose
        default is cash, on 31% of transitions. Under the override an agent asking to stay
        invested was emptied and refilled on every flip. Now the same flip trims.
        """
        invested_regime = self._target(3, True, 0.85)
        cash_regime = self._target(0, True, 0.85)
        assert invested_regime == self.ALLOCATION
        swing = invested_regime - cash_regime
        assert swing < self.ALLOCATION, "un giro de etiqueta ya no vacia la posicion"
        # And the swing is what the conviction says it should be: at 0.85 the agent carries
        # 0.70, so it keeps 70% of what it asked for.
        assert cash_regime == pytest.approx(self.ALLOCATION * D("0.70"))

    def test_the_agent_is_told_how_the_disagreement_resolves(self) -> None:
        # It cannot calibrate a mechanism it is not shown.
        block = render_playbook_block(3, 2.0)
        assert "a medio camino" in block
        assert "0.50 cede al regimen" in block


class TestAStrategyIsOnlyGrantedWhenItsDoctrineFits:
    """The eighth defect of the same shape: a doctrine in words, a label from a model.

    Regime 3's doctrine reads "tendencia alcista establecida" and its strategy is the largest
    allocation the playbook allows behind its widest stop. On the falling window the agent was
    exposed only 6% of the time and still lost 13.90%, and three quarters of that came from
    eight segments out of fifty-nine carrying that label: -10.39% at an effect of 1.3 standard
    errors, so not noise.

    In those eight the price averaged 6.4% BELOW its own 200-day average and seven of eight
    were below it. On the rising window the same label carried price 35.7% ABOVE that average,
    with two of thirty-four below. The label meant two different things, and in one of them the
    playbook handed a failing bounce its biggest position.

    The substitute is not chosen, it is the regime whose own description fits the observation.
    """

    def test_a_corroborated_label_is_left_alone(self) -> None:
        assert corroborated_regime(3, 35.7) == 3
        assert corroborated_regime(2, 19.1) == 2
        assert corroborated_regime(0, -12.7) == 0
        assert corroborated_regime(1, -24.0) == 1

    def test_a_strong_bull_below_its_own_average_is_not_an_established_uptrend(self) -> None:
        # The measured case: the mean of the eight losing segments.
        assert corroborated_regime(3, -6.4) == 0

    def test_a_consolidation_above_trend_below_the_average_is_not_above_trend(self) -> None:
        assert corroborated_regime(2, -5.0) == 0

    def test_a_below_average_regime_above_the_average_is_routed_up(self) -> None:
        # Symmetric, because the incoherence is symmetric. Regime 0 describes "lateral bajo la
        # media de 200d"; above it, the description that fits is regime 2.
        assert corroborated_regime(0, 4.2) == 2
        assert corroborated_regime(1, 10.0) == 2

    def test_the_substitute_is_never_the_most_extreme_strategy_of_its_side(self) -> None:
        """An uncorroborated label must not win a maximum allocation nor a minimum one.

        This is what makes the rule safe in both directions: regime 3's 90% and regime 1's
        20% are only ever granted when the price agrees with their doctrine.
        """
        for label in (0, 1, 2, 3):
            for reading in (-30.0, -6.4, -0.1, 0.1, 6.4, 40.0):
                resolved = corroborated_regime(label, reading)
                if resolved != label:
                    assert resolved in {TREND_SIDE_BELOW, TREND_SIDE_ABOVE}
                    assert resolved not in {1, 3}

    def test_the_resolved_regime_always_agrees_with_the_price(self) -> None:
        # The property the whole rule exists to guarantee, checked over a grid.
        for label in (0, 1, 2, 3):
            for reading in (-40.0, -12.7, -1.0, 1.0, 12.7, 35.7):
                resolved = corroborated_regime(label, reading)
                expects_above = resolved in {TREND_SIDE_ABOVE, 3}
                assert expects_above == (reading > 0.0), (label, reading, resolved)

    def test_a_missing_reading_leaves_the_classifier_alone(self) -> None:
        # No measurement is not evidence against the label.
        assert corroborated_regime(3, None) == 3
        assert corroborated_regime(1, None) == 1

    def test_an_unknown_label_still_falls_back_to_the_cautious_strategy(self) -> None:
        assert corroborated_regime(None, 10.0) == 1
        assert corroborated_regime(99, -10.0) == 1

    def test_it_would_have_removed_the_measured_loss_source(self) -> None:
        """The eight segments would have been sized as regime 0 rather than regime 3.

        Regime 0 defaults to cash, allocates a third as much and stops out three times
        sooner, which is what a bounce below the long-run average deserves.
        """
        bounce = strategy_for(corroborated_regime(3, -6.4))
        trend = strategy_for(3)
        # Exactly half as it happens, 45% against 90%, so the bound is inclusive.
        assert bounce.allocation_at_neutral <= trend.allocation_at_neutral / 2
        assert bounce.stop_vol_multiple < trend.stop_vol_multiple
        assert bounce.horizon_hours < trend.horizon_hours
        from btc_decision_agent.application.llm_tools import EXPOSURE_CASH

        assert bounce.default_exposure == EXPOSURE_CASH
