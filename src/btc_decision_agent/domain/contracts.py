"""Versioned, frozen Pydantic contracts for the offline decision domain."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum, IntEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import canonical_json, require_utc, sha256_id


class ClosedStrEnum(str, Enum):
    """Base for closed, case-sensitive string enums."""


class EventType(ClosedStrEnum):
    AGG_TRADE = "AGG_TRADE"
    KLINE_UPDATE = "KLINE_UPDATE"
    KLINE_CLOSED = "KLINE_CLOSED"
    BBO_UPDATE = "BBO_UPDATE"
    DEPTH_DIFF = "DEPTH_DIFF"
    DEPTH_SNAPSHOT = "DEPTH_SNAPSHOT"
    TICKER_24H = "TICKER_24H"
    SYMBOL_METADATA = "SYMBOL_METADATA"


class Transport(ClosedStrEnum):
    WEBSOCKET = "WEBSOCKET"
    REST = "REST"
    FIXTURE = "FIXTURE"


class DeliveryClass(ClosedStrEnum):
    ON_TIME = "ON_TIME"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    LATE = "LATE"


class QualityStatus(ClosedStrEnum):
    QUALIFIED = "QUALIFIED"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"


class FreshnessStatus(ClosedStrEnum):
    FRESH = "FRESH"
    SUSPECT = "SUSPECT"
    STALE = "STALE"
    MISSING = "MISSING"
    NOT_REQUIRED = "NOT_REQUIRED"


class PositionState(ClosedStrEnum):
    UNKNOWN = "UNKNOWN"
    FLAT = "FLAT"
    ENTRY_PENDING = "ENTRY_PENDING"
    LONG = "LONG"
    EXIT_PENDING = "EXIT_PENDING"


class EvaluationState(ClosedStrEnum):
    IDLE = "IDLE"
    ENTRY_CANDIDATE = "ENTRY_CANDIDATE"
    EXIT_CANDIDATE = "EXIT_CANDIDATE"
    COOLDOWN = "COOLDOWN"


class HealthState(ClosedStrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


class Action(ClosedStrEnum):
    ENTER_LONG = "ENTER_LONG"
    HOLD = "HOLD"
    EXIT_LONG = "EXIT_LONG"


class Disposition(ClosedStrEnum):
    ACTIONABLE = "ACTIONABLE"
    NO_CHANGE = "NO_CHANGE"
    BLOCKED = "BLOCKED"


class PriorityClass(IntEnum):
    P0_RECONCILIATION_BLOCK = 0
    P1_PROTECTIVE_EXIT = 1
    P2_SYSTEM_BLOCK = 2
    P3_STRATEGIC_EXIT = 3
    P4_ENTRY = 4
    P5_NO_CHANGE = 5


class TriggerType(ClosedStrEnum):
    STRATEGIC_EVALUATION = "STRATEGIC_EVALUATION"
    PROTECTIVE_EVALUATION = "PROTECTIVE_EVALUATION"


class IntentType(ClosedStrEnum):
    ENTRY_CANDIDATE = "ENTRY_CANDIDATE"
    EXIT_CANDIDATE = "EXIT_CANDIDATE"
    NO_INTENT = "NO_INTENT"


class RiskDecision(ClosedStrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TargetMode(ClosedStrEnum):
    ABSOLUTE = "ABSOLUTE"
    UNCHANGED = "UNCHANGED"


class Direction(ClosedStrEnum):
    FLAT = "FLAT"
    LONG = "LONG"
    UNKNOWN = "UNKNOWN"


class Product(ClosedStrEnum):
    SPOT = "SPOT"


class CostScenario(ClosedStrEnum):
    BASE = "BASE"
    ADVERSE = "ADVERSE"
    EXTREME = "EXTREME"


class ClockBasis(ClosedStrEnum):
    EVENT_TIME = "EVENT_TIME"
    OBSERVED_AT = "OBSERVED_AT"
    BAR_CLOSE = "BAR_CLOSE"
    SEQUENCE = "SEQUENCE"


class Usage(ClosedStrEnum):
    STRATEGIC = "STRATEGIC"
    PROTECTIVE = "PROTECTIVE"
    COST = "COST"
    CONTEXT = "CONTEXT"
    METADATA = "METADATA"


class BookSyncState(ClosedStrEnum):
    UNINITIALIZED = "UNINITIALIZED"
    BUFFERING = "BUFFERING"
    SNAPSHOT_PENDING = "SNAPSHOT_PENDING"
    REPLAYING = "REPLAYING"
    LIVE = "LIVE"
    GAP_DETECTED = "GAP_DETECTED"
    RESYNC_BACKOFF = "RESYNC_BACKOFF"
    BLOCKED = "BLOCKED"


class TestStatus(ClosedStrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    CONDITIONAL = "CONDITIONAL"


class RecordCompleteness(ClosedStrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class ContractModel(BaseModel):
    """Common strict contract policy and canonical serialization helpers."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: str
    utc_fields: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def validate_utc_fields(self) -> ContractModel:
        for name in self.utc_fields:
            value = getattr(self, name)
            if value is not None:
                require_utc(value)
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json(self)

    def canonical_hash(self) -> str:
        return sha256_id(self)


