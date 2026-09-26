"""Event-driven demo strategy with two-speed evidence and durable state.

Market observations update continuously. Structural evidence decides whether a
long regime is admissible; tactical evidence times entry and exit. Protective
state is checkpointed so restarts don't reset entry, trailing high or cooldown.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Protocol

from btc_decision_agent.adapters.binance_stream import StreamEvent, StreamEventType
from btc_decision_agent.application.execution import (
    AccountBalance,
    ExchangeOrder,
    ExecutionVenue,
    OrderResult,
    OrderSide,
    SymbolTradingRules,
    TradeFill,
)
from btc_decision_agent.application.execution_intents import ExecutionIntentStore
from btc_decision_agent.application.exposure_agent import PolicyDecision
from btc_decision_agent.domain.contracts import Action, PositionState
from btc_decision_agent.observability.journal import ActivityJournal, entry_from_live
from btc_decision_agent.policies.exposure_v1 import PARAMETER_VERSION, STRATEGY_VERSION

_LOGGER = logging.getLogger(__name__)

D = Decimal
_DEFAULT_ALLOCATION = D("0.80")
_DEFAULT_ROUND_TRIP_BPS = D("20")
_DEFAULT_MAX_SPREAD_BPS = D("12")
_HIGH_GRADE_CONFIDENCE = D("0.72")
"""Cutoff for labelling evidence quality HIGH in the journal.

