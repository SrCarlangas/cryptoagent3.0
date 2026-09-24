"""Fixture-first Binance public market-data normalization; network is never automatic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from btc_decision_agent.domain.canonical import sha256_id
from btc_decision_agent.domain.contracts import (
    DeliveryMetadata,
    EventType,
    MarketEventV1,
    QualityMetadata,
    RawMarketEvent,
    SequenceMetadata,
    Transport,
)

PROVIDER_VERSION = "BINANCE_SPOT_DOCS_2026-09-15"
PUBLIC_REST_BASE = "https://data-api.binance.vision"
PUBLIC_WS_BASE = "wss://data-stream.binance.vision"
PUBLIC_PATHS = frozenset({"/api/v3/klines", "/api/v3/depth", "/api/v3/ticker/24hr", "/api/v3/exchangeInfo"})
PRIVATE_MARKERS = frozenset({"apiKey", "signature", "listenKey", "/api/v3/order", "/api/v3/account"})
SOURCE_IDS = frozenset(f"S-{number:02d}" for number in range(1, 10))


def _utc_ms(value: int | str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("decimal field is missing or boolean")
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("decimal field must be finite")
    return parsed


def _symbol(raw: str) -> str:
    if raw.upper() != "BTCUSDT":
        raise ValueError("SYMBOL_MISMATCH")
    return "BTC/USDT"


def _levels(raw: list[list[str]]) -> tuple[tuple[Decimal, Decimal], ...]:
    return tuple((_decimal(level[0]), _decimal(level[1])) for level in raw)


class PublicMarketDataAdapter:
    """Configuration-only public adapter boundary, disabled unless explicitly enabled."""

    def __init__(self, *, enabled: bool = False, rest_base: str = PUBLIC_REST_BASE, ws_base: str = PUBLIC_WS_BASE) -> None:
        if any(marker in rest_base or marker in ws_base for marker in PRIVATE_MARKERS):
            raise ValueError("private/authenticated endpoint is prohibited")
        self.enabled = enabled
        self.rest_base = rest_base
        self.ws_base = ws_base

    def assert_offline(self) -> None:
        if self.enabled:
            raise RuntimeError("network adapter enabled; offline workflow refuses activation")

    def request_spec(self, path: str) -> tuple[str, str]:
        """Return a public request description without performing I/O."""
        if not self.enabled:
            raise RuntimeError("public network adapter is disabled by default")
        if path not in PUBLIC_PATHS:
            raise ValueError("only allowlisted public market-data paths are permitted")
        return "GET", f"{self.rest_base}{path}"


def normalize(raw: RawMarketEvent, *, transport: Transport = Transport.FIXTURE) -> MarketEventV1:
    """Normalize one versioned S-01..S-09 fixture into MarketEventV1."""
    source = raw.source_contract_id
    if source not in SOURCE_IDS:
        raise ValueError("unknown source contract")
    data = raw.raw_payload
    event_type: EventType
    event_time: datetime | None
    emitted_at: datetime | None
    identity: dict[str, Any]
    sequence_first: int | None = None
    sequence_last: int | None = None
    payload: dict[str, Any]
    symbol_raw = str(data.get("s", data.get("symbol", "BTCUSDT")))

    if source == "S-01":
        event_type, event_time, emitted_at = EventType.AGG_TRADE, _utc_ms(data["T"]), _utc_ms(data["E"])
        identity = {"aggregate_trade_id": int(data["a"])}
        sequence_first = sequence_last = int(data["a"])
        payload = {"price": _decimal(data["p"]), "base_qty": _decimal(data["q"]), "first_trade_id": int(data["f"]), "last_trade_id": int(data["l"]), "buyer_is_maker": bool(data["m"]), "aggressor_side": "SELL" if data["m"] else "BUY"}
        if payload["price"] <= 0 or payload["base_qty"] <= 0 or payload["first_trade_id"] > payload["last_trade_id"]:
            raise ValueError("invalid aggregate trade")
    elif source == "S-02":
        kline = data["k"]
        closed = bool(kline["x"])
        event_type, event_time, emitted_at = (EventType.KLINE_CLOSED if closed else EventType.KLINE_UPDATE), _utc_ms(kline["T"] if closed else data["E"]), _utc_ms(data["E"])
        identity = {"interval": kline["i"], "open_time": int(kline["t"]), "is_closed": closed}
        payload = {"bar_open_time": _utc_ms(kline["t"]), "bar_close_time": _utc_ms(kline["T"]), "interval": str(kline["i"]), "open": _decimal(kline["o"]), "high": _decimal(kline["h"]), "low": _decimal(kline["l"]), "close": _decimal(kline["c"]), "base_volume": _decimal(kline["v"]), "quote_volume": _decimal(kline["q"]), "trade_count": int(kline["n"]), "is_closed": closed}
        if payload["low"] > min(payload["open"], payload["close"]) or max(payload["open"], payload["close"]) > payload["high"] or payload["base_volume"] < 0:
            raise ValueError("invalid kline OHLCV")
    elif source == "S-03":
        values = data["kline"] if isinstance(data, dict) else data
        event_type, event_time, emitted_at = EventType.KLINE_CLOSED, _utc_ms(values[6]), None
        identity = {"interval": data.get("interval", "1h"), "open_time": int(values[0])}
        payload = {"bar_open_time": _utc_ms(values[0]), "bar_close_time": _utc_ms(values[6]), "interval": data.get("interval", "1h"), "open": _decimal(values[1]), "high": _decimal(values[2]), "low": _decimal(values[3]), "close": _decimal(values[4]), "base_volume": _decimal(values[5]), "quote_volume": _decimal(values[7]), "trade_count": int(values[8]), "is_closed": True}
    elif source == "S-04":
        event_type, event_time, emitted_at = EventType.BBO_UPDATE, None, None
        identity = {"update_id": int(data["u"])}
        sequence_first = sequence_last = int(data["u"])
        payload = {"bid_price": _decimal(data["b"]), "bid_qty": _decimal(data["B"]), "ask_price": _decimal(data["a"]), "ask_qty": _decimal(data["A"])}
        if payload["bid_price"] <= 0 or payload["bid_price"] > payload["ask_price"] or payload["bid_qty"] < 0 or payload["ask_qty"] < 0:
            raise ValueError("invalid BBO")
    elif source == "S-05":
        event_type, event_time, emitted_at = EventType.DEPTH_DIFF, _utc_ms(data["E"]), _utc_ms(data["E"])
        sequence_first, sequence_last = int(data["U"]), int(data["u"])
        identity = {"first_update_id": sequence_first, "final_update_id": sequence_last}
        payload = {"bids": _levels(data["b"]), "asks": _levels(data["a"])}
        if sequence_first > sequence_last:
            raise ValueError("invalid depth sequence")
    elif source == "S-06":
        event_type, event_time, emitted_at = EventType.DEPTH_SNAPSHOT, None, None
        sequence_first = sequence_last = int(data["lastUpdateId"])
        identity = {"last_update_id": sequence_last}
        payload = {"bids": _levels(data["bids"]), "asks": _levels(data["asks"]), "snapshot_limit": int(data.get("limit", 5000))}
    elif source in {"S-07", "S-08"}:
        window_open = data.get("O", data.get("openTime"))
        window_close = data.get("C", data.get("closeTime"))
        if window_open is None or window_close is None:
            raise ValueError("ticker window identity is missing")
        event_type, event_time, emitted_at = (
            EventType.TICKER_24H,
            _utc_ms(window_close),
            _utc_ms(data.get("E")),
        )
        identity = {"window_open": int(window_open), "window_close": int(window_close)}
        payload = {"last_price": _decimal(data.get("c", data.get("lastPrice"))), "open_price": _decimal(data.get("o", data.get("openPrice"))), "high_price": _decimal(data.get("h", data.get("highPrice"))), "low_price": _decimal(data.get("l", data.get("lowPrice"))), "base_volume": _decimal(data.get("v", data.get("volume"))), "quote_volume": _decimal(data.get("q", data.get("quoteVolume")))}
    else:
        event_type, event_time, emitted_at = EventType.SYMBOL_METADATA, raw.observed_at, None
        identity = {"symbol": symbol_raw, "response_hash": sha256_id(data)}
        symbol_info = data["symbols"][0] if "symbols" in data else data
        payload = {"status": symbol_info["status"], "base_asset": symbol_info["baseAsset"], "quote_asset": symbol_info["quoteAsset"], "filters": tuple(symbol_info.get("filters", ())), "order_types": tuple(symbol_info.get("orderTypes", ())), "spot_allowed": bool(symbol_info.get("isSpotTradingAllowed", True))}
        if payload["status"] != "TRADING" or not payload["spot_allowed"]:
            raise ValueError("symbol is not eligible for spot decisions")

    canonical_symbol = _symbol(symbol_raw)
    payload_hash = sha256_id(payload)
    source_key = {"provider": "BINANCE_SPOT", "source_contract_id": source, "event_type": event_type, "symbol": canonical_symbol, "source_identity": identity, "payload_hash": payload_hash}
    event_id = sha256_id(source_key)
    sequence_metadata = SequenceMetadata(
        first=sequence_first,
        last=sequence_last,
        identity_ref=None if sequence_first is not None else event_id,
    )
    return MarketEventV1(event_id=event_id, event_type=event_type, source_contract_id=source, provider_contract_version=PROVIDER_VERSION, transport=transport, channel=raw.channel, symbol=canonical_symbol, connection_id=raw.channel, precision_ref="S-09", raw_ref=raw.raw_ref, event_time=event_time, provider_emitted_at=emitted_at, observed_at=raw.observed_at, source_identity=identity, sequence_first=sequence_first, sequence_last=sequence_last, sequence_metadata=sequence_metadata, payload=payload, payload_hash=payload_hash, provenance={"data_source": "FIXTURE" if transport == Transport.FIXTURE else transport.value, "transform_version": "1.0.0", "source_refs": (raw.raw_ref,) if raw.raw_ref else ()}, delivery_metadata=DeliveryMetadata(connection_id=raw.channel), quality_metadata=QualityMetadata())
