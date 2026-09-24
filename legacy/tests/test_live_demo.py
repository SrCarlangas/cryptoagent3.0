"""Tests for the demo live runner using a fake adapter (no network, no orders)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from btc_decision_agent.application.live_demo import (
    BaselineParams,
    DemoLiveRunner,
    bar_is_fresh,
    baseline_action,
    reconcile_position,
    size_entry_usdt,
)

from btc_decision_agent.application.execution import ExecutionVenue, OrderResult, OrderSide
from btc_decision_agent.domain.contracts import Action, PositionState, RiskMandate

D = Decimal
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def mandate(max_exposure: str = "1000") -> RiskMandate:
    return RiskMandate(
        version="demo/1", authored_by="op", authored_at=NOW - timedelta(days=1),
        capital=D(max_exposure) * D("10"), risk_per_decision=D("0.0025"), max_exposure=D(max_exposure),
        daily_loss_max=D(max_exposure), drawdown_max=D(max_exposure) * D("2"), min_notional=D("10"),
        step_size=D("0.00001"), valid_from=NOW - timedelta(days=1), valid_until=NOW + timedelta(days=365),
    )


class FakeAdapter:
    def __init__(self, closes: list[str], *, btc: str, usdt: str, price: str, interval: str = "4h") -> None:
        self._closes = [D(c) for c in closes]
        self._btc, self._usdt, self._price = D(btc), D(usdt), D(price)
        self._interval = interval
        self.orders: list[tuple[OrderSide, Decimal]] = []

    def venue(self) -> ExecutionVenue:
        return ExecutionVenue.DEMO

    def ticker_price(self, symbol: str = "BTCUSDT") -> Decimal:
        return self._price

    def account_balance(self):
        from btc_decision_agent.application.execution import AccountBalance
        return AccountBalance(balances={"BTC": self._btc, "USDT": self._usdt})

    def recent_closed_klines(self, *, interval: str = "1h", limit: int = 200, symbol: str = "BTCUSDT"):
        step = timedelta(hours=4)
        bars = []
        for i, close in enumerate(self._closes):
            open_dt = NOW - step * (len(self._closes) - i)
            close_dt = open_dt + step
            bars.append({
                "open_time_ms": int(open_dt.timestamp() * 1000),
                "close_time_ms": int(close_dt.timestamp() * 1000),
                "open": close, "high": close, "low": close, "close": close, "base_volume": D("1"),
            })
        return bars

    def place_market_quote_order(self, side: OrderSide, quote_usdt: Decimal, symbol: str = "BTCUSDT") -> OrderResult:
        self.orders.append((side, quote_usdt))
        base = quote_usdt / self._price
        return OrderResult(ExecutionVenue.DEMO, "fake-1", side, quote_usdt, base, self._price, D("0"), 1, "FILLED")


def test_reconcile_flat_vs_long() -> None:
    flat = FakeAdapter(["100"], btc="0.00005", usdt="1000", price="75000")  # 3.75 USDT dust -> FLAT
    long_ = FakeAdapter(["100"], btc="0.02", usdt="10", price="75000")      # 1500 USDT -> LONG
    assert reconcile_position(flat).state == PositionState.FLAT  # type: ignore[arg-type]
    assert reconcile_position(long_).state == PositionState.LONG  # type: ignore[arg-type]


def test_baseline_action_enter_hold_exit() -> None:
    up = [str(v) for v in range(100, 160)]  # rising -> fast>slow
    down = [str(v) for v in range(160, 100, -1)]  # falling -> fast<slow
    params = BaselineParams(12, 48, "4h")
    assert baseline_action([D(c) for c in up], params, PositionState.FLAT)[0] == Action.ENTER_LONG
    assert baseline_action([D(c) for c in up], params, PositionState.LONG)[0] == Action.HOLD
    assert baseline_action([D(c) for c in down], params, PositionState.LONG)[0] == Action.EXIT_LONG
    assert baseline_action([D(c) for c in down], params, PositionState.FLAT)[0] == Action.HOLD


def test_size_entry_bounded_by_exposure_and_cash() -> None:
    from btc_decision_agent.application.live_demo import DemoPosition
    rich = DemoPosition(PositionState.FLAT, D("0"), D("100000"), D("75000"))
    poor = DemoPosition(PositionState.FLAT, D("0"), D("500"), D("75000"))
    assert size_entry_usdt(rich, mandate("1000")) == D("1000.00")   # capped by exposure
    assert size_entry_usdt(poor, mandate("1000")) <= D("500")        # capped by cash


def test_bar_freshness_guard() -> None:
    fresh_ms = int((NOW - timedelta(hours=1)).timestamp() * 1000)
    stale_ms = int((NOW - timedelta(days=3)).timestamp() * 1000)
    assert bar_is_fresh(fresh_ms, "4h", now=NOW) is True
    assert bar_is_fresh(stale_ms, "4h", now=NOW) is False


def test_runner_enters_when_flat_and_bullish() -> None:
    up = [str(v) for v in range(100, 160)]
    adapter = FakeAdapter(up, btc="0", usdt="5000", price="150")
    runner = DemoLiveRunner(adapter, mandate("1000"), BaselineParams(12, 48, "4h"))  # type: ignore[arg-type]
    decision = runner.evaluate_once(now=NOW)
    assert decision.action == Action.ENTER_LONG
    assert adapter.orders and adapter.orders[0][0] == OrderSide.BUY
    assert adapter.orders[0][1] <= D("1000")


def test_runner_dry_run_places_no_order() -> None:
    up = [str(v) for v in range(100, 160)]
    adapter = FakeAdapter(up, btc="0", usdt="5000", price="150")
    runner = DemoLiveRunner(adapter, mandate("1000"), BaselineParams(12, 48, "4h"))  # type: ignore[arg-type]
    decision = runner.evaluate_once(dry_run=True, now=NOW)
    assert decision.action == Action.ENTER_LONG
    assert adapter.orders == []


def test_runner_exits_when_long_and_bearish() -> None:
    down = [str(v) for v in range(160, 100, -1)]
    adapter = FakeAdapter(down, btc="10", usdt="10", price="130")  # 1300 USDT notional -> LONG
    runner = DemoLiveRunner(adapter, mandate("1000"), BaselineParams(12, 48, "4h"))  # type: ignore[arg-type]
    decision = runner.evaluate_once(now=NOW)
    assert decision.action == Action.EXIT_LONG
    assert adapter.orders and adapter.orders[0][0] == OrderSide.SELL
