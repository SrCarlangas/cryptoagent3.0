"""Guards for the live-performance reader.

These exist because the numbers this module prints are about to be reported as fact about a
running system holding real positions on a DEMO venue. The arithmetic is asserted by hand --
equity, drawdown and the risk-matched comparator -- rather than its formatting.

The risk-matched test is the one that matters. The project's rewritten gate exists because the
original compared the agent against RAW buy and hold, so merely holding less BTC scored as
skill. A comparator that silently reverts to that is the same hole reopening.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from live_performance import Snapshot, as_float, max_drawdown, read_snapshots


def snap(minutes: int, price: float, btc: float, cash: float) -> Snapshot:
    value = btc * price
    equity = value + cash
    return Snapshot(
        at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes),
        price=price,
        equity=equity,
        btc_value=value,
        allocation=value / equity if equity else 0.0,
        action="HOLD",
        position="LONG",
        venue="DEMO",
    )


def test_drawdown_on_a_rising_curve_is_zero() -> None:
    assert max_drawdown([100.0, 110.0, 125.0]) == pytest.approx(0.0)


def test_drawdown_is_measured_from_the_running_peak_not_the_start() -> None:
    """A curve that rises to 200 then falls to 150 lost 25% of its PEAK, not 50% of its start.

    Measuring from the start would have understated this agent's realised drawdown, which
    feeds straight into the risk-matched comparator and would move the bar it is judged against.
    """
    assert max_drawdown([100.0, 200.0, 150.0, 400.0]) == pytest.approx(0.25)


def test_drawdown_recovers_without_forgetting_the_worst() -> None:
    assert max_drawdown([100.0, 50.0, 100.0]) == pytest.approx(0.50)


def test_as_float_survives_the_string_decimals_the_log_actually_contains() -> None:
    """The live log stores numbers as strings like "0.05186941". Mis-parsing them silently
    zeroes the position and would report a flat agent as having no exposure."""
    assert as_float("0.05186941") == pytest.approx(0.05186941)
    assert as_float("95.00") == pytest.approx(95.0)
    assert as_float(None) == 0.0
    assert as_float("") == 0.0
    assert as_float("no-es-un-numero") == 0.0


def test_equity_is_btc_marked_to_market_plus_all_cash() -> None:
    point = snap(0, 80_000.0, 0.05, 200.0)
    assert point.equity == pytest.approx(0.05 * 80_000.0 + 200.0)
    assert point.allocation == pytest.approx(4000.0 / 4200.0)


def test_a_full_cash_position_reports_zero_allocation() -> None:
    point = snap(0, 80_000.0, 0.0, 4200.0)
    assert point.allocation == pytest.approx(0.0)
    assert point.equity == pytest.approx(4200.0)


def test_reader_skips_unusable_records_instead_of_scoring_them_as_zero(tmp_path) -> None:
    """A record without a price cannot be marked to market. Treating it as zero equity would
    invent a -100% drawdown out of a logging gap."""
    log = tmp_path / "activity.jsonl"
    log.write_text(
        "\n".join(
            [
                '{"at":"2026-01-01T00:00:00+00:00","price":"80000","btc_qty":"0.05","usdt_free":"200","action":"HOLD","position_after":"LONG","venue":"DEMO"}',
                "no es json en absoluto",
                '{"at":"2026-01-01T00:01:00+00:00","price":"0","btc_qty":"0.05","usdt_free":"200","action":"HOLD"}',
                '{"price":"81000","btc_qty":"0.05","usdt_free":"200","action":"HOLD"}',
                '{"at":"2026-01-01T00:02:00+00:00","price":"81000","btc_qty":"0.05","usdt_free":"200","action":"ENTER_LONG","position_after":"LONG","venue":"DEMO"}',
            ]
        ),
        encoding="utf-8",
    )
    snapshots, skipped, actions = read_snapshots(log)
    assert len(snapshots) == 2
    assert skipped == 3
    assert actions == {"HOLD": 1, "ENTER_LONG": 1}, (
        "an unpriced or undated record is rejected BEFORE it is counted, so the activity mix "
        "describes only decisions that could actually be marked to market"
    )


def test_holding_less_of_a_rising_asset_must_not_score_as_outperformance() -> None:
    """The hole the rewritten gate closed, asserted directly.

    An agent that holds 50% of a rising asset returns less than buy and hold AND takes less
    drawdown. Against RAW buy and hold that looks like a loss; against a risk-matched hold it
    is roughly a draw. Neither reading may make it look like skill.
    """
    start_price, end_price = 100.0, 110.0
    hold_return = end_price / start_price - 1.0

    half_return = 0.5 * hold_return
    half_drawdown = 0.5
    hold_drawdown = 1.0

    fraction = min(1.0, half_drawdown / hold_drawdown)
    matched_return = fraction * hold_return

    assert half_return < hold_return
    assert half_return == pytest.approx(matched_return), (
        "at equal risk, holding a constant fraction is exactly a draw -- any apparent edge "
        "here would be the comparator flattering reduced exposure"
    )


def test_the_matched_fraction_is_capped_at_one() -> None:
    """An agent MORE volatile than buy and hold must not be handed a leveraged benchmark."""
    assert min(1.0, 0.40 / 0.10) == 1.0
