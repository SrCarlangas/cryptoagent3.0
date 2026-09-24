"""Deterministic opportunity policies; outputs are CandidateIntent only."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from btc_decision_agent.domain.canonical import sha256_id
from btc_decision_agent.domain.contracts import (
    CandidateIntent,
    EvaluationState,
    HealthState,
    IntentType,
    PositionState,
    QualityStatus,
    SystemState,
    TriggerType,
)


class TrendSetupState(str, Enum):
    IDLE = "IDLE"
    PULLBACK_ARMED = "PULLBACK_ARMED"
    ENTRY_EMITTED = "ENTRY_EMITTED"


class EntryOutcome(str, Enum):
    NONE = "NONE"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class P101Parameters:
    """The complete 19-parameter POL-101 freeze."""

    version: str
    n_sma: int
    k_slope: int
    theta_slope_enter: Decimal
    theta_slope_exit: Decimal
    atr_min: Decimal
    atr_max: Decimal
    pullback_low: Decimal
    pullback_high: Decimal
    pullback_fail: Decimal
    resume_level: Decimal
    volume_confirm: Decimal
    cost_cap_bps: Decimal
    arm_timeout_bars: int
    exit_atr_multiple: Decimal
    max_holding_bars: int
    cd_setup_fail: int
    cd_entry_reject: int
    cd_exit: int
    cd_protective_exit: int

    def valid(self) -> bool:
        return (
            self.n_sma >= 2
            and self.k_slope >= 1
            and Decimal("0") <= self.atr_min < self.atr_max
            and self.pullback_fail < self.pullback_low <= self.pullback_high < self.resume_level
            and self.theta_slope_exit < self.theta_slope_enter
            and self.volume_confirm > 0
            and self.cost_cap_bps > 0
            and self.arm_timeout_bars >= 1
            and self.exit_atr_multiple > 0
            and self.max_holding_bars >= 1
            and min(self.cd_setup_fail, self.cd_entry_reject, self.cd_exit, self.cd_protective_exit) >= 0
        )


@dataclass(frozen=True)
class TrendPolicyState:
    state: TrendSetupState
    state_version: str
    parameter_version: str
    policy_version: str = "1.0.0"
    setup_id: str | None = None
    armed_at_bar_id: str | None = None
    bars_since_arm: int = 0
    pullback_extreme_distance: Decimal | None = None
    entry_intent_id: str | None = None

    @classmethod
    def idle(cls, parameter_version: str) -> TrendPolicyState:
        return cls(TrendSetupState.IDLE, sha256_id({"state": "IDLE", "parameters": parameter_version}), parameter_version)


@dataclass(frozen=True)
class PolicyFeatures:
    close: Decimal | None
    sma: Decimal | None
    distance: Decimal | None
    slope: Decimal | None
    volume_ratio: Decimal | None
    atr_fraction: Decimal | None
    spread_bps: Decimal | None
    round_trip_cost_bps: Decimal | None
    qualified: bool = True
    as_of_time: datetime | None = None

    def entry_complete(self, boundary: datetime) -> bool:
        values = (self.close, self.sma, self.distance, self.slope, self.volume_ratio, self.atr_fraction, self.spread_bps, self.round_trip_cost_bps)
        return self.qualified and all(value is not None and value.is_finite() for value in values) and self.as_of_time == boundary

    def exit_complete(self, boundary: datetime) -> bool:
        values = (self.distance, self.slope, self.atr_fraction)
        return self.qualified and all(value is not None and value.is_finite() for value in values) and self.as_of_time == boundary


@dataclass(frozen=True)
class POL101Context:
    evaluation_id: str
    trigger_type: TriggerType
    decision_time: datetime
    strategic_boundary: datetime
    next_boundary: datetime
    system_state: SystemState
    state_ref: str
    market_context_ref: str
    current_bar_id: str | None
    features: PolicyFeatures
    prior_features: PolicyFeatures | None
    policy_state: TrendPolicyState
    latest_entry_outcome: EntryOutcome = EntryOutcome.NONE
    holding_bars: int = 0
    duplicate_seen: bool = False
    cost_estimate_ref: str | None = None


@dataclass(frozen=True)
class PolicyEvaluationResult:
    candidate_intent: CandidateIntent
    next_policy_state: TrendPolicyState
    cooldown_bars: int | None
    evaluation_reason: str
    audit_predicates: Mapping[str, bool]


def _intent(ctx: POL101Context, intent_type: IntentType, reason: str, state: TrendPolicyState, evidence: tuple[str, ...] = ()) -> CandidateIntent:
    identity = {"type": intent_type, "policy": "POL-101", "version": "1.0.0", "evaluation": ctx.evaluation_id, "state": ctx.state_ref, "setup": state.setup_id, "reason": reason, "effective": ctx.decision_time, "expires": ctx.next_boundary, "evidence": sorted(evidence)}
    return CandidateIntent(intent_id=sha256_id(identity), intent_type=intent_type, policy_id="POL-101", policy_version="1.0.0", evaluation_id=ctx.evaluation_id, state_ref=ctx.state_ref, setup_id=state.setup_id, setup_state=state.state.value, market_context_ref=ctx.market_context_ref, cost_estimate_ref=ctx.cost_estimate_ref, evidence_refs=tuple(sorted(evidence)), invalidation_condition="POL101_ENTRY_INVALIDATION_V1" if intent_type == IntentType.ENTRY_CANDIDATE else None, primary_reason=reason, reason_codes=(reason,), effective_at=ctx.decision_time, expires_at=ctx.next_boundary, quality=QualityStatus.QUALIFIED)


def _result(ctx: POL101Context, reason: str, state: TrendPolicyState, *, intent_type: IntentType = IntentType.NO_INTENT, cooldown: int | None = None, predicates: Mapping[str, bool] | None = None) -> PolicyEvaluationResult:
    intent = _intent(ctx, intent_type, reason, state, (ctx.market_context_ref,) if intent_type != IntentType.NO_INTENT else ())
    if intent_type == IntentType.ENTRY_CANDIDATE:
        state = replace(state, state=TrendSetupState.ENTRY_EMITTED, entry_intent_id=intent.intent_id, state_version=sha256_id({"prior": state.state_version, "intent": intent.intent_id}))
    return PolicyEvaluationResult(intent, state, cooldown if cooldown and cooldown > 0 else None, reason, predicates or {})


def evaluate_pol101(ctx: POL101Context, p: P101Parameters) -> PolicyEvaluationResult:
    """Total implementation of normative evaluate_POL101 with fixed guard order."""
    idle = TrendPolicyState.idle(p.version)
    if ctx.duplicate_seen:
        return _result(ctx, "POL101_DUPLICATE", ctx.policy_state)
    if ctx.policy_state.policy_version != "1.0.0" or ctx.policy_state.parameter_version != p.version:
        return _result(ctx, "POL101_VERSION_CHANGED", idle)
    if not p.valid():
        return _result(ctx, "POL101_PARAMETER_INVALID", idle)
    if ctx.trigger_type == TriggerType.PROTECTIVE_EVALUATION:
        return _result(ctx, "POL101_PROTECTIVE_DEFERRED_TO_SYSTEM", ctx.policy_state)

    system = ctx.system_state
    if system.position == PositionState.UNKNOWN:
        return _result(ctx, "POL101_POSITION_UNKNOWN", idle)
    if system.position in {PositionState.ENTRY_PENDING, PositionState.EXIT_PENDING}:
        return _result(ctx, "POL101_PENDING_FEEDBACK", ctx.policy_state)
    if system.evaluation == EvaluationState.COOLDOWN:
        return _result(ctx, "POL101_COOLDOWN_ACTIVE", idle)
    if system.health != HealthState.READY:
        return _result(ctx, "POL101_HEALTH_NOT_READY", idle if system.position == PositionState.FLAT else ctx.policy_state)

    if ctx.policy_state.state == TrendSetupState.ENTRY_EMITTED:
        if ctx.latest_entry_outcome == EntryOutcome.FILLED:
            return _result(ctx, "POL101_ENTRY_FILLED", idle)
        if ctx.latest_entry_outcome in {EntryOutcome.REJECTED, EntryOutcome.CANCELLED}:
            return _result(ctx, "POL101_ENTRY_REJECTED", idle, cooldown=p.cd_entry_reject)
        if ctx.latest_entry_outcome == EntryOutcome.EXPIRED:
            return _result(ctx, "POL101_ENTRY_EXPIRED", idle, cooldown=p.cd_entry_reject)
        return _result(ctx, "POL101_PENDING_FEEDBACK", ctx.policy_state)

    f = ctx.features
    if system.position == PositionState.LONG:
        if not f.exit_complete(ctx.strategic_boundary):
            return _result(ctx, "POL101_FEATURE_MISSING", ctx.policy_state)
        slope, distance, atr_fraction = f.slope, f.distance, f.atr_fraction
        if slope is None or distance is None or atr_fraction is None:
            return _result(ctx, "POL101_FEATURE_MISSING", ctx.policy_state)
        if ctx.holding_bars >= p.max_holding_bars:
            return _result(ctx, "POL101_EXIT_TIME", idle, intent_type=IntentType.EXIT_CANDIDATE)
        if slope <= p.theta_slope_exit:
            return _result(ctx, "POL101_EXIT_TREND", idle, intent_type=IntentType.EXIT_CANDIDATE)
        if distance <= -p.exit_atr_multiple * atr_fraction:
            return _result(ctx, "POL101_EXIT_ANCHOR", idle, intent_type=IntentType.EXIT_CANDIDATE)
        return _result(ctx, "POL101_LONG_HOLD", idle)

    if not f.entry_complete(ctx.strategic_boundary):
        reason = "POL101_COST_UNKNOWN" if f.round_trip_cost_bps is None else "POL101_FEATURE_NOT_FRESH" if not f.qualified or f.as_of_time != ctx.strategic_boundary else "POL101_FEATURE_MISSING"
        return _result(ctx, reason, idle)

    close, sma_value = f.close, f.sma
    distance, slope = f.distance, f.slope
    volume_ratio, atr_fraction = f.volume_ratio, f.atr_fraction
    if any(
        value is None
        for value in (close, sma_value, distance, slope, volume_ratio, atr_fraction)
    ):
        return _result(ctx, "POL101_FEATURE_MISSING", idle)
    assert close is not None
    assert sma_value is not None
    assert distance is not None
    assert slope is not None
    assert volume_ratio is not None
    assert atr_fraction is not None
    trend = slope >= p.theta_slope_enter and close > sma_value and p.atr_min <= atr_fraction <= p.atr_max
    in_band = p.pullback_low <= distance <= p.pullback_high
    predicates = {"trend_context": trend, "in_pullback_band": in_band}
    if ctx.policy_state.state == TrendSetupState.IDLE:
        if not trend:
            return _result(ctx, "POL101_TREND_CONTEXT_FALSE", idle, predicates=predicates)
        if not in_band:
            return _result(ctx, "POL101_PULLBACK_NOT_IN_BAND", idle, predicates=predicates)
        setup_id = sha256_id({"policy": "POL-101", "parameter": p.version, "bar": ctx.current_bar_id, "state": ctx.state_ref})
        armed = TrendPolicyState(TrendSetupState.PULLBACK_ARMED, sha256_id({"setup": setup_id, "bars": 0}), p.version, setup_id=setup_id, armed_at_bar_id=ctx.current_bar_id, pullback_extreme_distance=distance)
        return _result(ctx, "POL101_PULLBACK_ARMED", armed, predicates=predicates)

    if ctx.policy_state.state == TrendSetupState.PULLBACK_ARMED:
        bars = ctx.policy_state.bars_since_arm + 1
        previous_extreme = ctx.policy_state.pullback_extreme_distance
        extreme = min(previous_extreme if previous_extreme is not None else distance, distance)
        armed = replace(ctx.policy_state, bars_since_arm=bars, pullback_extreme_distance=extreme, state_version=sha256_id({"prior": ctx.policy_state.state_version, "bars": bars, "extreme": extreme}))
        if bars > p.arm_timeout_bars:
            return _result(ctx, "POL101_ARM_TIMEOUT", idle, cooldown=p.cd_setup_fail)
        if not trend:
            return _result(ctx, "POL101_TREND_INVALIDATED", idle, cooldown=p.cd_setup_fail)
        if distance < p.pullback_fail:
            return _result(ctx, "POL101_PULLBACK_FAILED", idle, cooldown=p.cd_setup_fail)
        if f.round_trip_cost_bps is None:
            return _result(ctx, "POL101_COST_UNKNOWN", idle)
        if f.round_trip_cost_bps > p.cost_cap_bps:
            return _result(ctx, "POL101_COST_CAP_EXCEEDED", idle, cooldown=p.cd_setup_fail)
        prior = ctx.prior_features
        prior_distance = None
        if prior is not None:
            prior_values = (prior.close, prior.sma, prior.distance, prior.slope, prior.volume_ratio, prior.atr_fraction, prior.spread_bps, prior.round_trip_cost_bps)
            if prior.qualified and prior.as_of_time is not None and prior.as_of_time <= ctx.strategic_boundary and all(value is not None and value.is_finite() for value in prior_values):
                prior_distance = prior.distance
        resume = prior_distance is not None and prior_distance <= p.resume_level and distance > p.resume_level
        if not resume:
            return _result(ctx, "POL101_RESUME_NOT_CROSSED", armed, predicates={**predicates, "resume_crossed": False})
        if volume_ratio < p.volume_confirm:
            return _result(ctx, "POL101_VOLUME_NOT_CONFIRMED", armed, predicates={**predicates, "resume_crossed": True, "volume_confirmed": False})
        return _result(ctx, "POL101_ENTRY_SETUP_COMPLETE", armed, intent_type=IntentType.ENTRY_CANDIDATE, predicates={**predicates, "resume_crossed": True, "volume_confirmed": True, "cost_admissible": True})


class NullHoldPolicy:
    policy_id = "POL-000-NULL-HOLD"
    policy_version = "1.0.0"

    def evaluate(self, evaluation_id: str, state_ref: str, decision_time: datetime, next_boundary: datetime) -> CandidateIntent:
        identity = {"policy": self.policy_id, "version": self.policy_version, "evaluation": evaluation_id, "state": state_ref, "effective": decision_time, "expires": next_boundary}
        return CandidateIntent(intent_id=sha256_id(identity), intent_type=IntentType.NO_INTENT, policy_id=self.policy_id, policy_version=self.policy_version, evaluation_id=evaluation_id, state_ref=state_ref, primary_reason="POLICY_NULL_CONTROL", reason_codes=("POLICY_NULL_CONTROL",), effective_at=decision_time, expires_at=next_boundary, quality=QualityStatus.QUALIFIED)


@dataclass(frozen=True)
class ChallengerState:
    setup: str
    setup_id: str | None
    bars_armed: int
    version: str


@dataclass(frozen=True)
class ChallengerContext:
    evaluation_id: str
    state_ref: str
    decision_time: datetime
    next_boundary: datetime
    position: PositionState
    health: HealthState
    values: Mapping[str, Decimal | None]
    holding_bars: int = 0
    market_context_ref: str | None = None
    cost_estimate_ref: str | None = None


class ChallengerPolicy:
    """Deterministic regime/setup/entry/exit machines for POL-102 and POL-103."""

    def __init__(self, policy_id: str, version: str = "1.0.0") -> None:
        if policy_id not in {"POL-102", "POL-103"}:
            raise ValueError("unsupported challenger")
        self.policy_id, self.version = policy_id, version

    @staticmethod
    def _decimal(parameters: Mapping[str, Decimal | int], name: str, default: str) -> Decimal:
        return Decimal(str(parameters.get(name, default)))

    @staticmethod
    def _integer(parameters: Mapping[str, Decimal | int], name: str, default: int) -> int:
        return int(parameters.get(name, default))

    def evaluate(self, ctx: ChallengerContext, state: ChallengerState, parameters: Mapping[str, Decimal | int]) -> tuple[CandidateIntent, ChallengerState]:
        reason, intent_type, next_state = "NO_INTENT", IntentType.NO_INTENT, state
        cost = ctx.values.get("cost_bps")
        required_parameters = {
            "POL-102": {"entry_dislocation", "min_reversion_velocity", "hard_fail_atr", "slope_floor", "vol_ceiling", "cost_cap", "arm_timeout_bars", "reversion_target_atr", "trend_break_floor", "max_holding_bars"},
            "POL-103": {"compression_ceiling", "breakout_buffer_atr", "volume_confirm", "min_expansion_ratio", "cost_cap", "compression_timeout", "false_break_atr", "max_holding_bars"},
        }[self.policy_id]
        required_values = {
            "POL-102": {"volume_ratio", "dislocation_atr", "reversion_velocity", "sma_slope", "realized_volatility", "close", "confirmation_level"},
            "POL-103": {"volume_ratio", "compression_ratio", "breakout_distance_atr", "atr_fraction", "prior_atr_fraction"},
        }[self.policy_id]
        if ctx.health != HealthState.READY:
            reason, next_state = "HEALTH_STATE_OR_INPUT_BLOCKED", ChallengerState("IDLE", None, 0, self.version)
        elif state.version != self.version:
            reason, next_state = "CHALLENGER_VERSION_CHANGED", ChallengerState("IDLE", None, 0, self.version)
        elif required_parameters - set(parameters):
            reason, next_state = "CHALLENGER_PARAMETER_INVALID", ChallengerState("IDLE", None, 0, self.version)
        elif ctx.position == PositionState.LONG and cost is None:
            reason = f"{self.policy_id.replace('-', '')}_COST_UNKNOWN_INVALIDATED"
            intent_type = IntentType.EXIT_CANDIDATE
            next_state = ChallengerState("IDLE", None, 0, self.version)
        elif ctx.position == PositionState.LONG:
            reason, intent_type, next_state = self._evaluate_long(ctx, parameters)
        elif ctx.position != PositionState.FLAT:
            reason, next_state = "HEALTH_STATE_OR_INPUT_BLOCKED", ChallengerState("IDLE", None, 0, self.version)
        elif cost is None:
            reason, next_state = "COST_UNKNOWN", ChallengerState("IDLE", None, 0, self.version)
        elif any(ctx.values.get(name) is None for name in required_values):
            reason, next_state = "CHALLENGER_FEATURE_MISSING", ChallengerState("IDLE", None, 0, self.version)
        elif not cost.is_finite() or cost > self._decimal(parameters, "cost_cap", "Infinity"):
            reason, next_state = "COST_CAP_EXCEEDED", ChallengerState("IDLE", None, 0, self.version)
        elif self.policy_id == "POL-102":
            reason, intent_type, next_state = self._evaluate_reversion(ctx, state, parameters)
        else:
            reason, intent_type, next_state = self._evaluate_breakout(ctx, state, parameters)

        identity = {"policy": self.policy_id, "version": self.version, "evaluation": ctx.evaluation_id, "state": ctx.state_ref, "setup": next_state.setup_id, "type": intent_type, "reason": reason, "context": ctx.market_context_ref, "cost": ctx.cost_estimate_ref}
        evidence = tuple(sorted(ref for ref in (ctx.market_context_ref, ctx.cost_estimate_ref) if ref is not None))
        intent = CandidateIntent(intent_id=sha256_id(identity), intent_type=intent_type, policy_id=self.policy_id, policy_version=self.version, evaluation_id=ctx.evaluation_id, state_ref=ctx.state_ref, setup_id=next_state.setup_id, setup_state=next_state.setup, market_context_ref=ctx.market_context_ref, cost_estimate_ref=ctx.cost_estimate_ref, evidence_refs=evidence, invalidation_condition=f"{self.policy_id}_INVALIDATION_V1" if intent_type == IntentType.ENTRY_CANDIDATE else None, primary_reason=reason, reason_codes=(reason,), effective_at=ctx.decision_time, expires_at=ctx.next_boundary, quality=QualityStatus.QUALIFIED)
        return intent, next_state

    def _evaluate_long(self, ctx: ChallengerContext, parameters: Mapping[str, Decimal | int]) -> tuple[str, IntentType, ChallengerState]:
        idle = ChallengerState("IDLE", None, 0, self.version)
        if ctx.holding_bars >= self._integer(parameters, "max_holding_bars", 2**31 - 1):
            return f"{self.policy_id.replace('-', '')}_EXIT_TIME", IntentType.EXIT_CANDIDATE, idle
        if self.policy_id == "POL-102":
            dislocation = ctx.values.get("dislocation_atr")
            slope = ctx.values.get("sma_slope")
            volatility = ctx.values.get("realized_volatility")
            if dislocation is not None and dislocation >= self._decimal(parameters, "reversion_target_atr", "Infinity"):
                return "POL102_EXIT_TARGET", IntentType.EXIT_CANDIDATE, idle
            if (dislocation is not None and dislocation <= self._decimal(parameters, "hard_fail_atr", "-Infinity")) or (slope is not None and slope < self._decimal(parameters, "trend_break_floor", "-Infinity")) or (volatility is not None and volatility > self._decimal(parameters, "vol_ceiling", "Infinity")):
                return "POL102_EXIT_REGIME_FAIL", IntentType.EXIT_CANDIDATE, idle
            return "POL102_LONG_HOLD", IntentType.NO_INTENT, idle
        breakout = ctx.values.get("breakout_distance_atr")
        false_break_threshold = self._decimal(parameters, "breakout_buffer_atr", "Infinity") - self._decimal(parameters, "false_break_atr", "Infinity")
        if breakout is not None and breakout <= false_break_threshold:
            return "POL103_EXIT_FALSE_BREAK", IntentType.EXIT_CANDIDATE, idle
        if ctx.values.get("regime_valid") == Decimal("0"):
            return "POL103_EXIT_REGIME_FAIL", IntentType.EXIT_CANDIDATE, idle
        return "POL103_LONG_HOLD", IntentType.NO_INTENT, idle

    def _evaluate_reversion(self, ctx: ChallengerContext, state: ChallengerState, parameters: Mapping[str, Decimal | int]) -> tuple[str, IntentType, ChallengerState]:
        idle = ChallengerState("IDLE", None, 0, self.version)
        dislocation = ctx.values.get("dislocation_atr")
        velocity = ctx.values.get("reversion_velocity")
        slope = ctx.values.get("sma_slope")
        volatility = ctx.values.get("realized_volatility")
        close = ctx.values.get("close")
        confirmation = ctx.values.get("confirmation_level")
        admissible = (slope is None or slope >= self._decimal(parameters, "slope_floor", "-Infinity")) and (volatility is None or volatility <= self._decimal(parameters, "vol_ceiling", "Infinity"))
        if not admissible:
            return "POL102_REGIME_INVALIDATED", IntentType.NO_INTENT, idle
        if state.setup == "IDLE":
            if dislocation is not None and dislocation <= self._decimal(parameters, "entry_dislocation", "-Infinity"):
                setup_id = sha256_id({"policy": self.policy_id, "evaluation": ctx.evaluation_id, "state": ctx.state_ref})
                return "POL102_DISLOCATION_ARMED", IntentType.NO_INTENT, ChallengerState("DISLOCATION_ARMED", setup_id, 0, self.version)
            return "POL102_WAITING", IntentType.NO_INTENT, idle
        if state.setup != "DISLOCATION_ARMED":
            return "POL102_SETUP_INVALID", IntentType.NO_INTENT, idle
        armed = replace(state, bars_armed=state.bars_armed + 1)
        if armed.bars_armed > self._integer(parameters, "arm_timeout_bars", 2**31 - 1):
            return "POL102_ARM_TIMEOUT", IntentType.NO_INTENT, idle
        if dislocation is not None and dislocation <= self._decimal(parameters, "hard_fail_atr", "-Infinity"):
            return "POL102_FALLING_KNIFE_INVALIDATED", IntentType.NO_INTENT, idle
        confirmed_price = confirmation is None or (close is not None and close >= confirmation)
        if velocity is not None and velocity >= self._decimal(parameters, "min_reversion_velocity", "Infinity") and confirmed_price:
            return "POL102_REVERSION_CONFIRMED", IntentType.ENTRY_CANDIDATE, armed
        return "POL102_WAITING", IntentType.NO_INTENT, armed

    def _evaluate_breakout(self, ctx: ChallengerContext, state: ChallengerState, parameters: Mapping[str, Decimal | int]) -> tuple[str, IntentType, ChallengerState]:
        idle = ChallengerState("IDLE", None, 0, self.version)
        compression = ctx.values.get("compression_ratio")
        breakout = ctx.values.get("breakout_distance_atr")
        volume = ctx.values.get("volume_ratio")
        atr_fraction = ctx.values.get("atr_fraction")
        prior_atr = ctx.values.get("prior_atr_fraction")
        if state.setup == "IDLE":
            if compression is not None and compression <= self._decimal(parameters, "compression_ceiling", "-Infinity"):
                setup_id = sha256_id({"policy": self.policy_id, "evaluation": ctx.evaluation_id, "state": ctx.state_ref})
                return "POL103_COMPRESSION_ARMED", IntentType.NO_INTENT, ChallengerState("COMPRESSION_ARMED", setup_id, 0, self.version)
            return "POL103_WAITING", IntentType.NO_INTENT, idle
        if state.setup != "COMPRESSION_ARMED":
            return "POL103_SETUP_INVALID", IntentType.NO_INTENT, idle
        armed = replace(state, bars_armed=state.bars_armed + 1)
        if armed.bars_armed > self._integer(parameters, "compression_timeout", 2**31 - 1):
            return "POL103_COMPRESSION_TIMEOUT", IntentType.NO_INTENT, idle
        false_break_threshold = self._decimal(parameters, "breakout_buffer_atr", "Infinity") - self._decimal(parameters, "false_break_atr", "Infinity")
        if breakout is not None and breakout <= false_break_threshold:
            return "POL103_FALSE_BREAK_INVALIDATED", IntentType.NO_INTENT, idle
        expansion = atr_fraction is None or prior_atr is None or atr_fraction >= prior_atr * self._decimal(parameters, "min_expansion_ratio", "0")
        confirmed = breakout is not None and breakout > self._decimal(parameters, "breakout_buffer_atr", "Infinity") and volume is not None and volume >= self._decimal(parameters, "volume_confirm", "Infinity") and expansion
        if confirmed:
            return "POL103_BREAKOUT_CONFIRMED", IntentType.ENTRY_CANDIDATE, armed
        return "POL103_WAITING", IntentType.NO_INTENT, armed


POL101_PARAMETER_IDS = (
    "P101_N_SMA", "P101_K_SLOPE", "P101_THETA_SLOPE_ENTER", "P101_THETA_SLOPE_EXIT", "P101_ATR_MIN", "P101_ATR_MAX", "P101_PULLBACK_LOW", "P101_PULLBACK_HIGH", "P101_PULLBACK_FAIL", "P101_RESUME_LEVEL", "P101_VOLUME_CONFIRM", "P101_COST_CAP_BPS", "P101_ARM_TIMEOUT_BARS", "P101_EXIT_ATR_MULTIPLE", "P101_MAX_HOLDING_BARS", "P101_CD_SETUP_FAIL", "P101_CD_ENTRY_REJECT", "P101_CD_EXIT", "P101_CD_PROTECTIVE_EXIT",
)
