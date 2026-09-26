"""The live order path, which had no tests at all while it placed real orders.

Why this file exists
--------------------
`RealtimeDemoRunner.process_event` decides the size of every order the account places,
cancels and re-places the exchange-side protective stop, and writes the intent ledger that
makes a retry safe. Nothing in the suite instantiated it. The engine-side accounting for
scaling was pinned (`on_fill` top-up, trim and exit), and `plan_adjustment` was pinned, but
the code joining them to the exchange was not.

That mattered immediately, because position scaling existed in the backtest and not in the
live path. Replaying the same 60 bull-window decisions with scaling gives +28.45% and
without it +5.91%, so every number used to judge the agent described a system that was not
deployed. Wiring it in changes order sizing and the protective stop lifecycle, which is
precisely the code that should not be changed blind.

The fake adapter below is deliberately simple but it does hold real invariants: balances
move on fills, orders are recorded, and a stop order cannot be placed for more than the
position. It is not a Binance simulator and does not pretend to be one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from btc_decision_agent.application.execution import (
    AccountBalance,
    ExchangeOrder,
    ExecutionVenue,
    OrderResult,
    OrderSide,
    SymbolTradingRules,
)
from btc_decision_agent.application.realtime_demo import (
    EvidenceSnapshot,
    ProtectiveDecisionEngine,
    RealtimeDecision,
    RealtimeDemoRunner,
    RealtimeParams,
    deterministic_client_order_id,
)
from btc_decision_agent.application.regime_playbook import resolve_plan
from btc_decision_agent.domain.contracts import Action, PositionState
from btc_decision_agent.observability.journal import ActivityJournal

D = Decimal
NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
PRICE = D("80000")


@dataclass
class FakeAdapter:
    """Minimal account that moves balances on fills and remembers its orders."""

    usdt: Decimal = field(default_factory=lambda: D("10000"))
    btc: Decimal = field(default_factory=lambda: D("0"))
    price: Decimal = PRICE
    orders: list[OrderResult] = field(default_factory=list)
    resting: list[ExchangeOrder] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    reject_market: bool = False
    _sequence: int = 0

    def ticker_price(self, symbol: str = "BTCUSDT") -> Decimal:
        return self.price

    def account_balance(self) -> AccountBalance:
        # BTC committed to a resting stop order shows as locked, exactly as it does live.
        locked = sum((order.original_base_qty for order in self.resting), D("0"))
        return AccountBalance(
            balances={"USDT": self.usdt, "BTC": max(D("0"), self.btc - locked)},
            locked_balances={"BTC": min(locked, self.btc)},
        )

    def symbol_rules(self, symbol: str = "BTCUSDT") -> SymbolTradingRules:
        return SymbolTradingRules(
            symbol="BTCUSDT",
            status="TRADING",
            base_asset="BTC",
            quote_asset="USDT",
            tick_size=D("0.01"),
            lot_step_size=D("0.00001"),
            market_step_size=D("0.00001"),
            min_quantity=D("0.00001"),
            max_quantity=D("1000"),
            min_notional=D("10"),
            max_notional=None,
            market_quote_allowed=True,
            stop_loss_allowed=True,
        )

    def open_orders(self, symbol: str = "BTCUSDT") -> tuple[ExchangeOrder, ...]:
        return tuple(self.resting)

    def recent_trades(self, symbol: str = "BTCUSDT", *, limit: int = 100) -> tuple[()]:
        return ()

    def get_order_by_client_id(
        self, client_order_id: str, symbol: str = "BTCUSDT"
    ) -> ExchangeOrder | None:
        return next(
            (order for order in self.resting if order.client_order_id == client_order_id), None
        )

    def cancel_order(self, exchange_order_id: str, symbol: str = "BTCUSDT") -> ExchangeOrder:
        found = next(order for order in self.resting if order.exchange_order_id == exchange_order_id)
        self.resting = [order for order in self.resting if order is not found]
        self.cancelled.append(exchange_order_id)
        return replace(found, status="CANCELED")

    def place_stop_loss_base_order(
        self,
        base_quantity: Decimal,
        stop_price: Decimal,
        symbol: str = "BTCUSDT",
        *,
        client_order_id: str,
    ) -> ExchangeOrder:
        assert base_quantity <= self.btc, "un stop no puede cubrir mas de lo que hay"
        self._sequence += 1
        order = ExchangeOrder(
            exchange_order_id=f"stop-{self._sequence}",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type="STOP_LOSS",
            status="NEW",
            original_base_qty=base_quantity,
            executed_base_qty=D("0"),
            price=D("0"),
            stop_price=stop_price,
            update_time_ms=0,
        )
        self.resting.append(order)
        return order

    def recent_closed_klines(
        self, *, interval: str = "1h", limit: int = 200, symbol: str = "BTCUSDT"
    ) -> list[dict[str, object]]:
        return []

    def _fill(self, side: OrderSide, base: Decimal, client_order_id: str | None) -> OrderResult:
        self._sequence += 1
        quote = (base * self.price).quantize(D("0.01"))
        if side == OrderSide.BUY:
            self.usdt -= quote
            self.btc += base
        else:
            self.usdt += quote
            self.btc -= base
        result = OrderResult(
            venue=ExecutionVenue.DEMO,
            exchange_order_id=f"ord-{self._sequence}",
            side=side,
            executed_quote_usdt=quote,
            executed_base_qty=base,
            average_price=self.price,
            fees_usdt=D("0"),
            transact_time_ms=0,
            raw_status="REJECTED" if self.reject_market else "FILLED",
            client_order_id=client_order_id,
        )
        if self.reject_market:
            # Undo: a rejected order moves nothing.
            if side == OrderSide.BUY:
                self.usdt += quote
                self.btc -= base
            else:
                self.usdt -= quote
                self.btc += base
        self.orders.append(result)
        return result

    def place_market_quote_order(
        self,
        side: OrderSide,
        quote_usdt: Decimal,
        symbol: str = "BTCUSDT",
        *,
        client_order_id: str | None = None,
    ) -> OrderResult:
        return self._fill(side, quote_usdt / self.price, client_order_id)

    def place_market_base_order(
        self,
        side: OrderSide,
        base_quantity: Decimal,
        symbol: str = "BTCUSDT",
        *,
        client_order_id: str | None = None,
    ) -> OrderResult:
        return self._fill(side, base_quantity, client_order_id)


class ScriptedEngine(ProtectiveDecisionEngine):
    """Returns a prepared decision, so the runner is what is under test."""

    def __init__(self, params: RealtimeParams, decision: RealtimeDecision) -> None:
        super().__init__(params)
        self.scripted = decision

    def evaluate(self, evidence, position) -> RealtimeDecision:  # type: ignore[no-untyped-def]
        self.restore_position(position, now=evidence.at)
        return replace(self.scripted, evidence=evidence)


def _evidence() -> EvidenceSnapshot:
    return EvidenceSnapshot(
        at=NOW,
        event_id="evt-1",
        price=PRICE,
        confidence=D("0.8"),
        grade="HIGH",
        expected_edge_bps=D("5"),
        spread_bps=D("2"),
        data_age_ms=100,
        coverage=D("1"),
        horizons={"1d": D("5")},
        flow_imbalance=D("0"),
        qualified=True,
        reason="QUALIFIED",
        daily_closes=tuple(D(str(70000 + index * 10)) for index in range(240)),
    )


class _Observer:
    """The runner only needs observe() and snapshot() for these tests."""

    daily_history_days = 240

    def observe(self, event: object) -> None:
        return None

    def snapshot(self, now: datetime, params: RealtimeParams) -> EvidenceSnapshot:
        return replace(_evidence(), at=now)

    def bootstrap(self, bars: list[dict[str, object]]) -> None:
        return None

    def bootstrap_daily(self, bars: list[dict[str, object]]) -> None:
        return None


@dataclass
class _Event:
    observed_at: datetime = NOW
    event_type: object = None


def _runner(
    tmp_path: Path, adapter: FakeAdapter, decision: RealtimeDecision
) -> tuple[RealtimeDemoRunner, ScriptedEngine]:
    params = RealtimeParams(evaluation_min_seconds=0)
    engine = ScriptedEngine(params, decision)
    runner = RealtimeDemoRunner(
        adapter,  # type: ignore[arg-type]
        _Observer(),  # type: ignore[arg-type]
        engine,
        ActivityJournal(tmp_path / "journal.jsonl"),
        params,
        dry_run=False,
    )
    runner._rules = adapter.symbol_rules()
    runner._position = None
    return runner, engine


def _plan() -> dict[str, object]:
    return resolve_plan(
        regime=3, posture="NEUTRAL", conviction=0.7, daily_vol_pct=2.0
    ).to_dict()


class TestScalingReachesTheExchange:
    def test_an_opening_still_buys_against_free_cash(self, tmp_path: Path) -> None:
        adapter = FakeAdapter(usdt=D("10000"), btc=D("0"))
        decision = RealtimeDecision(
            Action.ENTER_LONG,
            "AGENT_BUY",
            _evidence(),
            execution_plan=_plan(),
            target_share=D("0.80"),
            share_before=D("0"),
        )
        runner, _ = _runner(tmp_path, adapter, decision)
        result = runner.process_event(_Event())  # type: ignore[arg-type]
        assert result is not None and result.action == Action.ENTER_LONG
        buys = [order for order in adapter.orders if order.side == OrderSide.BUY]
        assert len(buys) == 1
        # 80% of a 10,000 equity.
        assert buys[0].executed_quote_usdt == pytest.approx(D("8000"), abs=D("1"))

    def test_a_top_up_buys_only_the_gap_while_already_long(self, tmp_path: Path) -> None:
        """The case that could not be expressed before.

        Holding 50% and the plan asks for 80%: the order is the 30 point gap, not a fresh
        80% of free cash, which would have been 4000 instead of 3000.
        """
        adapter = FakeAdapter(usdt=D("5000"), btc=D("0.0625"))  # 5000 USDT + 5000 in BTC
        decision = RealtimeDecision(
            Action.ENTER_LONG,
            "AGENT_BUY_AMPLIA",
            _evidence(),
            execution_plan=None,
            target_share=D("0.80"),
            share_before=D("0.50"),
        )
        runner, engine = _runner(tmp_path, adapter, decision)
        engine.import_state(
            replace(
                engine.state,
                entry_price=D("70000"),
                high_since_entry=D("80000"),
                position_base_qty=D("0.0625"),
                execution_plan=_plan(),
            )
        )
        result = runner.process_event(_Event())  # type: ignore[arg-type]
        assert result is not None and result.action == Action.ENTER_LONG
        buys = [order for order in adapter.orders if order.side == OrderSide.BUY]
        assert len(buys) == 1
        assert buys[0].executed_quote_usdt == pytest.approx(D("3000"), abs=D("1"))

    def test_a_top_up_keeps_the_strategy_the_position_was_opened_under(
        self, tmp_path: Path
    ) -> None:
        """Otherwise a top-up moves the stop for the whole position.

        `effective_params` exists so a position is managed under the strategy its regime
        called for at entry. The runner used to call set_execution_plan on every BUY.
        """
        opened_under = _plan()
        adapter = FakeAdapter(usdt=D("5000"), btc=D("0.0625"))
        decision = RealtimeDecision(
            Action.ENTER_LONG,
            "AGENT_BUY_AMPLIA",
            _evidence(),
            execution_plan=None,
            target_share=D("0.80"),
            share_before=D("0.50"),
        )
        runner, engine = _runner(tmp_path, adapter, decision)
        engine.import_state(
            replace(
                engine.state,
                entry_price=D("70000"),
                high_since_entry=D("80000"),
                position_base_qty=D("0.0625"),
                execution_plan=opened_under,
            )
        )
        runner.process_event(_Event())  # type: ignore[arg-type]
        assert engine.state.execution_plan == opened_under

    def test_a_trim_sells_part_and_the_position_survives(self, tmp_path: Path) -> None:
        adapter = FakeAdapter(usdt=D("0"), btc=D("0.125"))  # 100% invested
        decision = RealtimeDecision(
            Action.EXIT_LONG,
            "AGENT_SELL_REDUCE",
            _evidence(),
            True,
            target_share=D("0.60"),
            share_before=D("1.0"),
        )
        runner, engine = _runner(tmp_path, adapter, decision)
        engine.import_state(
            replace(
                engine.state,
                entry_price=D("70000"),
                high_since_entry=D("80000"),
                position_base_qty=D("0.125"),
                execution_plan=_plan(),
            )
        )
        result = runner.process_event(_Event())  # type: ignore[arg-type]
        assert result is not None and result.action == Action.EXIT_LONG
        sells = [order for order in adapter.orders if order.side == OrderSide.SELL]
        assert len(sells) == 1
        assert sells[0].executed_base_qty < D("0.125"), "una reduccion no liquida"
        assert adapter.btc > 0, "la posicion sigue abierta"

    def test_a_trim_leaves_a_protective_stop_for_what_remains(self, tmp_path: Path) -> None:
        # The dangerous window: the exit branch cancels protection before it knows the size.
        adapter = FakeAdapter(usdt=D("0"), btc=D("0.125"))
        decision = RealtimeDecision(
            Action.EXIT_LONG,
            "AGENT_SELL_REDUCE",
            _evidence(),
            True,
            target_share=D("0.60"),
            share_before=D("1.0"),
        )
        runner, engine = _runner(tmp_path, adapter, decision)
        engine.import_state(
            replace(
                engine.state,
                entry_price=D("70000"),
                high_since_entry=D("80000"),
                position_base_qty=D("0.125"),
                execution_plan=_plan(),
            )
        )
        runner.process_event(_Event())  # type: ignore[arg-type]
        assert adapter.resting, "la posicion restante quedo sin stop"
        assert adapter.resting[0].original_base_qty <= adapter.btc

    def test_a_full_exit_still_sells_everything(self, tmp_path: Path) -> None:
        adapter = FakeAdapter(usdt=D("0"), btc=D("0.125"))
        decision = RealtimeDecision(
            Action.EXIT_LONG,
            "AGENT_SELL",
            _evidence(),
            True,
            target_share=D("0"),
            share_before=D("1.0"),
        )
        runner, engine = _runner(tmp_path, adapter, decision)
        engine.import_state(
            replace(
                engine.state,
                entry_price=D("70000"),
                high_since_entry=D("80000"),
                position_base_qty=D("0.125"),
                execution_plan=_plan(),
            )
        )
        runner.process_event(_Event())  # type: ignore[arg-type]
        assert adapter.btc == 0
        assert not adapter.resting


class TestTheGuardsStillHold:
    def test_an_opening_decided_flat_is_refused_if_the_book_became_long(
        self, tmp_path: Path
    ) -> None:
        """The staleness guard, which used to key off the action alone.

        With scaling an ENTER_LONG can be a top-up, so the guard reads the share the book
        held when the decision was taken. A decision taken flat must still require flat.
        """
        adapter = FakeAdapter(usdt=D("5000"), btc=D("0.0625"))
        decision = RealtimeDecision(
            Action.ENTER_LONG,
            "AGENT_BUY",
            _evidence(),
            execution_plan=_plan(),
            target_share=D("0.80"),
            share_before=D("0"),
        )
        runner, _ = _runner(tmp_path, adapter, decision)
        result = runner.process_event(_Event())  # type: ignore[arg-type]
        assert result is not None
        assert result.action == Action.HOLD
        assert result.reason == "POSITION_CHANGED"
        assert not adapter.orders

    def test_a_top_up_decided_long_is_refused_if_the_book_became_flat(
        self, tmp_path: Path
    ) -> None:
        adapter = FakeAdapter(usdt=D("10000"), btc=D("0"))
        decision = RealtimeDecision(
            Action.ENTER_LONG,
            "AGENT_BUY_AMPLIA",
            _evidence(),
            execution_plan=None,
            target_share=D("0.80"),
            share_before=D("0.50"),
        )
        runner, _ = _runner(tmp_path, adapter, decision)
        result = runner.process_event(_Event())  # type: ignore[arg-type]
        assert result is not None and result.reason == "POSITION_CHANGED"
        assert not adapter.orders

    def test_a_trim_that_would_leave_an_unprotectable_remainder_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Otherwise _sync_protection raises and takes the process down.

        The remainder has to clear the exchange minimum notional or it cannot carry a stop
        order, and a position that cannot be protected must not be created by a trim.
        """
        # 0.0002 BTC is 16 USDT. Trimming to 60% leaves under the 10 USDT minimum.
        adapter = FakeAdapter(usdt=D("0"), btc=D("0.0002"))
        decision = RealtimeDecision(
            Action.EXIT_LONG,
            "AGENT_SELL_REDUCE",
            _evidence(),
            True,
            target_share=D("0.60"),
            share_before=D("1.0"),
        )
        runner, engine = _runner(tmp_path, adapter, decision)
        engine.import_state(
            replace(
                engine.state,
                entry_price=D("70000"),
                high_since_entry=D("80000"),
                position_base_qty=D("0.0002"),
                execution_plan=_plan(),
            )
        )
        result = runner.process_event(_Event())  # type: ignore[arg-type]
        assert result is not None
        assert result.reason in {"REMAINDER_UNPROTECTABLE", "RESIDUAL_BELOW_MIN_NOTIONAL"}
        assert adapter.btc == D("0.0002"), "no vendio nada"

    def test_two_different_targets_in_one_event_get_different_order_ids(self) -> None:
        """Otherwise the second adjustment is dropped as a duplicate intent."""
        first = RealtimeDecision(
            Action.ENTER_LONG, "r", _evidence(), target_share=D("0.60"), share_before=D("0.1")
        )
        second = replace(first, target_share=D("0.80"))
        assert deterministic_client_order_id(first) != deterministic_client_order_id(second)

    def test_a_legacy_decision_without_a_target_keeps_the_old_id(self) -> None:
        plain = RealtimeDecision(Action.ENTER_LONG, "r", _evidence())
        assert deterministic_client_order_id(plain).startswith("rt-")
        assert not plain.is_adjustment
        assert not plain.tops_up


