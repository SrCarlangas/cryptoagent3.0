"""Append-only activity journal for live demo observability.

Each evaluation appends one JSON line describing the decision, the position,
SMAs, balances and any order. The dashboard reads this file; nothing here places
orders or touches the network. Values are serialized as strings to preserve
Decimal precision.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


@dataclass(frozen=True)
class ActivityEntry:
    at: str
    venue: str
    interval: str
    action: str
    reason: str
    position_before: str
    fast_sma: str | None
    slow_sma: str | None
    price: str | None
    usdt_free: str | None
    btc_qty: str | None
    order_side: str | None
    order_quote_usdt: str | None
    order_base_qty: str | None
    order_avg_price: str | None
    order_id: str | None
    position_after: str | None = None
    confidence: str | None = None
    confidence_grade: str | None = None
    confidence_model: str | None = None
    expected_edge_bps: str | None = None
    spread_bps: str | None = None
    data_age_ms: int | None = None
    coverage: str | None = None
    allocation_pct: str | None = None
    event_id: str | None = None
    order_status: str | None = None
    client_order_id: str | None = None
    structural_confidence: str | None = None
    tactical_confidence: str | None = None
    structural_return_bps: str | None = None
    tactical_return_bps: str | None = None
    entry_price: str | None = None
    high_since_entry: str | None = None
    active_stop_price: str | None = None
    engine_state_version: str | None = None
    btc_free: str | None = None
    btc_locked: str | None = None
    usdt_locked: str | None = None
    fees_usdt: str | None = None
    fees_by_asset: dict[str, str] | None = None
    protective_order_id: str | None = None
    risk_per_trade_pct: str | None = None
    breaker: str | None = None
    parameter_version: str | None = None
    strategy_version: str | None = None
    directional_model_version: str | None = None
    model_direction: str | None = None
    model_confidence: str | None = None
    model_probabilities: dict[str, str] | None = None
    online_learning: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize all fields while remaining backward-compatible with old rows."""
        return dict(self.__dict__)


class ActivityJournal:
    """Durable JSONL journal; safe to read while the runner appends."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: ActivityEntry) -> None:
        line = json.dumps(entry.to_dict(), separators=(",", ":"), sort_keys=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def read(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if limit is not None:
            lines = lines[-limit:]
        entries: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                # A crash may leave only the final append incomplete. Earlier
                # corruption is not safe to ignore.
                if index == len(lines) - 1:
                    break
                raise
            if not isinstance(parsed, dict):
                raise ValueError("journal entry must be an object")
            entries.append(parsed)
        return entries


def entry_from_live(
    *,
    venue: str,
    interval: str,
    action: str,
    reason: str,
    position_before: str,
    fast_sma: Decimal | None,
    slow_sma: Decimal | None,
    price: Decimal | None,
    usdt_free: Decimal | None,
    btc_qty: Decimal | None,
    order_side: str | None = None,
    order_quote_usdt: Decimal | None = None,
    order_base_qty: Decimal | None = None,
    order_avg_price: Decimal | None = None,
    order_id: str | None = None,
    position_after: str | None = None,
    confidence: Decimal | None = None,
    confidence_grade: str | None = None,
    confidence_model: str | None = None,
    expected_edge_bps: Decimal | None = None,
    spread_bps: Decimal | None = None,
    data_age_ms: int | None = None,
    coverage: Decimal | None = None,
    allocation_pct: Decimal | None = None,
    event_id: str | None = None,
    order_status: str | None = None,
    client_order_id: str | None = None,
    structural_confidence: Decimal | None = None,
    tactical_confidence: Decimal | None = None,
    structural_return_bps: Decimal | None = None,
    tactical_return_bps: Decimal | None = None,
    entry_price: Decimal | None = None,
    high_since_entry: Decimal | None = None,
    active_stop_price: Decimal | None = None,
    engine_state_version: str | None = None,
    btc_free: Decimal | None = None,
    btc_locked: Decimal | None = None,
    usdt_locked: Decimal | None = None,
    fees_usdt: Decimal | None = None,
    fees_by_asset: dict[str, Decimal] | None = None,
    protective_order_id: str | None = None,
    risk_per_trade_pct: Decimal | None = None,
    breaker: str | None = None,
    parameter_version: str | None = None,
    strategy_version: str | None = None,
    directional_model_version: str | None = None,
    model_direction: str | None = None,
    model_confidence: Decimal | None = None,
    model_probabilities: dict[str, Decimal] | None = None,
    online_learning: bool | None = None,
    at: datetime | None = None,
) -> ActivityEntry:
    moment = at or datetime.now(tz=UTC)
    return ActivityEntry(
        at=moment.isoformat(timespec="seconds"),
        venue=venue,
        interval=interval,
        action=action,
        reason=reason,
        position_before=position_before,
        fast_sma=_s(fast_sma),
        slow_sma=_s(slow_sma),
        price=_s(price),
        usdt_free=_s(usdt_free),
        btc_qty=_s(btc_qty),
        order_side=order_side,
        order_quote_usdt=_s(order_quote_usdt),
        order_base_qty=_s(order_base_qty),
        order_avg_price=_s(order_avg_price),
        order_id=order_id,
        position_after=position_after,
        confidence=_s(confidence),
        confidence_grade=confidence_grade,
        confidence_model=confidence_model,
        expected_edge_bps=_s(expected_edge_bps),
        spread_bps=_s(spread_bps),
        data_age_ms=data_age_ms,
        coverage=_s(coverage),
        allocation_pct=_s(allocation_pct),
        event_id=event_id,
        order_status=order_status,
        client_order_id=client_order_id,
        structural_confidence=_s(structural_confidence),
        tactical_confidence=_s(tactical_confidence),
        structural_return_bps=_s(structural_return_bps),
        tactical_return_bps=_s(tactical_return_bps),
        entry_price=_s(entry_price),
        high_since_entry=_s(high_since_entry),
        active_stop_price=_s(active_stop_price),
        engine_state_version=engine_state_version,
        btc_free=_s(btc_free),
        btc_locked=_s(btc_locked),
        usdt_locked=_s(usdt_locked),
        fees_usdt=_s(fees_usdt),
        fees_by_asset=(
            {asset: format(amount, "f") for asset, amount in fees_by_asset.items()}
            if fees_by_asset is not None
            else None
        ),
        protective_order_id=protective_order_id,
        risk_per_trade_pct=_s(risk_per_trade_pct),
        breaker=breaker,
        parameter_version=parameter_version,
        strategy_version=strategy_version,
        directional_model_version=directional_model_version,
        model_direction=model_direction,
        model_confidence=_s(model_confidence),
        model_probabilities=(
            {name: format(value, "f") for name, value in model_probabilities.items()}
            if model_probabilities is not None
            else None
        ),
        online_learning=online_learning,
    )


__all__ = ["ActivityEntry", "ActivityJournal", "entry_from_live"]
