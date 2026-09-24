"""Safety-focused tests for the demo execution adapter. No network is used."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from btc_decision_agent.adapters.binance_execution import (
    BinanceDemoExecutionAdapter,
    DemoExecutionConfig,
    build_demo_adapter,
)
from btc_decision_agent.application.execution import (
    ExecutionVenue,
    OrderSide,
    RealCapitalBlockedError,
    assert_non_real_venue,
)


def test_real_venue_is_blocked_everywhere() -> None:
    with pytest.raises(RealCapitalBlockedError):
        assert_non_real_venue(ExecutionVenue.REAL)
    with pytest.raises(RealCapitalBlockedError):
        DemoExecutionConfig(venue=ExecutionVenue.REAL).base_url()
    with pytest.raises(RealCapitalBlockedError):
        BinanceDemoExecutionAdapter(DemoExecutionConfig(venue=ExecutionVenue.REAL))


def test_adapter_is_disabled_by_default_and_hits_no_network() -> None:
    adapter = BinanceDemoExecutionAdapter()
    assert adapter.enabled is False
    assert adapter.venue() == ExecutionVenue.DEMO
    with pytest.raises(RuntimeError, match="disabled by default"):
        adapter.ticker_price()


def test_demo_and_testnet_base_urls_are_non_real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BINANCE_DEMO_REST_URL", raising=False)
    assert DemoExecutionConfig(venue=ExecutionVenue.DEMO).base_url() == "https://demo-api.binance.com"
    assert DemoExecutionConfig(venue=ExecutionVenue.TESTNET).base_url() == "https://testnet.binance.vision"


def test_rest_url_override_rejects_real_and_non_https(monkeypatch: pytest.MonkeyPatch) -> None:
    config = DemoExecutionConfig()
    monkeypatch.setenv("BINANCE_DEMO_REST_URL", "https://api.binance.com/api")
    with pytest.raises(ValueError, match="non-real endpoint"):
        config.base_url()
    monkeypatch.setenv("BINANCE_DEMO_REST_URL", "http://demo-api.binance.com")
    with pytest.raises(ValueError, match="non-real endpoint"):
        config.base_url()
    monkeypatch.setenv("BINANCE_DEMO_REST_URL", "https://demo-api.binance.com/api")
    # a bundled trailing '/api' is stripped so request paths are not doubled
    assert config.base_url() == "https://demo-api.binance.com"


def test_missing_credentials_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BINANCE_DEMO_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_DEMO_API_SECRET", raising=False)
    adapter = BinanceDemoExecutionAdapter(enabled=True)
    with pytest.raises(RuntimeError, match="missing demo credentials"):
        adapter.account_balance()


def test_signature_is_hmac_sha256(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = BinanceDemoExecutionAdapter(enabled=True)
    query = "symbol=BTCUSDT&timestamp=1"
    expected = hmac.new(b"secret", query.encode(), hashlib.sha256).hexdigest()
    assert adapter._sign("secret", query) == expected


def test_build_demo_adapter_blocks_real_venue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BINANCE_EXECUTION_VENUE", "REAL")
    with pytest.raises(RealCapitalBlockedError):
        build_demo_adapter()
    monkeypatch.setenv("BINANCE_EXECUTION_VENUE", "DEMO")
    assert build_demo_adapter().venue() == ExecutionVenue.DEMO


def test_place_order_rejects_non_positive_amount() -> None:
    from decimal import Decimal

    adapter = BinanceDemoExecutionAdapter(enabled=True)
    with pytest.raises(ValueError, match="must be positive"):
        adapter.place_market_quote_order(OrderSide.BUY, Decimal("0"))
