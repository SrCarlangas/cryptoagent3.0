from __future__ import annotations

import json
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from btc_decision_agent.adapters.book import DepthDiff, DepthSnapshot, LocalBook
from btc_decision_agent.adapters.market_data import (
    PRIVATE_MARKERS,
    PublicMarketDataAdapter,
    normalize,
)
from btc_decision_agent.adapters.quality import BarLifecycle, DataQualityGuard, classify_bar
from tests.helpers import NOW

from btc_decision_agent.domain.contracts import (
    ClockBasis,
    EventType,
    FreshnessPolicy,
    RawMarketEvent,
    Usage,
)


class MarketContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(Path("tests/fixtures/binance-public-v1.json").read_text())

    def raw(self, source: str) -> RawMarketEvent:
        value = self.fixture["sources"][source]
        return RawMarketEvent(source_contract_id=source, channel=value["channel"], observed_at=NOW + timedelta(seconds=1), raw_payload=value["payload"])

    def test_s01_through_s09_normalize_without_network(self) -> None:
        expected = {"S-01": "AGG_TRADE", "S-02": "KLINE_UPDATE", "S-03": "KLINE_CLOSED", "S-04": "BBO_UPDATE", "S-05": "DEPTH_DIFF", "S-06": "DEPTH_SNAPSHOT", "S-07": "TICKER_24H", "S-08": "TICKER_24H", "S-09": "SYMBOL_METADATA"}
        for source, event_type in expected.items():
            with self.subTest(source=source):
                event = normalize(self.raw(source))
                self.assertEqual(event.event_type.value, event_type)
                self.assertEqual(event.symbol, "BTC/USDT")
                self.assertTrue(event.event_id.startswith("sha256:"))

    def test_public_adapter_disabled_and_no_private_paths(self) -> None:
        adapter = PublicMarketDataAdapter()
        adapter.assert_offline()
        with self.assertRaises(RuntimeError):
            adapter.request_spec("/api/v3/klines")
        enabled = PublicMarketDataAdapter(enabled=True)
        self.assertEqual(enabled.request_spec("/api/v3/depth")[0], "GET")
        with self.assertRaises(ValueError):
            enabled.request_spec("/api/v3/order")
        self.assertFalse(any(marker in enabled.rest_base for marker in PRIVATE_MARKERS))

    def test_delivery_duplicate_out_of_order_stale_and_watermark(self) -> None:
        event = normalize(self.raw("S-04"))
        policy = FreshnessPolicy(policy_version="D-014/1", source_contract_id="S-04", event_type=EventType.BBO_UPDATE, usage=Usage.COST, required=True, clock_basis=ClockBasis.OBSERVED_AT, warning_age_ms=1000, max_age_ms=2000, allowed_lateness_ms=500, clock_skew_budget_ms=500, recovery_evidence_n=3, on_suspect="BLOCK", on_stale="BLOCK")
        guard = DataQualityGuard()
        first = guard.classify(event, policy, event.observed_at + timedelta(milliseconds=100))
        duplicate = guard.classify(event, policy, event.observed_at + timedelta(milliseconds=200))
        self.assertTrue(first.apply)
        self.assertFalse(duplicate.apply)
        self.assertEqual(duplicate.classification.value, "DUPLICATE")
        collision = event.model_copy(update={"event_id": "sha256:" + "c" * 64, "payload_hash": "sha256:" + "d" * 64, "payload": {"bid_price": Decimal("1")}})
        with self.assertRaisesRegex(ValueError, "IDENTITY_COLLISION"):
            guard.classify(collision, policy, event.observed_at + timedelta(milliseconds=300))
        stale_guard = DataQualityGuard()
        stale = stale_guard.classify(event, policy, event.observed_at + timedelta(seconds=3))
        self.assertFalse(stale.apply)
        self.assertEqual(stale.freshness.value, "STALE")

    def test_bar_forming_final_and_quality_guards(self) -> None:
        forming = normalize(self.raw("S-02"))
        self.assertEqual(classify_bar(forming, NOW + timedelta(hours=1), NOW + timedelta(hours=1), 5000), BarLifecycle.FORMING)
        closed = normalize(self.raw("S-03"))
        close_time = closed.payload["bar_close_time"]
        watermark = close_time + timedelta(seconds=5)
        self.assertEqual(classify_bar(closed, close_time + timedelta(seconds=10), watermark, 5000), BarLifecycle.FINAL)
        blocked = closed.model_copy(update={"quality": "BLOCKED"})
        gap = closed.model_copy(update={"flags": ("GAP_DETECTED",)})
        self.assertEqual(classify_bar(blocked, close_time + timedelta(seconds=10), watermark, 5000), BarLifecycle.INVALID)
        self.assertEqual(classify_bar(gap, close_time + timedelta(seconds=10), watermark, 5000), BarLifecycle.INVALID)


