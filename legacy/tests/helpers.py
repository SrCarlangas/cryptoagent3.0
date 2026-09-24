"""Deterministic factories shared by executable evidence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from btc_decision_agent.domain.contracts import (
    EvaluationState,
    HealthState,
    PortfolioState,
    PositionState,
    ProductMandate,
    RiskMandate,
    SystemState,
)
from btc_decision_agent.policies import P101Parameters, PolicyFeatures, TrendPolicyState

NOW = datetime(2026, 9, 15, 18, 0, tzinfo=UTC)
NEXT = NOW + timedelta(hours=1)
D = Decimal
ZERO = D("0")
DEFAULT_DISTANCE = D("0.010")
DEFAULT_SLOPE = D("0.013029")
DEFAULT_VOLUME = D("1.714286")
DEFAULT_COST = D("54.242622")


def state(position: PositionState = PositionState.FLAT, evaluation: EvaluationState = EvaluationState.IDLE, health: HealthState = HealthState.READY) -> SystemState:
    return SystemState(version=f"state:{position.value}:{evaluation.value}:{health.value}", position=position, evaluation=evaluation, health=health)


def portfolio(position: PositionState = PositionState.FLAT, quantity: Decimal = ZERO, *, reconciled: bool = True) -> PortfolioState:
    return PortfolioState(version=f"portfolio:{position.value}", position=position, base_quantity=quantity if position != PositionState.UNKNOWN else None, reference_price=D("100") if position != PositionState.UNKNOWN else None, available_cash=D("10000"), equity=D("10000"), reconciled=reconciled, observed_at=NOW)


def product() -> ProductMandate:
    return ProductMandate(version="D-001/1", valid_from=NOW - timedelta(days=1), valid_until=NOW + timedelta(days=1), authored_by="human")


def risk() -> RiskMandate:
    return RiskMandate(version="D-003/1", authored_by="human", authored_at=NOW - timedelta(days=1), capital=D("10000"), risk_per_decision=D("0.0025"), max_exposure=D("1000"), daily_loss_max=D("75"), drawdown_max=D("500"), min_notional=D("10"), step_size=D("0.00001"), valid_from=NOW - timedelta(days=1), valid_until=NOW + timedelta(days=1))


def params() -> P101Parameters:
    return P101Parameters("p101/1", 3, 1, D("0.010"), D("-0.005"), D("0.010"), D("0.060"), D("0.005"), D("0.019"), D("0.002"), D("0.020"), D("1.50"), D("60"), 3, D("1.5"), 8, 2, 2, 2, 4)


def features(*, distance: Decimal = DEFAULT_DISTANCE, slope: Decimal = DEFAULT_SLOPE, volume: Decimal = DEFAULT_VOLUME, cost: Decimal | None = DEFAULT_COST, qualified: bool = True) -> PolicyFeatures:
    return PolicyFeatures(D("106"), D("103.666667"), distance, slope, volume, D("0.037736"), D("18.867925"), cost, qualified, NOW)


def idle_policy() -> TrendPolicyState:
    return TrendPolicyState.idle(params().version)