class SequenceMetadata(ContractModel):
    schema_version: str = "sequence-metadata/1.0.0"
    first: int | None = Field(default=None, ge=0)
    last: int | None = Field(default=None, ge=0)
    identity_ref: str | None = None

    @model_validator(mode="after")
    def validate_range_or_identity(self) -> SequenceMetadata:
        if (self.first is None) != (self.last is None):
            raise ValueError("sequence metadata requires both endpoints")
        if self.first is not None and self.last is not None and self.first > self.last:
            raise ValueError("sequence metadata range is reversed")
        if self.first is None and not self.identity_ref:
            raise ValueError("sequence metadata requires a range or identity_ref")
        return self


class DeliveryMetadata(ContractModel):
    schema_version: str = "delivery-metadata/1.0.0"
    classification: DeliveryClass = DeliveryClass.ON_TIME
    attempt: int = Field(default=1, ge=1)
    connection_id: str | None = None


class QualityMetadata(ContractModel):
    schema_version: str = "quality-metadata/1.0.0"
    status: QualityStatus = QualityStatus.QUALIFIED
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_reasons(self) -> QualityMetadata:
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("quality reasons must be unique")
        return self


class ProvenanceMetadata(ContractModel):
    schema_version: str = "provenance-metadata/1.0.0"
    data_source: str | None = None
    transform_version: str | None = None
    source_refs: tuple[str, ...] = ()
    attributes: dict[str, str | int | bool | Decimal] = Field(default_factory=dict)


class RawMarketEvent(ContractModel):
    schema_version: str = "raw-market-event/1.0.0"
    source_contract_id: str
    channel: str
    observed_at: datetime
    raw_payload: dict[str, Any]
    raw_ref: str | None = None
    utc_fields = ("observed_at",)


class MarketEventV1(ContractModel):
    schema_version: str = "market-event/1.0.0"
    event_id: str
    event_type: EventType
    source_contract_id: str
    provider: str = "BINANCE_SPOT"
    provider_contract_version: str
    transport: Transport
    channel: str
    symbol: str
    connection_id: str | None = None
    precision_ref: str | None = None
    raw_ref: str | None = None
    event_time: datetime | None
    provider_emitted_at: datetime | None = None
    observed_at: datetime
    source_identity: dict[str, Any]
    sequence_first: int | None = None
    sequence_last: int | None = None
    sequence_metadata: SequenceMetadata | None = None
    payload: dict[str, Any]
    payload_hash: str
    provenance: ProvenanceMetadata = Field(default_factory=ProvenanceMetadata)
    delivery_class: DeliveryClass = DeliveryClass.ON_TIME
    delivery_attempt: int = Field(default=1, ge=1)
    delivery_metadata: DeliveryMetadata | None = None
    quality: QualityStatus = QualityStatus.QUALIFIED
    quality_metadata: QualityMetadata | None = None
    flags: tuple[str, ...] = ()
    utc_fields = ("event_time", "provider_emitted_at", "observed_at")

    @model_validator(mode="after")
    def validate_sequence_and_time(self) -> MarketEventV1:
        if (self.sequence_first is None) != (self.sequence_last is None):
            raise ValueError("sequence range must provide both endpoints")
        if (
            self.sequence_first is not None
            and self.sequence_last is not None
            and self.sequence_first > self.sequence_last
        ):
            raise ValueError("sequence_first must not exceed sequence_last")
        if self.event_time is not None and self.observed_at < self.event_time:
            raise ValueError("observed_at must not precede event_time")
        if self.sequence_metadata is not None:
            endpoints = (self.sequence_metadata.first, self.sequence_metadata.last)
            if endpoints != (self.sequence_first, self.sequence_last):
                raise ValueError("sequence metadata must preserve canonical endpoints")
        if self.delivery_metadata is not None and (
            self.delivery_metadata.classification != self.delivery_class
            or self.delivery_metadata.attempt != self.delivery_attempt
        ):
            raise ValueError("delivery metadata must preserve classification and attempt")
        if self.quality_metadata is not None and self.quality_metadata.status != self.quality:
            raise ValueError("quality metadata must preserve classification")
        return self


