"""Deterministic technical observability projection; no dashboard or execution controls."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from btc_decision_agent.domain.contracts import (
    CandidateIntent,
    CostEstimate,
    Decision,
    MarketContext,
    PortfolioState,
    RiskVerdict,
    SystemState,
)


@dataclass(frozen=True)
class ObservabilitySnapshot:
    state: str
    health_by_source: tuple[tuple[str, str], ...]
    freshness_by_source: tuple[tuple[str, str], ...]
    last_decision_id: str
    action: str
    disposition: str
    quality_status: str
    primary_reason: str
    reason_codes: tuple[str, ...]
    intent_id: str
    intent_type: str
    risk_verdict_id: str | None
    risk_decision: str | None
    risk_reason: str | None
    approved_quantity: Decimal | None
    portfolio_version: str
    portfolio_reconciled: bool
    position: str
    base_quantity: Decimal | None
    cost_estimate_version: str | None
    cost_quality: str | None
    total_cost_bps: Decimal | None
    product_mandate_version: str
    risk_mandate_version: str | None
    policy_id: str | None
    policy_version: str | None
    market_context_version: str | None
    expires_at: str
    ledger_record_id: str
    replay_ref: str | None


def project(*, state: SystemState, source_health: dict[str, str], decision: Decision, intent: CandidateIntent, verdict: RiskVerdict | None, portfolio: PortfolioState, cost: CostEstimate | None, ledger_record_id: str, replay_ref: str | None = None, market_context: MarketContext | None = None, source_freshness: dict[str, str] | None = None) -> ObservabilitySnapshot:
    """Project critical versions, authorization and blocking evidence in stable order."""
    return ObservabilitySnapshot(
        state=f"{state.position.value}/{state.evaluation.value}/{state.health.value}",
        health_by_source=tuple(sorted(source_health.items())),
        freshness_by_source=tuple(sorted((source_freshness or {}).items())),
        last_decision_id=decision.decision_id,
        action=decision.action.value,
        disposition=decision.disposition.value,
        quality_status=decision.quality_status.value,
        primary_reason=decision.primary_reason,
        reason_codes=decision.reason_codes,
        intent_id=intent.intent_id,
        intent_type=intent.intent_type.value,
        risk_verdict_id=verdict.verdict_id if verdict else None,
        risk_decision=verdict.decision.value if verdict else None,
        risk_reason=verdict.reason if verdict else None,
        approved_quantity=verdict.approved_qty if verdict else None,
        portfolio_version=portfolio.version,
        portfolio_reconciled=portfolio.reconciled,
        position=portfolio.position.value,
        base_quantity=portfolio.base_quantity,
        cost_estimate_version=cost.version if cost else None,
        cost_quality=cost.quality.value if cost else None,
        total_cost_bps=cost.total_bps if cost else None,
        product_mandate_version=decision.product_mandate_version,
        risk_mandate_version=decision.risk_mandate_version,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        market_context_version=market_context.version if market_context else decision.market_context_ref,
        expires_at=decision.expires_at.isoformat(),
        ledger_record_id=ledger_record_id,
        replay_ref=replay_ref,
    )
