from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from btc_decision_agent.adapters.ledger import (
    JsonlDecisionLedger,
    LedgerCollisionError,
    LedgerIncompleteError,
)
from btc_decision_agent.application.decision import DecisionMachine
from btc_decision_agent.application.services import DecisionPipeline
from btc_decision_agent.domain.features import build_cost_estimate
from btc_decision_agent.domain.risk import (
    RiskGovernor,
    assess_protection,
    initial_stop,
    trailing_stop,
)
from btc_decision_agent.domain.state_machine import StateEvent, transition
from tests.helpers import NEXT, NOW, D, portfolio, product, risk, state

from btc_decision_agent.domain.canonical import sha256_id
from btc_decision_agent.domain.contracts import (
    Action,
    CandidateIntent,
    CostScenario,
    EvaluationState,
    FreshnessStatus,
    IntentType,
    MarketContext,
    PositionState,
    PriorityClass,
    QualifiedMarketFrame,
    QualityStatus,
    RiskDecision,
    TriggerType,
)
from btc_decision_agent.policies import NullHoldPolicy


def context(version: str = "context-1", frame_ref: str = "frame-1") -> MarketContext:
    return MarketContext(version=version, frame_ref=frame_ref, symbol="BTC/USDT", decision_time=NOW, horizon="1h", current_bar_id=None, features=(), quality=QualityStatus.QUALIFIED)


def entry_intent(*, state_ref: str | None = None, context_ref: str = "context-1", cost_ref: str = "cost-1", evaluation_id: str = "eval-1") -> CandidateIntent:
    actual_state = state_ref or state().version
    identity = {"policy": "POL-101", "evaluation": evaluation_id, "state": actual_state, "time": NOW}
    return CandidateIntent(intent_id=sha256_id(identity), intent_type=IntentType.ENTRY_CANDIDATE, policy_id="POL-101", policy_version="1.0.0", evaluation_id=evaluation_id, state_ref=actual_state, market_context_ref=context_ref, cost_estimate_ref=cost_ref, primary_reason="POL101_ENTRY_SETUP_COMPLETE", reason_codes=("POL101_ENTRY_SETUP_COMPLETE",), effective_at=NOW, expires_at=NEXT, quality=QualityStatus.QUALIFIED)


def frame(frame_id: str = "frame-1", event_id: str = "event-1") -> QualifiedMarketFrame:
    return QualifiedMarketFrame(frame_id=frame_id, symbol="BTC/USDT", event_time_max=NOW, observed_at=NOW, event_ids=(event_id,), source_watermarks={"S-04": NOW}, complete=True, freshness=FreshnessStatus.FRESH, quality=QualityStatus.QUALIFIED, bid=D("99.9"), ask=D("100.1"), bbo_event_id=event_id, bbo_observed_at=NOW)