class QualifiedMarketFrame(ContractModel):
    schema_version: str = "qualified-frame/1.1.0"
    frame_id: str
    symbol: str
    event_time_max: datetime
    observed_at: datetime
    event_ids: tuple[str, ...]
    sequence_or_identity: tuple[str, ...] = ()
    source_watermarks: dict[str, datetime]
    provenance: ProvenanceMetadata = Field(default_factory=ProvenanceMetadata)
    complete: bool
    gaps: tuple[str, ...] = ()
    freshness: FreshnessStatus
    quality: QualityStatus
    bid: Decimal | None = None
    ask: Decimal | None = None
    bbo_event_id: str | None = None
    bbo_observed_at: datetime | None = None
    utc_fields = ("event_time_max", "observed_at", "bbo_observed_at")

    @model_validator(mode="after")
    def validate_frame(self) -> QualifiedMarketFrame:
        for stamp in self.source_watermarks.values():
            require_utc(stamp)
        if self.event_time_max > self.observed_at:
            raise ValueError("frame cannot consume future events")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("frame event ids must be unique")
        if not self.sequence_or_identity:
            object.__setattr__(self, "sequence_or_identity", self.event_ids)
        if len(set(self.sequence_or_identity)) != len(self.sequence_or_identity):
            raise ValueError("frame sequence/identity refs must be unique")
        quote_values = (self.bid, self.ask, self.bbo_event_id, self.bbo_observed_at)
        if any(value is None for value in quote_values) and any(value is not None for value in quote_values):
            raise ValueError("frame BBO values and provenance must appear together")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid must not exceed ask")
        if self.bbo_event_id is not None and self.bbo_event_id not in self.event_ids:
            raise ValueError("frame BBO event must belong to frame events")
        if self.bbo_observed_at is not None and self.bbo_observed_at > self.observed_at:
            raise ValueError("frame BBO cannot be observed after evaluation")
        if self.quality == QualityStatus.QUALIFIED and (
            not self.complete
            or self.gaps
            or self.freshness != FreshnessStatus.FRESH
            or self.bbo_event_id is None
        ):
            raise ValueError("qualified frame must be complete, fresh, gap-free and BBO-bound")
        return self


class PortfolioState(ContractModel):
    schema_version: str = "portfolio-state/1.0.0"
    version: str
    position: PositionState
    base_quantity: Decimal | None
    reference_price: Decimal | None
    available_cash: Decimal | None
    equity: Decimal | None
    daily_loss: Decimal = Decimal("0")
    drawdown: Decimal = Decimal("0")
    exposure: Decimal | None = None
    reconciled: bool
    pending_refs: tuple[str, ...] = ()
    pending_order_refs: tuple[str, ...] = ()
    pending_fill_refs: tuple[str, ...] = ()
    observed_at: datetime
    utc_fields = ("observed_at",)

    @model_validator(mode="after")
    def validate_position(self) -> PortfolioState:
        values = (self.available_cash, self.equity, self.daily_loss, self.drawdown, self.exposure)
        if any(value is not None and value < 0 for value in values):
            raise ValueError("portfolio amounts must be non-negative")
        all_refs = (*self.pending_refs, *self.pending_order_refs, *self.pending_fill_refs)
        if len(set(all_refs)) != len(all_refs):
            raise ValueError("pending order/fill refs must be unique")
        if self.position == PositionState.UNKNOWN:
            if self.reconciled or self.base_quantity is not None or self.exposure is not None:
                raise ValueError("unknown position cannot be reconciled or quantified")
        elif not self.reconciled or self.base_quantity is None:
            raise ValueError("known position must be reconciled and quantified")
        elif self.position == PositionState.FLAT and (
            self.base_quantity != 0 or self.exposure not in {None, Decimal("0")}
        ):
            raise ValueError("flat quantity and exposure must be zero")
        elif self.position in {PositionState.LONG, PositionState.EXIT_PENDING} and self.base_quantity <= 0:
            raise ValueError("long exposure must have positive quantity")
        if (
            self.exposure is not None
            and self.base_quantity is not None
            and self.reference_price is not None
            and self.exposure != self.base_quantity * self.reference_price
        ):
            raise ValueError("exposure must equal quantity times reference price")
        return self


