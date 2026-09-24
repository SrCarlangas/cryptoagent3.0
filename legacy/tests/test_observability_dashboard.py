"""Tests for the activity journal and dashboard state (no network, no server bind)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from btc_decision_agent.observability.dashboard import build_equity_series, build_floor, build_state

from btc_decision_agent.observability.journal import ActivityJournal, entry_from_live

D = Decimal
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def _journal(tmp_path: Path) -> ActivityJournal:
    return ActivityJournal(tmp_path / "activity.jsonl")


def test_journal_roundtrip_preserves_decimal_strings(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.append(
        entry_from_live(
            venue="DEMO", interval="4h", action="HOLD", reason="HOLD_FLAT",
            position_before="FLAT", fast_sma=D("76958.86"), slow_sma=D("77493.78"),
            price=D("75644.90"), usdt_free=D("4298.04704894"), btc_qty=D("0.00033175"),
            at=NOW,
        )
    )
    rows = journal.read()
    assert len(rows) == 1
    assert rows[0]["fast_sma"] == "76958.86"
    assert rows[0]["usdt_free"] == "4298.04704894"
    assert rows[0]["order_side"] is None


def test_build_state_summarizes_orders_and_equity(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.append(entry_from_live(venue="DEMO", interval="4h", action="HOLD", reason="HOLD_FLAT", position_before="FLAT", fast_sma=D("1"), slow_sma=D("2"), price=D("100"), usdt_free=D("1000"), btc_qty=D("0"), at=NOW))
    journal.append(entry_from_live(venue="DEMO", interval="4h", action="ENTER_LONG", reason="SMA_CROSS_UP", position_before="FLAT", fast_sma=D("3"), slow_sma=D("2"), price=D("100"), usdt_free=D("900"), btc_qty=D("1"), order_side="BUY", order_quote_usdt=D("100"), order_base_qty=D("1"), order_avg_price=D("100"), order_id="1", at=NOW))
    state = build_state(journal)
    assert state["eval_count"] == 2
    assert state["order_count"] == 1
    assert state["buy_count"] == 1
    assert state["sell_count"] == 0
    assert state["position"] == "FLAT"
    assert state["last_action"] == "ENTER_LONG"
    # equity = usdt_free + btc_qty * price = 900 + 1*100 = 1000
    assert state["equity_usdt"] == "1000"
    assert state["recent"][0]["action"] == "ENTER_LONG"  # most recent first


def test_build_state_empty_journal_is_safe(tmp_path: Path) -> None:
    state = build_state(_journal(tmp_path))
    assert state["eval_count"] == 0
    assert state["position"] is None
    assert state["recent"] == []
    assert state["equity_series"] == []
    assert state["strategy_vs_hold"] is None
    assert [a["id"] for a in state["floor"]] == ["sensor", "research", "policy", "risk", "execution", "ledger"]
    assert all(a["status"] == "idle" for a in state["floor"])


def test_floor_reflects_order_and_block_states() -> None:
    filled = {
        "action": "ENTER_LONG", "reason": "SMA_CROSS_UP", "order_side": "BUY",
        "price": "75000", "fast_sma": "3", "slow_sma": "2", "position_before": "FLAT",
        "order_quote_usdt": "999.57", "order_avg_price": "75610.48",
    }
    floor = {a["id"]: a for a in build_floor(filled)}
    assert floor["policy"]["status"] == "success"
    assert floor["risk"]["status"] == "working"
    assert floor["execution"]["status"] == "success"

    blocked = {"action": "HOLD", "reason": "DATA_BLOCKED", "order_side": None, "position_before": "FLAT"}
    floor_b = {a["id"]: a for a in build_floor(blocked)}
    assert floor_b["sensor"]["status"] == "alert"
    assert floor_b["policy"]["status"] == "idle"
    assert floor_b["execution"]["status"] == "idle"

    capital = {"action": "HOLD", "reason": "CAPITAL_INSUFFICIENT", "order_side": None, "position_before": "FLAT"}
    floor_c = {a["id"]: a for a in build_floor(capital)}
    assert floor_c["risk"]["status"] == "alert"
    assert floor_c["execution"]["status"] == "alert"


def test_equity_series_and_excess_vs_buy_hold(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    # Start flat with 1000 USDT at price 100 -> buy&hold buys 10 BTC.
    journal.append(entry_from_live(venue="DEMO", interval="4h", action="HOLD", reason="HOLD_FLAT", position_before="FLAT", fast_sma=None, slow_sma=None, price=D("100"), usdt_free=D("1000"), btc_qty=D("0"), at=NOW))
    # Price rises to 120. Strategy stayed flat (still 1000). Buy&hold = 10*120 = 1200.
    journal.append(entry_from_live(venue="DEMO", interval="4h", action="HOLD", reason="HOLD_FLAT", position_before="FLAT", fast_sma=None, slow_sma=None, price=D("120"), usdt_free=D("1000"), btc_qty=D("0"), at=NOW))
    series = build_equity_series(journal.read())
    assert series[0]["strategy"] == "1000" and series[0]["buy_hold"] == "1000"
    assert series[1]["strategy"] == "1000" and series[1]["buy_hold"] == "1200"
    svh = build_state(journal)["strategy_vs_hold"]
    assert svh is not None
    assert D(svh["strategy_return_pct"]) == D("0")
    assert D(svh["buy_hold_return_pct"]) == D("20")
    assert D(svh["excess_pct"]) == D("-20")  # staying flat underperformed a rising market
