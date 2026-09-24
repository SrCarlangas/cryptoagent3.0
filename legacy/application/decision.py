"""Pure DecisionMachine with mandatory P0..P5 precedence and current-state binding."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from btc_decision_agent.domain.canonical import sha256_id
from btc_decision_agent.domain.contracts import (
    Action,
    CandidateIntent,
    CostEstimate,
    Decision,
    Direction,
    Disposition,
    EvaluationState,
    HealthState,
    IntentType,
    MarketContext,
    PortfolioState,
    PositionState,
    PriorityClass,
    ProductMandate,
    RiskDecision,
    RiskMandate,
    RiskVerdict,
    SystemState,
    TargetMode,
    TargetPosition,
    TriggerType,
)


class DecisionMachine:
    """Resolve one contractual action without executing or mutating portfolio state."""

    def decide(
        self,
        *,
        evaluation_id: str,
        state: SystemState,
        portfolio: PortfolioState,
        product_mandate: ProductMandate,
        risk_mandate: RiskMandate | None = None,
        market_context: MarketContext | None = None,
        cost_estimate: CostEstimate | None = None,
        risk_verdict: RiskVerdict | None = None,
        intent: CandidateIntent,
        trigger_type: TriggerType,
        event_time_max: datetime,
        decision_time: datetime,
        expires_at: datetime,
        blockers: tuple[str, ...] = (),
        protective_reason: str | None = None,
    ) -> Decision:
        action, disposition, priority, reason = Action.HOLD, Disposition.NO_CHANGE, PriorityClass.P5_NO_CHANGE, "NO_INTENT"
        after = state

        if protective_reason is not None and protective_reason not in {"RISK_LIMIT_BREACH", "PROTECTIVE_INVALIDATION", "MANDATE_REVOKED", "POSITION_ANOMALY", "DATA_RISK_WITH_KNOWN_POSITION"}:
            raise ValueError("unknown protective reason")

        if state.position == PositionState.UNKNOWN or not portfolio.reconciled:
            disposition, priority, reason = Disposition.BLOCKED, PriorityClass.P0_RECONCILIATION_BLOCK, "STATE_UNKNOWN"
            after = self._blocked_state(state, reason)
        elif protective_reason is not None and state.position == PositionState.LONG:
            action, disposition, priority, reason = Action.EXIT_LONG, Disposition.ACTIONABLE, PriorityClass.P1_PROTECTIVE_EXIT, protective_reason
            after = SystemState(version=sha256_id({"before": state.version, "position": "EXIT_PENDING", "reason": reason}), position=PositionState.EXIT_PENDING, evaluation=EvaluationState.IDLE, health=state.health)
        elif blockers:
            disposition, priority, reason = Disposition.BLOCKED, PriorityClass.P2_SYSTEM_BLOCK, sorted(blockers)[0]
            after = self._blocked_state(state, reason)
        elif intent.intent_type == IntentType.EXIT_CANDIDATE and state.position == PositionState.LONG:
            action, disposition, priority, reason = Action.EXIT_LONG, Disposition.ACTIONABLE, PriorityClass.P3_STRATEGIC_EXIT, intent.primary_reason
            after = SystemState(version=sha256_id({"before": state.version, "position": "EXIT_PENDING", "reason": reason}), position=PositionState.EXIT_PENDING, evaluation=EvaluationState.IDLE, health=state.health)
        elif intent.intent_type == IntentType.ENTRY_CANDIDATE:
            entry_rejection = self._entry_rejection(
                evaluation_id=evaluation_id,
                state=state,
                portfolio=portfolio,
                product_mandate=product_mandate,
                risk_mandate=risk_mandate,
                market_context=market_context,
                cost_estimate=cost_estimate,
                risk_verdict=risk_verdict,
                intent=intent,
                decision_time=decision_time,
            )
            if entry_rejection is not None:
                reason = entry_rejection
                disposition, priority = Disposition.BLOCKED, PriorityClass.P2_SYSTEM_BLOCK
                if reason.startswith(("MANDATE_", "PRODUCT_MANDATE_", "DATA_", "CONTEXT_", "COST_")):
                    after = self._blocked_state(state, reason)
            else:
                action, disposition, priority, reason = Action.ENTER_LONG, Disposition.ACTIONABLE, PriorityClass.P4_ENTRY, "OPPORTUNITY_APPROVED"
                after = SystemState(version=sha256_id({"before": state.version, "position": "ENTRY_PENDING", "intent": intent.intent_id}), position=PositionState.ENTRY_PENDING, evaluation=EvaluationState.IDLE, health=HealthState.READY)
        elif state.evaluation == EvaluationState.COOLDOWN:
            reason = "COOLDOWN"
        elif state.position in {PositionState.ENTRY_PENDING, PositionState.EXIT_PENDING}:
            reason = "PENDING_FEEDBACK"
        elif intent.primary_reason == "POLICY_NULL_CONTROL":
            reason = "NO_INTENT"
        else:
            reason = intent.primary_reason

        if action == Action.ENTER_LONG:
            quantity = risk_verdict.approved_qty if risk_verdict else None
            target = TargetPosition(mode=TargetMode.ABSOLUTE, direction=Direction.LONG, base_quantity=quantity, source="RISK_VERDICT", portfolio_state_version=portfolio.version)
        elif action == Action.EXIT_LONG:
            target = TargetPosition(mode=TargetMode.ABSOLUTE, direction=Direction.FLAT, base_quantity=Decimal("0"), source="PROTECTIVE_FULL_EXIT" if priority == PriorityClass.P1_PROTECTIVE_EXIT else "CURRENT_RECONCILED_STATE", portfolio_state_version=portfolio.version)
        elif portfolio.position == PositionState.UNKNOWN:
            target = TargetPosition(mode=TargetMode.UNCHANGED, direction=Direction.UNKNOWN, base_quantity=None, source="CURRENT_RECONCILED_STATE", portfolio_state_version=portfolio.version)
        else:
            direction = Direction.LONG if portfolio.base_quantity and portfolio.base_quantity > 0 else Direction.FLAT
            target = TargetPosition(mode=TargetMode.UNCHANGED, direction=direction, base_quantity=portfolio.base_quantity, source="CURRENT_RECONCILED_STATE", portfolio_state_version=portfolio.version)

        reasons = tuple(sorted({reason, *blockers}))
        explicit_refs = {intent.intent_id, *(ref for ref in (intent.market_context_ref, intent.cost_estimate_ref) if ref is not None)}
        if risk_verdict is not None:
            explicit_refs.add(risk_verdict.verdict_id)
        evidence = tuple(sorted(explicit_refs | set(blockers)))
        identity = {
            "schema_version": "decision/1.0.0",
            "evaluation_id": evaluation_id,
            "action": action,
            "priority_class": priority,
            "state_before": state.version,
            "portfolio_state_version": portfolio.version,
            "product_mandate_version": product_mandate.version,
            "risk_mandate_version": risk_verdict.mandate_version if risk_verdict else None,
            "policy_id": intent.policy_id,
            "policy_version": intent.policy_version,
            "market_context_version": market_context.version if market_context else None,
            "cost_estimate_version": cost_estimate.version if cost_estimate else None,
            "risk_verdict_version": risk_verdict.verdict_id if risk_verdict else None,
            "decision_time": decision_time,
            "effective_at": decision_time,
            "expires_at": expires_at,
            "target_position": target,
            "primary_reason": reason,
            "reason_codes": reasons,
            "evidence_refs": evidence,
        }
        return Decision(decision_id=sha256_id(identity), evaluation_id=evaluation_id, action=action, disposition=disposition, priority_class=priority, trigger_type=trigger_type, symbol=product_mandate.symbol, product_mandate_version=product_mandate.version, risk_mandate_version=risk_verdict.mandate_version if risk_verdict else None, policy_id=intent.policy_id, policy_version=intent.policy_version, intent_ref=intent.intent_id, market_context_ref=intent.market_context_ref, cost_estimate_ref=intent.cost_estimate_ref, risk_verdict_ref=risk_verdict.verdict_id if risk_verdict else None, state_before=state, state_after=after, target_position=target, primary_reason=reason, reason_codes=reasons, evidence_refs=evidence, event_time_max=event_time_max, decision_time=decision_time, effective_at=decision_time, expires_at=expires_at, quality_status=after.health)

    @staticmethod
    def _blocked_state(state: SystemState, reason: str) -> SystemState:
        return SystemState(version=sha256_id({"before": state.version, "health": "BLOCKED", "reason": reason}), position=state.position, evaluation=EvaluationState.IDLE, health=HealthState.BLOCKED)

    @staticmethod
    def _entry_rejection(
        *,
        evaluation_id: str,
        state: SystemState,
        portfolio: PortfolioState,
        product_mandate: ProductMandate,
        risk_mandate: RiskMandate | None,
        market_context: MarketContext | None,
        cost_estimate: CostEstimate | None,
        risk_verdict: RiskVerdict | None,
        intent: CandidateIntent,
        decision_time: datetime,
    ) -> str | None:
        if not (product_mandate.valid_from <= decision_time < product_mandate.valid_until):
            return "PRODUCT_MANDATE_EXPIRED"
        if risk_mandate is None:
            return "MANDATE_MISSING"
        if not (risk_mandate.valid_from <= decision_time < risk_mandate.valid_until):
            return "MANDATE_EXPIRED"
        if intent.state_ref != state.version:
            return "INTENT_STATE_MISMATCH"
        if intent.evaluation_id != evaluation_id:
            return "INTENT_EVALUATION_MISMATCH"
        if not (intent.effective_at <= decision_time < intent.expires_at):
            return "INTENT_OR_VERDICT_EXPIRED"
        if state.position != PositionState.FLAT or state.health != HealthState.READY or state.evaluation not in {EvaluationState.IDLE, EvaluationState.ENTRY_CANDIDATE}:
            return "INVALID_STATE_COMBINATION"
        if market_context is None or intent.market_context_ref != market_context.version:
            return "CONTEXT_REFERENCE_MISMATCH"
        if market_context.decision_time != decision_time or market_context.quality.value != "QUALIFIED":
            return "CONTEXT_NOT_CURRENT"
        if cost_estimate is None or intent.cost_estimate_ref != cost_estimate.version:
            return "COST_REFERENCE_MISMATCH"
        if cost_estimate.quality.value != "QUALIFIED" or cost_estimate.total_bps is None or cost_estimate.as_of_time > decision_time or cost_estimate.max_input_event_time > decision_time or cost_estimate.action != Action.ENTER_LONG:
            return "COST_NOT_APPLICABLE"
        if cost_estimate.frame_ref != market_context.frame_ref:
            return "COST_FRAME_MISMATCH"
        if risk_verdict is None or risk_verdict.decision != RiskDecision.APPROVED:
            return "RISK_REJECTED"
        if risk_verdict.intent_id != intent.intent_id:
            return "RISK_VERDICT_MISMATCH"
        if risk_verdict.state_ref != state.version:
            return "RISK_STATE_MISMATCH"
        if risk_verdict.portfolio_state_version != portfolio.version:
            return "RISK_PORTFOLIO_MISMATCH"
        if risk_verdict.cost_estimate_version != cost_estimate.version:
            return "RISK_COST_MISMATCH"
        if risk_verdict.market_context_ref != market_context.version:
            return "RISK_CONTEXT_MISMATCH"
        if risk_verdict.mandate_version != risk_mandate.version:
            return "RISK_MANDATE_MISMATCH"
        if risk_verdict.as_of_time != decision_time:
            return "INTENT_OR_VERDICT_EXPIRED"
        if risk_verdict.approved_qty is None or risk_verdict.approved_qty > cost_estimate.base_quantity:
            return "COST_SIZE_MISMATCH"
        return None