class FeatureValue(ContractModel):
    schema_version: str = "feature-value/1.0.0"
    feature_id: str
    feature_version: str = "1.0.0"
    value: Decimal | None
    unit: str
    symbol: str = "BTC/USDT"
    as_of_time: datetime
    max_input_event_time: datetime
    horizon: str
    window_definition: str
    parameter_values: dict[str, Any] = Field(default_factory=dict)
    formula_hash: str | None = None
    input_event_ids: tuple[str, ...] = ()
    source_contract_ids: tuple[str, ...] = ()
    source_watermarks: dict[str, datetime] = Field(default_factory=dict)
    conditional_profile_ref: str | None = None
    quality: QualityStatus
    null_reason: str | None = None
    utc_fields = ("as_of_time", "max_input_event_time")

    @model_validator(mode="after")
    def validate_feature(self) -> FeatureValue:
        if self.max_input_event_time > self.as_of_time and self.quality == QualityStatus.QUALIFIED:
            raise ValueError("qualified feature cannot consume future data")
        for stamp in self.source_watermarks.values():
            require_utc(stamp)
            if stamp > self.as_of_time:
                raise ValueError("feature source watermark cannot be in the future")
        if len(set(self.input_event_ids)) != len(self.input_event_ids):
            raise ValueError("feature input event ids must be unique")
        if (self.value is None) != (self.null_reason is not None):
            raise ValueError("null value and null_reason must appear together")
        if self.value is not None and not self.value.is_finite():
            raise ValueError("feature value must be finite")
        return self


class MarketContext(ContractModel):
    schema_version: str = "market-context/1.1.0"
    version: str
    frame_ref: str
    symbol: str
    decision_time: datetime
    horizon: str
    current_bar_id: str | None
    features: tuple[FeatureValue, ...]
    volatility: Decimal | None = None
    liquidity: Decimal | None = None
    quality: QualityStatus
    insufficiency_reasons: tuple[str, ...] = ()
    utc_fields = ("decision_time",)

    @model_validator(mode="after")
    def validate_context(self) -> MarketContext:
        if not self.frame_ref:
            raise ValueError("context frame reference is required")
        if any(feature.as_of_time > self.decision_time for feature in self.features):
            raise ValueError("context cannot contain future features")
        metrics = (self.volatility, self.liquidity)
        if any(value is not None and (not value.is_finite() or value < 0) for value in metrics):
            raise ValueError("volatility/liquidity must be finite and non-negative")
        if self.quality == QualityStatus.QUALIFIED and self.insufficiency_reasons:
            raise ValueError("qualified context cannot be insufficient")
        return self


