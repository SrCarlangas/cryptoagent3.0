"""Delivery classification, freshness, watermarks and closed-bar lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from btc_decision_agent.domain.canonical import sha256_id
from btc_decision_agent.domain.contracts import (
    ClockBasis,
    DeliveryClass,
    DeliveryMetadata,
    FreshnessPolicy,
    FreshnessStatus,
    MarketEventV1,
    QualityMetadata,
    QualityStatus,
)


class BarLifecycle(str, Enum):
    FORMING = "FORMING"
    CLOSE_SEEN = "CLOSE_SEEN"
    RECONCILING = "RECONCILING"
    FINAL = "FINAL"
    LATE_CORRECTION = "LATE_CORRECTION"
    INVALID = "INVALID"


@dataclass(frozen=True)
class DeliveryResult:
    event: MarketEventV1
    classification: DeliveryClass
    freshness: FreshnessStatus
    watermark_at: datetime | None
    apply: bool
    reason: str


class DataQualityGuard:
    """Stateful delivery guard whose watermark follows source progress only."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}
        self._attempts: dict[str, int] = {}
        self._high_water: dict[str, int] = {}
        self._event_progress: dict[str, datetime] = {}
        self._watermarks: dict[str, datetime] = {}

    def classify(self, event: MarketEventV1, policy: FreshnessPolicy, decision_time: datetime) -> DeliveryResult:
        if policy.source_contract_id != event.source_contract_id or policy.event_type != event.event_type:
            raise ValueError("FRESHNESS_POLICY_MISMATCH")
        scope = f"{event.source_contract_id}:{event.symbol}:{event.event_type.value}"
        economic_key = sha256_id({"provider": event.provider, "source_contract_id": event.source_contract_id, "event_type": event.event_type, "symbol": event.symbol, "source_identity": event.source_identity})
        attempt = self._attempts.get(economic_key, 0) + 1
        self._attempts[economic_key] = attempt
        existing = self._seen.get(economic_key)
        if existing is not None:
            if existing != event.payload_hash:
                raise ValueError("IDENTITY_COLLISION")
            duplicate = event.model_copy(update={"delivery_class": DeliveryClass.DUPLICATE, "delivery_attempt": attempt, "delivery_metadata": DeliveryMetadata(classification=DeliveryClass.DUPLICATE, attempt=attempt, connection_id=event.connection_id), "quality_metadata": QualityMetadata(status=event.quality, reason_codes=("DO_NOT_REAPPLY",)), "flags": tuple(sorted((*event.flags, "DO_NOT_REAPPLY")))})
            return DeliveryResult(duplicate, DeliveryClass.DUPLICATE, FreshnessStatus.FRESH, self._watermarks.get(scope), False, "DUPLICATE")

        basis: datetime | None
        if policy.clock_basis == ClockBasis.EVENT_TIME:
            basis = event.event_time
        elif policy.clock_basis == ClockBasis.OBSERVED_AT:
            basis = event.observed_at
        elif policy.clock_basis == ClockBasis.BAR_CLOSE:
            candidate = event.payload.get("bar_close_time")
            basis = candidate if isinstance(candidate, datetime) else None
        else:
            basis = event.observed_at if event.sequence_last is not None else None
        if basis is None:
            blocked = event.model_copy(update={"quality": QualityStatus.BLOCKED, "quality_metadata": QualityMetadata(status=QualityStatus.BLOCKED, reason_codes=("CLOCK_BASIS_MISSING",))})
            return DeliveryResult(blocked, DeliveryClass.ON_TIME, FreshnessStatus.MISSING, self._watermarks.get(scope), False, "CLOCK_BASIS_MISSING")

        age_ms = int((decision_time - basis).total_seconds() * 1000)
        if age_ms < -policy.clock_skew_budget_ms:
            blocked = event.model_copy(update={"quality": QualityStatus.BLOCKED, "quality_metadata": QualityMetadata(status=QualityStatus.BLOCKED, reason_codes=("CLOCK_FAULT",))})
            return DeliveryResult(blocked, DeliveryClass.ON_TIME, FreshnessStatus.STALE, self._watermarks.get(scope), False, "CLOCK_FAULT")

        previous_watermark = self._watermarks.get(scope)
        if event.event_time is not None and previous_watermark is not None and event.event_time < previous_watermark:
            self._seen[economic_key] = event.payload_hash
            late = event.model_copy(update={"delivery_class": DeliveryClass.LATE, "delivery_attempt": attempt, "delivery_metadata": DeliveryMetadata(classification=DeliveryClass.LATE, attempt=attempt, connection_id=event.connection_id), "quality": QualityStatus.DEGRADED, "quality_metadata": QualityMetadata(status=QualityStatus.DEGRADED, reason_codes=("NO_RETROACTIVE_DECISION",)), "flags": tuple(sorted((*event.flags, "NO_RETROACTIVE_DECISION")))})
            return DeliveryResult(late, DeliveryClass.LATE, FreshnessStatus.STALE, previous_watermark, False, "NO_RETROACTIVE_DECISION")

        self._seen[economic_key] = event.payload_hash
        freshness = FreshnessStatus.FRESH if age_ms <= policy.warning_age_ms else FreshnessStatus.SUSPECT if age_ms <= policy.max_age_ms else FreshnessStatus.STALE
        classification = DeliveryClass.ON_TIME
        apply = freshness == FreshnessStatus.FRESH and event.quality == QualityStatus.QUALIFIED
        reason = freshness.value
        if event.sequence_last is not None:
            high = self._high_water.get(scope)
            if high is not None and event.sequence_last < high:
                classification = DeliveryClass.OUT_OF_ORDER
                apply = False
                reason = "DO_NOT_ROLL_BACK"
            else:
                self._high_water[scope] = event.sequence_last

        if classification == DeliveryClass.ON_TIME and event.event_time is not None:
            progress = max(event.event_time, self._event_progress.get(scope, event.event_time))
            self._event_progress[scope] = progress
            source_watermark = progress - timedelta(milliseconds=policy.allowed_lateness_ms)
            self._watermarks[scope] = max(source_watermark, self._watermarks.get(scope, source_watermark))

        status = QualityStatus.QUALIFIED if apply else QualityStatus.DEGRADED
        qualified = event.model_copy(update={"delivery_class": classification, "delivery_attempt": attempt, "delivery_metadata": DeliveryMetadata(classification=classification, attempt=attempt, connection_id=event.connection_id), "quality": status, "quality_metadata": QualityMetadata(status=status, reason_codes=() if apply else (reason,))})
        return DeliveryResult(qualified, classification, freshness, self._watermarks.get(scope), apply, reason)


