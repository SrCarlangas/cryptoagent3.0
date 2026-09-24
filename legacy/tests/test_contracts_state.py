from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal

from btc_decision_agent.domain.state_machine import StateEvent, resolve_precedence, transition
from pydantic import ValidationError
from tests.helpers import NOW, state

from btc_decision_agent.domain.canonical import canonical_json, sha256_id
from btc_decision_agent.domain.contracts import (
    DeliveryClass,
    EvaluationState,
    FeatureValue,
    HealthState,
    MarketEventV1,
    PositionState,
    QualityStatus,
    SystemState,
    Transport,
)


class ContractTests(unittest.TestCase):
    def test_frozen_extra_forbid_utc_and_exact_decimal(self) -> None:
        feature = FeatureValue(feature_id="F-001", value=Decimal("103.6600"), unit="USDT/BTC", as_of_time=NOW, max_input_event_time=NOW, horizon="1h", window_definition="N=3", quality=QualityStatus.QUALIFIED)
        self.assertEqual(feature.value, Decimal("103.6600"))
        with self.assertRaises(ValidationError):
            FeatureValue(feature_id="F", value=Decimal("1"), unit="ratio", as_of_time=NOW, max_input_event_time=NOW, horizon="1h", window_definition="x", quality=QualityStatus.QUALIFIED, surprise=True)
        with self.assertRaises(ValidationError):
            FeatureValue(feature_id="F", value=Decimal("1"), unit="ratio", as_of_time=datetime(2026, 1, 1), max_input_event_time=NOW, horizon="1h", window_definition="x", quality=QualityStatus.QUALIFIED)
        with self.assertRaises(ValidationError):
            feature.value = Decimal("2")

    def test_canonical_decimal_order_and_hash_are_deterministic(self) -> None:
        first = {"z": Decimal("1.2300"), "a": ["x", Decimal("0.00")]}
        second = {"a": ["x", Decimal("0")], "z": Decimal("1.23")}
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(sha256_id(first), sha256_id(second))
        self.assertEqual(len(sha256_id(first)), 71)

    def test_event_identity_excludes_delivery_metadata(self) -> None:
        base = dict(event_id="sha256:" + "a" * 64, event_type="BBO_UPDATE", source_contract_id="S-04", provider_contract_version="v", transport=Transport.FIXTURE, channel="book", symbol="BTC/USDT", event_time=None, observed_at=NOW, source_identity={"update_id": 1}, sequence_first=1, sequence_last=1, payload={"bid": Decimal("1")}, payload_hash="sha256:" + "b" * 64, provenance={})
        one = MarketEventV1(**base)
        two = MarketEventV1(**{**base, "delivery_class": DeliveryClass.DUPLICATE, "delivery_attempt": 2})
        self.assertEqual(one.event_id, two.event_id)
        self.assertNotEqual(one.canonical_bytes(), two.canonical_bytes())

    def test_feature_rejects_future_null_and_nan(self) -> None:
        with self.assertRaises(ValidationError):
            FeatureValue(feature_id="F", value=Decimal("1"), unit="x", as_of_time=NOW, max_input_event_time=NOW.replace(hour=19), horizon="1h", window_definition="x", quality=QualityStatus.QUALIFIED)
        with self.assertRaises(ValidationError):
            FeatureValue(feature_id="F", value=None, unit="x", as_of_time=NOW, max_input_event_time=NOW, horizon="1h", window_definition="x", quality=QualityStatus.BLOCKED)
        with self.assertRaises(ValidationError):
            FeatureValue(feature_id="F", value=Decimal("NaN"), unit="x", as_of_time=NOW, max_input_event_time=NOW, horizon="1h", window_definition="x", quality=QualityStatus.QUALIFIED)


class StateMachineTests(unittest.TestCase):
    def test_total_for_every_known_event(self) -> None:
        current = state()
        for event in StateEvent:
            with self.subTest(event=event):
                result = transition(current, event)
                self.assertIsNotNone(result.action)
                self.assertTrue(result.rule_id.startswith("SM-"))

    def test_core_sm_transitions_and_prohibitions(self) -> None:
        unknown = state(PositionState.UNKNOWN, EvaluationState.IDLE, HealthState.BLOCKED)
        recovered = transition(unknown, StateEvent.POSITION_SYNC_FLAT, {"authoritative": True, "quantity": 0})
        self.assertEqual((recovered.rule_id, recovered.state_after.position), ("SM-001", PositionState.FLAT))
        ready = transition(recovered.state_after, StateEvent.QUALITY_READY, {"mandates_valid": True})
        self.assertEqual(ready.rule_id, "SM-004")
        candidate = transition(ready.state_after, StateEvent.ENTRY_INTENT, {"intent_valid": True, "cost_known": True})
        self.assertEqual(candidate.state_after.evaluation, EvaluationState.ENTRY_CANDIDATE)
        blocked = transition(candidate.state_after, StateEvent.QUALITY_DEGRADED)
        self.assertEqual((blocked.rule_id, blocked.state_after.health), ("SM-006", HealthState.DEGRADED))
        self.assertNotEqual(blocked.action.value, "ENTER_LONG")

    def test_precedence_p0_wins_over_entry(self) -> None:
        current = state()
        entry = transition(current, StateEvent.ENTRY_INTENT, {"intent_valid": True, "cost_known": True})
        conflict = transition(current, StateEvent.POSITION_CONFLICT)
        self.assertEqual(resolve_precedence([entry, conflict]).rule_id, "SM-003")

    def test_duplicate_is_idempotent(self) -> None:
        current = state()
        first = transition(current, StateEvent.DUPLICATE_IDENTITY)
        second = transition(current, StateEvent.DUPLICATE_IDENTITY)
        self.assertEqual(first, second)
        self.assertIs(first.state_after, current)

    def test_invalid_state_combinations_rejected(self) -> None:
        cases = [
            (PositionState.UNKNOWN, EvaluationState.ENTRY_CANDIDATE, HealthState.READY),
            (PositionState.LONG, EvaluationState.ENTRY_CANDIDATE, HealthState.READY),
            (PositionState.FLAT, EvaluationState.EXIT_CANDIDATE, HealthState.READY),
            (PositionState.ENTRY_PENDING, EvaluationState.COOLDOWN, HealthState.READY),
        ]
        for position, evaluation, health in cases:
            with self.subTest(position=position, evaluation=evaluation, health=health), self.assertRaises(ValidationError):
                SystemState(version="bad", position=position, evaluation=evaluation, health=health)


if __name__ == "__main__":
    unittest.main()