class CostEstimate(ContractModel):
    schema_version: str = "cost-estimate/1.1.0"
    version: str
    frame_ref: str
    action: Action
    base_quantity: Decimal
    scenario: CostScenario
    horizon: str = "DECISION"
    source: str = "MODEL"
    fee_bps: Decimal | None
    cross_bps: Decimal | None
    depth_slippage_bps: Decimal | None
    impact_bps: Decimal | None
    other_bps: Decimal | None
    total_bps: Decimal | None
    conservative_lower_bps: Decimal | None = None
    conservative_upper_bps: Decimal | None = None
    quality: QualityStatus
    as_of_time: datetime
    max_input_event_time: datetime
    input_event_ids: tuple[str, ...]
    assumptions: tuple[str, ...] = ()
    utc_fields = ("as_of_time", "max_input_event_time")

    @model_validator(mode="after")
    def validate_cost(self) -> CostEstimate:
        if not self.frame_ref:
            raise ValueError("cost frame reference is required")
        if self.max_input_event_time > self.as_of_time:
            raise ValueError("cost cannot consume future events")
        if len(set(self.input_event_ids)) != len(self.input_event_ids):
            raise ValueError("cost input event ids must be unique")
        if self.quality == QualityStatus.QUALIFIED and not self.input_event_ids:
            raise ValueError("qualified cost requires input events")
        if self.base_quantity <= 0:
            raise ValueError("cost size must be positive")
        terms = (
            self.fee_bps,
            self.cross_bps,
            self.depth_slippage_bps,
            self.impact_bps,
            self.other_bps,
        )
        if any(term is not None and term < 0 for term in terms):
            raise ValueError("cost components must be non-negative")
        bounds = (self.conservative_lower_bps, self.conservative_upper_bps)
        if (bounds[0] is None) != (bounds[1] is None):
            raise ValueError("conservative cost range requires lower and upper")
        if bounds[0] is not None and bounds[1] is not None:
            if bounds[0] < 0 or bounds[0] > bounds[1]:
                raise ValueError("conservative cost range is invalid")
            if self.total_bps is not None and not bounds[0] <= self.total_bps <= bounds[1]:
                raise ValueError("scenario point must be inside conservative cost range")
        if self.total_bps is None:
            if self.quality == QualityStatus.QUALIFIED:
                raise ValueError("unknown total cost cannot be qualified")
        else:
            complete_terms = tuple(term for term in terms if term is not None)
            if len(complete_terms) != len(terms) or self.total_bps != sum(
                complete_terms, Decimal("0")
            ):
                raise ValueError("total_bps must exactly equal all cost terms")
        return self


class CandidateIntent(ContractModel):
    schema_version: str = "candidate-intent/1.0.0"
    intent_id: str
    intent_type: IntentType
    policy_id: str
    policy_version: str
    evaluation_id: str
    state_ref: str
    setup_id: str | None = None
    setup_state: str | None = None
    market_context_ref: str | None = None
    cost_estimate_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    invalidation_condition: str | None = None
    expected_gross_return: Decimal | None = None
    primary_reason: str
    reason_codes: tuple[str, ...]
    effective_at: datetime
    expires_at: datetime
    quality: QualityStatus
    utc_fields = ("effective_at", "expires_at")

    @model_validator(mode="after")
    def validate_intent(self) -> CandidateIntent:
        if self.effective_at >= self.expires_at:
            raise ValueError("intent expiry must follow effective time")
        if self.primary_reason not in self.reason_codes or len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("intent reasons must be unique and include primary")
        return self


class ProductMandate(ContractModel):
    schema_version: str = "product-mandate/1.0.0"
    version: str
    symbol: str = "BTC/USDT"
    product: Product = Product.SPOT
    allowed_directions: tuple[Direction, ...] = (Direction.LONG, Direction.FLAT)
    leverage: Decimal = Decimal("0")
    restrictions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ("SPOT", "LONG_ONLY")
    valid_from: datetime
    valid_until: datetime
    authored_by: str
    utc_fields = ("valid_from", "valid_until")

    @model_validator(mode="after")
    def validate_product(self) -> ProductMandate:
        if self.valid_from >= self.valid_until or self.leverage != 0:
            raise ValueError("mandate requires valid interval and unleveraged spot")
        if Direction.LONG not in self.allowed_directions or Direction.FLAT not in self.allowed_directions:
            raise ValueError("long/flat directions required")
        if len(set(self.restrictions)) != len(self.restrictions) or len(
            set(self.capabilities)
        ) != len(self.capabilities):
            raise ValueError("mandate restrictions/capabilities must be unique")
        if set(self.restrictions) & set(self.capabilities):
            raise ValueError("a product capability cannot also be restricted")
        return self


