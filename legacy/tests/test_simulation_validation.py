from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from btc_decision_agent.simulation.fills import (
    BookObservation,
    FillStatus,
    OrderSide,
    TradeObservation,
    simulate_limit,
    simulate_market,
)
from btc_decision_agent.validation.offline import (
    FrozenOOSGate,
    OOSMetrics,
    TimedSample,
    evaluate_frozen_gate,
    prepare_walk_forward,
)
from tests.helpers import NOW, D

from btc_decision_agent.domain.contracts import (
    BookSyncState,
    FreshnessStatus,
    QualityStatus,
)


def book(observed_at=NOW, *, generation: str = "book-gen", freshness: FreshnessStatus = FreshnessStatus.FRESH) -> BookObservation:
    return BookObservation(observed_at, ((D("99"), D("10")),), ((D("101"), D("10")),), generation, BookSyncState.LIVE, QualityStatus.QUALIFIED, freshness, (f"book:{generation}",))


def trade(price: str, quantity: str, offset_ms: int, *, generation: str = "book-gen", trade_id: str = "trade-1") -> TradeObservation:
    return TradeObservation(NOW + timedelta(milliseconds=offset_ms), D(price), D(quantity), trade_id, generation, QualityStatus.QUALIFIED, FreshnessStatus.FRESH, ("S-01",))


class SimulationTests(unittest.TestCase):
    def test_market_waits_for_latency_walks_book_and_partial_fills(self) -> None:
        books = [book(), replace(book(NOW + timedelta(milliseconds=100)), bids=((D("98"), D("0.5")),), asks=((D("102"), D("0.5")),))]
        fill = simulate_market(OrderSide.BUY, D("1"), NOW, books, latency_ms=50, taker_fee_rate=D("0.001"), adverse_selection_bps=D("5"))
        self.assertEqual((fill.status, fill.filled_qty, fill.residual_qty), (FillStatus.PARTIAL, D("0.5"), D("0.5")))
        self.assertEqual(fill.average_price, D("102"))
        self.assertGreater(fill.fee_paid, 0)
        self.assertGreater(fill.adverse_selection_cost, 0)

    def test_market_rejects_non_live_stale_or_unqualified_book(self) -> None:
        stale = book(NOW + timedelta(milliseconds=100), freshness=FreshnessStatus.STALE)
        with self.assertRaisesRegex(ValueError, "not LIVE/fresh/qualified"):
            simulate_market(OrderSide.BUY, D("1"), NOW, (stale,), latency_ms=50, taker_fee_rate=D("0.001"), adverse_selection_bps=D("5"))

    def test_limit_uses_side_price_reach_queue_partial_cancel_and_no_reach(self) -> None:
        books = (book(NOW + timedelta(milliseconds=100)),)
        buy_partial = simulate_limit(OrderSide.BUY, D("1"), D("100"), NOW, books, (trade("100", "5.4", 100),), latency_ms=100, maker_fee_rate=D("0.0005"), queue_ahead=D("5"), adverse_selection_bps=D("3"))
        sell_partial = simulate_limit(OrderSide.SELL, D("1"), D("100"), NOW, books, (trade("100", "5.4", 100, trade_id="sell-trade"),), latency_ms=100, maker_fee_rate=D("0.0005"), queue_ahead=D("5"), adverse_selection_bps=D("3"))
        no_reach = simulate_limit(OrderSide.BUY, D("1"), D("99"), NOW, books, (trade("100", "10", 100),), latency_ms=100, maker_fee_rate=D("0.0005"), queue_ahead=D("0"), adverse_selection_bps=D("3"))
        no_queue = simulate_limit(OrderSide.BUY, D("1"), D("100"), NOW, books, (trade("100", "4", 100),), latency_ms=100, maker_fee_rate=D("0.0005"), queue_ahead=D("5"), adverse_selection_bps=D("3"))
        cancelled = simulate_limit(OrderSide.BUY, D("1"), D("100"), NOW, books, (trade("100", "10", 100),), latency_ms=100, maker_fee_rate=D("0.0005"), queue_ahead=D("0"), adverse_selection_bps=D("3"), cancelled=True)
        self.assertEqual((buy_partial.status, buy_partial.filled_qty, buy_partial.side), (FillStatus.PARTIAL, D("0.4"), OrderSide.BUY))
        self.assertEqual((sell_partial.status, sell_partial.filled_qty, sell_partial.side), (FillStatus.PARTIAL, D("0.4"), OrderSide.SELL))
        self.assertEqual((no_reach.status, no_reach.reason), (FillStatus.NO_FILL, "PRICE_NOT_REACHED"))
        self.assertEqual((no_queue.status, no_queue.reason), (FillStatus.NO_FILL, "QUEUE_NOT_CLEARED"))
        self.assertEqual(cancelled.status, FillStatus.CANCELLED)

    def test_limit_rejects_generation_mismatch(self) -> None:
        books = (book(NOW + timedelta(milliseconds=100)),)
        with self.assertRaisesRegex(ValueError, "generation mismatch"):
            simulate_limit(OrderSide.BUY, D("1"), D("100"), NOW, books, (trade("100", "10", 100, generation="other"),), latency_ms=100, maker_fee_rate=D("0.0005"), queue_ahead=D("0"), adverse_selection_bps=D("3"))


class OfflineValidationTests(unittest.TestCase):
    def test_walk_forward_purges_overlap_and_embargoes_future(self) -> None:
        samples = [TimedSample(str(index), NOW + timedelta(hours=index), NOW + timedelta(hours=index + 1)) for index in range(10)]
        folds = prepare_walk_forward(samples, train_size=4, test_size=2, purge=timedelta(hours=1), embargo=timedelta(hours=1))
        self.assertEqual(len(folds), 3)
        self.assertTrue(folds[0].purged_ids)
        self.assertTrue(folds[0].embargoed_ids)
        self.assertFalse(set(folds[0].train_ids) & set(folds[0].test_ids))

    def test_frozen_gate_reports_failures_without_inventing_oos(self) -> None:
        failing = OOSMetrics(99, D("0.009"), D("0.69"), D("0.20"), 1, False, D("0.26"), D("0.31"), D("20"), D("21"))
        result = evaluate_frozen_gate(failing)
        self.assertFalse(result.passed)
        self.assertEqual(result.gate_version, "D-009/1.0.0")
        self.assertIn("INSUFFICIENT_EFFECTIVE_SAMPLE", result.reasons)
        passing_supplied_evidence = OOSMetrics(100, D("0.01"), D("0.70"), D("0.19"), 0, True, D("0.25"), D("0.10"), D("22"), D("21"))
        self.assertTrue(evaluate_frozen_gate(passing_supplied_evidence).passed)
        self.assertEqual(FrozenOOSGate().margin_min, D("0.01"))


if __name__ == "__main__":
    unittest.main()
