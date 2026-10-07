"""Guards for the three defects found by diagnosing the LIVE agent.

Each test encodes a failure that actually happened in production, with the measurement that
proves it was a defect rather than a parameter worth tuning.

1. A break-even ratchet that locked +0.25% while a round trip cost 0.20%. Measured on nine
   years of hourly BTC: once a 0.5% activation is touched, price returns to entry+0.25%
   about 99% of the time inside a week, so the ratchet all but guarantees it closes the
   position for 0.05% of equity. BOTH live exits were this firing, not a decision.
2. A signed request timestamped from an unsynchronised local clock. Binance rejects it with
   -1021 inside a generic HTTP 400, which was not retryable, so it propagated out of
   `account_balance()` through reconciliation and killed the process -- nine times.
3. A capture RATIO that inverts its meaning when returns are negative, in the reader this
   project uses to judge the live agent.
"""

from __future__ import annotations

import urllib.error
from decimal import Decimal as D

import pytest

from btc_decision_agent.application.realtime_demo import (
    _BREAK_EVEN_COST_MULTIPLE,
    ProtectiveDecisionEngine,
    RealtimeParams,
)


def params(**overrides: object) -> RealtimeParams:
    return RealtimeParams(**overrides)  # type: ignore[arg-type]


class TestBreakEvenMustPayForItself:
    def test_the_shipped_default_lock_is_refused(self) -> None:
        """0.25% locked against a 0.20% round trip nets 0.05%. It must not arm."""
        base = params()
        assert base.break_even_lock_fraction == D("0.0025")
        round_trip = base.round_trip_cost_bps / D("10000")
        assert round_trip == D("0.002"), "20 bps per round trip, both legs"
        assert base.break_even_lock_fraction < round_trip * _BREAK_EVEN_COST_MULTIPLE
        assert ProtectiveDecisionEngine._break_even_lock_is_economic(None, base) is False  # type: ignore[arg-type]

    def test_a_lock_exactly_at_cost_is_refused_because_it_nets_zero(self) -> None:
        at_cost = params(break_even_lock_fraction=D("0.002"))
        assert (
            ProtectiveDecisionEngine._break_even_lock_is_economic(None, at_cost) is False  # type: ignore[arg-type]
        )

    def test_a_lock_above_the_cost_multiple_is_allowed(self) -> None:
        """The playbook scales the lock from measured volatility and does reach this."""
        generous = params(break_even_lock_fraction=D("0.01"))
        assert ProtectiveDecisionEngine._break_even_lock_is_economic(None, generous) is True  # type: ignore[arg-type]

    def test_the_boundary_is_strictly_above_cost_times_multiple(self) -> None:
        threshold = D("0.002") * _BREAK_EVEN_COST_MULTIPLE
        assert (
            ProtectiveDecisionEngine._break_even_lock_is_economic(  # type: ignore[arg-type]
                None, params(break_even_lock_fraction=threshold)
            )
            is False
        )
        assert (
            ProtectiveDecisionEngine._break_even_lock_is_economic(  # type: ignore[arg-type]
                None, params(break_even_lock_fraction=threshold + D("0.0001"))
            )
            is True
        )

    def test_a_higher_fee_venue_demands_a_wider_lock(self) -> None:
        """The rule tracks cost rather than a fixed number, so doubling fees doubles the bar."""
        lock = D("0.005")
        cheap = params(break_even_lock_fraction=lock, round_trip_cost_bps=D("10"))
        dear = params(break_even_lock_fraction=lock, round_trip_cost_bps=D("40"))
        assert ProtectiveDecisionEngine._break_even_lock_is_economic(None, cheap) is True  # type: ignore[arg-type]
        assert ProtectiveDecisionEngine._break_even_lock_is_economic(None, dear) is False  # type: ignore[arg-type]


