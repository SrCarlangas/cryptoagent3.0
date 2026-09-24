"""Public Binance WebSocket ingestion for the demo decision runtime.

The adapter is read-only and emits typed observations. It owns reconnect and
heartbeat handling, but it never decides or places orders.
"""

from __future__ import annotations

import json
import logging
import ssl
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

import certifi
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

PUBLIC_WS_BASE = "wss://data-stream.binance.vision"
_LOGGER = logging.getLogger(__name__)


class StreamEventType(str, Enum):
    AGG_TRADE = "AGG_TRADE"
    BBO = "BBO"
    KLINE_UPDATE = "KLINE_UPDATE"
    KLINE_CLOSED = "KLINE_CLOSED"


@dataclass(frozen=True)
class StreamEvent:
    event_type: StreamEventType
    event_id: str
    event_time: datetime
    observed_at: datetime
    price: Decimal | None = None
    quantity: Decimal | None = None
    buyer_is_maker: bool | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    bar_open_time: datetime | None = None
    bar_close_time: datetime | None = None
    bar_open: Decimal | None = None
    bar_high: Decimal | None = None
    bar_low: Decimal | None = None
    bar_close: Decimal | None = None
    bar_volume: Decimal | None = None
    bar_closed: bool = False


def _utc_ms(value: object) -> datetime:
    return datetime.fromtimestamp(int(str(value)) / 1000, tz=UTC)


def _decimal(value: object) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("stream decimal must be finite")
    return parsed


def parse_stream_message(message: str | bytes, *, observed_at: datetime | None = None) -> StreamEvent:
    """Parse one Binance combined-stream message into a typed observation."""
    raw: object = json.loads(message)
    if not isinstance(raw, Mapping):
        raise ValueError("stream message must be an object")
    data = raw.get("data", raw)
    if not isinstance(data, Mapping):
        raise ValueError("stream payload must be an object")
    observed = observed_at or datetime.now(tz=UTC)
    kind = str(data.get("e", ""))
    if not kind and all(key in data for key in ("u", "b", "a")):
        kind = "bookTicker"

    if kind == "aggTrade":
        aggregate_id = int(data["a"])
        price, quantity = _decimal(data["p"]), _decimal(data["q"])
        maker = data["m"]
        if price <= 0 or quantity <= 0 or not isinstance(maker, bool):
            raise ValueError("invalid aggregate trade")
        return StreamEvent(
            event_type=StreamEventType.AGG_TRADE,
            event_id=f"trade:{aggregate_id}",
            event_time=_utc_ms(data["T"]),
            observed_at=observed,
            price=price,
            quantity=quantity,
            buyer_is_maker=maker,
        )

    if kind == "bookTicker":
        update_id = int(data["u"])
        bid, ask = _decimal(data["b"]), _decimal(data["a"])
        if bid <= 0 or ask < bid:
            raise ValueError("invalid BBO")
        return StreamEvent(
            event_type=StreamEventType.BBO,
            event_id=f"bbo:{update_id}",
            event_time=observed,
            observed_at=observed,
            bid=bid,
            ask=ask,
            price=(bid + ask) / Decimal("2"),
        )

    if kind == "kline":
        kline = data.get("k")
        if not isinstance(kline, Mapping):
            raise ValueError("kline payload is missing")
        closed = bool(kline["x"])
        open_time = _utc_ms(kline["t"])
        event_type = StreamEventType.KLINE_CLOSED if closed else StreamEventType.KLINE_UPDATE
        # Every forming update is a revision, so E (not only bar identity) is part
        # of the event id. The final close has its own stable identity.
        revision = int(data["E"])
        event_id = f"kline:{kline['i']}:{int(kline['t'])}:{'final' if closed else revision}"
        bar_open = _decimal(kline["o"])
        bar_high = _decimal(kline["h"])
        bar_low = _decimal(kline["l"])
        bar_close = _decimal(kline["c"])
        bar_volume = _decimal(kline["v"])
        if (
            min(bar_open, bar_high, bar_low, bar_close) <= 0
            or bar_low > min(bar_open, bar_close)
            or bar_high < max(bar_open, bar_close)
            or bar_volume < 0
        ):
            raise ValueError("invalid kline")
        return StreamEvent(
            event_type=event_type,
            event_id=event_id,
            event_time=_utc_ms(kline["T"] if closed else data["E"]),
            observed_at=observed,
            price=bar_close,
            bar_open_time=open_time,
            bar_close_time=_utc_ms(kline["T"]),
            bar_open=bar_open,
            bar_high=bar_high,
            bar_low=bar_low,
            bar_close=bar_close,
            bar_volume=bar_volume,
            bar_closed=closed,
        )

    raise ValueError(f"unsupported stream event: {kind or 'unknown'}")


class BinancePublicStreamAdapter:
    """Reconnectable public stream for trades, BBO and one-minute klines."""

    def __init__(
        self,
        *,
        symbol: str = "btcusdt",
        ws_base: str = PUBLIC_WS_BASE,
        reconnect_max_seconds: float = 30.0,
    ) -> None:
        normalized = symbol.lower()
        if not normalized.isalnum():
            raise ValueError("symbol must be alphanumeric")
        if not ws_base.startswith("wss://"):
            raise ValueError("public stream must use wss")
        if reconnect_max_seconds <= 0:
            raise ValueError("reconnect_max_seconds must be positive")
        self.symbol = normalized
        self.ws_base = ws_base.rstrip("/")
        self.reconnect_max_seconds = reconnect_max_seconds
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.last_error: str | None = None

    @property
    def url(self) -> str:
        streams = "/".join(
            (
                f"{self.symbol}@aggTrade",
                f"{self.symbol}@bookTicker",
                f"{self.symbol}@kline_1m",
            )
        )
        return f"{self.ws_base}/stream?streams={streams}"

    def events(self, stop: threading.Event) -> Iterator[StreamEvent]:
        """Yield observations until stopped; reconnect with bounded backoff."""
        backoff = 1.0
        while not stop.is_set():
            try:
                with connect(
                    self.url,
                    ssl=self._ssl_context,
                    open_timeout=10,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_queue=1024,
                    user_agent_header="btc-decision-agent/0.1",
                ) as socket:
                    backoff = 1.0
                    while not stop.is_set():
                        try:
                            message = socket.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        try:
                            yield parse_stream_message(message)
                        except (
                            InvalidOperation,
                            KeyError,
                            OverflowError,
                            TypeError,
                            ValueError,
                            json.JSONDecodeError,
                        ) as error:
                            self.last_error = f"{type(error).__name__}: {error}"
                            _LOGGER.warning("Binance stream message skipped: %s", self.last_error)
            except (ConnectionClosed, OSError, TimeoutError) as error:
                if stop.is_set():
                    break
                self.last_error = f"{type(error).__name__}: {error}"
                _LOGGER.warning("Binance stream reconnecting after %s", self.last_error)
                stop.wait(backoff)
                backoff = min(backoff * 2, self.reconnect_max_seconds)


__all__ = [
    "PUBLIC_WS_BASE",
    "BinancePublicStreamAdapter",
    "StreamEvent",
    "StreamEventType",
    "parse_stream_message",
]