Descriptive only. No decision reads the grade; the agent decides from its own
features. It survives because the journal and dashboard display it.
"""
_DEFAULT_STOP_LOSS = D("0.03")
_DEFAULT_TRAILING_STOP = D("0.025")
_DEFAULT_TRAILING_ACTIVATION = D("0.01")
_DEFAULT_BREAK_EVEN_ACTIVATION = D("0.005")
_DEFAULT_BREAK_EVEN_LOCK = D("0.0025")
_DEFAULT_MIN_COVERAGE = D("0.65")
_DEFAULT_MIN_NOTIONAL = D("10")
_DEFAULT_BASE_STEP = D("0.00001")
_DEFAULT_RISK_PER_TRADE = D("0.02")
_DEFAULT_DAILY_LOSS = D("0.05")
_DEFAULT_DRAWDOWN = D("0.10")
_HALF = D("0.5")
_ZERO = D("0")
_STATE_VERSION = "realtime-engine-state/v5"


class RealtimeStream(Protocol):
    def events(self, stop: threading.Event) -> Iterator[StreamEvent]: ...


class RealtimeExecutionAdapter(Protocol):
    def ticker_price(self, symbol: str = "BTCUSDT") -> Decimal: ...

    def account_balance(self) -> AccountBalance: ...

    def symbol_rules(self, symbol: str = "BTCUSDT") -> SymbolTradingRules: ...

    def open_orders(self, symbol: str = "BTCUSDT") -> tuple[ExchangeOrder, ...]: ...

    def recent_trades(
        self, symbol: str = "BTCUSDT", *, limit: int = 100
    ) -> tuple[TradeFill, ...]: ...

    def get_order_by_client_id(
        self, client_order_id: str, symbol: str = "BTCUSDT"
    ) -> ExchangeOrder | None: ...

    def cancel_order(
        self, exchange_order_id: str, symbol: str = "BTCUSDT"
    ) -> ExchangeOrder: ...

    def place_stop_loss_base_order(
        self,
        base_quantity: Decimal,
        stop_price: Decimal,
        symbol: str = "BTCUSDT",
        *,
        client_order_id: str,
    ) -> ExchangeOrder: ...

    def recent_closed_klines(
        self, *, interval: str = "1h", limit: int = 200, symbol: str = "BTCUSDT"
    ) -> list[dict[str, object]]: ...

    def place_market_quote_order(
        self,
        side: OrderSide,
        quote_usdt: Decimal,
        symbol: str = "BTCUSDT",
        *,
        client_order_id: str | None = None,
    ) -> OrderResult: ...

    def place_market_base_order(
        self,
        side: OrderSide,
        base_quantity: Decimal,
        symbol: str = "BTCUSDT",
        *,
        client_order_id: str | None = None,
    ) -> OrderResult: ...


@dataclass(frozen=True)
class RealtimeParams:
    allocation_fraction: Decimal = _DEFAULT_ALLOCATION
    round_trip_cost_bps: Decimal = _DEFAULT_ROUND_TRIP_BPS
    cooldown_seconds: int = 0
    minimum_holding_seconds: int = 0
    """Both default to zero because the agent controls churn economically.

    The V4 engine needed a forced cooldown and a minimum hold to survive a model
    that flipped every few minutes. The exposure agent pays its own transaction
    costs inside its reward, so reluctance to trade is learned rather than imposed.
    Leaving these as blunt overrides at nonzero values would silently prevent the
    agent from exiting a position it has decided to leave.
    """
    evaluation_min_seconds: int = 5
    max_candidate_gap_seconds: int = 15
    max_data_age_seconds: int = 15
    max_spread_bps: Decimal = _DEFAULT_MAX_SPREAD_BPS
    stop_loss_fraction: Decimal = _DEFAULT_STOP_LOSS
    trailing_stop_fraction: Decimal = _DEFAULT_TRAILING_STOP
    trailing_activation_fraction: Decimal = _DEFAULT_TRAILING_ACTIVATION
    break_even_activation_fraction: Decimal = _DEFAULT_BREAK_EVEN_ACTIVATION
    break_even_lock_fraction: Decimal = _DEFAULT_BREAK_EVEN_LOCK
    min_coverage: Decimal = _DEFAULT_MIN_COVERAGE
    min_notional_usdt: Decimal = _DEFAULT_MIN_NOTIONAL
    base_step_size: Decimal = _DEFAULT_BASE_STEP
    risk_per_trade_fraction: Decimal = _DEFAULT_RISK_PER_TRADE
    daily_loss_fraction: Decimal = _DEFAULT_DAILY_LOSS
    max_drawdown_fraction: Decimal = _DEFAULT_DRAWDOWN

    def __post_init__(self) -> None:
        fractions = (
            self.allocation_fraction,
            self.stop_loss_fraction,
            self.trailing_stop_fraction,
            self.trailing_activation_fraction,
            self.break_even_activation_fraction,
            self.break_even_lock_fraction,
            self.min_coverage,
            self.risk_per_trade_fraction,
            self.daily_loss_fraction,
            self.max_drawdown_fraction,
        )
        if any(not value.is_finite() for value in fractions):
            raise ValueError("realtime fractions must be finite")
        if not D("0") < self.allocation_fraction <= D("1"):
            raise ValueError("allocation_fraction must be in (0, 1]")
        if not D("0") < self.min_coverage <= D("1"):
            raise ValueError("min_coverage must be in (0, 1]")
        if not all(D("0") < value < D("1") for value in (
            self.stop_loss_fraction,
            self.trailing_stop_fraction,
            self.trailing_activation_fraction,
            self.break_even_activation_fraction,
            self.break_even_lock_fraction,
        )):
            raise ValueError("stop and trailing fractions must be in (0, 1)")
        if not all(
            D("0") < value < D("1")
            for value in (
                self.risk_per_trade_fraction,
                self.daily_loss_fraction,
                self.max_drawdown_fraction,
            )
        ):
            raise ValueError("risk fractions must be in (0, 1)")
        if min(
            self.cooldown_seconds,
            self.minimum_holding_seconds,
            self.evaluation_min_seconds,
            self.max_candidate_gap_seconds,
            self.max_data_age_seconds,
        ) < 0:
            raise ValueError("timing parameters cannot be negative")
        if self.max_candidate_gap_seconds < self.evaluation_min_seconds:
            raise ValueError("candidate gap must cover evaluation cadence")
        if min(
            self.round_trip_cost_bps,
            self.max_spread_bps,
            self.min_notional_usdt,
            self.base_step_size,
        ) <= 0:
            raise ValueError("cost, spread, notional and step parameters must be positive")


@dataclass(frozen=True)
class PricePoint:
    at: datetime
    price: Decimal


@dataclass(frozen=True)
class EvidenceSnapshot:
    at: datetime
    event_id: str
    price: Decimal
    confidence: Decimal
    grade: str
    expected_edge_bps: Decimal
    spread_bps: Decimal | None
    data_age_ms: int
    coverage: Decimal
    horizons: dict[str, Decimal]
    flow_imbalance: Decimal
    qualified: bool
    reason: str
    model_version: str = STRATEGY_VERSION
    structural_confidence: Decimal = _HALF
    tactical_confidence: Decimal = _HALF
    structural_return_bps: Decimal = _ZERO
    tactical_return_bps: Decimal = _ZERO
    active_stop_price: Decimal | None = None
    daily_closes: tuple[Decimal, ...] = ()
    """Completed daily closes, oldest first, for the exposure agent's perception.

    Carried on the evidence rather than read from the observer so the decision
    remains a pure function of its snapshot, which is what makes a live decision
    reproducible from the journal.
    """


class AdaptiveMarketObserver:
    """Maintain bounded, multi-scale state from continuously arriving events."""

    _HORIZONS: tuple[tuple[str, timedelta, Decimal], ...] = (
        ("5m", timedelta(minutes=5), D("20")),
        ("30m", timedelta(minutes=30), D("50")),
        ("4h", timedelta(hours=4), D("150")),
        ("1d", timedelta(days=1), D("300")),
        ("7d", timedelta(days=7), D("700")),
        ("30d", timedelta(days=30), D("1500")),
    )
    _TACTICAL_WEIGHTS: ClassVar[dict[str, Decimal]] = {
        "5m": D("0.35"),
        "30m": D("0.35"),
        "4h": D("0.30"),
    }
    _STRUCTURAL_WEIGHTS: ClassVar[dict[str, Decimal]] = {
        "4h": D("0.25"),
        "1d": D("0.30"),
        "7d": D("0.30"),
        "30d": D("0.15"),
    }

    def __init__(
        self, *, max_points: int = 70_000, flow_window: timedelta = timedelta(minutes=5)
    ) -> None:
        self._points: deque[PricePoint] = deque(maxlen=max_points)
        self._trades: deque[tuple[datetime, Decimal, bool, str]] = deque()
        self._trade_ids: deque[str] = deque(maxlen=20_000)
        self._trade_id_set: set[str] = set()
        self._flow_window = flow_window
        self._latest_price: Decimal | None = None
        self._bid: Decimal | None = None
        self._ask: Decimal | None = None
        self._last_price_observed: datetime | None = None
        self._last_bbo_observed: datetime | None = None
        self._last_event_id = "bootstrap"
        self._closed_bar_ids: deque[str] = deque(maxlen=5_000)
        self._closed_bar_id_set: set[str] = set()
        # Completed daily closes, keyed by the day's open time in ms. The exposure
        # agent needs 200 of these, which is far more history than the intraday
        # point buffer holds, so it is tracked separately and fed from 1d klines.
        self._daily_closes: dict[int, Decimal] = {}

    def bootstrap(self, bars: list[dict[str, object]]) -> None:
        points: dict[int, PricePoint] = {}
        for bar in bars:
            close_ms = int(str(bar["close_time_ms"]))
            price = D(str(bar["close"]))
            if price > 0:
                points[close_ms] = PricePoint(
                    datetime.fromtimestamp(close_ms / 1000, tz=UTC), price
                )
        for point in sorted(points.values(), key=lambda item: item.at):
            self._append_point(point)
        if self._points:
            self._latest_price = self._points[-1].price

    MAX_DAILY_HISTORY: ClassVar[int] = 400
    """Comfortably above the agent's 200-day requirement, bounded so the process
    does not accumulate state without limit."""

    def bootstrap_daily(self, bars: list[dict[str, object]]) -> None:
        """Load completed daily closes for the exposure agent's perception.

        Callers must pass CLOSED daily bars only. `recent_closed_klines` already
        drops the still-forming bar, which is what preserves the training contract:
        the agent sees days that have ended and never today's partial candle.

        Idempotent and safe to call repeatedly, so the same routine serves both
        startup and the periodic refresh that rolls the series forward.
        """
        for bar in bars:
            open_ms = int(str(bar["open_time_ms"]))
            price = D(str(bar["close"]))
            if price > 0:
                self._daily_closes[open_ms] = price
        if len(self._daily_closes) > self.MAX_DAILY_HISTORY:
            for key in sorted(self._daily_closes)[: -self.MAX_DAILY_HISTORY]:
                del self._daily_closes[key]

    def daily_closes(self) -> list[Decimal]:
        """Completed daily closes, oldest first."""
        return [self._daily_closes[key] for key in sorted(self._daily_closes)]

    @property
    def daily_history_days(self) -> int:
        return len(self._daily_closes)

    def observe(self, event: StreamEvent) -> None:
        self._last_event_id = event.event_id
        if event.price is not None and event.price > 0:
            self._latest_price = event.price
            self._last_price_observed = event.observed_at
        if event.event_type == StreamEventType.BBO:
            self._bid, self._ask = event.bid, event.ask
            self._last_bbo_observed = event.observed_at
        elif event.event_type == StreamEventType.AGG_TRADE:
            if (
                event.quantity is not None
                and event.quantity > 0
                and event.buyer_is_maker is not None
                and event.event_id not in self._trade_id_set
            ):
                self._remember_trade_id(event.event_id)
                self._trades.append(
                    (event.event_time, event.quantity, event.buyer_is_maker, event.event_id)
                )
                self._trim_trades(event.event_time)
        elif (
            event.event_type == StreamEventType.KLINE_CLOSED
            and event.event_id not in self._closed_bar_id_set
            and event.bar_close_time is not None
            and event.bar_close is not None
            and event.bar_close > 0
        ):
            self._remember_closed_bar(event.event_id)
            self._append_point(PricePoint(event.bar_close_time, event.bar_close))

    def _remember_trade_id(self, event_id: str) -> None:
        if len(self._trade_ids) == self._trade_ids.maxlen and self._trade_ids:
            self._trade_id_set.discard(self._trade_ids[0])
        self._trade_ids.append(event_id)
        self._trade_id_set.add(event_id)

    def _remember_closed_bar(self, event_id: str) -> None:
        if len(self._closed_bar_ids) == self._closed_bar_ids.maxlen and self._closed_bar_ids:
            self._closed_bar_id_set.discard(self._closed_bar_ids[0])
        self._closed_bar_ids.append(event_id)
        self._closed_bar_id_set.add(event_id)

    def _append_point(self, point: PricePoint) -> None:
        if self._points and point.at < self._points[-1].at:
            return
        if self._points and point.at == self._points[-1].at:
            self._points[-1] = point
            return
        self._points.append(point)

    def _trim_trades(self, now: datetime) -> None:
        cutoff = now - self._flow_window
        while self._trades and self._trades[0][0] < cutoff:
            self._trades.popleft()

    def _price_at(self, target: datetime, tolerance: timedelta) -> Decimal | None:
        for point in reversed(self._points):
            if point.at <= target:
                return point.price if target - point.at <= tolerance else None
        return None

    def _flow_imbalance(self, now: datetime) -> Decimal:
        self._trim_trades(now)
        buy = sum((qty for _, qty, maker, _ in self._trades if not maker), D("0"))
        sell = sum((qty for _, qty, maker, _ in self._trades if maker), D("0"))
        total = buy + sell
        return (buy - sell) / total if total > 0 else D("0")

    @staticmethod
    def _confidence(score: Decimal) -> Decimal:
        clipped = max(-4.0, min(4.0, float(score)))
        return D(str(1 / (1 + math.exp(-1.8 * clipped)))).quantize(D("0.0001"))

    @staticmethod
    def _weighted(
        returns: dict[str, Decimal],
        scales: dict[str, Decimal],
        weights: dict[str, Decimal],
    ) -> tuple[Decimal, Decimal, Decimal]:
        score = D("0")
        raw = D("0")
        coverage = D("0")
        for name, weight in weights.items():
            value = returns.get(name)
            if value is None:
                continue
            normalized = max(D("-2"), min(D("2"), value / scales[name]))
            score += weight * normalized
            raw += weight * value
            coverage += weight
        if coverage <= 0:
            return D("0"), D("0"), D("0")
        return score / coverage, raw / coverage, coverage

    def snapshot(self, now: datetime, params: RealtimeParams) -> EvidenceSnapshot:
        price = self._latest_price
        if price is None or price <= 0:
            return EvidenceSnapshot(
                now,
                self._last_event_id,
                D("0"),
                D("0.5"),
                "UNAVAILABLE",
                D("0"),
                None,
                2**31 - 1,
                D("0"),
                {},
                D("0"),
                False,
                "PRICE_MISSING",
            )

        price_age_ms = (
            int((now - self._last_price_observed).total_seconds() * 1000)
            if self._last_price_observed is not None
            else 2**31 - 1
        )
        bbo_age_ms = (
            int((now - self._last_bbo_observed).total_seconds() * 1000)
            if self._last_bbo_observed is not None
            else 2**31 - 1
        )
        data_age_ms = max(price_age_ms, bbo_age_ms, 0)
        spread: Decimal | None = None
        if self._bid is not None and self._ask is not None and self._ask >= self._bid:
            midpoint = (self._bid + self._ask) / D("2")
            spread = (self._ask - self._bid) / midpoint * D("10000") if midpoint > 0 else None

        returns: dict[str, Decimal] = {}
        scales: dict[str, Decimal] = {}
        for name, horizon, scale_bps in self._HORIZONS:
            tolerance = min(horizon / 5, timedelta(hours=2))
            historic = self._price_at(now - horizon, tolerance)
            if historic is None or historic <= 0:
                continue
            returns[name] = (price / historic - D("1")) * D("10000")
            scales[name] = scale_bps

        structural_score, structural_return, structural_coverage = self._weighted(
            returns, scales, self._STRUCTURAL_WEIGHTS
        )
        tactical_score, tactical_return, tactical_coverage = self._weighted(
            returns, scales, self._TACTICAL_WEIGHTS
        )
        flow = self._flow_imbalance(now)
        structural_confidence = self._confidence(structural_score)
        tactical_confidence = self._confidence(tactical_score + flow * D("0.20"))
        # Descriptive only, shown in the journal and dashboard. The agent does not
        # read this; it prices costs itself inside its reward function.
        net_tactical_edge = tactical_return - params.round_trip_cost_bps
        if spread is not None:
            net_tactical_edge -= spread
        coverage = min(structural_coverage, tactical_coverage)
        grade = (
            "HIGH"
            if structural_confidence >= _HIGH_GRADE_CONFIDENCE
            else "MEDIUM"
            if structural_confidence >= D("0.58")
            else "LOW"
        )

        reason = "QUALIFIED"
        qualified = True
        if data_age_ms > params.max_data_age_seconds * 1000:
            reason, qualified = "DATA_STALE", False
        elif coverage < params.min_coverage:
            reason, qualified = "HISTORY_INSUFFICIENT", False
        elif spread is None:
            reason, qualified = "BBO_MISSING", False
        elif spread > params.max_spread_bps:
            reason, qualified = "SPREAD_TOO_WIDE", False

        return EvidenceSnapshot(
            at=now,
            event_id=self._last_event_id,
            price=price,
            confidence=structural_confidence,
            grade=grade,
            expected_edge_bps=net_tactical_edge.quantize(D("0.01")),
            spread_bps=spread.quantize(D("0.0001")) if spread is not None else None,
            data_age_ms=data_age_ms,
            coverage=coverage,
            horizons=returns,
            flow_imbalance=flow.quantize(D("0.0001")),
            qualified=qualified,
            reason=reason,
            structural_confidence=structural_confidence,
            tactical_confidence=tactical_confidence,
            structural_return_bps=structural_return.quantize(D("0.01")),
            tactical_return_bps=tactical_return.quantize(D("0.01")),
            daily_closes=tuple(self.daily_closes()),
        )


@dataclass(frozen=True)
class ReconciledPosition:
    state: PositionState
    btc_qty: Decimal
    usdt_free: Decimal
    price: Decimal
    btc_free: Decimal = _ZERO
    btc_locked: Decimal = _ZERO
    usdt_locked: Decimal = _ZERO

    @property
    def equity(self) -> Decimal:
        return self.usdt_free + self.usdt_locked + self.btc_qty * self.price


class CandidateAction(str, Enum):
    ENTER_LONG = "ENTER_LONG"
    EXIT_LONG = "EXIT_LONG"


@dataclass(frozen=True)
class RealtimeDecision:
    action: Action
    reason: str
    evidence: EvidenceSnapshot
    protective: bool = False
    agent_decision: PolicyDecision | None = None
    """The agent's own output, when the decision came from the agent.

    None means a deterministic layer produced this outcome (a breaker, a
    protective stop, or an abstention), which is exactly the distinction an
    auditor needs: every directional action carries the agent's reasoning, and
    anything without it was a veto.
    """
    execution_plan: dict[str, Any] | None = None
    """The strategy this decision is to be executed under, when entering.

    Carried on the decision rather than read from shared configuration because sizing
    happens in the runner at order time while the stop is computed in the engine, and
    the two must agree on the same plan. A position sized for a 10% stop and then
    protected by a 3% one is a different bet than the one that was decided.
    """


@dataclass(frozen=True)
class EnginePersistentState:
    version: str = _STATE_VERSION
    candidate: str | None = None
    candidate_since: datetime | None = None
    candidate_last_seen: datetime | None = None
    cooldown_until: datetime | None = None
    entry_price: Decimal | None = None
    entry_at: datetime | None = None
    high_since_entry: Decimal | None = None
    position_base_qty: Decimal | None = None
    peak_equity: Decimal | None = None
    day_start_equity: Decimal | None = None
    equity_day: str | None = None
    protective_order_id: str | None = None
    protective_client_order_id: str | None = None
    protective_stop_price: Decimal | None = None
    recovery_source: str = "NEW"
    execution_plan: dict[str, Any] | None = None
    """The strategy this position was opened under, as chosen for its regime.

    Persisted because the stop is recomputed from scratch on every market event out of
    `entry_price`, `high_since_entry` and the stop fractions. If the plan were held
    only in memory, a restart would silently reimpose the default geometry on an open
    position: a position entered under a wide trend-following stop would suddenly be
    protected by a tight one, or the reverse, and `_sync_protection` would move the
    resting exchange order to match.
    """

    def to_dict(self) -> dict[str, str | None] | dict[str, Any]:
        def timestamp(value: datetime | None) -> str | None:
            return value.isoformat() if value is not None else None

        def decimal(value: Decimal | None) -> str | None:
            return format(value, "f") if value is not None else None

        return {
            "version": self.version,
            "candidate": self.candidate,
            "candidate_since": timestamp(self.candidate_since),
            "candidate_last_seen": timestamp(self.candidate_last_seen),
            "cooldown_until": timestamp(self.cooldown_until),
            "entry_price": decimal(self.entry_price),
            "entry_at": timestamp(self.entry_at),
            "high_since_entry": decimal(self.high_since_entry),
            "position_base_qty": decimal(self.position_base_qty),
            "peak_equity": decimal(self.peak_equity),
            "day_start_equity": decimal(self.day_start_equity),
            "equity_day": self.equity_day,
            "protective_order_id": self.protective_order_id,
            "protective_client_order_id": self.protective_client_order_id,
            "protective_stop_price": decimal(self.protective_stop_price),
            "recovery_source": self.recovery_source,
            "execution_plan": self.execution_plan,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EnginePersistentState:
        version = str(raw.get("version", ""))
        if version not in {
            _STATE_VERSION,
            "realtime-engine-state/v4",
            "realtime-engine-state/v3",
            "realtime-engine-state/v2",
        }:
            raise ValueError("unsupported engine state version")

        def timestamp(name: str) -> datetime | None:
            value = raw.get(name)
            return datetime.fromisoformat(str(value)) if value else None

        def decimal(name: str) -> Decimal | None:
            value = raw.get(name)
            return D(str(value)) if value is not None else None

        return cls(
            candidate=str(raw["candidate"]) if raw.get("candidate") else None,
            candidate_since=timestamp("candidate_since"),
            candidate_last_seen=timestamp("candidate_last_seen"),
            cooldown_until=timestamp("cooldown_until"),
            entry_price=decimal("entry_price"),
            entry_at=timestamp("entry_at"),
            high_since_entry=decimal("high_since_entry"),
            position_base_qty=decimal("position_base_qty"),
            peak_equity=decimal("peak_equity"),
            day_start_equity=decimal("day_start_equity"),
            equity_day=str(raw["equity_day"]) if raw.get("equity_day") else None,
            protective_order_id=(
                str(raw["protective_order_id"])
                if raw.get("protective_order_id")
                else None
            ),
            protective_client_order_id=(
                str(raw["protective_client_order_id"])
                if raw.get("protective_client_order_id")
                else None
            ),
            protective_stop_price=decimal("protective_stop_price"),
            recovery_source=str(raw.get("recovery_source", "STATE_FILE")),
            # Absent on v2-v4 checkpoints, which simply means "no plan recorded";
            # the engine then falls back to its configured defaults.
            execution_plan=(
                dict(raw["execution_plan"])
                if isinstance(raw.get("execution_plan"), dict)
                else None
            ),
        )


class EngineStateStore:
    """Atomic, fsync'd checkpoint for protective and persistence state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> EnginePersistentState | None:
        if not self.path.exists():
            return None
        raw: object = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("engine state must be an object")
        return EnginePersistentState.from_dict(raw)

    def save(self, state: EnginePersistentState) -> None:
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        payload = json.dumps(state.to_dict(), separators=(",", ":"), sort_keys=True)
        with temporary.open("w", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        directory_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


class ProtectiveDecisionEngine:
    """Risk and bookkeeping machinery with NO directional opinion of its own.

    This class deliberately cannot decide to buy or sell. It owns circuit breakers,
    exchange-side stop tracking, equity and drawdown bookkeeping, and durable state
    across restarts. Direction is supplied by a subclass, which is how the agent
    ends up as the only source of a trade while these protections still apply.

    `evaluate` is intentionally unimplemented: an engine with no decision source
    must fail loudly rather than quietly hold forever.
    """

    def __init__(self, params: RealtimeParams) -> None:
        self.params = params
        self._state = EnginePersistentState()

    @property
    def state(self) -> EnginePersistentState:
        return self._state

    def import_state(self, state: EnginePersistentState) -> None:
        self._state = state

    def restore_position(self, position: ReconciledPosition, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(tz=UTC)
        if position.state == PositionState.FLAT:
            had_position = self._state.entry_price is not None
            cooldown = self._state.cooldown_until
            if had_position:
                cooldown = max(
                    cooldown or moment,
                    moment + timedelta(seconds=self.params.cooldown_seconds),
                )
            self._state = replace(
                self._state,
                candidate=None if had_position else self._state.candidate,
                candidate_since=None if had_position else self._state.candidate_since,
                candidate_last_seen=None if had_position else self._state.candidate_last_seen,
                cooldown_until=cooldown,
                entry_price=None,
                entry_at=None,
                high_since_entry=None,
                position_base_qty=None,
                protective_order_id=None,
                protective_client_order_id=None,
                protective_stop_price=None,
                execution_plan=None,
            )
            return

        entry = self._state.entry_price or position.price
        high = max(self._state.high_since_entry or position.price, position.price)
        self._state = replace(
            self._state,
            entry_price=entry,
            high_since_entry=high,
            position_base_qty=position.btc_qty,
        )

    def on_fill(
        self,
        side: OrderSide,
        fill_price: Decimal,
        base_quantity: Decimal,
        at: datetime,
    ) -> None:
        held = self._state.position_base_qty or _ZERO
        if side == OrderSide.BUY and self._state.entry_price is not None and held > 0:
            # Adding to an existing position, not opening one. Treating this as a fresh
            # entry would rewrite entry_price to the new, higher fill and reset
            # high_since_entry, which tightens the stop on the whole position at the
            # exact moment of scaling up and throws away the trailing high watermark.
            #
            # The cost basis becomes the weighted average of what was paid, because that
            # is what the stop is measured from and what the profit is measured against.
            total = held + base_quantity
            averaged = (
                (self._state.entry_price * held + fill_price * base_quantity) / total
            )
            self._state = replace(
                self._state,
                candidate=None,
                candidate_since=None,
                candidate_last_seen=None,
                entry_price=averaged,
                high_since_entry=max(self._state.high_since_entry or fill_price, fill_price),
                position_base_qty=total,
                # The resting stop no longer covers the position, so it is recorded as
                # absent and the forced sync that follows a fill places one for the
                # full quantity. The exchange order is still discoverable by its client
                # id prefix, so it can be cancelled.
                protective_order_id=None,
                protective_client_order_id=None,
                protective_stop_price=None,
                recovery_source="FILL",
            )
        elif side == OrderSide.SELL and held > 0 and base_quantity < held:
            # Trimming, not leaving. Selling part of a position does not change what was
            # paid for the remainder, so the cost basis and the high watermark stand and
            # the position keeps the strategy it was opened under.
            self._state = replace(
                self._state,
                candidate=None,
                candidate_since=None,
                candidate_last_seen=None,
                position_base_qty=held - base_quantity,
                protective_order_id=None,
                protective_client_order_id=None,
                protective_stop_price=None,
                recovery_source="FILL",
            )
        elif side == OrderSide.BUY:
            self._state = replace(
                self._state,
                candidate=None,
                candidate_since=None,
                candidate_last_seen=None,
                entry_price=fill_price,
                entry_at=at,
                high_since_entry=fill_price,
                position_base_qty=base_quantity,
                protective_order_id=None,
                protective_client_order_id=None,
                protective_stop_price=None,
                recovery_source="FILL",
            )
        else:
            self._state = replace(
                self._state,
                candidate=None,
                candidate_since=None,
                candidate_last_seen=None,
                cooldown_until=at + timedelta(seconds=self.params.cooldown_seconds),
                entry_price=None,
                entry_at=None,
                high_since_entry=None,
                position_base_qty=None,
                protective_order_id=None,
                protective_client_order_id=None,
                protective_stop_price=None,
                execution_plan=None,
                recovery_source="FILL",
            )

    def update_equity(self, equity: Decimal, at: datetime) -> None:
        day = at.date().isoformat()
        day_start = self._state.day_start_equity
        if self._state.equity_day != day or day_start is None:
            day_start = equity
        peak = max(self._state.peak_equity or equity, equity)
        self._state = replace(
            self._state,
            peak_equity=peak,
            day_start_equity=day_start,
            equity_day=day,
        )

    def breaker_reason(self, equity: Decimal) -> str | None:
        if (
            self._state.day_start_equity is not None
            and equity
            <= self._state.day_start_equity * (D("1") - self.params.daily_loss_fraction)
        ):
            return "DAILY_LOSS_BREAKER"
        if (
            self._state.peak_equity is not None
            and equity
            <= self._state.peak_equity * (D("1") - self.params.max_drawdown_fraction)
        ):
            return "DRAWDOWN_BREAKER"
        return None

    def set_execution_plan(self, plan: dict[str, Any] | None) -> None:
        """Record the strategy a position is being opened under."""
        self._state = replace(self._state, execution_plan=plan)

    def set_protective_order(self, order: ExchangeOrder | None) -> None:
        self._state = replace(
            self._state,
            protective_order_id=order.exchange_order_id if order else None,
            protective_client_order_id=order.client_order_id if order else None,
            protective_stop_price=order.stop_price if order else None,
        )

    @property
    def effective_params(self) -> RealtimeParams:
        """Configured parameters, overridden by the open position's own strategy.

        A position is opened under the strategy its regime called for, and it must be
        managed under that same strategy until it closes. Recomputing the stop from the
        process defaults instead would move the stop under a live position every time
        the regime changed or the process restarted.
        """
        raw = self._state.execution_plan
        if not raw:
            return self.params
        try:
            from btc_decision_agent.application.regime_playbook import ExecutionPlan

            return ExecutionPlan.from_dict(raw).apply(self.params)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            # A malformed plan must not disable protection; fall back to defaults,
            # which are tighter than anything the playbook can produce at the top end.
            return self.params

    def active_stop(self, price: Decimal) -> Decimal | None:
        return self._active_stop(price)

    def _active_stop(self, price: Decimal) -> Decimal | None:
        entry = self._state.entry_price
        if entry is None:
            return None
        params = self.effective_params
        initial = entry * (D("1") - params.stop_loss_fraction)
        high = self._state.high_since_entry or price
        if high >= entry * (D("1") + params.break_even_activation_fraction):
            initial = max(
                initial,
                entry * (D("1") + params.break_even_lock_fraction),
            )
        activation = entry * (D("1") + params.trailing_activation_fraction)
        if high < activation:
            return initial
        trailing = high * (D("1") - params.trailing_stop_fraction)
        return max(initial, trailing)

    def evaluate(
        self, evidence: EvidenceSnapshot, position: ReconciledPosition
    ) -> RealtimeDecision:
        """Must be provided by a subclass that owns a decision source.

        Raising rather than returning HOLD is deliberate. A silent hold would look
        like a working agent that simply never finds an opportunity, which is the
        hardest kind of failure to notice in production.
        """
        raise NotImplementedError(
            "ProtectiveDecisionEngine has no decision source; use ExposureAgentEngine"
        )

    def _persisted(self, action: CandidateAction, now: datetime, seconds: int) -> bool:
        if (
            self._state.candidate != action.value
            or self._state.candidate_since is None
            or self._state.candidate_last_seen is None
            or now - self._state.candidate_last_seen
            > timedelta(seconds=self.params.max_candidate_gap_seconds)
        ):
            self._state = replace(
                self._state,
                candidate=action.value,
                candidate_since=now,
                candidate_last_seen=now,
            )
            return seconds == 0
        candidate_since = self._state.candidate_since
        assert candidate_since is not None
        self._state = replace(
            self._state,
            candidate=action.value,
            candidate_since=candidate_since,
            candidate_last_seen=now,
        )
        return now - candidate_since >= timedelta(seconds=seconds)

    def _reset_candidate(self) -> None:
        self._state = replace(
            self._state,
            candidate=None,
            candidate_since=None,
            candidate_last_seen=None,
        )


def recover_engine_state(
    entries: list[dict[str, Any]],
    position: ReconciledPosition,
    params: RealtimeParams,
    now: datetime,
) -> EnginePersistentState:
    """Recover entry/high/cooldown from the journal when no checkpoint exists."""
    last_order_index: int | None = None
    last_order_side: str | None = None
    for index, entry in enumerate(entries):
        if entry.get("order_side") in {"BUY", "SELL"} and entry.get("order_id"):
            last_order_index = index
            last_order_side = str(entry["order_side"])

    if position.state == PositionState.LONG:
        entry_price = position.price
        high = position.price
        entry_at: datetime | None = None
        if last_order_index is not None and last_order_side == "BUY":
            order_entry = entries[last_order_index]
            entry_at = datetime.fromisoformat(str(order_entry["at"]))
            if order_entry.get("order_avg_price") is not None:
                entry_price = D(str(order_entry["order_avg_price"]))
            prices = (
                D(str(entry["price"]))
                for entry in entries[last_order_index:]
                if entry.get("price") is not None
            )
            high = max((entry_price, position.price, *prices))
        return EnginePersistentState(
            entry_price=entry_price,
            entry_at=entry_at,
            high_since_entry=high,
            position_base_qty=position.btc_qty,
            recovery_source="JOURNAL" if last_order_side == "BUY" else "ADOPTED_POSITION",
        )

    cooldown: datetime | None = None
    if entries and (entries[-1].get("position_after") or entries[-1].get("position_before")) == "LONG":
        cooldown = now + timedelta(seconds=params.cooldown_seconds)
    return EnginePersistentState(cooldown_until=cooldown, recovery_source="JOURNAL")


def reconcile_realtime_position(
    adapter: RealtimeExecutionAdapter, *, dust_usdt: Decimal = _DEFAULT_MIN_NOTIONAL
) -> ReconciledPosition:
    price = adapter.ticker_price()
    balance = adapter.account_balance()
    btc_free = balance.balances.get("BTC", D("0"))
    btc_locked = balance.locked_balances.get("BTC", D("0"))
    usdt = balance.balances.get("USDT", D("0"))
    usdt_locked = balance.locked_balances.get("USDT", D("0"))
    btc_total = btc_free + btc_locked
    state = PositionState.LONG if btc_total * price > dust_usdt else PositionState.FLAT
    return ReconciledPosition(
        state,
        btc_total,
        usdt,
        price,
        btc_free=btc_free,
        btc_locked=btc_locked,
        usdt_locked=usdt_locked,
    )


def size_entry_percentage(
    usdt_free: Decimal,
    allocation_fraction: Decimal,
    *,
    min_notional: Decimal = _DEFAULT_MIN_NOTIONAL,
    equity: Decimal | None = None,
    risk_per_trade_fraction: Decimal | None = None,
    stop_loss_fraction: Decimal | None = None,
) -> Decimal:
    """Bound entry by cash allocation and optional maximum loss at the stop."""
    if usdt_free < 0 or not D("0") < allocation_fraction <= D("1"):
        raise ValueError("invalid balance or allocation fraction")
    by_cash = usdt_free * allocation_fraction
    raw = by_cash
    risk_values = (equity, risk_per_trade_fraction, stop_loss_fraction)
    if any(value is not None for value in risk_values):
        if any(value is None for value in risk_values):
            raise ValueError("equity, risk fraction and stop fraction must be provided together")
        assert equity is not None
        assert risk_per_trade_fraction is not None
        assert stop_loss_fraction is not None
        if equity <= 0 or not D("0") < risk_per_trade_fraction < D("1"):
            raise ValueError("invalid equity or risk fraction")
        if not D("0") < stop_loss_fraction < D("1"):
            raise ValueError("invalid stop fraction")
        raw = min(by_cash, equity * risk_per_trade_fraction / stop_loss_fraction)
    quote = raw.quantize(D("0.01"), rounding=ROUND_DOWN)
    return quote if quote >= min_notional else D("0")


def size_exit_base(btc_free: Decimal, step_size: Decimal) -> Decimal:
    if btc_free < 0 or step_size <= 0:
        raise ValueError("invalid BTC balance or step size")
    return (btc_free / step_size).to_integral_value(rounding=ROUND_DOWN) * step_size


def deterministic_client_order_id(decision: RealtimeDecision) -> str:
    raw = f"{decision.action.value}:{decision.evidence.event_id}:{decision.evidence.model_version}"
    return "rt-" + hashlib.sha256(raw.encode()).hexdigest()[:28]


class RealtimeDemoRunner:
    """Single order authority joining stream, evidence, account and durable state."""

    def __init__(
        self,
        adapter: RealtimeExecutionAdapter,
        observer: AdaptiveMarketObserver,
        engine: ProtectiveDecisionEngine,
        journal: ActivityJournal,
        params: RealtimeParams,
        *,
        state_store: EngineStateStore | None = None,
        intent_store: ExecutionIntentStore | None = None,
        dry_run: bool = True,
    ) -> None:
        self.adapter = adapter
        self.observer = observer
        self.engine = engine
        self.journal = journal
        self.params = params
        self.state_store = state_store
        self.intent_store = intent_store
        self.dry_run = dry_run
        self._rules: SymbolTradingRules | None = None
        self._position: ReconciledPosition | None = None
        self._last_reconcile: datetime | None = None
        self._last_daily_refresh: datetime | None = None
        self._last_evaluation: datetime | None = None
        self._last_protection_sync: datetime | None = None
        self._pending_external_order: OrderResult | None = None
        self._pending_external_before: ReconciledPosition | None = None
        self._loaded_state = state_store.load() if state_store is not None else None
        if self._loaded_state is not None:
            self.engine.import_state(self._loaded_state)

    def _persist_state(self) -> None:
        if self.state_store is not None:
            self.state_store.save(self.engine.state)

    def _resolve_unfinished_intents(self) -> None:
        if self.intent_store is None:
            return
        now = datetime.now(tz=UTC)
        for intent in self.intent_store.unresolved():
            order = self.adapter.get_order_by_client_id(intent.client_order_id)
            if order is None:
                if now - intent.created_at < timedelta(seconds=30):
                    raise RuntimeError(f"execution intent still ambiguous: {intent.client_order_id}")
                self.intent_store.mark(intent.client_order_id, "NOT_FOUND")
                continue
            self.intent_store.mark(
                intent.client_order_id,
                order.status,
                exchange_order_id=order.exchange_order_id,
                response={
                    "type": order.order_type,
                    "status": order.status,
                    "executed_base_qty": format(order.executed_base_qty, "f"),
                },
            )
            if order.status not in {
                "FILLED",
                "CANCELED",
                "REJECTED",
                "EXPIRED",
                "EXPIRED_IN_MATCH",
            }:
                raise RuntimeError(
                    f"non-terminal execution intent blocks strategy: {intent.client_order_id}"
                )

    @staticmethod
    def _quantize_down(value: Decimal, step: Decimal) -> Decimal:
        if step <= 0:
            raise ValueError("quantization step must be positive")
        return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

    def _owned_protective_orders(self) -> tuple[ExchangeOrder, ...]:
        return tuple(
            order
            for order in self.adapter.open_orders()
            if order.client_order_id.startswith("rtp-")
            and order.side == OrderSide.SELL
            and order.order_type in {"STOP_LOSS", "STOP_LOSS_LIMIT"}
        )

    def _cancel_protection(self) -> None:
        for order in self._owned_protective_orders():
            cancelled = self.adapter.cancel_order(order.exchange_order_id)
            if cancelled.status not in {"CANCELED", "FILLED", "EXPIRED"}:
                raise RuntimeError(f"protective order cancellation unresolved: {order.exchange_order_id}")
        self.engine.set_protective_order(None)
        self._persist_state()

    def _sync_protection(
        self, position: ReconciledPosition, *, force: bool = False
    ) -> ReconciledPosition:
        now = datetime.now(tz=UTC)
        if (
            not force
            and self._last_protection_sync is not None
            and now - self._last_protection_sync < timedelta(seconds=30)
        ):
            return position
        self._last_protection_sync = now
        if self.dry_run or self._rules is None:
            return position
        existing = self._owned_protective_orders()
        if position.state == PositionState.FLAT:
            if existing:
                self._cancel_protection()
            return position
        if not self._rules.stop_loss_allowed:
            raise RuntimeError("exchange does not support STOP_LOSS protection")
        stop = self.engine.active_stop(position.price)
        if stop is None:
            raise RuntimeError("LONG position has no protective stop")
        stop = self._quantize_down(stop, self._rules.tick_size)
        quantity = self._quantize_down(position.btc_qty, self._rules.lot_step_size)
        if quantity < self._rules.min_quantity or quantity * stop < self._rules.min_notional:
            raise RuntimeError("position is too small for exchange-side protection")
        replacement_threshold = max(self._rules.tick_size * D("10"), stop * D("0.001"))
        matching = next(
            (
                order
                for order in existing
                if order.stop_price >= stop - replacement_threshold
                and abs(order.original_base_qty - quantity) < self._rules.lot_step_size
            ),
            None,
        )
        if matching is not None:
            self.engine.set_protective_order(matching)
            self._persist_state()
            return position
        if existing:
            self._cancel_protection()
            position = reconcile_realtime_position(
                self.adapter, dust_usdt=self._rules.min_notional
            )
            quantity = self._quantize_down(position.btc_free, self._rules.lot_step_size)
        client_seed = f"{self.engine.state.entry_price}:{stop}:{quantity}"
        client_id = "rtp-" + hashlib.sha256(client_seed.encode()).hexdigest()[:27]
        protective = self.adapter.place_stop_loss_base_order(
            quantity, stop, client_order_id=client_id
        )
        if protective.status not in {"NEW", "PARTIALLY_FILLED"}:
            raise RuntimeError(f"protective order rejected with status {protective.status}")
        self.engine.set_protective_order(protective)
        self._persist_state()
        return reconcile_realtime_position(
            self.adapter, dust_usdt=self._rules.min_notional
        )

    def bootstrap(self) -> None:
        self._rules = self.adapter.symbol_rules()
        if self._rules.status != "TRADING" or not self._rules.market_quote_allowed:
            raise RuntimeError("BTCUSDT is not eligible for market execution")
        self._resolve_unfinished_intents()
        bars = self.adapter.recent_closed_klines(interval="1h", limit=1000)
        bars.extend(self.adapter.recent_closed_klines(interval="1m", limit=1000))
        self.observer.bootstrap(bars)
        # 1000 hourly bars is only ~41 days, nowhere near the 200 completed days
        # the exposure agent's perception requires, so daily history is loaded from
        # its own 1d series (1000 daily bars is about 2.7 years).
        self._refresh_daily_history(datetime.now(tz=UTC))
        self._position = reconcile_realtime_position(
            self.adapter, dust_usdt=self._rules.min_notional
        )
        now = datetime.now(tz=UTC)
        if self._loaded_state is None:
            recovered = recover_engine_state(self.journal.read(), self._position, self.params, now)
            self.engine.import_state(recovered)
        self.engine.restore_position(self._position, now=now)
        self.engine.update_equity(self._position.equity, now)
        self._persist_state()
        self._position = self._sync_protection(self._position, force=True)
        self._last_reconcile = now

    DAILY_REFRESH_INTERVAL: ClassVar[timedelta] = timedelta(minutes=30)
    """How often the daily series is re-pulled.

    Rebuilding days from the 1m stream would work until the first dropped
    connection silently left a hole in a 200-day average. Re-reading the
    authoritative 1d series on a timer is cheap (one unsigned request) and
    self-healing: any gap caused by a disconnect is repaired on the next pass.
    """

    def _refresh_daily_history(self, now: datetime) -> None:
        """Pull completed daily closes; never fatal, since the agent can abstain."""
        try:
            daily = self.adapter.recent_closed_klines(interval="1d", limit=1000)
        except Exception as error:  # stale history must not kill the loop
            # Operational telemetry, not trading activity, so it goes to the log
            # rather than the activity journal. The agent degrades safely on its
            # own: without enough daily history it abstains instead of guessing.
            _LOGGER.warning(
                "daily history refresh failed (%d days held): %r",
                self.observer.daily_history_days,
                error,
            )
            return
        self.observer.bootstrap_daily(daily)
        self._last_daily_refresh = now

    def _protective_fill_result(self, exchange_order_id: str) -> OrderResult | None:
        fills = tuple(
            trade
            for trade in self.adapter.recent_trades(limit=100)
            if trade.exchange_order_id == exchange_order_id and not trade.is_buyer
        )
        if not fills:
            return None
        base = sum((fill.base_qty for fill in fills), D("0"))
        quote = sum((fill.quote_qty for fill in fills), D("0"))
        average = quote / base if base > 0 else D("0")
        fees_by_asset: dict[str, Decimal] = {}
        for fill in fills:
            fees_by_asset[fill.commission_asset] = (
                fees_by_asset.get(fill.commission_asset, D("0")) + fill.commission
            )
        fees_usdt = fees_by_asset.get("USDT", D("0"))
        fees_usdt += fees_by_asset.get("BTC", D("0")) * average
        return OrderResult(
            venue=ExecutionVenue.DEMO,
            exchange_order_id=exchange_order_id,
            side=OrderSide.SELL,
            executed_quote_usdt=quote,
            executed_base_qty=base,
            average_price=average,
            fees_usdt=fees_usdt,
            transact_time_ms=max(fill.time_ms for fill in fills),
            raw_status="FILLED",
            client_order_id=self.engine.state.protective_client_order_id,
            fees_by_asset=fees_by_asset,
        )

    def _reconcile(self, now: datetime) -> ReconciledPosition:
        previous = self._position
        current = reconcile_realtime_position(
            self.adapter,
            dust_usdt=self._rules.min_notional if self._rules else self.params.min_notional_usdt,
        )
        if previous is not None and previous.state != current.state:
            protective_id = self.engine.state.protective_order_id
            if previous.state == PositionState.LONG and current.state == PositionState.FLAT:
                external_fill = (
                    self._protective_fill_result(protective_id)
                    if protective_id is not None
                    else None
                )
                if external_fill is not None:
                    self._pending_external_order = external_fill
                    self._pending_external_before = previous
                    self.engine.on_fill(
                        OrderSide.SELL,
                        external_fill.average_price,
                        external_fill.executed_base_qty,
                        now,
                    )
                else:
                    self.engine.restore_position(current, now=now)
            else:
                self.engine.restore_position(current, now=now)
            self._persist_state()
        self._position = current
        self._last_reconcile = now
        return current

    def process_event(self, event: StreamEvent) -> RealtimeDecision | None:
        self.observer.observe(event)
        now = event.observed_at
        force = event.event_type == StreamEventType.KLINE_CLOSED
        if (
            not force
            and self._last_evaluation is not None
            and now - self._last_evaluation < timedelta(seconds=self.params.evaluation_min_seconds)
        ):
            return None
        self._last_evaluation = now
        if (
            self._position is None
            or self._last_reconcile is None
            or now - self._last_reconcile >= timedelta(seconds=30)
        ):
            self._reconcile(now)
        if (
            self._last_daily_refresh is None
            or now - self._last_daily_refresh >= self.DAILY_REFRESH_INTERVAL
        ):
            self._refresh_daily_history(now)

        evidence = self.observer.snapshot(now, self.params)
        assert self._position is not None
        if self._pending_external_order is not None:
            external_order = self._pending_external_order
            external_before = self._pending_external_before or self._position
            self._pending_external_order = None
            self._pending_external_before = None
            decision = RealtimeDecision(
                Action.EXIT_LONG, "PROTECTIVE_ORDER_FILLED", evidence, True
            )
            self._record(
                decision,
                decision.reason,
                external_before,
                self._position,
                external_order,
            )
            return decision
        decision = self.engine.evaluate(evidence, self._position)
        order: OrderResult | None = None
        before = self._position
        after = before
        final_reason = decision.reason
        self._persist_state()

        if decision.action == Action.HOLD:
            if before.state == PositionState.LONG:
                after = self._sync_protection(before)
                self._position = after
        elif not self.dry_run:
            before = self._reconcile(now)
            expected_state = (
                PositionState.FLAT if decision.action == Action.ENTER_LONG else PositionState.LONG
            )
            if before.state != expected_state:
                decision = replace(decision, action=Action.HOLD, reason="POSITION_CHANGED")
                final_reason = decision.reason
            else:
                client_id = deterministic_client_order_id(decision)
                if decision.action == Action.ENTER_LONG:
                    minimum = self._rules.min_notional if self._rules else self.params.min_notional_usdt
                    # Size under the decision's own strategy. Sizing here and the stop
                    # in the engine must use the same plan, or the position is sized for
                    # one bet and protected for another.
                    sizing = self.params
                    if decision.execution_plan:
                        try:
                            from btc_decision_agent.application.regime_playbook import (
                                ExecutionPlan,
                            )

                            sizing = ExecutionPlan.from_dict(decision.execution_plan).apply(
                                self.params
                            )
                        except (KeyError, TypeError, ValueError, ArithmeticError):
                            _LOGGER.warning(
                                "plan de ejecucion invalido; se usa la configuracion por defecto"
                            )
                    quote = size_entry_percentage(
                        before.usdt_free,
                        sizing.allocation_fraction,
                        min_notional=minimum,
                        equity=before.equity,
                        risk_per_trade_fraction=sizing.risk_per_trade_fraction,
                        stop_loss_fraction=sizing.stop_loss_fraction,
                    )
                    requested_base: Decimal | None = None
                else:
                    self._cancel_protection()
                    before = self._reconcile(now)
                    if before.state != PositionState.LONG:
                        decision = replace(decision, action=Action.HOLD, reason="POSITION_CHANGED")
                        final_reason = decision.reason
                        quote = D("0")
                        requested_base = None
                    else:
                        step = self._rules.market_step_size if self._rules else self.params.base_step_size
                        requested_base = size_exit_base(before.btc_free, step)
                        quote = D("0")

                if decision.action == Action.ENTER_LONG and quote == 0:
                    decision = replace(decision, action=Action.HOLD, reason="CAPITAL_INSUFFICIENT")
                    final_reason = decision.reason
                elif (
                    decision.action == Action.EXIT_LONG
                    and requested_base is not None
                    and requested_base * before.price
                    < (self._rules.min_notional if self._rules else self.params.min_notional_usdt)
                ):
                    decision = replace(
                        decision, action=Action.HOLD, reason="RESIDUAL_BELOW_MIN_NOTIONAL"
                    )
                    final_reason = decision.reason
                elif decision.action != Action.HOLD:
                    existing_intent = None
                    if self.intent_store is not None:
                        existing_intent = self.intent_store.prepare(
                            client_order_id=client_id,
                            event_id=evidence.event_id,
                            action=decision.action.value,
                            side=(
                                OrderSide.BUY.value
                                if decision.action == Action.ENTER_LONG
                                else OrderSide.SELL.value
                            ),
                            requested_quote=quote if quote > 0 else None,
                            requested_base=requested_base,
                        )
                    if existing_intent is not None and existing_intent.terminal:
                        decision = replace(decision, action=Action.HOLD, reason="DUPLICATE_INTENT")
                        final_reason = decision.reason
                    else:
                        try:
                            if decision.action == Action.ENTER_LONG:
                                order = self.adapter.place_market_quote_order(
                                    OrderSide.BUY, quote, client_order_id=client_id
                                )
                            else:
                                assert requested_base is not None
                                order = self.adapter.place_market_base_order(
                                    OrderSide.SELL, requested_base, client_order_id=client_id
                                )
                        except Exception:
                            if self.intent_store is not None:
                                self.intent_store.mark(client_id, "UNKNOWN")
                            raise

                if order is not None:
                    if self.intent_store is not None:
                        self.intent_store.mark(
                            client_id,
                            order.raw_status,
                            exchange_order_id=order.exchange_order_id,
                            response={
                                "executed_base_qty": format(order.executed_base_qty, "f"),
                                "executed_quote_usdt": format(order.executed_quote_usdt, "f"),
                                "fees_by_asset": {
                                    asset: format(amount, "f")
                                    for asset, amount in order.fees_by_asset.items()
                                },
                            },
                        )
                    if (
                        order.raw_status != "FILLED"
                        or order.executed_base_qty <= 0
                        or order.average_price <= 0
                    ):
                        decision = replace(decision, action=Action.HOLD, reason="ORDER_NOT_FILLED")
                        final_reason = decision.reason
                    else:
                        self.engine.on_fill(
                            order.side,
                            order.average_price,
                            order.executed_base_qty,
                            now,
                        )
                        # on_fill clears the plan, so a BUY records the strategy it was
                        # opened under immediately afterwards. The very next call is
                        # _sync_protection, which reads the stop from this plan.
                        if order.side == OrderSide.BUY and decision.execution_plan:
                            self.engine.set_execution_plan(decision.execution_plan)
                        self._persist_state()
                    after = self._reconcile(now)
                    if after.state == PositionState.LONG:
                        after = self._sync_protection(after, force=True)
                        self._position = after
        else:
            final_reason = f"DRY_RUN:{decision.reason}"

        self._persist_state()
        self._record(decision, final_reason, before, after, order)
        return decision

    def run(self, stream: RealtimeStream, stop: threading.Event) -> None:
        if self._position is None:
            self.bootstrap()
        for event in stream.events(stop):
            if stop.is_set():
                break
            self.process_event(event)

    def _agent_online_learning(self) -> bool:
        """Whether the decision source is still learning, for the audit record."""
        agent = getattr(self.engine, "agent", None)
        return bool(getattr(agent, "online_learning", False))

    def _record(
        self,
        decision: RealtimeDecision,
        reason: str,
        before: ReconciledPosition,
        after: ReconciledPosition,
        order: OrderResult | None,
    ) -> None:
        evidence = decision.evidence
        state = self.engine.state
        agent = decision.agent_decision
        self.journal.append(
            entry_from_live(
                venue="DEMO",
                interval="adaptive",
                action=decision.action.value,
                reason=reason,
                position_before=before.state.value,
                position_after=after.state.value,
                fast_sma=None,
                slow_sma=None,
                price=after.price,
                usdt_free=after.usdt_free,
                btc_qty=after.btc_qty,
                order_side=order.side.value if order else None,
                order_quote_usdt=order.executed_quote_usdt if order else None,
                order_base_qty=order.executed_base_qty if order else None,
                order_avg_price=order.average_price if order else None,
                order_id=order.exchange_order_id if order else None,
                order_status=order.raw_status if order else None,
                client_order_id=order.client_order_id if order else None,
                confidence=evidence.confidence,
                confidence_grade=evidence.grade,
                confidence_model=evidence.model_version,
                expected_edge_bps=evidence.expected_edge_bps,
                structural_confidence=evidence.structural_confidence,
                tactical_confidence=evidence.tactical_confidence,
                structural_return_bps=evidence.structural_return_bps,
                tactical_return_bps=evidence.tactical_return_bps,
                spread_bps=evidence.spread_bps,
                data_age_ms=evidence.data_age_ms,
                coverage=evidence.coverage,
                allocation_pct=self.engine.effective_params.allocation_fraction * D("100"),
                event_id=evidence.event_id,
                entry_price=state.entry_price,
                high_since_entry=state.high_since_entry,
                active_stop_price=self.engine.active_stop(evidence.price),
                engine_state_version=state.version,
                btc_free=after.btc_free,
                btc_locked=after.btc_locked,
                usdt_locked=after.usdt_locked,
                fees_usdt=order.fees_usdt if order else None,
                fees_by_asset=order.fees_by_asset if order else None,
                protective_order_id=state.protective_order_id,
                risk_per_trade_pct=(
                    self.engine.effective_params.risk_per_trade_fraction * D("100")
                ),
                breaker=self.engine.breaker_reason(after.equity),
                parameter_version=PARAMETER_VERSION,
                strategy_version=STRATEGY_VERSION,
                directional_model_version=(
                    agent.policy_version if agent is not None else None
                ),
                model_direction=(agent.decision.value if agent is not None else None),
                model_confidence=(
                    D(str(agent.confidence)) if agent is not None else None
                ),
                model_probabilities=(
                    {
                        name: D(str(probability))
                        for name, probability in agent.action_probabilities.items()
                    }
                    if agent is not None
                    else None
                ),
                online_learning=self._agent_online_learning(),
                order_authority=not self.dry_run,
                at=evidence.at,
            )
        )


__all__ = [
    "AdaptiveMarketObserver",
    "EnginePersistentState",
    "EngineStateStore",
    "EvidenceSnapshot",
    "ProtectiveDecisionEngine",
    "RealtimeDecision",
    "RealtimeDemoRunner",
    "RealtimeParams",
    "ReconciledPosition",
    "deterministic_client_order_id",
    "reconcile_realtime_position",
    "recover_engine_state",
    "size_entry_percentage",
    "size_exit_base",
]