class RiskMandate(ContractModel):
    schema_version: str = "risk-mandate/1.0.0"
    version: str
    authored_by: str
    authored_at: datetime
    capital: Decimal
    risk_per_decision: Decimal
    max_exposure: Decimal
    daily_loss_max: Decimal
    drawdown_max: Decimal
    allowed_directions: tuple[Direction, ...] = (Direction.LONG, Direction.FLAT)
    min_notional: Decimal
    step_size: Decimal
    time_stop_is_protective: bool = False
    valid_from: datetime
    valid_until: datetime
    liquidity_gates: tuple[str, ...] = ()
    data_quality_gates: tuple[str, ...] = ()
    block_conditions: tuple[str, ...] = ()
    utc_fields = ("authored_at", "valid_from", "valid_until")

    @model_validator(mode="after")
    def validate_risk(self) -> RiskMandate:
        positive = (self.capital, self.risk_per_decision, self.max_exposure, self.daily_loss_max, self.drawdown_max, self.min_notional, self.step_size)
        if any(value <= 0 for value in positive):
            raise ValueError("risk mandate amounts must be positive")
        if self.risk_per_decision > 1 or self.max_exposure > self.capital:
            raise ValueError("risk fraction/exposure outside conservative bounds")
        if self.valid_from >= self.valid_until or not self.authored_by:
            raise ValueError("risk mandate authority and validity are required")
        gates = (*self.liquidity_gates, *self.data_quality_gates, *self.block_conditions)
        if len(set(gates)) != len(gates):
            raise ValueError("risk gates and block conditions must be unique")
        return self


class RiskVerdict(ContractModel):
    schema_version: str = "risk-verdict/1.1.0"
    verdict_id: str
    decision: RiskDecision
    intent_id: str
    state_ref: str
    portfolio_state_version: str
    cost_estimate_version: str | None
    market_context_ref: str | None
    mandate_version: str | None
    approved_qty: Decimal | None
    binding_limits: tuple[str, ...]
    reason: str
    as_of_time: datetime
    utc_fields = ("as_of_time",)

    @model_validator(mode="after")
    def validate_verdict(self) -> RiskVerdict:
        approved = self.decision == RiskDecision.APPROVED
        if approved != (self.approved_qty is not None and self.approved_qty > 0):
            raise ValueError("approved verdict requires a positive quantity only")
        if approved and (self.mandate_version is None or self.cost_estimate_version is None or self.market_context_ref is None):
            raise ValueError("approval requires mandate, cost and context references")
        if not self.state_ref or not self.portfolio_state_version:
            raise ValueError("verdict must bind system and portfolio state")
        return self


class SystemState(ContractModel):
    schema_version: str = "system-state/1.0.0"
    version: str
    position: PositionState
    evaluation: EvaluationState
    health: HealthState

    @model_validator(mode="after")
    def validate_combination(self) -> SystemState:
        if self.position == PositionState.UNKNOWN and (self.evaluation != EvaluationState.IDLE or self.health != HealthState.BLOCKED):
            raise ValueError("unknown position requires IDLE/BLOCKED")
        if self.position in {PositionState.ENTRY_PENDING, PositionState.EXIT_PENDING} and self.evaluation != EvaluationState.IDLE:
            raise ValueError("pending positions require IDLE evaluation")
        if self.evaluation == EvaluationState.ENTRY_CANDIDATE and (self.position != PositionState.FLAT or self.health != HealthState.READY):
            raise ValueError("entry candidate requires FLAT/READY")
        if self.evaluation == EvaluationState.EXIT_CANDIDATE and self.position != PositionState.LONG:
            raise ValueError("exit candidate requires LONG")
        if self.evaluation == EvaluationState.COOLDOWN and self.position != PositionState.FLAT:
            raise ValueError("cooldown requires FLAT")
        return self


class TargetPosition(ContractModel):
    schema_version: str = "target-position/1.0.0"
    mode: TargetMode
    asset: str = "BTC"
    direction: Direction
    base_quantity: Decimal | None
    source: str
    portfolio_state_version: str

    @model_validator(mode="after")
    def validate_target(self) -> TargetPosition:
        if self.direction == Direction.UNKNOWN and self.base_quantity is not None:
            raise ValueError("unknown target cannot invent quantity")
        if self.direction == Direction.FLAT and self.mode == TargetMode.ABSOLUTE and self.base_quantity != 0:
            raise ValueError("absolute flat target must be zero")
        if self.direction == Direction.LONG and (self.base_quantity is None or self.base_quantity <= 0):
            raise ValueError("long target requires positive quantity")
        return self