class RiskDecisionTests(unittest.TestCase):
    def cost(self, version: str = "cost-1", frame_ref: str = "frame-1"):
        return build_cost_estimate(
            version,
            D("10"),
            CostScenario.ADVERSE,
            D("20"),
            D("18"),
            D("10"),
            D("5"),
            D("1"),
            NOW,
            frame_ref=frame_ref,
            input_event_ids=("event-1",),
            max_input_event_time=NOW,
        )

    def verdict(self, intent: CandidateIntent | None = None):
        chosen = intent or entry_intent()
        market_context = context(chosen.market_context_ref or "context-1")
        return RiskGovernor().evaluate(chosen, risk(), portfolio(), self.cost(chosen.cost_estimate_ref or "cost-1"), NOW, market_context=market_context, reference_price=D("100"), stop_distance=D("4"), adverse_buffer=D("1"))

    def test_governor_sizing_is_bounded_pure_and_binds_inputs(self) -> None:
        intent = entry_intent()
        cost = self.cost()
        governor = RiskGovernor()
        market_context = context()
        verdict = governor.evaluate(intent, risk(), portfolio(), cost, NOW, market_context=market_context, reference_price=D("100"), stop_distance=D("4"), adverse_buffer=D("1"))
        repeated = governor.evaluate(intent, risk(), portfolio(), cost, NOW, market_context=market_context, reference_price=D("100"), stop_distance=D("4"), adverse_buffer=D("1"))
        self.assertEqual(verdict.decision, RiskDecision.APPROVED)
        self.assertLessEqual(verdict.approved_qty * D("100"), risk().max_exposure)
        self.assertEqual(verdict.canonical_bytes(), repeated.canonical_bytes())
        self.assertEqual((verdict.state_ref, verdict.portfolio_state_version, verdict.cost_estimate_version, verdict.market_context_ref), (state().version, portfolio().version, cost.version, context().version))
        rejected = governor.evaluate(intent, None, portfolio(), cost, NOW, market_context=market_context, reference_price=D("100"), stop_distance=D("4"))
        self.assertEqual((rejected.decision, rejected.reason), (RiskDecision.REJECTED, "MANDATE_MISSING"))
        zero_vol = governor.evaluate(intent, risk(), portfolio(), cost, NOW, market_context=market_context, reference_price=D("100"), stop_distance=D("0"))
        self.assertEqual(zero_vol.decision, RiskDecision.REJECTED)

    def test_stop_and_trailing_never_relax(self) -> None:
        self.assertEqual(initial_stop(D("100"), D("4"), D("1.5")), D("94.0"))
        self.assertEqual(trailing_stop(D("95"), D("110"), D("4"), D("2")), D("102"))
        self.assertEqual(trailing_stop(D("105"), D("110"), D("4"), D("2")), D("105"))
        protection = assess_protection(portfolio(PositionState.LONG, D("1")), risk(), current_price=D("93"), initial_stop_price=D("94"))
        self.assertTrue(protection.triggered)
        self.assertEqual(protection.reason, "PROTECTIVE_INVALIDATION")
        cooldown = transition(state(), StateEvent.COOLDOWN_STARTED, {"duration_bars": 2})
        self.assertEqual(cooldown.state_after.evaluation, EvaluationState.COOLDOWN)

    def test_machine_requires_all_current_authority_bindings(self) -> None:
        machine, intent, cost, market_context = DecisionMachine(), entry_intent(), self.cost(), context()
        verdict = self.verdict(intent)
        inputs = dict(evaluation_id="eval-1", state=state(), portfolio=portfolio(), product_mandate=product(), risk_mandate=risk(), market_context=market_context, cost_estimate=cost, risk_verdict=verdict, intent=intent, trigger_type=TriggerType.STRATEGIC_EVALUATION, event_time_max=NOW, decision_time=NOW, expires_at=NEXT)
        approved = machine.decide(**inputs)
        self.assertEqual((approved.action, approved.priority_class), (Action.ENTER_LONG, PriorityClass.P4_ENTRY))

        expired_product = product().model_copy(update={"valid_until": NOW})
        expired_risk = risk().model_copy(update={"valid_until": NOW})
        stale_context = context("context-stale")
        stale_cost = self.cost("cost-stale")
        cases = {
            "PRODUCT_MANDATE_EXPIRED": {"product_mandate": expired_product},
            "MANDATE_EXPIRED": {"risk_mandate": expired_risk},
            "INTENT_STATE_MISMATCH": {"intent": intent.model_copy(update={"state_ref": "stale-state"})},
            "RISK_PORTFOLIO_MISMATCH": {"risk_verdict": verdict.model_copy(update={"portfolio_state_version": "stale-portfolio"})},
            "RISK_COST_MISMATCH": {"risk_verdict": verdict.model_copy(update={"cost_estimate_version": "stale-cost"})},
            "CONTEXT_REFERENCE_MISMATCH": {"market_context": stale_context},
            "RISK_CONTEXT_MISMATCH": {"risk_verdict": verdict.model_copy(update={"market_context_ref": "stale-context"})},
            "RISK_MANDATE_MISMATCH": {"risk_verdict": verdict.model_copy(update={"mandate_version": "stale-mandate"})},
            "COST_REFERENCE_MISMATCH": {"cost_estimate": stale_cost},
        }
        for expected, changes in cases.items():
            with self.subTest(expected=expected):
                decision = machine.decide(**{**inputs, **changes})
                self.assertEqual((decision.action, decision.primary_reason), (Action.HOLD, expected))

        blocked = machine.decide(**{**inputs, "blockers": ("DATA_BLOCKED",)})
        self.assertEqual((blocked.action, blocked.priority_class, blocked.state_after.health, blocked.quality_status), (Action.HOLD, PriorityClass.P2_SYSTEM_BLOCK, blocked.quality_status.BLOCKED, blocked.quality_status.BLOCKED))
        risk_rejected = machine.decide(**{**inputs, "risk_verdict": verdict.model_copy(update={"decision": RiskDecision.REJECTED, "approved_qty": None})})
        self.assertEqual((risk_rejected.action, risk_rejected.state_after.health), (Action.HOLD, state().health))

    def test_ledger_validates_real_artifacts_and_suppresses_duplicate_export(self) -> None:
        intent, cost, market_context = entry_intent(), self.cost(), context()
        verdict = self.verdict(intent)
        decision_inputs = dict(evaluation_id="eval-1", state=state(), portfolio=portfolio(), product_mandate=product(), risk_mandate=risk(), market_context=market_context, cost_estimate=cost, risk_verdict=verdict, intent=intent, trigger_type=TriggerType.STRATEGIC_EVALUATION, event_time_max=NOW, decision_time=NOW, expires_at=NEXT)
        artifacts = {"frame": frame(), "context": market_context, "cost": cost, "intent": intent, "product_mandate": product(), "risk_mandate": risk(), "portfolio": portfolio(), "system_state": state(), "risk_verdict": verdict}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            pipeline = DecisionPipeline(JsonlDecisionLedger(path))
            first = pipeline.decide_record_export(DecisionMachine(), artifacts=artifacts, transition_rule="SM-013", recorded_at=NOW, **decision_inputs)
            second = pipeline.decide_record_export(DecisionMachine(), artifacts=artifacts, transition_rule="SM-013", recorded_at=NOW, **decision_inputs)
            self.assertTrue(first.exported)
            self.assertFalse(second.exported)
            self.assertEqual(second.status, "DUPLICATE_SUPPRESSED")
            self.assertEqual(len(path.read_bytes().splitlines()), 1)
            self.assertEqual(JsonlDecisionLedger(path).records()[0].record_hash, first.record.record_hash)
            with self.assertRaises(LedgerIncompleteError):
                JsonlDecisionLedger(Path(directory) / "incomplete.jsonl").append(first.decision, {"intent": intent}, "SM-013", NOW)
            foreign_path = Path(directory) / "foreign-frame.jsonl"
            foreign_artifacts = {
                **artifacts,
                "frame": frame("unrelated-frame", "unrelated-event"),
            }
            with self.assertRaisesRegex(LedgerIncompleteError, "context frame"):
                JsonlDecisionLedger(foreign_path).append(first.decision, foreign_artifacts, "SM-013", NOW)
            self.assertFalse(foreign_path.exists())
            conflicting = first.decision.model_copy(update={"primary_reason": "DIFFERENT"})
            with self.assertRaises(LedgerCollisionError):
                pipeline.ledger.append(conflicting, artifacts, "SM-013", NOW)

            null_intent = NullHoldPolicy().evaluate("eval-2", state().version, NOW, NEXT)
            hold = DecisionMachine().decide(evaluation_id="eval-2", state=state(), portfolio=portfolio(), product_mandate=product(), intent=null_intent, trigger_type=TriggerType.STRATEGIC_EVALUATION, event_time_max=NOW, decision_time=NOW, expires_at=NEXT)
            hold_artifacts = {"intent": null_intent, "product_mandate": product(), "portfolio": portfolio(), "system_state": state()}
            pipeline.ledger.append(hold, hold_artifacts, "SM-009", NOW + timedelta(seconds=1))
            tampered_lines = [json.loads(line) for line in path.read_text().splitlines()]
            tampered_lines[1]["previous_record_hash"] = None
            path.write_text("\n".join(json.dumps(line, separators=(",", ":")) for line in tampered_lines) + "\n")
            with self.assertRaisesRegex(LedgerCollisionError, "broken ledger chain"):
                JsonlDecisionLedger(path)


if __name__ == "__main__":
    unittest.main()