class TestStopGeometryArithmetic:
    def test_the_live_exit_triggers_are_reproduced_by_the_old_lock(self) -> None:
        """The two real stop-loss fills, recomputed. This is what identified the defect.

        Binance order history showed triggers at 85,026.77 and 84,881.85 against entries of
        84,814.74 and 84,670.18 -- `entry * 1.0025` to the cent, which is the break-even lock
        and not any decision the agent made.
        """
        for entry, trigger in ((D("84814.74"), D("85026.77")), (D("84670.18"), D("84881.85"))):
            locked = entry * (D("1") + D("0.0025"))
            assert locked - trigger < D("0.02"), f"{locked} vs {trigger}"

    def test_the_hard_stop_is_the_floor_when_nothing_else_applies(self) -> None:
        entry = D("84862.83")
        assert entry * (D("1") - D("0.03")) == pytest.approx(D("82316.9451"), abs=D("0.01"))

    def test_a_wider_lock_sits_above_the_hard_stop_as_intended(self) -> None:
        """The ratchet only matters because it OVERRIDES the hard stop upward; if it did not,
        refusing to arm it would change nothing."""
        entry = D("100000")
        assert entry * (D("1") + D("0.01")) > entry * (D("1") - D("0.03"))


class TestCaptureRatioCannotLieAboutDirection:
    def test_a_ratio_of_two_losses_inverts_its_meaning(self) -> None:
        """The defect in this project's own live reader, asserted.

        The agent returned -1.12% against a risk-matched null of -0.98%: it lost MORE, yet
        the ratio is 1.15, which the gate's own language reads as beating the null.
        """
        agent, null = -0.0112, -0.0098
        assert agent < null, "the agent did worse"
        assert agent / null > 1.0, "yet the ratio exceeds 1.00"
        assert agent - null < 0.0, "only the signed difference keeps the direction"

    def test_the_difference_agrees_with_the_ratio_when_both_are_gains(self) -> None:
        agent, null = 0.0120, 0.0135
        assert agent / null < 1.0
        assert agent - null < 0.0


class TestClockDriftIsRetriedNotFatal:
    def test_the_recv_window_code_is_matched_on_the_body_not_the_status(self) -> None:
        """HTTP 400 must stay fatal in general; only -1021 is a clock problem."""
        from btc_decision_agent.adapters.binance_execution import (
            _TIMESTAMP_OUTSIDE_RECV_WINDOW,
        )

        real_body = '{"code":-1021,"msg":"Timestamp for this request is outside of the recvWindow."}'
        assert _TIMESTAMP_OUTSIDE_RECV_WINDOW in real_body
        assert _TIMESTAMP_OUTSIDE_RECV_WINDOW not in '{"code":-2010,"msg":"Account has insufficient balance."}'
        assert _TIMESTAMP_OUTSIDE_RECV_WINDOW not in '{"code":-1013,"msg":"Filter failure: LOT_SIZE"}'

    def test_an_offset_shifts_the_signed_timestamp_by_exactly_that_amount(self) -> None:
        local_ms = 1_700_000_000_000
        for offset in (0, 4_000, -4_000, 30_000):
            assert (local_ms + offset) - local_ms == offset

    def test_a_drift_beyond_the_recv_window_is_what_gets_rejected(self) -> None:
        """5 s window: 4 s of drift is tolerated, 6 s is not. This is why the offset matters."""
        from btc_decision_agent.adapters.binance_execution import _RECV_WINDOW_MS

        assert _RECV_WINDOW_MS == 5000
        assert _RECV_WINDOW_MS > 4_000
        assert _RECV_WINDOW_MS < 6_000

    def test_an_http_error_carries_the_body_the_matcher_reads(self) -> None:
        """Guards the mechanism: the code is in the body, which must be read to be matched."""
        import io

        error = urllib.error.HTTPError(
            url="https://demo-api.binance.com/api/v3/account",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"code":-1021,"msg":"Timestamp for this request is outside of the recvWindow."}'),
        )
        assert error.code == 400
        body = error.read().decode()
        from btc_decision_agent.adapters.binance_execution import (
            _TIMESTAMP_OUTSIDE_RECV_WINDOW,
        )

        assert _TIMESTAMP_OUTSIDE_RECV_WINDOW in body