def classify_bar(event: MarketEventV1, decision_time: datetime, watermark: datetime | None, allowed_lateness_ms: int, conflict: bool = False) -> BarLifecycle:
    """Promote a kline only when quality, continuity, close and watermark agree."""
    if event.event_type.value not in {"KLINE_UPDATE", "KLINE_CLOSED"}:
        return BarLifecycle.INVALID
    if event.quality != QualityStatus.QUALIFIED:
        return BarLifecycle.INVALID
    blocking_flags = {"GAP", "GAP_DETECTED", "CONTINUITY_BROKEN", "DO_NOT_ROLL_BACK", "CLOCK_FAULT"}
    metadata_reasons = set(event.quality_metadata.reason_codes if event.quality_metadata else ())
    if blocking_flags.intersection(set(event.flags) | metadata_reasons):
        return BarLifecycle.INVALID
    payload = event.payload
    close_time = payload.get("bar_close_time")
    if not payload.get("is_closed", False) or not isinstance(close_time, datetime) or decision_time < close_time:
        return BarLifecycle.FORMING
    if conflict:
        return BarLifecycle.RECONCILING
    required_watermark = close_time + timedelta(milliseconds=allowed_lateness_ms)
    if watermark is None or watermark < required_watermark:
        return BarLifecycle.CLOSE_SEEN
    if event.delivery_class == DeliveryClass.LATE:
        return BarLifecycle.LATE_CORRECTION
    return BarLifecycle.FINAL
