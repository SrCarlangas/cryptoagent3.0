"""Execution port and safe defaults for translating a Decision into an order.

This is the boundary the domain never crosses on its own. A Decision is produced
and recorded first (record-before-export); only an explicitly enabled execution
adapter may act on it. Real-money endpoints are blocked by default and require an
explicit, separate operator confirmation that this project does not grant.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class ExecutionVenue(str, Enum):
    DEMO = "DEMO"          # https://demo-api.binance.com — no real funds
    TESTNET = "TESTNET"    # testnet.binance.vision — no real funds
    REAL = "REAL"          # real money — blocked in this project


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class OrderResult:
    venue: ExecutionVenue
    exchange_order_id: str
    side: OrderSide
    executed_quote_usdt: Decimal
    executed_base_qty: Decimal
    average_price: Decimal
    fees_usdt: Decimal
    transact_time_ms: int
    raw_status: str
    client_order_id: str | None = None
    fees_by_asset: dict[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountBalance:
    """Free and locked balances from one authoritative account snapshot."""

    balances: dict[str, Decimal]
    locked_balances: dict[str, Decimal] = field(default_factory=dict)
    observed_at_ms: int | None = None

    def total(self, asset: str) -> Decimal:
        return self.balances.get(asset, Decimal("0")) + self.locked_balances.get(
            asset, Decimal("0")
        )


@dataclass(frozen=True)
class SymbolTradingRules:
    symbol: str
    status: str
    base_asset: str
    quote_asset: str
    tick_size: Decimal
    lot_step_size: Decimal
    market_step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal
    min_notional: Decimal
    max_notional: Decimal | None
    market_quote_allowed: bool
    stop_loss_allowed: bool


@dataclass(frozen=True)
class ExchangeOrder:
    exchange_order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: str
    status: str
    original_base_qty: Decimal
    executed_base_qty: Decimal
    price: Decimal
    stop_price: Decimal
    update_time_ms: int


@dataclass(frozen=True)
class TradeFill:
    trade_id: str
    exchange_order_id: str
    price: Decimal
    base_qty: Decimal
    quote_qty: Decimal
    commission: Decimal
    commission_asset: str
    time_ms: int
    is_buyer: bool


class ExecutionPort(ABC):
    """Minimal execution surface. Only non-real venues are permitted here."""

    @abstractmethod
    def venue(self) -> ExecutionVenue: ...

    @abstractmethod
    def ticker_price(self, symbol: str = "BTCUSDT") -> Decimal: ...

    @abstractmethod
    def account_balance(self) -> AccountBalance: ...

    @abstractmethod
    def place_market_quote_order(
        self,
        side: OrderSide,
        quote_usdt: Decimal,
        symbol: str = "BTCUSDT",
        *,
        client_order_id: str | None = None,
    ) -> OrderResult: ...


class RealCapitalBlockedError(RuntimeError):
    """Raised whenever any real-money execution is attempted."""


def assert_non_real_venue(venue: ExecutionVenue) -> None:
    """Fail closed: this project only permits demo/testnet execution."""
    if venue == ExecutionVenue.REAL:
        raise RealCapitalBlockedError(
            "real-capital execution is blocked in this project; use DEMO or TESTNET"
        )


__all__ = [
    "AccountBalance",
    "ExchangeOrder",
    "ExecutionPort",
    "ExecutionVenue",
    "OrderResult",
    "OrderSide",
    "RealCapitalBlockedError",
    "SymbolTradingRules",
    "TradeFill",
    "assert_non_real_venue",
]
