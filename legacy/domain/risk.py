"""Pure risk equations, protective controls and mandate governance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from .canonical import sha256_id
from .contracts import (
    CandidateIntent,
    CostEstimate,
    IntentType,
    MarketContext,
    PortfolioState,
    RiskDecision,
    RiskMandate,
    RiskVerdict,
)


def quantize_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def conservative_size(mandate: RiskMandate, portfolio: PortfolioState, reference_price: Decimal, stop_distance: Decimal, adverse_buffer: Decimal, cost_buffer_fraction: Decimal) -> tuple[Decimal | None, tuple[str, ...]]:
    """Bound quantity by risk, exposure and cash, always rounding down."""
    if not portfolio.reconciled or portfolio.available_cash is None:
        return None, ("STATE_UNKNOWN",)
    loss_per_unit = stop_distance + adverse_buffer
    if reference_price <= 0 or loss_per_unit <= 0 or cost_buffer_fraction < 0:
        return None, ("RISK_INPUT_INVALID",)
    qty_risk = mandate.risk_per_decision * mandate.capital / loss_per_unit
    qty_exposure = mandate.max_exposure / reference_price
    qty_cash = portfolio.available_cash / (reference_price * (Decimal("1") + cost_buffer_fraction))
    raw = min(qty_risk, qty_exposure, qty_cash)
    quantity = quantize_down(raw, mandate.step_size)
    if quantity <= 0 or quantity * reference_price < mandate.min_notional:
        return None, ("CAPITAL_INSUFFICIENT",)
    binding = []
    if raw == qty_risk:
        binding.append("RISK_PER_DECISION")
    if raw == qty_exposure:
        binding.append("MAX_EXPOSURE")
    if raw == qty_cash:
        binding.append("AVAILABLE_CASH")
    return quantity, tuple(binding)


def initial_stop(entry_ref: Decimal, atr_abs: Decimal, multiple: Decimal) -> Decimal:
    if entry_ref <= 0 or atr_abs <= 0 or multiple <= 0:
        raise ValueError("stop inputs must be positive")
    return entry_ref - atr_abs * multiple


def trailing_stop(previous: Decimal, high_since_entry: Decimal, atr_abs: Decimal, multiple: Decimal) -> Decimal:
    if min(previous, high_since_entry, atr_abs, multiple) <= 0:
        raise ValueError("trailing inputs must be positive")
    return max(previous, high_since_entry - atr_abs * multiple)


def breaker_reason(portfolio: PortfolioState, mandate: RiskMandate) -> str | None:
    if portfolio.drawdown >= mandate.drawdown_max:
        return "DRAWDOWN_BREAKER"
    if portfolio.daily_loss >= mandate.daily_loss_max:
        return "DAILY_LOSS_BREAKER"
    return None


class RiskGovernor:
    """Pure authority boundary: CandidateIntent in, immutable RiskVerdict out."""

    def evaluate(self, intent: CandidateIntent, mandate: RiskMandate | None, portfolio: PortfolioState, cost: CostEstimate | None, as_of: datetime, *, market_context: MarketContext | None = None, reference_price: Decimal | None = None, stop_distance: Decimal | None = None, adverse_buffer: Decimal = Decimal("0")) -> RiskVerdict:
        reason = "RISK_REJECTED"
        quantity: Decimal | None = None
        limits: tuple[str, ...] = ()
        if intent.intent_type != IntentType.ENTRY_CANDIDATE:
            reason = "NO_ENTRY_INTENT"
        elif intent.quality.value != "QUALIFIED":
            reason = "INTENT_NOT_QUALIFIED"
        elif not (intent.effective_at <= as_of < intent.expires_at):
            reason = "INTENT_EXPIRED"
        elif intent.market_context_ref is None:
            reason = "CONTEXT_MISSING"
        elif mandate is None:
            reason = "MANDATE_MISSING"
        elif not (mandate.valid_from <= as_of < mandate.valid_until):
            reason = "MANDATE_EXPIRED"
        elif mandate.block_conditions:
            reason = "MANDATE_BLOCKED"
        elif not portfolio.reconciled or portfolio.position.value != "FLAT":
            reason = "STATE_UNKNOWN_OR_NOT_FLAT"
        elif breaker_reason(portfolio, mandate):
            reason = breaker_reason(portfolio, mandate) or reason
        elif market_context is None or intent.market_context_ref != market_context.version:
            reason = "CONTEXT_REFERENCE_MISMATCH"
        elif market_context.decision_time != as_of or market_context.quality.value != "QUALIFIED":
            reason = "CONTEXT_NOT_CURRENT"
        elif cost is None or cost.total_bps is None:
            reason = "COST_UNKNOWN"
        elif cost.action.value != "ENTER_LONG" or cost.quality.value != "QUALIFIED" or cost.as_of_time > as_of or cost.max_input_event_time > as_of:
            reason = "COST_NOT_APPLICABLE"
        elif cost.frame_ref != market_context.frame_ref:
            reason = "COST_FRAME_MISMATCH"
        elif intent.cost_estimate_ref != cost.version:
            reason = "COST_REFERENCE_MISMATCH"
        elif reference_price is None or stop_distance is None:
            reason = "RISK_INPUT_INVALID"
        else:
            quantity, limits = conservative_size(mandate, portfolio, reference_price, stop_distance, adverse_buffer, cost.total_bps / Decimal("10000"))
            if quantity is not None and quantity > cost.base_quantity:
                quantity, limits, reason = None, ("COST_SIZE_MISMATCH",), "COST_SIZE_MISMATCH"
            else:
                reason = "APPROVED" if quantity is not None else limits[0]
        decision = RiskDecision.APPROVED if quantity is not None else RiskDecision.REJECTED
        identity = {
            "intent": intent.intent_id,
            "state": intent.state_ref,
            "portfolio": portfolio.version,
            "context": intent.market_context_ref,
            "mandate": mandate.version if mandate else None,
            "cost": cost.version if cost else None,
            "as_of": as_of,
            "decision": decision,
            "quantity": quantity,
            "limits": limits,
            "reason": reason,
        }
        return RiskVerdict(
            verdict_id=sha256_id(identity),
            decision=decision,
            intent_id=intent.intent_id,
            state_ref=intent.state_ref,
            portfolio_state_version=portfolio.version,
            cost_estimate_version=cost.version if cost else None,
            market_context_ref=intent.market_context_ref,
            mandate_version=mandate.version if mandate else None,
            approved_qty=quantity,
            binding_limits=limits,
            reason=reason,
            as_of_time=as_of,
        )


@dataclass(frozen=True)
class ProtectiveAssessment:
    triggered: bool
    reason: str | None
    threshold: Decimal | None


def assess_protection(portfolio: PortfolioState, mandate: RiskMandate, *, current_price: Decimal, initial_stop_price: Decimal | None = None, trailing_stop_price: Decimal | None = None) -> ProtectiveAssessment:
    """Convert authoritative risk state into a closed P1 trigger reason."""
    if not portfolio.reconciled or portfolio.position.value != "LONG" or current_price <= 0:
        return ProtectiveAssessment(False, None, None)
    breaker = breaker_reason(portfolio, mandate)
    if breaker is not None:
        return ProtectiveAssessment(True, "RISK_LIMIT_BREACH", None)
    thresholds = tuple(value for value in (initial_stop_price, trailing_stop_price) if value is not None)
    if thresholds:
        active = max(thresholds)
        if current_price <= active:
            return ProtectiveAssessment(True, "PROTECTIVE_INVALIDATION", active)
    return ProtectiveAssessment(False, None, max(thresholds) if thresholds else None)