class Decision(ContractModel):
    schema_version: str = "decision/1.0.0"
    decision_id: str
    evaluation_id: str
    action: Action
    disposition: Disposition
    priority_class: PriorityClass
    trigger_type: TriggerType
    symbol: str
    product_mandate_version: str
    risk_mandate_version: str | None
    policy_id: str | None
    policy_version: str | None
    intent_ref: str | None = None
    market_context_ref: str | None = None
    cost_estimate_ref: str | None = None
    risk_verdict_ref: str | None = None
    state_before: SystemState
    state_after: SystemState
    target_position: TargetPosition
    primary_reason: str
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    event_time_max: datetime
    decision_time: datetime
    effective_at: datetime
    expires_at: datetime
    supersedes_decision_id: str | None = None
    quality_status: HealthState
    ledger_precondition: str = "RECORD_BEFORE_EXPORT"
    utc_fields = ("event_time_max", "decision_time", "effective_at", "expires_at")

    @model_validator(mode="after")
    def validate_decision(self) -> Decision:
        if not self.event_time_max <= self.decision_time <= self.effective_at < self.expires_at:
            raise ValueError("decision timestamps are not causal")
        if self.primary_reason not in self.reason_codes or len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("decision reasons must be unique and include primary")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence refs must be unique")
        explicit_refs = tuple(
            ref
            for ref in (
                self.intent_ref,
                self.market_context_ref,
                self.cost_estimate_ref,
                self.risk_verdict_ref,
            )
            if ref is not None
        )
        if any(ref not in self.evidence_refs for ref in explicit_refs):
            raise ValueError("explicit decision refs must be present in evidence_refs")
        if self.disposition == Disposition.BLOCKED and self.action != Action.HOLD:
            raise ValueError("blocked disposition requires HOLD")
        if self.action == Action.ENTER_LONG:
            if (
                self.disposition != Disposition.ACTIONABLE
                or self.priority_class != PriorityClass.P4_ENTRY
                or self.target_position.direction != Direction.LONG
                or self.quality_status != HealthState.READY
                or self.intent_ref is None
                or self.risk_verdict_ref is None
            ):
                raise ValueError("invalid entry decision")
        elif self.action == Action.EXIT_LONG:
            if self.disposition != Disposition.ACTIONABLE or self.target_position.direction != Direction.FLAT:
                raise ValueError("invalid exit decision")
        elif self.target_position.mode != TargetMode.UNCHANGED:
            raise ValueError("HOLD target must be unchanged")
        if self.ledger_precondition != "RECORD_BEFORE_EXPORT":
            raise ValueError("ledger must precede export")
        return self


class DecisionRecord(ContractModel):
    schema_version: str = "decision-record/1.0.0"
    record_id: str
    decision: Decision
    artifact_hashes: dict[str, str]
    transition_rule: str
    completeness: RecordCompleteness = RecordCompleteness.COMPLETE
    outcome_ref: str | None = None
    recorded_at: datetime
    previous_record_hash: str | None
    record_hash: str
    utc_fields = ("recorded_at",)

    @model_validator(mode="after")
    def validate_record(self) -> DecisionRecord:
        if self.completeness == RecordCompleteness.COMPLETE and (
            not self.artifact_hashes or not self.transition_rule or not self.record_hash
        ):
            raise ValueError("complete decision record requires artifacts, transition and hash")
        return self


class TestVerdict(ContractModel):
    schema_version: str = "test-verdict/1.0.0"
    obligation_id: str
    component_id: str = "UNSPECIFIED"
    test_id: str = "UNSPECIFIED"
    status: TestStatus
    evidence_refs: tuple[str, ...]
    reason: str
    evaluated_at: datetime
    utc_fields = ("evaluated_at",)

    @model_validator(mode="after")
    def validate_test_verdict(self) -> TestVerdict:
        if self.component_id == "UNSPECIFIED":
            object.__setattr__(self, "component_id", self.obligation_id)
        if self.test_id == "UNSPECIFIED":
            object.__setattr__(self, "test_id", self.obligation_id)
        if not self.component_id or not self.test_id or not self.reason:
            raise ValueError("test verdict component, test id and reason are required")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("test verdict evidence refs must be unique")
        return self


