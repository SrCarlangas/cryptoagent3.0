"""Conservative local fill simulations; no network and no execution capability."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum

from btc_decision_agent.domain.contracts import BookSyncState, FreshnessStatus, QualityStatus


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class FillStatus(str, Enum):
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    NO_FILL = "NO_FILL"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class BookObservation:
    observed_at: datetime
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    generation_id: str
    sync_status: BookSyncState
    quality: QualityStatus
    freshness: FreshnessStatus
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() != UTC.utcoffset(self.observed_at):
            raise ValueError("book observation timestamp must be UTC")
        if not self.generation_id or not self.provenance:
            raise ValueError("book generation and provenance are required")
        if not self.bids or not self.asks or any(price <= 0 or quantity <= 0 for price, quantity in (*self.bids, *self.asks)):
            raise ValueError("book observation requires positive two-sided depth")
        if tuple(sorted(self.bids, reverse=True)) != self.bids or tuple(sorted(self.asks)) != self.asks or self.bids[0][0] > self.asks[0][0]:
            raise ValueError("book observation is unordered or crossed")

    @property
    def usable(self) -> bool:
        return self.sync_status == BookSyncState.LIVE and self.quality == QualityStatus.QUALIFIED and self.freshness == FreshnessStatus.FRESH


@dataclass(frozen=True)
class TradeObservation:
    observed_at: datetime
    price: Decimal
    quantity: Decimal
    trade_id: str
    generation_id: str
    quality: QualityStatus
    freshness: FreshnessStatus
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() != UTC.utcoffset(self.observed_at):
            raise ValueError("trade observation timestamp must be UTC")
        if self.price <= 0 or self.quantity <= 0 or not self.trade_id or not self.generation_id or not self.provenance:
            raise ValueError("trade observation requires positive values and provenance")

    @property
    def usable(self) -> bool:
        return self.quality == QualityStatus.QUALIFIED and self.freshness == FreshnessStatus.FRESH


@dataclass(frozen=True)
class SimulatedFill:
    status: FillStatus
    requested_qty: Decimal
    filled_qty: Decimal
    average_price: Decimal | None
    fee_paid: Decimal
    adverse_selection_cost: Decimal
    effective_at: datetime
    residual_qty: Decimal
    reason: str
    side: OrderSide
    book_generation_id: str | None
    evidence_refs: tuple[str, ...]


def _post_latency(books: Sequence[BookObservation], submitted_at: datetime, latency_ms: int) -> BookObservation:
    eligible_at = submitted_at + timedelta(milliseconds=latency_ms)
    for book in sorted(books, key=lambda value: value.observed_at):
        if book.observed_at >= eligible_at:
            if not book.usable:
                raise ValueError("post-latency book is not LIVE/fresh/qualified")
            return book
    raise ValueError("no post-latency book observation")


def simulate_market(side: OrderSide, quantity: Decimal, submitted_at: datetime, books: Sequence[BookObservation], *, latency_ms: int, taker_fee_rate: Decimal, adverse_selection_bps: Decimal) -> SimulatedFill:
    """Walk the first trustworthy post-latency book; visible depth bounds fills."""
    if quantity <= 0 or latency_ms < 0 or taker_fee_rate < 0 or adverse_selection_bps < 0:
        raise ValueError("invalid market simulation inputs")
    book = _post_latency(books, submitted_at, latency_ms)
    levels = book.asks if side == OrderSide.BUY else book.bids
    remaining, notional = quantity, Decimal("0")
    for price, available in levels:
        fill_qty = min(remaining, available)
        notional += price * fill_qty
        remaining -= fill_qty
        if remaining == 0:
            break
    filled = quantity - remaining
    refs = tuple(sorted(book.provenance))
    if filled == 0:
        return SimulatedFill(FillStatus.NO_FILL, quantity, Decimal("0"), None, Decimal("0"), Decimal("0"), book.observed_at, quantity, "NO_VISIBLE_DEPTH", side, book.generation_id, refs)
    average = notional / filled
    fee = notional * taker_fee_rate
    adverse = notional * adverse_selection_bps / Decimal("10000")
    status = FillStatus.FILLED if remaining == 0 else FillStatus.PARTIAL
    return SimulatedFill(status, quantity, filled, average, fee, adverse, book.observed_at, remaining, "BOOK_WALK", side, book.generation_id, refs)


def simulate_limit(side: OrderSide, quantity: Decimal, limit_price: Decimal, submitted_at: datetime, books: Sequence[BookObservation], trades: Sequence[TradeObservation], *, latency_ms: int, maker_fee_rate: Decimal, queue_ahead: Decimal, adverse_selection_bps: Decimal, cancelled: bool = False) -> SimulatedFill:
    """Fill only after side-aware price reach and traded-through evidence clears queue."""
    if quantity <= 0 or limit_price <= 0 or latency_ms < 0 or min(maker_fee_rate, queue_ahead, adverse_selection_bps) < 0:
        raise ValueError("invalid limit simulation inputs")
    book = _post_latency(books, submitted_at, latency_ms)
    effective = book.observed_at
    if cancelled:
        return SimulatedFill(FillStatus.CANCELLED, quantity, Decimal("0"), None, Decimal("0"), Decimal("0"), effective, quantity, "CANCELLED_BEFORE_FILL", side, book.generation_id, tuple(sorted(book.provenance)))
    eligible = [trade for trade in trades if trade.observed_at >= effective]
    if any(not trade.usable for trade in eligible):
        raise ValueError("trade evidence is not fresh/qualified")
    if any(trade.generation_id != book.generation_id for trade in eligible):
        raise ValueError("book/trade generation mismatch")
    reached = [trade for trade in eligible if trade.price <= limit_price] if side == OrderSide.BUY else [trade for trade in eligible if trade.price >= limit_price]
    if not reached:
        return SimulatedFill(FillStatus.NO_FILL, quantity, Decimal("0"), None, Decimal("0"), Decimal("0"), effective, quantity, "PRICE_NOT_REACHED", side, book.generation_id, tuple(sorted(book.provenance)))
    traded_through = sum((trade.quantity for trade in reached), Decimal("0"))
    executable_volume = max(Decimal("0"), traded_through - queue_ahead)
    filled = min(quantity, executable_volume)
    refs = tuple(sorted({*book.provenance, *(trade.trade_id for trade in reached), *(ref for trade in reached for ref in trade.provenance)}))
    if filled == 0:
        return SimulatedFill(FillStatus.NO_FILL, quantity, filled, None, Decimal("0"), Decimal("0"), reached[-1].observed_at, quantity, "QUEUE_NOT_CLEARED", side, book.generation_id, refs)
    notional = filled * limit_price
    status = FillStatus.FILLED if filled == quantity else FillStatus.PARTIAL
    return SimulatedFill(status, quantity, filled, limit_price, notional * maker_fee_rate, notional * adverse_selection_bps / Decimal("10000"), reached[-1].observed_at, quantity - filled, "QUEUE_CLEARED_CONSERVATIVELY", side, book.generation_id, refs)
