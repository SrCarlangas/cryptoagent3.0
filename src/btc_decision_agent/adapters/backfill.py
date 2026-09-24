"""Read-only public kline backfill and an immutable, versioned historical dataset.

Security: this module performs GET requests only against the public Binance
market-data host. It never sends orders, uses credentials, signs requests or
touches private endpoints. It is disabled unless the caller sets enabled=True.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import certifi

from btc_decision_agent.domain.canonical import canonical_json, sha256_id

PUBLIC_REST_BASE = "https://data-api.binance.vision"
KLINES_PATH = "/api/v3/klines"
PROVIDER_CONTRACT_VERSION = "BINANCE_SPOT_DOCS_2026-09-15"
PRIVATE_MARKERS = frozenset({"apiKey", "signature", "listenKey", "/api/v3/order", "/api/v3/account"})
MAX_LIMIT = 1000
_USER_AGENT = "btc-decision-agent-backfill/0.1 (public-market-data; read-only)"


def _interval_ms(interval: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    return int(interval[:-1]) * units[interval[-1]]


def _epoch_ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("backfill timestamps must be UTC")
    return int(value.timestamp() * 1000)


@dataclass(frozen=True)
class BackfillConfig:
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    start: datetime = datetime(2020, 1, 1, tzinfo=UTC)
    end: datetime | None = None
    rest_base: str = PUBLIC_REST_BASE
    request_limit: int = MAX_LIMIT
    max_requests: int = 100_000
    timeout_s: float = 30.0
    max_retries: int = 5
    backoff_base_s: float = 1.0

    def __post_init__(self) -> None:
        if any(marker in self.rest_base for marker in PRIVATE_MARKERS):
            raise ValueError("private/authenticated endpoint is prohibited")
        if not self.rest_base.startswith("https://"):
            raise ValueError("backfill requires https public market data")
        if self.request_limit < 1 or self.request_limit > MAX_LIMIT:
            raise ValueError("request limit out of public bounds")


class PublicKlineBackfill:
    """Paginate public klines with bounded retries and jitter; no private access."""

    def __init__(self, config: BackfillConfig, *, enabled: bool = False) -> None:
        self.config = config
        self.enabled = enabled
        self._context = ssl.create_default_context(cafile=certifi.where())

    def _request(self, start_ms: int) -> list[list[Any]]:
        query = f"symbol={self.config.symbol}&interval={self.config.interval}&limit={self.config.request_limit}&startTime={start_ms}"
        url = f"{self.config.rest_base}{KLINES_PATH}?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT}, method="GET")
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_s, context=self._context) as response:
                    payload = json.load(response)
                if not isinstance(payload, list):
                    raise ValueError("unexpected klines payload shape")
                return payload
            except urllib.error.HTTPError as error:
                if error.code in {418, 429}:
                    retry_after = error.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else self.config.backoff_base_s * (2**attempt)
                    time.sleep(min(delay, 60.0))
                    last_error = error
                    continue
                raise
            except (urllib.error.URLError, TimeoutError) as error:
                time.sleep(min(self.config.backoff_base_s * (2**attempt) + attempt * 0.1, 60.0))
                last_error = error
        raise RuntimeError(f"backfill request failed after retries: {last_error}")

    def iter_closed_klines(self) -> Iterator[dict[str, Any]]:
        """Yield only closed 1h klines strictly before now, in ascending open time."""
        if not self.enabled:
            raise RuntimeError("backfill adapter is disabled by default; explicit opt-in required")
        interval_ms = _interval_ms(self.config.interval)
        cursor = _epoch_ms(self.config.start)
        end_ms = _epoch_ms(self.config.end) if self.config.end else _epoch_ms(datetime.now(tz=UTC))
        seen_last: int | None = None
        for _ in range(self.config.max_requests):
            if cursor >= end_ms:
                return
            rows = self._request(cursor)
            if not rows:
                return
            progressed = False
            for row in rows:
                open_ms, close_ms = int(row[0]), int(row[6])
                if close_ms >= end_ms:
                    continue
                if seen_last is not None and open_ms <= seen_last:
                    continue
                seen_last = open_ms
                progressed = True
                yield {
                    "open_time": open_ms,
                    "close_time": close_ms,
                    "open": str(row[1]),
                    "high": str(row[2]),
                    "low": str(row[3]),
                    "close": str(row[4]),
                    "base_volume": str(row[5]),
                    "quote_volume": str(row[7]),
                    "trade_count": int(row[8]),
                }
            next_cursor = (seen_last + interval_ms) if seen_last is not None else cursor + interval_ms
            if not progressed or next_cursor <= cursor:
                return
            cursor = next_cursor


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    symbol: str
    interval: str
    provider_contract_version: str
    row_count: int
    first_open_time: str
    last_close_time: str
    gap_count: int
    gaps: tuple[dict[str, Any], ...]
    content_hash: str
    created_at: str


class HistoricalDataset:
    """Immutable JSONL dataset with a manifest for reproducible offline validation."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.data_path = self.directory / "klines-1h.jsonl"
        self.manifest_path = self.directory / "manifest.json"

    def write(self, config: BackfillConfig, rows: list[dict[str, Any]]) -> DatasetManifest:
        if not rows:
            raise ValueError("refusing to freeze an empty dataset")
        ordered = sorted(rows, key=lambda item: item["open_time"])
        if len({row["open_time"] for row in ordered}) != len(ordered):
            raise ValueError("dataset contains duplicate open times")
        interval_ms = _interval_ms(config.interval)
        gaps: list[dict[str, Any]] = []
        for previous, current in pairwise(ordered):
            delta = current["open_time"] - previous["open_time"]
            if delta < interval_ms:
                raise ValueError("dataset is not monotonic before freeze")
            if delta != interval_ms:
                gaps.append(
                    {
                        "after_open_time": _iso(previous["open_time"]),
                        "before_open_time": _iso(current["open_time"]),
                        "missing_bars": delta // interval_ms - 1,
                    }
                )
        self.directory.mkdir(parents=True, exist_ok=True)
        lines = [canonical_json(row) for row in ordered]
        self.data_path.write_bytes(b"\n".join(lines) + b"\n")
        content_hash = sha256_id({"rows": ordered, "provider": config.symbol, "interval": config.interval})
        manifest = DatasetManifest(
            dataset_id=sha256_id({"content": content_hash, "symbol": config.symbol, "interval": config.interval}),
            symbol=config.symbol,
            interval=config.interval,
            provider_contract_version=PROVIDER_CONTRACT_VERSION,
            row_count=len(ordered),
            first_open_time=_iso(ordered[0]["open_time"]),
            last_close_time=_iso(ordered[-1]["close_time"]),
            gap_count=len(gaps),
            gaps=tuple(gaps),
            content_hash=content_hash,
            created_at=datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        )
        self.manifest_path.write_text(json.dumps(manifest.__dict__, indent=2, sort_keys=True) + "\n")
        return manifest

    def load(self) -> tuple[DatasetManifest, tuple[dict[str, Any], ...]]:
        raw_manifest = json.loads(self.manifest_path.read_text())
        raw_manifest["gaps"] = tuple(dict(gap) for gap in raw_manifest.get("gaps", ()))
        manifest = DatasetManifest(**raw_manifest)
        rows = tuple(json.loads(line) for line in self.data_path.read_bytes().splitlines())
        recomputed = sha256_id({"rows": [dict(row) for row in rows], "provider": manifest.symbol, "interval": manifest.interval})
        if recomputed != manifest.content_hash or len(rows) != manifest.row_count:
            raise ValueError("dataset content does not match its manifest hash")
        return manifest, rows


def _iso(open_ms: int) -> str:
    return datetime.fromtimestamp(open_ms / 1000, tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def as_decimal_bars(rows: tuple[dict[str, Any], ...], *, interval: str = "1h") -> tuple[dict[str, Any], ...]:
    """Project frozen rows into Decimal OHLCV bars using the half-open [open, close) convention.

    Binance reports close_time as open + interval - 1 ms. The canonical bar close
    is the start of the next interval (open + interval), so contiguous bars satisfy
    ``left.close_time == right.open_time``. The raw provider close is preserved.
    """
    interval_ms = _interval_ms(interval)
    projected = []
    for row in rows:
        open_time = datetime.fromtimestamp(row["open_time"] / 1000, tz=UTC)
        projected.append(
            {
                "open_time": open_time,
                "close_time": datetime.fromtimestamp((row["open_time"] + interval_ms) / 1000, tz=UTC),
                "provider_close_time": datetime.fromtimestamp(row["close_time"] / 1000, tz=UTC),
                "open": Decimal(str(row["open"])),
                "high": Decimal(str(row["high"])),
                "low": Decimal(str(row["low"])),
                "close": Decimal(str(row["close"])),
                "base_volume": Decimal(str(row["base_volume"])),
            }
        )
    return tuple(projected)
