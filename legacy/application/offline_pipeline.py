"""Fixture-first offline composition from raw market events to a recorded Decision."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from btc_decision_agent.adapters.quality import (
    BarLifecycle,
    DataQualityGuard,
    DeliveryResult,
    classify_bar,
)
from btc_decision_agent.domain.features import Bar
from btc_decision_agent.domain.risk import RiskGovernor
from btc_decision_agent.policies.core import (
    P101Parameters,
    POL101Context,
    PolicyEvaluationResult,
    PolicyFeatures,
    TrendPolicyState,
    evaluate_pol101,
)

from btc_decision_agent.domain.canonical import sha256_id
from btc_decision_agent.domain.contracts import (
    ClockBasis,
    ContractModel,
    CostEstimate,
    DeliveryClass,
    EventType,
    FreshnessPolicy,
    FreshnessStatus,
    MarketContext,
    MarketEventV1,
    PortfolioState,
    ProductMandate,
    QualifiedMarketFrame,
    QualityStatus,
    RawMarketEvent,
    RiskMandate,
    RiskVerdict,
    SystemState,
    TriggerType,
    Usage,
)

from .decision import DecisionMachine
from .services import (
    CostLiquidityModel,
    DecisionPipeline,
    ExportResult,
    MarketSensor,
    StateCustodian,
    TemporalMarketModel,
)


@dataclass(frozen=True)
class OfflinePipelineRequest:
    raw_events: tuple[RawMarketEvent, ...]
    portfolio_observations: tuple[PortfolioState, ...]
    system_state: SystemState
    product_mandate: ProductMandate
    risk_mandate: RiskMandate
    policy_state: TrendPolicyState
    parameters: P101Parameters
    evaluation_id: str
    decision_time: datetime
    expires_at: datetime
    quote_quantity: Decimal
    reference_price: Decimal
    stop_distance: Decimal
    fee_bps: Decimal = Decimal("20")
    depth_bps: Decimal = Decimal("10")
    impact_bps: Decimal = Decimal("5")
    other_bps: Decimal = Decimal("1")


@dataclass(frozen=True)
class OfflinePipelineResult:
    events: tuple[MarketEventV1, ...]
    deliveries: tuple[DeliveryResult, ...]
    frame: QualifiedMarketFrame
    bars: tuple[Bar, ...]
    context: MarketContext
    cost: CostEstimate
    policy_result: PolicyEvaluationResult
    verdict: RiskVerdict
    export: ExportResult
    artifacts: dict[str, ContractModel]


class OfflineDecisionService:
    """Compose the ten responsibilities without network, credentials or execution."""

    def __init__(self, decision_pipeline: DecisionPipeline, *, policy: Callable[[POL101Context, P101Parameters], PolicyEvaluationResult] = evaluate_pol101) -> None:
        self._decision_pipeline = decision_pipeline
        self._opportunity_policy = policy
        self._sensor = MarketSensor()
        self._custodian = StateCustodian()
        self._temporal = TemporalMarketModel()
        self._costs = CostLiquidityModel()
        self._governor = RiskGovernor()
        self._machine = DecisionMachine()

    def evaluate(self, request: OfflinePipelineRequest) -> OfflinePipelineResult:
        guard = DataQualityGuard()
        events = tuple(self._sensor.ingest(raw) for raw in request.raw_events)
        deliveries = tuple(self._classify(event, guard, request.decision_time) for event in events)
        bars = self._bars(deliveries, request.decision_time)
        frame = self._frame(deliveries, bars, request.decision_time, request.parameters)
        context = self._temporal.build(frame, bars, n_sma=request.parameters.n_sma, k_slope=request.parameters.k_slope, n_volume=request.parameters.n_sma, n_atr=request.parameters.n_sma, n_volatility=request.parameters.n_sma)
        cost = self._costs.estimate(frame, quantity=request.quote_quantity, fee_bps=request.fee_bps, depth_bps=request.depth_bps, impact_bps=request.impact_bps, other_bps=request.other_bps)
        portfolio = self._portfolio(request)
        blockers = self._blockers(request, frame, context, portfolio)
        policy_features = self._policy_features(context, bars[-1] if bars else None, cost)
        prior_features = None
        if len(bars) >= request.parameters.n_sma + 1:
            prior_window = bars[-request.parameters.n_sma - 1 : -1]
            prior_average = sum((bar.close for bar in prior_window), Decimal("0")) / Decimal(request.parameters.n_sma)
            prior_bar = bars[-2]
            prior_features = replace(policy_features, close=prior_bar.close, sma=prior_average, distance=prior_bar.close / prior_average - Decimal("1"))
        policy_context = POL101Context(evaluation_id=request.evaluation_id, trigger_type=TriggerType.STRATEGIC_EVALUATION, decision_time=request.decision_time, strategic_boundary=request.decision_time, next_boundary=request.expires_at, system_state=request.system_state, state_ref=request.system_state.version, market_context_ref=context.version, current_bar_id=bars[-1].event_id if bars else None, features=policy_features, prior_features=prior_features, policy_state=request.policy_state, cost_estimate_ref=cost.version)
        policy_result = self._opportunity_policy(policy_context, request.parameters)
        intent = policy_result.candidate_intent
        verdict = self._governor.evaluate(intent, request.risk_mandate, portfolio, cost, request.decision_time, market_context=context, reference_price=request.reference_price, stop_distance=request.stop_distance)
        artifacts: dict[str, ContractModel] = {
            "frame": frame,
            "context": context,
            "cost": cost,
            "intent": intent,
            "product_mandate": request.product_mandate,
            "risk_mandate": request.risk_mandate,
            "portfolio": portfolio,
            "system_state": request.system_state,
            "risk_verdict": verdict,
        }
        artifacts.update({f"event:{index:04d}": event for index, event in enumerate(events)})
        artifacts.update({f"feature:{index:04d}": feature for index, feature in enumerate(context.features)})
        export = self._decision_pipeline.decide_record_export(
            self._machine,
            artifacts=artifacts,
            transition_rule=f"DECISION-{request.system_state.position.value}-{intent.intent_type.value}",
            recorded_at=request.decision_time,
            evaluation_id=request.evaluation_id,
            state=request.system_state,
            portfolio=portfolio,
            product_mandate=request.product_mandate,
            risk_mandate=request.risk_mandate,
            market_context=context,
            cost_estimate=cost,
            risk_verdict=verdict,
            intent=intent,
            trigger_type=TriggerType.STRATEGIC_EVALUATION,
            event_time_max=frame.event_time_max,
            decision_time=request.decision_time,
            expires_at=request.expires_at,
            blockers=blockers,
        )
        return OfflinePipelineResult(events, deliveries, frame, bars, context, cost, policy_result, verdict, export, artifacts)

    @staticmethod
    def _freshness_policy(event: MarketEventV1) -> FreshnessPolicy:
        is_bbo = event.event_type == EventType.BBO_UPDATE
        return FreshnessPolicy(policy_version="D-014/1.0.0", source_contract_id=event.source_contract_id, event_type=event.event_type, usage=Usage.COST if is_bbo else Usage.STRATEGIC, required=True, clock_basis=ClockBasis.OBSERVED_AT if is_bbo else ClockBasis.BAR_CLOSE, warning_age_ms=1000 if is_bbo else 2000, max_age_ms=2000 if is_bbo else 5000, allowed_lateness_ms=0, clock_skew_budget_ms=500, recovery_evidence_n=3 if is_bbo else 1, on_suspect="BLOCK", on_stale="BLOCK")

    @classmethod
    def _classify(cls, event: MarketEventV1, guard: DataQualityGuard, decision_time: datetime) -> DeliveryResult:
        evaluation_time = decision_time if event.event_type == EventType.BBO_UPDATE else event.observed_at
        return guard.classify(event, cls._freshness_policy(event), evaluation_time)

    @staticmethod
    def _bars(deliveries: tuple[DeliveryResult, ...], decision_time: datetime) -> tuple[Bar, ...]:
        result: list[Bar] = []
        for delivery in deliveries:
            event = delivery.event
            if event.event_type != EventType.KLINE_CLOSED:
                continue
            lifecycle = classify_bar(event, decision_time, delivery.watermark_at, 0)
            payload = event.payload
            result.append(Bar(event_id=event.event_id, open_time=payload["bar_open_time"], close_time=payload["bar_close_time"], open=payload["open"], high=payload["high"], low=payload["low"], close=payload["close"], base_volume=payload["base_volume"], final=lifecycle == BarLifecycle.FINAL, event_time_max=event.event_time or payload["bar_close_time"], quality=event.quality, continuity=delivery.apply, gaps=() if delivery.apply else (delivery.reason,), source_contract_ids=(event.source_contract_id,), source_watermarks={event.source_contract_id: delivery.watermark_at} if delivery.watermark_at else {}))
        result.sort(key=lambda bar: bar.open_time)
        return tuple(result)

    @staticmethod
    def _frame(deliveries: tuple[DeliveryResult, ...], bars: tuple[Bar, ...], decision_time: datetime, parameters: P101Parameters) -> QualifiedMarketFrame:
        relevant = tuple(
            delivery
            for delivery in deliveries
            if delivery.event.event_type in {EventType.KLINE_CLOSED, EventType.BBO_UPDATE}
        )
        bbo = next(
            (
                delivery
                for delivery in reversed(relevant)
                if delivery.event.event_type == EventType.BBO_UPDATE and delivery.apply
            ),
            None,
        )
        bar_gap = any(left.close_time != right.open_time for left, right in pairwise(bars))
        delivery_failures = tuple(
            sorted(
                {
                    delivery.reason
                    for delivery in relevant
                    if not delivery.apply
                    and delivery.classification != DeliveryClass.DUPLICATE
                }
            )
        )
        gap_reasons = set(delivery_failures)
        if bar_gap:
            gap_reasons.add("BAR_GAP")
        gaps = tuple(sorted(gap_reasons))
        complete = len(bars) >= parameters.n_sma + 1 and bbo is not None and not bar_gap
        quality = QualityStatus.QUALIFIED if complete and not gaps else QualityStatus.BLOCKED
        freshness = FreshnessStatus.FRESH if quality == QualityStatus.QUALIFIED else FreshnessStatus.STALE
        event_ids = tuple(dict.fromkeys(delivery.event.event_id for delivery in relevant))
        watermarks = {delivery.event.source_contract_id: delivery.watermark_at for delivery in deliveries if delivery.watermark_at is not None}
        bid = bbo.event.payload["bid_price"] if bbo is not None else None
        ask = bbo.event.payload["ask_price"] if bbo is not None else None
        bbo_event_id = bbo.event.event_id if bbo is not None else None
        bbo_observed_at = bbo.event.observed_at if bbo is not None else None
        consumed_times = tuple(
            delivery.event.event_time or delivery.event.observed_at
            for delivery in relevant
            if delivery.apply
        )
        event_time_max = max(consumed_times, default=decision_time)
        identity = {
            "events": event_ids,
            "decision_time": decision_time,
            "gaps": gaps,
            "complete": complete,
            "bbo_event_id": bbo_event_id,
            "bbo_observed_at": bbo_observed_at,
        }
        return QualifiedMarketFrame(frame_id=sha256_id(identity), symbol="BTC/USDT", event_time_max=event_time_max, observed_at=decision_time, event_ids=event_ids, source_watermarks=watermarks, complete=complete, gaps=gaps, freshness=freshness, quality=quality, bid=bid, ask=ask, bbo_event_id=bbo_event_id, bbo_observed_at=bbo_observed_at)

    @staticmethod
    def _portfolio(request: OfflinePipelineRequest) -> PortfolioState:
        try:
            return StateCustodian().reconcile(request.portfolio_observations)
        except ValueError:
            return PortfolioState(version=sha256_id({"evaluation": request.evaluation_id, "portfolio": "UNKNOWN"}), position="UNKNOWN", base_quantity=None, reference_price=None, available_cash=None, equity=None, reconciled=False, observed_at=request.decision_time)

    @staticmethod
    def _blockers(request: OfflinePipelineRequest, frame: QualifiedMarketFrame, context: MarketContext, portfolio: PortfolioState) -> tuple[str, ...]:
        reasons: set[str] = set()
        if frame.quality != QualityStatus.QUALIFIED:
            reasons.add("DATA_BLOCKED")
        if context.quality != QualityStatus.QUALIFIED:
            reasons.add("CONTEXT_INSUFFICIENT")
        if not portfolio.reconciled:
            reasons.add("STATE_UNKNOWN")
        if not (request.product_mandate.valid_from <= request.decision_time < request.product_mandate.valid_until):
            reasons.add("PRODUCT_MANDATE_EXPIRED")
        if not (request.risk_mandate.valid_from <= request.decision_time < request.risk_mandate.valid_until):
            reasons.add("MANDATE_EXPIRED")
        return tuple(sorted(reasons))

    @staticmethod
    def _policy_features(context: MarketContext, current_bar: Bar | None, cost: CostEstimate) -> PolicyFeatures:
        by_id = {feature.feature_id: feature for feature in context.features}
        required = tuple(by_id.get(key) for key in ("F-001", "F-002", "F-003", "F-004", "F-006F", "F-008"))
        qualified = context.quality == QualityStatus.QUALIFIED and all(feature is not None and feature.quality == QualityStatus.QUALIFIED for feature in required)
        return PolicyFeatures(close=current_bar.close if current_bar is not None else None, sma=by_id["F-001"].value if "F-001" in by_id else None, distance=by_id["F-002"].value if "F-002" in by_id else None, slope=by_id["F-003"].value if "F-003" in by_id else None, volume_ratio=by_id["F-004"].value if "F-004" in by_id else None, atr_fraction=by_id["F-006F"].value if "F-006F" in by_id else None, spread_bps=by_id["F-008"].value if "F-008" in by_id else None, round_trip_cost_bps=cost.total_bps, qualified=qualified and cost.quality == QualityStatus.QUALIFIED, as_of_time=context.decision_time)
