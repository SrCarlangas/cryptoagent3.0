"""Guards for the out-of-sample validation of the stop geometry.

The module decides whether a change to the live agent's protective logic is adopted, so its
arithmetic is asserted rather than its formatting.

The first two tests are the ones that matter. `stop_for` must mirror the engine's own
`_active_stop` exactly -- a validation harness that models a DIFFERENT stop than production
measures a strategy nobody is running. And a stop must be tested against bar LOWS with the
adverse intrabar ordering, because checking closes would quietly let every stop be escaped.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from multislot_sim import Bar
from stop_geometry_validation import (
    FIXED,
    NOISE_WIDE,
    SHIPPED,
    Geometry,
    buy_and_hold,
    risk_matched,
    simulate,
)

from btc_decision_agent.application.realtime_demo import (
    ProtectiveDecisionEngine,
    RealtimeParams,
)


def bars_from(prices: list[tuple[float, float, float]]) -> list[Bar]:
    """(high, low, close) per bar."""
    return [
        Bar(
            open_time_ms=index * 3_600_000,
            open=close,
            high=high,
            low=low,
            close=close,
            contiguous_run=index + 1,
        )
        for index, (high, low, close) in enumerate(prices)
    ]


class TestHarnessMirrorsProduction:
    @pytest.mark.parametrize(
        ("hard", "trail", "trail_act", "be_act", "be_lock"),
        [
            (0.03, 0.025, 0.01, 0.005, 0.0025),
            (0.03, 0.025, 0.01, 0.015, 0.01),
            (0.10, 0.08, 0.05, 0.02, 0.0),
            (0.05, 0.04, 0.02, 0.03, 0.02),
        ],
    )
    def test_stop_for_equals_the_engines_active_stop(
        self, hard: float, trail: float, trail_act: float, be_act: float, be_lock: float
    ) -> None:
        """The harness and the engine must agree to the cent at every geometry.

        The engine REFUSES an uneconomic break-even lock, so the harness models that by
        setting the lock to zero in the fixed geometry. Where the lock is economic both must
        apply it; where it is not, neither may.
        """
        from dataclasses import replace as dc_replace

        engine_lock = D(str(be_lock))
        params = RealtimeParams(
            stop_loss_fraction=D(str(hard)),
            trailing_stop_fraction=D(str(trail)),
            trailing_activation_fraction=D(str(trail_act)),
            break_even_activation_fraction=D(str(be_act)),
            break_even_lock_fraction=engine_lock if engine_lock > 0 else D("0.0025"),
        )
        economic = ProtectiveDecisionEngine._break_even_lock_is_economic(None, params)  # type: ignore[arg-type]
        harness = Geometry(
            "t", hard, trail, trail_act, be_act, be_lock if economic and be_lock > 0 else 0.0
        )
        engine = ProtectiveDecisionEngine(params)

        for entry, high in ((80_000.0, 80_000.0), (80_000.0, 80_400.0), (80_000.0, 88_000.0)):
            engine.import_state(
                dc_replace(
                    engine.state, entry_price=D(str(entry)), high_since_entry=D(str(high))
                )
            )
            produced = engine.active_stop(D(str(high)))
            assert produced is not None
            assert float(produced) == pytest.approx(harness.stop_for(entry, high), rel=1e-9)


class TestStopIsTestedAdversely:
    def test_a_bar_that_dips_to_the_stop_exits_even_if_it_also_makes_a_new_high(self) -> None:
        """Hourly bars cannot order intrabar events, so the adverse reading is mandatory.

        Entry 100, hard stop 10% -> 90. The second bar reaches 130 but also dips to 89. It
        must count as a stop; crediting the high would fabricate return that no real order
        could have captured.
        """
        geometry = Geometry("adverse", 0.10, 0.50, 0.90, 0.90, 0.0)
        bars = bars_from([(100.0, 100.0, 100.0), (130.0, 89.0, 125.0), (126.0, 124.0, 125.0)])
        outcome = simulate(bars, geometry)
        assert outcome.stopped_out == 1
        assert outcome.net_return_pct < 0.0

    def test_a_bar_that_never_reaches_the_stop_does_not_exit(self) -> None:
        geometry = Geometry("safe", 0.10, 0.50, 0.90, 0.90, 0.0)
        bars = bars_from([(100.0, 100.0, 100.0), (105.0, 99.0, 104.0), (106.0, 103.0, 105.0)])
        outcome = simulate(bars, geometry)
        assert outcome.stopped_out == 0


class TestFeesAndNulls:
    def test_both_legs_are_charged(self) -> None:
        """A flat market must LOSE exactly the round trip, never break even."""
        geometry = Geometry("flat", 0.50, 0.90, 0.95, 0.95, 0.0)
        flat = bars_from([(100.0, 100.0, 100.0)] * 40)
        outcome = simulate(flat, geometry)
        assert outcome.net_return_pct < 0.0
        assert outcome.fees_paid_pct == pytest.approx(0.2, abs=1e-9)

    def test_buy_and_hold_charges_entry_and_exit(self) -> None:
        doubling = bars_from([(100.0, 100.0, 100.0), (200.0, 100.0, 200.0)])
        result, _drawdown = buy_and_hold(doubling)
        expected = (2.0 * (1.0 - 0.001) * (1.0 - 0.001) - 1.0) * 100.0
        assert result == pytest.approx(expected, rel=1e-9)

    def test_risk_matched_null_scales_down_but_never_leverages_up(self) -> None:
        assert risk_matched(100.0, 80.0, 40.0) == pytest.approx(50.0)
        assert risk_matched(100.0, 80.0, 80.0) == pytest.approx(100.0)
        assert risk_matched(100.0, 20.0, 80.0) == pytest.approx(100.0), (
            "an agent riskier than buy and hold must not be handed a leveraged benchmark"
        )

    def test_a_zero_drawdown_null_is_not_divided_by_zero(self) -> None:
        assert risk_matched(5.0, 0.0, 0.0) == pytest.approx(5.0)


class TestTheGeometriesUnderTest:
    def test_the_shipped_geometry_carries_the_defective_lock(self) -> None:
        assert SHIPPED.break_even_lock == 0.0025

    def test_the_fixed_geometry_disarms_it(self) -> None:
        assert FIXED.break_even_lock == 0.0
        assert FIXED.hard_stop == SHIPPED.hard_stop, "only the lock changes"
        assert FIXED.trailing == SHIPPED.trailing

    def test_the_noise_sized_geometry_is_wider_than_measured_daily_volatility(self) -> None:
        """Measured on 79,477 hourly bars (`research/stop_noise_sizing.py`).

        The precise claim, corrected from a looser one: the shipped 2.5% trail is NOT below
        every year's daily volatility -- the calmest year, 2023, came in at 2.23%. What it is
        below is the MEDIAN 24-hour maximum adverse excursion of 2.85%, which is the number
        that decides whether a stop is hit by noise. Half of all 24-hour windows retrace
        further than the shipped trail, and 57% retrace past it at some point.
        """
        median_24h_excursion = 0.0285
        assert SHIPPED.trailing < median_24h_excursion, (
            "the shipped trail sits inside the median one-day retracement"
        )
        # The hard stop is 3%, just ABOVE the 2.85% one-day median -- so the damning number
        # for it is not the daily median but the weekly touch probability: 96.25% of 7-day
        # windows retrace at least 3%, and 100% of 30-day windows do.
        median_7d_excursion = 0.0776
        assert SHIPPED.hard_stop < median_7d_excursion, (
            "a 3% stop is far inside the median one-week retracement of 7.76%"
        )
        assert NOISE_WIDE.trailing > 0.0763, "wider than the most volatile year measured"
        assert NOISE_WIDE.hard_stop >= 0.08, (
            "a 7-day noise touch probability below 50% needs at least 8%"
        )
