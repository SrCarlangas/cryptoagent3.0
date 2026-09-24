"""Application ports and the ten explicit responsibility services."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from btc_decision_agent.adapters.market_data import normalize
from btc_decision_agent.adapters.quality import DataQualityGuard
from btc_decision_agent.domain.features import (
    Bar,
    atr,
    build_cost_estimate,
    distance_to_sma,
    realized_volatility,
    sma,
    sma_slope,
    spread_features,
    volume_ratio,
)
from btc_decision_agent.domain.risk import RiskGovernor, assess_protection

from btc_decision_agent.domain.canonical import sha256_id
from btc_decision_agent.domain.contracts import (
    CandidateIntent,
    ContractModel,
    CostEstimate,
    CostScenario,
    Decision,
    DecisionRecord,
    MarketContext,
    MarketEventV1,
    PortfolioState,
    QualifiedMarketFrame,
    QualityStatus,
    RawMarketEvent,
    TestStatus,
    TestVerdict,
)

from .decision import DecisionMachine


class Clock(Protocol):
    def now(self) -> datetime: ...


class AppendReceipt(Protocol):
    record: DecisionRecord
    inserted: bool


class LedgerPort(Protocol):
    def append(self, decision: Decision, artifacts: Mapping[str, ContractModel], transition_rule: str, recorded_at: datetime, *, outcome_ref: str | None = None) -> AppendReceipt: ...


class OpportunityPolicy(Protocol):
    def evaluate(self, *args: Any, **kwargs: Any) -> CandidateIntent: ...


class MarketSensor:
    def ingest(self, raw: RawMarketEvent) -> MarketEventV1:
        return normalize(raw)


class StateCustodian:
    """Reconcile only authoritative observations; never decide strategy."""

    def reconcile(self, observations: Sequence[PortfolioState]) -> PortfolioState:
        if not observations:
            raise ValueError("STATE_UNKNOWN")
        latest = max(observations, key=lambda value: value.observed_at)
        same_time = [value for value in observations if value.observed_at == latest.observed_at]
        if any(value.position != latest.position or value.base_quantity != latest.base_quantity for value in same_time):
            raise ValueError("POSITION_CONFLICT")
        return latest


class TemporalMarketModel:
    """Build a causal context from a qualified frame and qualified FINAL bars."""

    def build(self, frame: QualifiedMarketFrame, bars: Sequence[Bar], *, n_sma: int, k_slope: int, n_volume: int, n_atr: int, n_volatility: int) -> MarketContext:
        decision_time = frame.observed_at
        current_sma = sma(bars, n_sma, decision_time)
        prior_sma = sma(bars[:-k_slope], n_sma, decision_time)
        current_close = bars[-1].close if bars else None
        distance = distance_to_sma(current_close, current_sma.value, decision_time, input_features=(current_sma,))
        slope = sma_slope(current_sma.value, prior_sma.value, k_slope, decision_time, input_features=(current_sma, prior_sma))
        volume = volume_ratio(bars, n_volume, decision_time)
        atr_value, atr_fraction = atr(bars, n_atr, decision_time)
        volatility = realized_volatility(bars, n_volatility, decision_time)
        features = [current_sma, distance, slope, volume, atr_value, atr_fraction, volatility]
        if frame.bid is not None and frame.ask is not None and frame.bbo_event_id is not None and frame.bbo_observed_at is not None:
            features.extend(spread_features(frame.bid, frame.ask, decision_time, event_id=frame.bbo_event_id, event_time=frame.bbo_observed_at).values())
        reasons = tuple(sorted(feature.null_reason for feature in features if feature.null_reason is not None))
        quality = QualityStatus.QUALIFIED if frame.quality == QualityStatus.QUALIFIED and not reasons else QualityStatus.BLOCKED
        identity = {"frame": frame.frame_id, "bars": [bar.event_id for bar in bars], "features": [feature.canonical_hash() for feature in features]}
        return MarketContext(version=sha256_id(identity), frame_ref=frame.frame_id, symbol=frame.symbol, decision_time=decision_time, horizon="1h", current_bar_id=bars[-1].event_id if bars else None, features=tuple(features), volatility=volatility.value, liquidity=None, quality=quality, insufficiency_reasons=reasons)


class CostLiquidityModel:
    """Estimate a conservative round-trip cost from a qualified current BBO."""

    def estimate(self, frame: QualifiedMarketFrame, *, quantity: Decimal, fee_bps: Decimal, depth_bps: Decimal, impact_bps: Decimal, other_bps: Decimal, scenario: CostScenario = CostScenario.ADVERSE) -> CostEstimate:
        bbo_time = frame.bbo_observed_at or frame.observed_at
        bbo_inputs = (frame.bbo_event_id,) if frame.bbo_event_id is not None else ()
        if frame.quality != QualityStatus.QUALIFIED or frame.bid is None or frame.ask is None or frame.bbo_event_id is None:
            return build_cost_estimate(
                sha256_id({"frame": frame.frame_id, "quantity": quantity, "blocked": True}),
                quantity,
                scenario,
                None,
                None,
                None,
                None,
                None,
                bbo_time,
                frame_ref=frame.frame_id,
                input_event_ids=bbo_inputs,
                max_input_event_time=bbo_time,
            )
        spread = spread_features(frame.bid, frame.ask, frame.observed_at, event_id=frame.bbo_event_id, event_time=bbo_time)
        cross = spread["spread_bps"].value
        version = sha256_id({"frame": frame.frame_id, "quantity": quantity, "scenario": scenario, "fee": fee_bps, "cross": cross, "depth": depth_bps, "impact": impact_bps, "other": other_bps})
        return build_cost_estimate(
            version,
            quantity,
            scenario,
            fee_bps,
            cross,
            depth_bps,
            impact_bps,
            other_bps,
            bbo_time,
            frame_ref=frame.frame_id,
            input_event_ids=bbo_inputs,
            max_input_event_time=bbo_time,
        )


class TheoreticalValidator:
    """Reject nominal PASS verdicts without executable evidence references."""

    def validate(self, verdict: TestVerdict) -> TestVerdict:
        if verdict.status == TestStatus.PASS and not verdict.evidence_refs:
            return verdict.model_copy(update={"status": TestStatus.FAIL, "reason": "PASS_REQUIRES_EXECUTABLE_EVIDENCE"})
        return verdict


@dataclass(frozen=True)
class ExportResult:
    decision: Decision
    record: DecisionRecord
    exported: bool
    status: str

    def __iter__(self) -> Iterator[Decision | DecisionRecord]:
        yield self.decision
        yield self.record


class DecisionPipeline:
    """Record-before-export boundary with duplicate suppression."""

    def __init__(self, ledger: LedgerPort) -> None:
        self.ledger = ledger

    def decide_record_export(self, machine: DecisionMachine, *, artifacts: Mapping[str, ContractModel], transition_rule: str, recorded_at: datetime, **decision_inputs: Any) -> ExportResult:
        decision = machine.decide(**decision_inputs)
        receipt = self.ledger.append(decision, artifacts, transition_rule, recorded_at)
        exported = receipt.inserted
        status = "EXPORTED" if exported else "DUPLICATE_SUPPRESSED"
        return ExportResult(decision, receipt.record, exported, status)

    def record_before_export(self, decision: Decision, artifacts: Mapping[str, ContractModel], transition_rule: str, recorded_at: datetime) -> ExportResult:
        receipt = self.ledger.append(decision, artifacts, transition_rule, recorded_at)
        exported = receipt.inserted
        return ExportResult(decision, receipt.record, exported, "EXPORTED" if exported else "DUPLICATE_SUPPRESSED")


__all__ = [
    "Clock",
    "CostLiquidityModel",
    "DataQualityGuard",
    "DecisionMachine",
    "DecisionPipeline",
    "ExportResult",
    "LedgerPort",
    "MarketSensor",
    "OpportunityPolicy",
    "RiskGovernor",
    "StateCustodian",
    "TemporalMarketModel",
    "TheoreticalValidator",
    "assess_protection",
]
