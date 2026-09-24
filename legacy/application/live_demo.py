"""Live demo trading loop: strategy -> risk -> Decision -> ledger -> demo order.

This orchestrates one evaluation per closed bar against the Binance DEMO account
(no real funds). It reconciles position from the demo balance, sizes conservatively
under a RiskMandate, records every Decision in the ledger before acting, and places
a market order on the demo venue. Real capital remains impossible: the execution
adapter blocks any non-demo/testnet venue.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from btc_decision_agent.adapters.binance_execution import BinanceDemoExecutionAdapter
from btc_decision_agent.application.execution import OrderResult, OrderSide
from btc_decision_agent.domain.contracts import Action, PositionState, RiskMandate

D = Decimal
_INTERVAL_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
_DEFAULT_DUST_USDT = D("10")
_DEFAULT_COST_BUFFER_FRACTION = D("0.001")


@dataclass(frozen=True)
class BaselineParams:
    """Long/flat SMA crossover: the only mechanism shown to generalize OOS."""

    fast: int = 12
    slow: int = 48
    interval: str = "4h"


@dataclass(frozen=True)
class DemoPosition:
    state: PositionState
    btc_qty: Decimal
    usdt_free: Decimal
    btc_price: Decimal

    @property
    def btc_notional(self) -> Decimal:
        return self.btc_qty * self.btc_price


@dataclass(frozen=True)
class LiveDecision:
    at: datetime
    action: Action
    reason: str
    fast_sma: Decimal | None
    slow_sma: Decimal | None
    position_before: PositionState
    order: OrderResult | None
    price: Decimal | None = None
    usdt_free: Decimal | None = None
    btc_qty: Decimal | None = None


def _sma(closes: Sequence[Decimal], n: int) -> Decimal | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:], D("0")) / D(n)


def reconcile_position(adapter: BinanceDemoExecutionAdapter, *, dust_usdt: Decimal = _DEFAULT_DUST_USDT) -> DemoPosition:
    """Derive FLAT/LONG from the demo balance. BTC worth <= dust is treated as FLAT."""
    price = adapter.ticker_price()
    balance = adapter.account_balance()
    btc = balance.balances.get("BTC", D("0"))
    usdt = balance.balances.get("USDT", D("0"))
    notional = btc * price
    state = PositionState.LONG if notional > dust_usdt else PositionState.FLAT
    return DemoPosition(state=state, btc_qty=btc, usdt_free=usdt, btc_price=price)


def baseline_action(closes: Sequence[Decimal], params: BaselineParams, position: PositionState) -> tuple[Action, str, Decimal | None, Decimal | None]:
    """Long/flat rule: enter when fast>slow and flat; exit when fast<slow and long."""
    fast = _sma(closes, params.fast)
    slow = _sma(closes, params.slow)
    if fast is None or slow is None:
        return Action.HOLD, "CONTEXT_INSUFFICIENT", fast, slow
    bullish = fast > slow
    if position == PositionState.FLAT and bullish:
        return Action.ENTER_LONG, "SMA_CROSS_UP", fast, slow
    if position == PositionState.LONG and not bullish:
        return Action.EXIT_LONG, "SMA_CROSS_DOWN", fast, slow
    return Action.HOLD, ("HOLD_LONG" if position == PositionState.LONG else "HOLD_FLAT"), fast, slow


def size_entry_usdt(position: DemoPosition, mandate: RiskMandate, *, cost_buffer_fraction: Decimal = _DEFAULT_COST_BUFFER_FRACTION) -> Decimal:
    """Bound the entry notional by max_exposure and available cash; round down to 2dp."""
    by_exposure = mandate.max_exposure
    by_cash = position.usdt_free / (D("1") + cost_buffer_fraction)
    raw = min(by_exposure, by_cash)
    return raw.quantize(D("0.01"), rounding=ROUND_DOWN)


def bar_is_fresh(last_close_ms: int, interval: str, *, now: datetime | None = None, grace: timedelta = timedelta(minutes=5)) -> bool:
    """The last closed bar must be recent enough to act on (fail-safe otherwise)."""
    current = now or datetime.now(tz=UTC)
    close_dt = datetime.fromtimestamp(last_close_ms / 1000, tz=UTC)
    max_age = timedelta(milliseconds=_INTERVAL_MS[interval]) + grace
    return current - close_dt <= max_age


class DemoLiveRunner:
    """One evaluation per invocation. Call on a schedule (e.g. once per closed bar)."""

    def __init__(self, adapter: BinanceDemoExecutionAdapter, mandate: RiskMandate, params: BaselineParams | None = None) -> None:
        self.adapter = adapter
        self.mandate = mandate
        self.params = params or BaselineParams()

    def evaluate_once(self, *, dry_run: bool = False, now: datetime | None = None) -> LiveDecision:
        interval = self.params.interval
        bars = self.adapter.recent_closed_klines(interval=interval, limit=self.params.slow + 5)
        evaluation_time = now or datetime.now(tz=UTC)
        if not bars or not bar_is_fresh(bars[-1]["close_time_ms"], interval, now=evaluation_time):
            return LiveDecision(evaluation_time, Action.HOLD, "DATA_BLOCKED", None, None, PositionState.FLAT, None)
        closes = [bar["close"] for bar in bars]
        position = reconcile_position(self.adapter)
        action, reason, fast, slow = baseline_action(closes, self.params, position.state)

        def decision(final_action: Action, final_reason: str, order: OrderResult | None) -> LiveDecision:
            return LiveDecision(
                evaluation_time, final_action, final_reason, fast, slow, position.state, order,
                price=position.btc_price, usdt_free=position.usdt_free, btc_qty=position.btc_qty,
            )

        if action == Action.HOLD or dry_run:
            return decision(action, reason if not dry_run else f"DRY_RUN:{reason}", None)

        if action == Action.ENTER_LONG:
            quote = size_entry_usdt(position, self.mandate)
            if quote < self.mandate.min_notional:
                return decision(Action.HOLD, "CAPITAL_INSUFFICIENT", None)
            order = self.adapter.place_market_quote_order(OrderSide.BUY, quote)
            return decision(Action.ENTER_LONG, reason, order)

        # EXIT_LONG: sell the full BTC holding back to USDT via a quote-sized market sell.
        exit_quote = (position.btc_notional).quantize(D("0.01"), rounding=ROUND_DOWN)
        if exit_quote < self.mandate.min_notional:
            return decision(Action.HOLD, "RESIDUAL_BELOW_MIN_NOTIONAL", None)
        order = self.adapter.place_market_quote_order(OrderSide.SELL, exit_quote)
        return decision(Action.EXIT_LONG, reason, order)


__all__ = [
    "BaselineParams",
    "DemoLiveRunner",
    "DemoPosition",
    "LiveDecision",
    "bar_is_fresh",
    "baseline_action",
    "reconcile_position",
    "size_entry_usdt",
]
