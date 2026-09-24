"""Binance demo execution adapter (https://demo-api.binance.com).

Adapted from cryptoagent2.0's BinanceAdapter but rebuilt for this project:
a lightweight signed REST client (stdlib + certifi), no python-binance dependency,
credentials read only from environment variables, and hard-blocked for real money.

Security:
- Disabled unless explicitly enabled by the caller.
- Only DEMO/TESTNET venues are allowed; REAL raises RealCapitalBlockedError.
- API key/secret come from env vars, never from code or the repo.
- Withdrawals are never called. Only ticker, account and market orders are used.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

import certifi

from btc_decision_agent.application.execution import (
    AccountBalance,
    ExchangeOrder,
    ExecutionPort,
    ExecutionVenue,
    OrderResult,
    OrderSide,
    RealCapitalBlockedError,
    SymbolTradingRules,
    TradeFill,
    assert_non_real_venue,
)

_DEMO_REST = "https://demo-api.binance.com"
_TESTNET_REST = "https://testnet.binance.vision"
_RECV_WINDOW_MS = 5000
_USER_AGENT = "btc-decision-agent-demo/0.1"


@dataclass(frozen=True)
class DemoExecutionConfig:
    venue: ExecutionVenue = ExecutionVenue.DEMO
    symbol: str = "BTCUSDT"
    timeout_s: float = 15.0
    max_retries: int = 3
    api_key_env: str = "BINANCE_DEMO_API_KEY"
    api_secret_env: str = "BINANCE_DEMO_API_SECRET"
    rest_url_env: str = "BINANCE_DEMO_REST_URL"

    def base_url(self) -> str:
        assert_non_real_venue(self.venue)
        override = os.environ.get(self.rest_url_env)
        if override:
            is_https = override.startswith("https://")
            is_non_real = ("demo-api.binance.com" in override) or ("testnet.binance.vision" in override)
            if not is_https or not is_non_real:
                raise ValueError("demo/testnet REST url must be an https non-real endpoint")
            base = override.rstrip("/")
            # request paths already include the '/api/v3/...' prefix, so strip a
            # trailing '/api' if the configured URL bundles it (matches the
            # BINANCE_DEMO_REST_URL=.../api convention from cryptoagent2.0).
            if base.endswith("/api"):
                base = base[: -len("/api")]
            return base
        return _DEMO_REST if self.venue == ExecutionVenue.DEMO else _TESTNET_REST


class BinanceDemoExecutionAdapter(ExecutionPort):
    """Signed REST client against the Binance demo endpoint; no real funds."""

    def __init__(self, config: DemoExecutionConfig | None = None, *, enabled: bool = False) -> None:
        self.config = config or DemoExecutionConfig()
        assert_non_real_venue(self.config.venue)
        self.enabled = enabled
        self._context = ssl.create_default_context(cafile=certifi.where())

    def venue(self) -> ExecutionVenue:
        return self.config.venue

    def _credentials(self) -> tuple[str, str]:
        key = os.environ.get(self.config.api_key_env, "")
        secret = os.environ.get(self.config.api_secret_env, "")
        if not key or not secret:
            raise RuntimeError(
                f"missing demo credentials; set {self.config.api_key_env} and {self.config.api_secret_env}"
            )
        return key, secret

    def _sign(self, secret: str, query: str) -> str:
        return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict[str, str], *, signed: bool) -> Any:
        if not self.enabled:
            raise RuntimeError("execution adapter is disabled by default; explicit opt-in required")
        assert_non_real_venue(self.config.venue)
        key, secret = self._credentials() if signed else ("", "")
        headers = {"User-Agent": _USER_AGENT}
        if signed:
            headers["X-MBX-APIKEY"] = key
        url = f"{self.config.base_url()}{path}"
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries):
            query_params = dict(params)
            if signed:
                query_params["timestamp"] = str(int(time.time() * 1000))
                query_params["recvWindow"] = str(_RECV_WINDOW_MS)
                unsigned_query = urllib.parse.urlencode(query_params)
                query_params["signature"] = self._sign(secret, unsigned_query)
            query_string = urllib.parse.urlencode(query_params)
            try:
                if method == "GET":
                    request = urllib.request.Request(f"{url}?{query_string}", headers=headers, method="GET")
                else:
                    request = urllib.request.Request(url, data=query_string.encode(), headers=headers, method=method)
                with urllib.request.urlopen(request, timeout=self.config.timeout_s, context=self._context) as response:
                    payload: Any = json.loads(response.read())
                    return payload
            except urllib.error.HTTPError as error:
                body = error.read().decode(errors="replace")
                if error.code in {418, 429} and attempt < self.config.max_retries - 1:
                    time.sleep(min(2**attempt, 8))
                    last_error = error
                    continue
                raise RuntimeError(f"binance demo HTTP {error.code}: {body}") from error
            except (urllib.error.URLError, TimeoutError) as error:
                time.sleep(min(2**attempt, 8))
                last_error = error
        raise RuntimeError(f"binance demo request failed after retries: {last_error}")

    def ticker_price(self, symbol: str = "BTCUSDT") -> Decimal:
        payload = self._request("GET", "/api/v3/ticker/price", {"symbol": symbol}, signed=False)
        return Decimal(str(payload["price"]))

    def recent_closed_klines(self, *, interval: str = "1h", limit: int = 200, symbol: str = "BTCUSDT") -> list[dict[str, Any]]:
        """Return recent CLOSED klines (oldest first), excluding the forming bar.

        A kline is closed only when the current server time is at/after its
        close_time; the last element Binance returns is usually still forming.
        """
        raw = self._request("GET", "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": str(min(limit, 1000))}, signed=False)
        now_ms = int(time.time() * 1000)
        bars: list[dict[str, Any]] = []
        for row in raw:
            close_ms = int(row[6])
            if close_ms >= now_ms:
                continue  # still forming; never used as a strategic bar
            bars.append(
                {
                    "open_time_ms": int(row[0]),
                    "close_time_ms": close_ms,
                    "open": Decimal(str(row[1])),
                    "high": Decimal(str(row[2])),
                    "low": Decimal(str(row[3])),
                    "close": Decimal(str(row[4])),
                    "base_volume": Decimal(str(row[5])),
                }
            )
        return bars

    def account_balance(self) -> AccountBalance:
        payload = self._request("GET", "/api/v3/account", {}, signed=True)
        free: dict[str, Decimal] = {}
        locked: dict[str, Decimal] = {}
        for entry in payload.get("balances", []):
            asset = str(entry["asset"])
            free_value = Decimal(str(entry["free"]))
            locked_value = Decimal(str(entry["locked"]))
            if free_value > 0:
                free[asset] = free_value
            if locked_value > 0:
                locked[asset] = locked_value
        return AccountBalance(
            balances=free,
            locked_balances=locked,
            observed_at_ms=int(time.time() * 1000),
        )

    def symbol_rules(self, symbol: str = "BTCUSDT") -> SymbolTradingRules:
        payload = self._request(
            "GET", "/api/v3/exchangeInfo", {"symbol": symbol}, signed=False
        )
        symbols = payload.get("symbols", [])
        if len(symbols) != 1:
            raise RuntimeError(f"symbol metadata unavailable for {symbol}")
        info = symbols[0]
        filters = {item["filterType"]: item for item in info.get("filters", [])}
        price_filter = filters.get("PRICE_FILTER", {})
        lot = filters.get("LOT_SIZE", {})
        market_lot = filters.get("MARKET_LOT_SIZE", {})
        notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {}))
        market_step = Decimal(str(market_lot.get("stepSize", "0")))
        lot_step = Decimal(str(lot.get("stepSize", "0")))
        effective_market_step = market_step if market_step > 0 else lot_step
        order_types = set(info.get("orderTypes", []))
        return SymbolTradingRules(
            symbol=str(info["symbol"]),
            status=str(info["status"]),
            base_asset=str(info["baseAsset"]),
            quote_asset=str(info["quoteAsset"]),
            tick_size=Decimal(str(price_filter.get("tickSize", "0"))),
            lot_step_size=lot_step,
            market_step_size=effective_market_step,
            min_quantity=Decimal(str(lot.get("minQty", "0"))),
            max_quantity=Decimal(str(lot.get("maxQty", "0"))),
            min_notional=Decimal(str(notional.get("minNotional", "0"))),
            max_notional=(
                Decimal(str(notional["maxNotional"]))
                if notional.get("maxNotional") is not None
                else None
            ),
            market_quote_allowed=bool(info.get("quoteOrderQtyMarketAllowed", False)),
            stop_loss_allowed="STOP_LOSS" in order_types,
        )

    @staticmethod
    def _exchange_order(order: dict[str, Any]) -> ExchangeOrder:
        return ExchangeOrder(
            exchange_order_id=str(order.get("orderId", "")),
            client_order_id=str(order.get("clientOrderId", "")),
            symbol=str(order.get("symbol", "")),
            side=OrderSide(str(order.get("side", "BUY"))),
            order_type=str(order.get("type", "")),
            status=str(order.get("status", "")),
            original_base_qty=Decimal(str(order.get("origQty", "0"))),
            executed_base_qty=Decimal(str(order.get("executedQty", "0"))),
            price=Decimal(str(order.get("price", "0"))),
            stop_price=Decimal(str(order.get("stopPrice", "0"))),
            update_time_ms=int(order.get("updateTime", order.get("transactTime", 0))),
        )

    def open_orders(self, symbol: str = "BTCUSDT") -> tuple[ExchangeOrder, ...]:
        payload = self._request(
            "GET", "/api/v3/openOrders", {"symbol": symbol}, signed=True
        )
        return tuple(self._exchange_order(order) for order in payload)

    def recent_trades(
        self, symbol: str = "BTCUSDT", *, limit: int = 100
    ) -> tuple[TradeFill, ...]:
        payload = self._request(
            "GET",
            "/api/v3/myTrades",
            {"symbol": symbol, "limit": str(max(1, min(limit, 1000)))},
            signed=True,
        )
        return tuple(
            TradeFill(
                trade_id=str(trade.get("id", "")),
                exchange_order_id=str(trade.get("orderId", "")),
                price=Decimal(str(trade.get("price", "0"))),
                base_qty=Decimal(str(trade.get("qty", "0"))),
                quote_qty=Decimal(str(trade.get("quoteQty", "0"))),
                commission=Decimal(str(trade.get("commission", "0"))),
                commission_asset=str(trade.get("commissionAsset", "")),
                time_ms=int(trade.get("time", 0)),
                is_buyer=bool(trade.get("isBuyer", False)),
            )
            for trade in payload
        )

    def get_order_by_client_id(
        self, client_order_id: str, symbol: str = "BTCUSDT"
    ) -> ExchangeOrder | None:
        self._validate_client_order_id(client_order_id)
        try:
            payload = self._request(
                "GET",
                "/api/v3/order",
                {"symbol": symbol, "origClientOrderId": client_order_id},
                signed=True,
            )
        except RuntimeError as error:
            if "-2013" in str(error):
                return None
            raise
        return self._exchange_order(payload)

    def cancel_order(
        self, exchange_order_id: str, symbol: str = "BTCUSDT"
    ) -> ExchangeOrder:
        payload = self._request(
            "DELETE",
            "/api/v3/order",
            {"symbol": symbol, "orderId": exchange_order_id},
            signed=True,
        )
        return self._exchange_order(payload)

    @staticmethod
    def _validate_client_order_id(client_order_id: str | None) -> None:
        if client_order_id is None:
            return
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
        if not client_order_id or len(client_order_id) > 36 or any(char not in allowed for char in client_order_id):
            raise ValueError("invalid Binance client order id")

    def _order_result(self, order: dict[str, Any], side: OrderSide, client_order_id: str | None) -> OrderResult:
        executed_quote = Decimal(str(order.get("cummulativeQuoteQty", "0")))
        executed_base = Decimal(str(order.get("executedQty", "0")))
        average = executed_quote / executed_base if executed_base > 0 else Decimal("0")
        fills = order.get("fills", [])
        fees_by_asset: dict[str, Decimal] = {}
        for fill in fills:
            asset = str(fill.get("commissionAsset", "UNKNOWN"))
            fees_by_asset[asset] = fees_by_asset.get(asset, Decimal("0")) + Decimal(
                str(fill.get("commission", "0"))
            )
        fees_usdt = fees_by_asset.get("USDT", Decimal("0"))
        fees_usdt += fees_by_asset.get("BTC", Decimal("0")) * average
        return OrderResult(
            venue=self.config.venue,
            exchange_order_id=str(order.get("orderId", "")),
            side=side,
            executed_quote_usdt=executed_quote,
            executed_base_qty=executed_base,
            average_price=average,
            fees_usdt=fees_usdt,
            transact_time_ms=int(order.get("transactTime", order.get("updateTime", 0))),
            raw_status=str(order.get("status", "")),
            client_order_id=str(order.get("clientOrderId", client_order_id or "")) or None,
            fees_by_asset=fees_by_asset,
        )

    def _place_market_order(
        self,
        side: OrderSide,
        params: dict[str, str],
        symbol: str,
        client_order_id: str | None,
    ) -> OrderResult:
        self._validate_client_order_id(client_order_id)
        request = {
            "symbol": symbol,
            "side": side.value,
            "type": "MARKET",
            "newOrderRespType": "FULL",
            **params,
        }
        if client_order_id is not None:
            request["newClientOrderId"] = client_order_id
        try:
            order = self._request("POST", "/api/v3/order", request, signed=True)
        except RuntimeError as placement_error:
            if client_order_id is None:
                raise
            # A timeout after exchange acceptance is ambiguous. Querying by the
            # deterministic client id makes retry/restart idempotent.
            try:
                order = self._request(
                    "GET",
                    "/api/v3/order",
                    {"symbol": symbol, "origClientOrderId": client_order_id},
                    signed=True,
                )
            except RuntimeError as lookup_error:
                raise placement_error from lookup_error
        return self._order_result(order, side, client_order_id)

    def place_market_quote_order(
        self,
        side: OrderSide,
        quote_usdt: Decimal,
        symbol: str = "BTCUSDT",
        *,
        client_order_id: str | None = None,
    ) -> OrderResult:
        assert_non_real_venue(self.config.venue)
        if quote_usdt <= 0:
            raise ValueError("quote order amount must be positive")
        quote_2dp = quote_usdt.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        return self._place_market_order(
            side, {"quoteOrderQty": str(quote_2dp)}, symbol, client_order_id
        )

    def place_market_base_order(
        self,
        side: OrderSide,
        base_quantity: Decimal,
        symbol: str = "BTCUSDT",
        *,
        client_order_id: str | None = None,
    ) -> OrderResult:
        """Place an exact base-quantity market order (used to exit all BTC)."""
        assert_non_real_venue(self.config.venue)
        if base_quantity <= 0:
            raise ValueError("base order amount must be positive")
        return self._place_market_order(
            side, {"quantity": format(base_quantity, "f")}, symbol, client_order_id
        )
    def place_stop_loss_base_order(
        self,
        base_quantity: Decimal,
        stop_price: Decimal,
        symbol: str = "BTCUSDT",
        *,
        client_order_id: str,
    ) -> ExchangeOrder:
        """Place a server-side STOP_LOSS market sell protecting base quantity."""
        assert_non_real_venue(self.config.venue)
        if base_quantity <= 0 or stop_price <= 0:
            raise ValueError("stop quantity and price must be positive")
        self._validate_client_order_id(client_order_id)
        payload = self._request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": OrderSide.SELL.value,
                "type": "STOP_LOSS",
                "quantity": format(base_quantity, "f"),
                "stopPrice": format(stop_price, "f"),
                "newClientOrderId": client_order_id,
                "newOrderRespType": "RESULT",
            },
            signed=True,
        )
        return self._exchange_order(payload)


def build_demo_adapter(*, enabled: bool = False) -> BinanceDemoExecutionAdapter:
    """Factory that fails closed if someone points it at a real venue via env."""
    venue_name = os.environ.get("BINANCE_EXECUTION_VENUE", "DEMO").upper()
    venue = ExecutionVenue(venue_name) if venue_name in {v.value for v in ExecutionVenue} else ExecutionVenue.DEMO
    if venue == ExecutionVenue.REAL:
        raise RealCapitalBlockedError("BINANCE_EXECUTION_VENUE=REAL is blocked in this project")
    return BinanceDemoExecutionAdapter(DemoExecutionConfig(venue=venue), enabled=enabled)


__all__ = ["BinanceDemoExecutionAdapter", "DemoExecutionConfig", "build_demo_adapter"]
