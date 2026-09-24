from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import timedelta

from btc_decision_agent.adapters.book import DepthDiff, DepthSnapshot, LocalBook
from btc_decision_agent.adapters.quality import DataQualityGuard
from btc_decision_agent.application.decision import DecisionMachine
from btc_decision_agent.domain.features import Bar, depth_vwap, round_trip_cost, true_range
from btc_decision_agent.domain.state_machine import StateEvent, transition
from btc_decision_agent.validation.offline import FrozenOOSGate, OOSMetrics, evaluate_frozen_gate
from tests.helpers import NEXT, NOW, D, features, idle_policy, params, portfolio, product, state

from btc_decision_agent.domain.contracts import (
    Action,
    ClockBasis,
    EvaluationState,
    EventType,
    FreshnessPolicy,
    HealthState,
    IntentType,
    MarketEventV1,
    PositionState,
    PriorityClass,
    QualityStatus,
    Transport,
    TriggerType,
    Usage,
)
from btc_decision_agent.policies import (
    NullHoldPolicy,
    POL101Context,
    TrendSetupState,
    evaluate_pol101,
)


class NormativeScenarioEvidence(unittest.TestCase):
    def ctx(self, **changes: object) -> POL101Context:
        base = POL101Context("eval", TriggerType.STRATEGIC_EVALUATION, NOW, NOW, NEXT, state(), "state", "context", "bar", features(), features(distance=D("0.018")), idle_policy())
        return replace(base, **changes)

    def armed(self):
        return replace(idle_policy(), state=TrendSetupState.PULLBACK_ARMED, setup_id="setup", armed_at_bar_id="bar", state_version="armed")

    def null(self, system_state=None):
        selected = system_state or state()
        return NullHoldPolicy().evaluate("eval", selected.version, NOW, NEXT)

    def test_sc_01_through_sc_24_execute_real_guards(self) -> None:
        p, armed = params(), self.armed()
        long_state = state(PositionState.LONG)
        exit_pending = state(PositionState.EXIT_PENDING)
        scenarios = {
            "SC-01": evaluate_pol101(self.ctx(policy_state=armed, features=features(distance=D("0.021"))), p).candidate_intent.intent_type == IntentType.ENTRY_CANDIDATE,
            "SC-02": evaluate_pol101(self.ctx(policy_state=armed, features=features(distance=D("0.021"), volume=D("1"))), p).evaluation_reason == "POL101_VOLUME_NOT_CONFIRMED",
            "SC-03": not features(qualified=False).entry_complete(NOW),
            "SC-04": evaluate_pol101(self.ctx(policy_state=armed, features=features(cost=D("61"))), p).evaluation_reason == "POL101_COST_CAP_EXCEEDED",
            "SC-05": DecisionMachine().decide(evaluation_id="e", state=state(), portfolio=portfolio(), product_mandate=product(), risk_verdict=None, intent=self.null(), trigger_type=TriggerType.STRATEGIC_EVALUATION, event_time_max=NOW, decision_time=NOW, expires_at=NEXT, blockers=("DATA_BLOCKED",)).action == Action.HOLD,
            "SC-06": self._l2_gap_revokes(),
            "SC-07": evaluate_pol101(self.ctx(policy_state=armed, features=features(slope=D("0"))), p).evaluation_reason == "POL101_TREND_INVALIDATED",
            "SC-08": self.null().intent_type == IntentType.NO_INTENT,
            "SC-09": evaluate_pol101(self.ctx(features=replace(features(), atr_fraction=D("0.061"))), p).evaluation_reason == "POL101_TREND_CONTEXT_FALSE",
            "SC-10": evaluate_pol101(self.ctx(duplicate_seen=True), p).evaluation_reason == "POL101_DUPLICATE",
            "SC-11": DecisionMachine().decide(evaluation_id="e", state=state(PositionState.UNKNOWN, EvaluationState.IDLE, HealthState.BLOCKED), portfolio=portfolio(PositionState.UNKNOWN, reconciled=False), product_mandate=product(), risk_verdict=None, intent=self.null(state(PositionState.UNKNOWN, EvaluationState.IDLE, HealthState.BLOCKED)), trigger_type=TriggerType.STRATEGIC_EVALUATION, event_time_max=NOW, decision_time=NOW, expires_at=NEXT).priority_class == PriorityClass.P0_RECONCILIATION_BLOCK,
            "SC-12": transition(state(), StateEvent.POSITION_CONFLICT).state_after.position == PositionState.UNKNOWN,
            "SC-13": DecisionMachine().decide(evaluation_id="e", state=state(), portfolio=portfolio(), product_mandate=product(), risk_verdict=None, intent=evaluate_pol101(self.ctx(policy_state=armed, features=features(distance=D("0.021"))), p).candidate_intent, trigger_type=TriggerType.STRATEGIC_EVALUATION, event_time_max=NOW, decision_time=NOW, expires_at=NEXT).primary_reason == "MANDATE_MISSING",
            "SC-14": self._protective(long_state).priority_class == PriorityClass.P1_PROTECTIVE_EXIT,
            "SC-15": evaluate_pol101(self.ctx(system_state=long_state, features=features(slope=D("-0.01"))), p).candidate_intent.intent_type == IntentType.EXIT_CANDIDATE,
            "SC-16": evaluate_pol101(self.ctx(policy_state=armed, features=features(cost=None)), p).evaluation_reason == "POL101_COST_UNKNOWN",
            "SC-17": self._protective(state(PositionState.LONG, EvaluationState.IDLE, HealthState.DEGRADED)).action == Action.EXIT_LONG,
            "SC-18": transition(exit_pending, StateEvent.EXIT_PARTIAL, {"authoritative": True, "residual": D("0.5")}).rule_id == "SM-024",
            "SC-19": transition(exit_pending, StateEvent.EXECUTION_CANCELLED, {"residual": D("0.5")}).rule_id == "SM-026",
            "SC-20": evaluate_pol101(self.ctx(system_state=state(PositionState.FLAT, EvaluationState.COOLDOWN, HealthState.READY)), p).evaluation_reason == "POL101_COOLDOWN_ACTIVE",
            "SC-21": transition(state(), StateEvent.UNKNOWN_SCHEMA).rule_id == "SM-031",
            "SC-22": transition(state(), StateEvent.MANDATE_EXPIRED).rule_id == "SM-008",
            "SC-23": evaluate_pol101(self.ctx(policy_state=replace(armed, bars_since_arm=3)), p).evaluation_reason == "POL101_ARM_TIMEOUT",
            "SC-24": evaluate_pol101(self.ctx(system_state=long_state, holding_bars=8), p).evaluation_reason == "POL101_EXIT_TIME",
        }
        self.assertEqual(len(scenarios), 24)
        for scenario_id, observed_behavior in scenarios.items():
            with self.subTest(scenario=scenario_id):
                self.assertTrue(observed_behavior)

    def _protective(self, system_state):
        return DecisionMachine().decide(evaluation_id="protect", state=system_state, portfolio=portfolio(PositionState.LONG, D("1")), product_mandate=product(), risk_verdict=None, intent=self.null(system_state), trigger_type=TriggerType.PROTECTIVE_EVALUATION, event_time_max=NOW, decision_time=NOW, expires_at=NEXT, protective_reason="RISK_LIMIT_BREACH")

    def _l2_gap_revokes(self) -> bool:
        book = LocalBook("evidence", "meta")
        book.open()
        book.buffer_diff(DepthDiff(101, 101, ((D("100"), D("1")),), ((D("101"), D("1")),), NOW, NOW))
        book.request_snapshot()
        book.load_snapshot(DepthSnapshot(100, ((D("100"), D("1")),), ((D("101"), D("1")),), 100, NOW))
        result = book.apply_diff(DepthDiff(104, 104, (), (), NOW, NOW))
        return not result and book.generation.revoked