class LocalBookTests(unittest.TestCase):
    def test_bootstrap_overlap_delete_gap_and_revocation(self) -> None:
        book = LocalBook("connection-1", "meta-1")
        book.open()
        first = DepthDiff(101, 103, ((Decimal("100"), Decimal("2")),), ((Decimal("101"), Decimal("2")),), NOW, NOW)
        second = DepthDiff(104, 105, ((Decimal("99"), Decimal("1")),), (), NOW, NOW)
        book.buffer_diff(first)
        book.request_snapshot()
        book.buffer_diff(second)
        snapshot = DepthSnapshot(100, ((Decimal("100"), Decimal("1")),), ((Decimal("101"), Decimal("1")),), 500, NOW)
        self.assertTrue(book.load_snapshot(snapshot))
        self.assertEqual((book.view().last_update_id, book.generation.rule_id), (105, "L2-009"))
        overlap = DepthDiff(104, 107, ((Decimal("100"), Decimal("0")), (Decimal("99"), Decimal("3"))), (), NOW, NOW)
        self.assertTrue(book.apply_diff(overlap))
        self.assertNotIn(Decimal("100"), dict(book.view().bids))
        gap = DepthDiff(110, 112, (), (), NOW, NOW)
        self.assertFalse(book.apply_diff(gap))
        self.assertEqual(book.state.value, "GAP_DETECTED")
        with self.assertRaises(RuntimeError):
            book.view()
        old_generation = book.generation.generation_id
        book.begin_backoff()
        book.backoff_expired(budget_available=True)
        self.assertEqual(book.state.value, "UNINITIALIZED")
        self.assertNotEqual(book.generation.generation_id, old_generation)
        book.open()
        book.buffer_diff(DepthDiff(201, 201, ((Decimal("100"), Decimal("1")),), ((Decimal("101"), Decimal("1")),), NOW, NOW))
        book.request_snapshot()
        self.assertTrue(book.load_snapshot(DepthSnapshot(200, ((Decimal("100"), Decimal("1")),), ((Decimal("101"), Decimal("1")),), 500, NOW)))
        self.assertFalse(book.generation.revoked)
        self.assertEqual(book.view().last_update_id, 201)

    def test_l2_023_atomic_handoff(self) -> None:
        def live(connection: str, start: int) -> LocalBook:
            result = LocalBook(connection, "meta-1")
            result.open()
            result.buffer_diff(DepthDiff(start + 1, start + 1, ((Decimal("100"), Decimal("1")),), ((Decimal("101"), Decimal("1")),), NOW, NOW))
            result.request_snapshot()
            self.assertTrue(result.load_snapshot(DepthSnapshot(start, ((Decimal("100"), Decimal("1")),), ((Decimal("101"), Decimal("1")),), 500, NOW)))
            return result

        old, replacement = live("old", 100), live("new", 200)
        replacement_id = replacement.generation.generation_id
        old.handoff(replacement)
        self.assertEqual((old.generation.generation_id, old.generation.rule_id), (replacement_id, "L2-023"))
        self.assertEqual(old.view().last_update_id, 201)

    def test_l2_blocks_time_regression_without_publishing_rollback(self) -> None:
        book = LocalBook("time-order", "meta-1")
        book.open()
        book.buffer_diff(DepthDiff(101, 101, ((Decimal("100"), Decimal("1")),), ((Decimal("101"), Decimal("1")),), NOW, NOW))
        book.request_snapshot()
        self.assertTrue(book.load_snapshot(DepthSnapshot(100, ((Decimal("100"), Decimal("1")),), ((Decimal("101"), Decimal("1")),), 500, NOW)))
        before = book.view()
        regressive = DepthDiff(102, 102, ((Decimal("100"), Decimal("2")),), (), NOW - timedelta(seconds=1), NOW + timedelta(seconds=1))
        self.assertFalse(book.apply_diff(regressive))
        self.assertEqual(book.state.value, "BLOCKED")
        self.assertEqual(before.last_update_id, 101)
        with self.assertRaises(RuntimeError):
            book.view()

    def test_old_snapshot_and_transport_fault(self) -> None:
        book = LocalBook("connection-2", "meta-1")
        book.open()
        book.buffer_diff(DepthDiff(200, 201, ((Decimal("100"), Decimal("1")),), ((Decimal("101"), Decimal("1")),), NOW, NOW))
        book.request_snapshot()
        self.assertFalse(book.load_snapshot(DepthSnapshot(150, ((Decimal("100"), Decimal("1")),), ((Decimal("101"), Decimal("1")),), 500, NOW)))
        self.assertEqual(book.generation.rule_id, "L2-006")
        book.snapshot_error()
        self.assertEqual(book.generation.rule_id, "L2-005")


if __name__ == "__main__":
    unittest.main()