class TestProtectionIsRestoredWhenASellIsVetoed:
    def test_a_rejected_sell_does_not_leave_the_position_naked(self, tmp_path: Path) -> None:
        """The exit branch cancels protection before it knows whether it can order.

        If the order is then vetoed or rejected, the position sits without an exchange-side
        stop until some later event happens to re-sync. With a trim that window covers a
        position that is still open, so it has to be closed explicitly.
        """
        adapter = FakeAdapter(usdt=D("0"), btc=D("0.125"), reject_market=True)
        decision = RealtimeDecision(
            Action.EXIT_LONG,
            "AGENT_SELL_REDUCE",
            _evidence(),
            True,
            target_share=D("0.60"),
            share_before=D("1.0"),
        )
        runner, engine = _runner(tmp_path, adapter, decision)
        engine.import_state(
            replace(
                engine.state,
                entry_price=D("70000"),
                high_since_entry=D("80000"),
                position_base_qty=D("0.125"),
                execution_plan=_plan(),
            )
        )
        adapter.place_stop_loss_base_order(
            D("0.125"), D("70000"), client_order_id="rtp-inicial"
        )
        result = runner.process_event(_Event())  # type: ignore[arg-type]
        assert result is not None and result.reason == "ORDER_NOT_FILLED"
        assert adapter.btc == D("0.125"), "nada se vendio"
        assert adapter.resting, "quedo sin stop protector tras el rechazo"


def test_the_runner_can_be_driven_by_a_stream_without_blocking(tmp_path: Path) -> None:
    """Smoke test that the wiring holds end to end under the public entry point."""
    adapter = FakeAdapter()
    decision = RealtimeDecision(Action.HOLD, "AGENT_HOLD", _evidence())
    runner, _ = _runner(tmp_path, adapter, decision)

    class _Stream:
        def events(self, stop: threading.Event):  # type: ignore[no-untyped-def]
            yield _Event(observed_at=NOW)
            yield _Event(observed_at=NOW + timedelta(seconds=1))

    runner._position = runner._reconcile(NOW)
    runner.run(_Stream(), threading.Event())  # type: ignore[arg-type]
    assert adapter.orders == []
    assert runner._position is not None
    assert runner._position.state == PositionState.FLAT