class FreshnessPolicy(ContractModel):
    schema_version: str = "freshness-policy/1.0.0"
    policy_version: str
    source_contract_id: str
    event_type: EventType
    usage: Usage
    required: bool
    clock_basis: ClockBasis
    expected_cadence_ms: int | None = Field(default=None, ge=0)
    warning_age_ms: int = Field(ge=0)
    max_age_ms: int = Field(ge=0)
    allowed_lateness_ms: int = Field(ge=0)
    clock_skew_budget_ms: int = Field(ge=0)
    close_grace_ms: int | None = Field(default=None, ge=0)
    heartbeat_timeout_ms: int | None = Field(default=None, ge=0)
    recovery_evidence_n: int = Field(ge=1)
    recovery_rule: str = "CONSECUTIVE_QUALIFIED"
    on_suspect: str
    on_stale: str
    decision_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_budgets(self) -> FreshnessPolicy:
        if self.warning_age_ms > self.max_age_ms:
            raise ValueError("warning age must not exceed hard max")
        if not self.recovery_rule or not self.on_suspect or not self.on_stale:
            raise ValueError("freshness recovery and actions must be explicit")
        if len(set(self.decision_refs)) != len(self.decision_refs):
            raise ValueError("freshness decision refs must be unique")
        return self


class LocalBookView(ContractModel):
    schema_version: str = "local-book-view/1.0.0"
    book_generation_id: str
    symbol: str
    metadata_version: str
    last_update_id: int = Field(ge=0)
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None
    snapshot_limit: int = Field(gt=0, le=5000)
    coverage: str = "LIMITED"
    event_time_max: datetime
    observed_at: datetime
    sync_status: BookSyncState
    quality: QualityStatus
    utc_fields = ("event_time_max", "observed_at")

    @model_validator(mode="after")
    def validate_book(self) -> LocalBookView:
        if self.sync_status != BookSyncState.LIVE or self.quality != QualityStatus.QUALIFIED:
            raise ValueError("only qualified LIVE books may be published")
        if not self.bids or not self.asks:
            raise ValueError("published book requires both sides")
        if any(price <= 0 or qty <= 0 for price, qty in (*self.bids, *self.asks)):
            raise ValueError("book levels must be positive")
        if tuple(sorted(self.bids, reverse=True)) != self.bids or tuple(
            sorted(self.asks)
        ) != self.asks:
            raise ValueError("book sides are not correctly ordered")
        derived_bid, derived_ask = self.bids[0][0], self.asks[0][0]
        if self.best_bid is not None and self.best_bid != derived_bid:
            raise ValueError("best_bid must equal the highest bid")
        if self.best_ask is not None and self.best_ask != derived_ask:
            raise ValueError("best_ask must equal the lowest ask")
        object.__setattr__(self, "best_bid", derived_bid)
        object.__setattr__(self, "best_ask", derived_ask)
        if derived_bid > derived_ask:
            raise ValueError("crossed book")
        if self.event_time_max > self.observed_at:
            raise ValueError("book observation precedes event")
        return self


__all__ = [
    "Action",
    "BookSyncState",
    "CandidateIntent",
    "ClockBasis",
    "ContractModel",
    "CostEstimate",
    "CostScenario",
    "Decision",
    "DecisionRecord",
    "DeliveryClass",
    "DeliveryMetadata",
    "Direction",
    "Disposition",
    "EvaluationState",
    "EventType",
    "FeatureValue",
    "FreshnessPolicy",
    "FreshnessStatus",
    "HealthState",
    "IntentType",
    "LocalBookView",
    "MarketContext",
    "MarketEventV1",
    "PortfolioState",
    "PositionState",
    "PriorityClass",
    "Product",
    "ProductMandate",
    "ProvenanceMetadata",
    "QualifiedMarketFrame",
    "QualityMetadata",
    "QualityStatus",
    "RawMarketEvent",
    "RecordCompleteness",
    "RiskDecision",
    "RiskMandate",
    "RiskVerdict",
    "SequenceMetadata",
    "SystemState",
    "TargetMode",
    "TargetPosition",
    "TestStatus",
    "TestVerdict",
    "Transport",
    "TriggerType",
    "Usage",
]