class AdversarialEvidence(unittest.TestCase):
    def test_fmea_01_through_14_have_observable_mitigations(self) -> None:
        cost_unknown = round_trip_cost((D("1"), None)) is None
        state_unknown = transition(state(), StateEvent.POSITION_CONFLICT).state_after.health == HealthState.BLOCKED
        duplicate = transition(state(), StateEvent.DUPLICATE_IDENTITY).state_after == state()
        gap = NormativeScenarioEvidence()._l2_gap_revokes()
        mitigations = {
            "FM-01": cost_unknown,
            "FM-02": gap,
            "FM-03": not features(qualified=False).entry_complete(NOW),
            "FM-04": round_trip_cost((D("1"), None)) is None,
            "FM-05": duplicate,
            "FM-06": bool(DecisionMachine().decide(evaluation_id="e", state=state(), portfolio=portfolio(), product_mandate=product(), risk_verdict=None, intent=NullHoldPolicy().evaluate("e", "s", NOW, NEXT), trigger_type=TriggerType.STRATEGIC_EVALUATION, event_time_max=NOW, decision_time=NOW, expires_at=NEXT).primary_reason),
            "FM-07": transition(state(), StateEvent.POSITION_CONFLICT).priority == PriorityClass.P0_RECONCILIATION_BLOCK,
            "FM-08": DecisionMachine().decide(evaluation_id="e", state=state(), portfolio=portfolio(), product_mandate=product(), risk_verdict=None, intent=NullHoldPolicy().evaluate("e", "s", NOW, NEXT).model_copy(update={"intent_type": IntentType.ENTRY_CANDIDATE}), trigger_type=TriggerType.STRATEGIC_EVALUATION, event_time_max=NOW, decision_time=NOW, expires_at=NEXT).action == Action.HOLD,
            "FM-09": not hasattr(NullHoldPolicy(), "risk_mandate"),
            "FM-10": state_unknown,
            "FM-11": self._late_correction_is_non_retroactive(),
            "FM-12": cost_unknown,
            "FM-13": transition(state(PositionState.EXIT_PENDING), StateEvent.EXIT_PARTIAL, {"authoritative": True, "residual": D("0.5")}).state_after.position == PositionState.EXIT_PENDING,
            "FM-14": transition(state(PositionState.EXIT_PENDING), StateEvent.EXECUTION_CANCELLED, {"residual": D("0.5")}).state_after.evaluation == EvaluationState.EXIT_CANDIDATE,
        }
        self.assertEqual(len(mitigations), 14)
        for failure_id, mitigated in mitigations.items():
            with self.subTest(failure=failure_id):
                self.assertTrue(mitigated)

    def _late_correction_is_non_retroactive(self) -> bool:
        historical = DecisionMachine().decide(
            evaluation_id="historical",
            state=state(),
            portfolio=portfolio(),
            product_mandate=product(),
            risk_verdict=None,
            intent=NullHoldPolicy().evaluate("historical", "state", NOW, NEXT),
            trigger_type=TriggerType.STRATEGIC_EVALUATION,
            event_time_max=NOW,
            decision_time=NOW,
            expires_at=NEXT,
        )
        before = historical.canonical_bytes()
        event = MarketEventV1(
            event_id="late-event",
            event_type=EventType.KLINE_CLOSED,
            source_contract_id="S-03",
            provider_contract_version="v1",
            transport=Transport.FIXTURE,
            channel="kline",
            symbol="BTC/USDT",
            event_time=NOW,
            observed_at=NOW + timedelta(seconds=10),
            source_identity={"bar": "old"},
            payload={"is_closed": True, "bar_close_time": NOW},
            payload_hash="late-payload",
            provenance={},
            quality=QualityStatus.QUALIFIED,
        )
        policy = FreshnessPolicy(
            policy_version="D-014/1",
            source_contract_id="S-03",
            event_type=EventType.KLINE_CLOSED,
            usage=Usage.STRATEGIC,
            required=True,
            clock_basis=ClockBasis.EVENT_TIME,
            warning_age_ms=100,
            max_age_ms=1000,
            allowed_lateness_ms=500,
            clock_skew_budget_ms=100,
            recovery_evidence_n=2,
            on_suspect="BLOCK",
            on_stale="BLOCK",
            decision_refs=(historical.decision_id,),
        )
        guard = DataQualityGuard()
        progress = event.model_copy(update={"event_id": "progress-event", "event_time": NEXT, "observed_at": NEXT, "source_identity": {"bar": "new"}, "payload_hash": "progress-payload"})
        guard.classify(progress, policy, NEXT)
        correction = guard.classify(event, policy, NOW + timedelta(seconds=10))
        return (
            not correction.apply
            and correction.reason == "NO_RETROACTIVE_DECISION"
            and historical.canonical_bytes() == before
        )

    def test_red_team_01_through_10_cannot_force_entry(self) -> None:
        p = params()
        armed = replace(idle_policy(), state=TrendSetupState.PULLBACK_ARMED, setup_id="s", armed_at_bar_id="b", state_version="armed")
        helper = NormativeScenarioEvidence()
        attacks = {
            "RT-01": evaluate_pol101(helper.ctx(policy_state=armed, features=features(slope=D("0"))), p).candidate_intent.intent_type != IntentType.ENTRY_CANDIDATE,
            "RT-02": true_range(Bar("now", NOW, NEXT, D("110"), D("112"), D("109"), D("111"), D("1")), Bar("prior", NOW - timedelta(hours=1), NOW, D("100"), D("101"), D("99"), D("100"), D("1")), NEXT).value == D("12"),
            "RT-03": not features(qualified=False).entry_complete(NOW),
            "RT-04": NullHoldPolicy().evaluate("e", "s", NOW, NEXT).intent_type == IntentType.NO_INTENT,
            "RT-05": depth_vwap(((D("101"), D("0.1")),), D("1"), "buy")[0] is None,
            "RT-06": round_trip_cost((D("20"), D("20"), D("20"))) == D("60"),
            "RT-07": round_trip_cost((D("20"), None)) is None,
            "RT-08": transition(state(), StateEvent.DUPLICATE_IDENTITY).action == Action.HOLD,
            "RT-09": not features(qualified=False).entry_complete(NOW),
            "RT-10": self._frozen_gate_resists_failed_tampering(),
        }
        self.assertEqual(len(attacks), 10)
        for attack_id, resisted in attacks.items():
            with self.subTest(attack=attack_id):
                self.assertTrue(resisted)

    def _frozen_gate_resists_failed_tampering(self) -> bool:
        gate = FrozenOOSGate()
        before = asdict(gate)
        failing = OOSMetrics(
            1,
            D("-1"),
            D("0"),
            D("1"),
            1,
            False,
            D("1"),
            D("1"),
            D("0"),
            D("100"),
        )
        result = evaluate_frozen_gate(failing, gate)
        mutation_blocked = False
        try:
            gate.margin_min = D("-999")  # type: ignore[misc]
        except FrozenInstanceError:
            mutation_blocked = True
        return not result.passed and mutation_blocked and asdict(gate) == before


if __name__ == "__main__":
    unittest.main()
