"""Revocable Binance local L2 book with atomic generations (L2-001..023)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from btc_decision_agent.domain.canonical import sha256_id
from btc_decision_agent.domain.contracts import BookSyncState, LocalBookView, QualityStatus


class BookEvent(str, Enum):
    WS_OPEN = "WS_OPEN"
    DIFF = "DIFF"
    SNAPSHOT_REQUESTED = "SNAPSHOT_REQUESTED"
    SNAPSHOT = "SNAPSHOT"
    SNAPSHOT_ERROR = "SNAPSHOT_ERROR"
    WS_CLOSE = "WS_CLOSE"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    BUFFER_OVERFLOW = "BUFFER_OVERFLOW"
    INCOMPATIBLE = "INCOMPATIBLE"
    INVARIANT_FAILURE = "INVARIANT_FAILURE"
    BACKOFF_EXPIRED = "BACKOFF_EXPIRED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    RESET = "RESET"


@dataclass(frozen=True)
class DepthDiff:
    first_update_id: int
    final_update_id: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    event_time: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.first_update_id > self.final_update_id:
            raise ValueError("invalid diff range")


@dataclass(frozen=True)
class DepthSnapshot:
    last_update_id: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    limit: int
    observed_at: datetime


@dataclass
class BookGeneration:
    generation_id: str
    connection_id: str
    symbol: str
    metadata_version: str
    state: BookSyncState = BookSyncState.UNINITIALIZED
    snapshot_last_update_id: int | None = None
    last_update_id: int | None = None
    snapshot_limit: int = 5000
    first_buffered_u: int | None = None
    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    asks: dict[Decimal, Decimal] = field(default_factory=dict)
    buffer: list[DepthDiff] = field(default_factory=list)
    event_time_max: datetime | None = None
    observed_at: datetime | None = None
    revoked: bool = False
    rule_id: str = "L2-000"


class LocalBook:
    """Single-writer generation builder; views publish only from continuous LIVE state."""

    def __init__(self, connection_id: str, metadata_version: str, *, max_buffer_events: int = 10_000) -> None:
        generation_id = sha256_id({"connection": connection_id, "metadata": metadata_version})
        self.generation = BookGeneration(generation_id, connection_id, "BTC/USDT", metadata_version)
        self.max_buffer_events = max_buffer_events

    @property
    def state(self) -> BookSyncState:
        return self.generation.state

    def open(self) -> None:
        if self.state != BookSyncState.UNINITIALIZED:
            raise ValueError("L2-001 requires UNINITIALIZED")
        self.generation.state, self.generation.rule_id = BookSyncState.BUFFERING, "L2-001"

    def request_snapshot(self) -> None:
        if self.state != BookSyncState.BUFFERING:
            raise ValueError("L2-003 requires BUFFERING")
        self.generation.state, self.generation.rule_id = BookSyncState.SNAPSHOT_PENDING, "L2-003"

    def buffer_diff(self, diff: DepthDiff) -> None:
        if self.state not in {BookSyncState.BUFFERING, BookSyncState.SNAPSHOT_PENDING}:
            raise ValueError("diff buffering only allowed before replay")
        if self.generation.first_buffered_u is None:
            self.generation.first_buffered_u = diff.first_update_id
            self.generation.rule_id = "L2-002"
        else:
            self.generation.rule_id = "L2-004"
        self.generation.buffer.append(diff)
        if len(self.generation.buffer) > self.max_buffer_events:
            self._gap("L2-016")

    def load_snapshot(self, snapshot: DepthSnapshot) -> bool:
        if self.state != BookSyncState.SNAPSHOT_PENDING:
            raise ValueError("snapshot requires SNAPSHOT_PENDING")
        first = self.generation.first_buffered_u
        if first is not None and snapshot.last_update_id + 1 < first:
            self.generation.rule_id = "L2-006"
            return False
        self.generation.snapshot_last_update_id = snapshot.last_update_id
        self.generation.last_update_id = snapshot.last_update_id
        self.generation.snapshot_limit = snapshot.limit
        self.generation.bids = {price: qty for price, qty in snapshot.bids if qty > 0}
        self.generation.asks = {price: qty for price, qty in snapshot.asks if qty > 0}
        self.generation.observed_at = snapshot.observed_at
        self.generation.state, self.generation.rule_id = BookSyncState.REPLAYING, "L2-007"
        buffered = tuple(self.generation.buffer)
        self.generation.buffer.clear()
        for diff in buffered:
            if diff.final_update_id <= snapshot.last_update_id:
                continue
            if not self.apply_diff(diff, replay=True):
                return False
        if not self._invariants():
            self.block("L2-018")
            return False
        self.generation.state, self.generation.rule_id = BookSyncState.LIVE, "L2-009"
        return True

    def apply_diff(self, diff: DepthDiff, *, replay: bool = False) -> bool:
        if self.state not in ({BookSyncState.REPLAYING} if replay else {BookSyncState.LIVE}):
            raise ValueError("diff application requires REPLAYING or LIVE")
        local_id = self.generation.last_update_id
        if local_id is None:
            self.block("L2-018")
            return False
        if diff.final_update_id <= local_id:
            self.generation.rule_id = "L2-011" if self.state == BookSyncState.LIVE else "L2-008"
            return True
        if diff.first_update_id > local_id + 1:
            self._gap("L2-010" if replay else "L2-013")
            return False
        if (
            self.generation.event_time_max is not None
            and diff.event_time < self.generation.event_time_max
        ) or (
            self.generation.observed_at is not None
            and diff.observed_at < self.generation.observed_at
        ):
            self.block("L2-018-TIME_REGRESSION")
            return False
        self._replace_levels(self.generation.bids, diff.bids)
        self._replace_levels(self.generation.asks, diff.asks)
        self.generation.last_update_id = diff.final_update_id
        self.generation.event_time_max = diff.event_time
        self.generation.observed_at = diff.observed_at
        self.generation.rule_id = "L2-008" if replay else "L2-012"
        if not self._invariants():
            self.block("L2-018")
            return False
        return True

    @staticmethod
    def _replace_levels(side: dict[Decimal, Decimal], levels: Iterable[tuple[Decimal, Decimal]]) -> None:
        for price, quantity in levels:
            if price <= 0 or quantity < 0:
                raise ValueError("invalid depth level")
            if quantity == 0:
                side.pop(price, None)
            else:
                side[price] = quantity

    def _invariants(self) -> bool:
        return bool(self.generation.bids and self.generation.asks and max(self.generation.bids) <= min(self.generation.asks))

    def _gap(self, rule: str) -> None:
        self.generation.revoked = True
        self.generation.state = BookSyncState.GAP_DETECTED
        self.generation.rule_id = rule

    def transport_fault(self, *, heartbeat: bool = False) -> None:
        if self.state in {BookSyncState.BUFFERING, BookSyncState.SNAPSHOT_PENDING, BookSyncState.REPLAYING, BookSyncState.LIVE}:
            self._gap("L2-015" if heartbeat else "L2-014")

    def snapshot_error(self) -> None:
        self.generation.revoked = True
        self.generation.state, self.generation.rule_id = BookSyncState.RESYNC_BACKOFF, "L2-005"

    def begin_backoff(self) -> None:
        if self.state != BookSyncState.GAP_DETECTED:
            raise ValueError("L2-019 requires GAP_DETECTED")
        self.generation.state, self.generation.rule_id = BookSyncState.RESYNC_BACKOFF, "L2-019"

    def backoff_expired(self, *, budget_available: bool) -> None:
        if self.state != BookSyncState.RESYNC_BACKOFF:
            raise ValueError("backoff event requires RESYNC_BACKOFF")
        if budget_available:
            old = self.generation
            self.generation = BookGeneration(
                sha256_id({"prior": old.generation_id, "resync": True}),
                f"{old.connection_id}:resync",
                old.symbol,
                old.metadata_version,
                rule_id="L2-020",
            )
        else:
            self.generation.state, self.generation.rule_id = BookSyncState.BLOCKED, "L2-021"

    def block(self, rule: str = "L2-017") -> None:
        self.generation.revoked = True
        self.generation.state, self.generation.rule_id = BookSyncState.BLOCKED, rule

    def reset(self) -> None:
        if self.state != BookSyncState.BLOCKED:
            raise ValueError("L2-022 requires BLOCKED")
        old = self.generation
        self.generation = BookGeneration(sha256_id({"prior": old.generation_id, "reset": True}), old.connection_id, old.symbol, old.metadata_version, rule_id="L2-022")

    def handoff(self, replacement: LocalBook) -> None:
        """L2-023: atomically replace one LIVE generation with another LIVE generation."""
        if self.state != BookSyncState.LIVE or replacement.state != BookSyncState.LIVE:
            raise ValueError("L2-023 requires old and replacement generations LIVE")
        if self.generation.symbol != replacement.generation.symbol or self.generation.metadata_version != replacement.generation.metadata_version:
            raise ValueError("L2-023 generation metadata mismatch")
        self.generation = replacement.generation
        self.generation.rule_id = "L2-023"

    def view(self) -> LocalBookView:
        if self.state != BookSyncState.LIVE or self.generation.revoked or self.generation.event_time_max is None or self.generation.observed_at is None or self.generation.last_update_id is None:
            raise RuntimeError("revoked/non-LIVE book cannot publish")
        bids = tuple(sorted(self.generation.bids.items(), reverse=True))
        asks = tuple(sorted(self.generation.asks.items()))
        return LocalBookView(book_generation_id=self.generation.generation_id, symbol=self.generation.symbol, metadata_version=self.generation.metadata_version, last_update_id=self.generation.last_update_id, bids=bids, asks=asks, snapshot_limit=self.generation.snapshot_limit, event_time_max=self.generation.event_time_max, observed_at=self.generation.observed_at, sync_status=BookSyncState.LIVE, quality=QualityStatus.QUALIFIED)
