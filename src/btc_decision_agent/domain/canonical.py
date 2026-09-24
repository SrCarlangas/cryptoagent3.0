"""Canonical serialization primitives used by every deterministic identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel


def require_utc(value: datetime) -> datetime:
    """Reject naive/non-UTC timestamps and normalize UTC aliases."""
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value.astimezone(UTC)


def decimal_text(value: Decimal) -> str:
    """Return a locale-independent, non-exponent decimal representation."""
    if not value.is_finite():
        raise ValueError("decimal must be finite")
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def canonical_value(value: Any) -> Any:
    """Convert supported domain values to canonical JSON-compatible values."""
    if isinstance(value, BaseModel):
        return canonical_value(value.model_dump(mode="python"))
    if is_dataclass(value) and not isinstance(value, type):
        return canonical_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, datetime):
        stamp = require_utc(value)
        if stamp.microsecond:
            return stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")
        return stamp.isoformat(timespec="seconds").replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        converted = [canonical_value(item) for item in value]
        return sorted(converted, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def canonical_json(value: Any) -> bytes:
    """Serialize with sorted keys and no insignificant whitespace."""
    return json.dumps(
        canonical_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_id(value: Any) -> str:
    """Return a namespaced SHA-256 identity for canonical content."""
    return f"sha256:{hashlib.sha256(canonical_json(value)).hexdigest()}"
