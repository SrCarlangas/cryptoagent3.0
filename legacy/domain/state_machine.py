"""Hierarchical SystemState machine SM-001..SM-031 and P0..P5 precedence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .canonical import sha256_id
from .contracts import (
    Action,
    EvaluationState,
    HealthState,
    PositionState,
    PriorityClass,
    SystemState,
)


class StateEvent(str, Enum):
    POSITION_SYNC_FLAT = "POSITION_SYNC_FLAT"
    POSITION_SYNC_LONG = "POSITION_SYNC_LONG"
    POSITION_CONFLICT = "POSITION_CONFLICT"
    QUALITY_READY = "QUALITY_READY"
    QUALITY_DEGRADED = "QUALITY_DEGRADED"
    QUALITY_BLOCKED = "QUALITY_BLOCKED"
    STRATEGIC_TICK = "STRATEGIC_TICK"
    NO_INTENT = "NO_INTENT"
    ENTRY_INTENT = "ENTRY_INTENT"
    EXIT_INTENT = "EXIT_INTENT"
    PROTECTIVE_TRIGGER = "PROTECTIVE_TRIGGER"
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    MANDATE_EXPIRED = "MANDATE_EXPIRED"
    DECISION_RECORDED = "DECISION_RECORDED"
    DECISION_EXPIRED = "DECISION_EXPIRED"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    ENTRY_FILLED = "ENTRY_FILLED"
    EXIT_PARTIAL = "EXIT_PARTIAL"
    EXIT_FILLED = "EXIT_FILLED"
    EXECUTION_REJECTED = "EXECUTION_REJECTED"
    EXECUTION_CANCELLED = "EXECUTION_CANCELLED"
    COOLDOWN_STARTED = "COOLDOWN_STARTED"
    COOLDOWN_EXPIRED = "COOLDOWN_EXPIRED"
    UNKNOWN_SCHEMA = "UNKNOWN_SCHEMA"


@dataclass(frozen=True)
class Transition:
    rule_id: str
    state_before: SystemState
    event: StateEvent
    state_after: SystemState
    action: Action
    reason: str
    priority: PriorityClass


def _state(current: SystemState, position: PositionState | None = None, evaluation: EvaluationState | None = None, health: HealthState | None = None) -> SystemState:
    values = {
        "position": position or current.position,
        "evaluation": evaluation or current.evaluation,
        "health": health or current.health,
    }
    version = sha256_id({"previous": current.version, **{key: value.value for key, value in values.items()}})
    return SystemState(version=version, **values)


def _result(rule: str, current: SystemState, event: StateEvent, after: SystemState, action: Action, reason: str, priority: PriorityClass) -> Transition:
    return Transition(rule, current, event, after, action, reason, priority)


def transition(current: SystemState, event: StateEvent, guards: dict[str, Any] | None = None) -> Transition:
    """Apply exactly one normative state transition, defaulting to safe self-loop."""
    g = guards or {}
    p, e, h = current.position, current.evaluation, current.health

    if event == StateEvent.POSITION_CONFLICT:
        after = _state(current, PositionState.UNKNOWN, EvaluationState.IDLE, HealthState.BLOCKED)
        return _result("SM-003", current, event, after, Action.HOLD, "STATE_UNKNOWN", PriorityClass.P0_RECONCILIATION_BLOCK)
    if event == StateEvent.UNKNOWN_SCHEMA:
        position = p if g.get("position_trustworthy", p != PositionState.UNKNOWN) else PositionState.UNKNOWN
        after = _state(current, position, EvaluationState.IDLE, HealthState.BLOCKED)
        return _result("SM-031", current, event, after, Action.HOLD, "UNKNOWN_SCHEMA", PriorityClass.P0_RECONCILIATION_BLOCK)
    if event == StateEvent.DUPLICATE_IDENTITY:
        return _result("SM-029", current, event, current, Action.HOLD, "DUPLICATE", PriorityClass.P5_NO_CHANGE)

    if p == PositionState.UNKNOWN and e == EvaluationState.IDLE and h == HealthState.BLOCKED:
        if event == StateEvent.POSITION_SYNC_FLAT and g.get("authoritative", False) and g.get("quantity") == 0:
            return _result("SM-001", current, event, _state(current, PositionState.FLAT), Action.HOLD, "STATE_RECOVERED", PriorityClass.P0_RECONCILIATION_BLOCK)
        if event == StateEvent.POSITION_SYNC_LONG and g.get("authoritative", False) and g.get("quantity", 0) > 0:
            return _result("SM-002", current, event, _state(current, PositionState.LONG), Action.HOLD, "STATE_RECOVERED", PriorityClass.P0_RECONCILIATION_BLOCK)

    if event in {StateEvent.QUALITY_BLOCKED, StateEvent.MANDATE_EXPIRED} and p != PositionState.UNKNOWN:
        after = _state(current, evaluation=EvaluationState.IDLE, health=HealthState.BLOCKED)
        return _result("SM-008", current, event, after, Action.HOLD, "MANDATE_EXPIRED" if event == StateEvent.MANDATE_EXPIRED else "DATA_BLOCKED", PriorityClass.P2_SYSTEM_BLOCK)
    if event == StateEvent.QUALITY_DEGRADED and h == HealthState.READY and p != PositionState.UNKNOWN:
        return _result("SM-006", current, event, _state(current, evaluation=EvaluationState.IDLE, health=HealthState.DEGRADED), Action.HOLD, "DATA_BLOCKED", PriorityClass.P2_SYSTEM_BLOCK)
    if event == StateEvent.QUALITY_READY and p in {PositionState.FLAT, PositionState.LONG} and h in {HealthState.BLOCKED, HealthState.DEGRADED} and g.get("mandates_valid", False):
        rule = "SM-004" if p == PositionState.FLAT and h == HealthState.BLOCKED else "SM-005" if p == PositionState.LONG and h == HealthState.BLOCKED else "SM-007"
        return _result(rule, current, event, _state(current, health=HealthState.READY), Action.HOLD, "READY", PriorityClass.P5_NO_CHANGE)

    if event == StateEvent.COOLDOWN_STARTED and p == PositionState.FLAT and e == EvaluationState.IDLE and g.get("duration_bars", 0) > 0:
        return _result("SM-018", current, event, _state(current, evaluation=EvaluationState.COOLDOWN), Action.HOLD, "COOLDOWN", PriorityClass.P5_NO_CHANGE)

    if p == PositionState.FLAT and e == EvaluationState.IDLE and h == HealthState.READY:
        if event in {StateEvent.STRATEGIC_TICK, StateEvent.NO_INTENT} and g.get("no_intent", event == StateEvent.NO_INTENT):
            return _result("SM-009", current, event, current, Action.HOLD, "NO_INTENT", PriorityClass.P5_NO_CHANGE)
        if event == StateEvent.ENTRY_INTENT and g.get("intent_valid", False) and g.get("cost_known", False):
            return _result("SM-010", current, event, _state(current, evaluation=EvaluationState.ENTRY_CANDIDATE), Action.HOLD, "ENTRY_CANDIDATE", PriorityClass.P4_ENTRY)

    if p == PositionState.FLAT and e == EvaluationState.ENTRY_CANDIDATE and h == HealthState.READY:
        if event == StateEvent.RISK_REJECTED:
            return _result("SM-011", current, event, _state(current, evaluation=EvaluationState.IDLE), Action.HOLD, "RISK_REJECTED", PriorityClass.P2_SYSTEM_BLOCK)
        if event == StateEvent.DECISION_EXPIRED or not g.get("guards_valid", True):
            target_health = HealthState.BLOCKED if g.get("blocked", False) else HealthState.DEGRADED
            return _result("SM-012", current, event, _state(current, evaluation=EvaluationState.IDLE, health=target_health), Action.HOLD, "DECISION_EXPIRED", PriorityClass.P2_SYSTEM_BLOCK)
        if event == StateEvent.DECISION_RECORDED and g.get("risk_approved", False) and g.get("entry_contract_complete", False):
            return _result("SM-013", current, event, _state(current, PositionState.ENTRY_PENDING, EvaluationState.IDLE), Action.ENTER_LONG, "OPPORTUNITY_APPROVED", PriorityClass.P4_ENTRY)

    if p == PositionState.ENTRY_PENDING:
        if event in {StateEvent.STRATEGIC_TICK, StateEvent.ENTRY_INTENT}:
            return _result("SM-014", current, event, current, Action.HOLD, "PENDING_FEEDBACK", PriorityClass.P5_NO_CHANGE)
        if event == StateEvent.ENTRY_FILLED and g.get("authoritative", False) and g.get("quantity", 0) > 0:
            return _result("SM-015", current, event, _state(current, PositionState.LONG), Action.HOLD, "ENTRY_FILLED", PriorityClass.P5_NO_CHANGE)
        if event in {StateEvent.EXECUTION_REJECTED, StateEvent.EXECUTION_CANCELLED, StateEvent.DECISION_EXPIRED} and g.get("quantity", 0) == 0:
            return _result("SM-016", current, event, _state(current, PositionState.FLAT, EvaluationState.COOLDOWN), Action.HOLD, "ENTRY_NOT_FILLED", PriorityClass.P5_NO_CHANGE)

    if p == PositionState.FLAT and e == EvaluationState.COOLDOWN:
        if event == StateEvent.COOLDOWN_EXPIRED and g.get("cause_resolved", False):
            return _result("SM-017", current, event, _state(current, evaluation=EvaluationState.IDLE), Action.HOLD, "COOLDOWN_DONE", PriorityClass.P5_NO_CHANGE)
        if event in {StateEvent.STRATEGIC_TICK, StateEvent.ENTRY_INTENT}:
            return _result("SM-018", current, event, current, Action.HOLD, "COOLDOWN", PriorityClass.P5_NO_CHANGE)

    if p == PositionState.LONG:
        if event in {StateEvent.STRATEGIC_TICK, StateEvent.NO_INTENT} and e == EvaluationState.IDLE and h == HealthState.READY and g.get("no_intent", event == StateEvent.NO_INTENT):
            return _result("SM-019", current, event, current, Action.HOLD, "NO_INTENT", PriorityClass.P5_NO_CHANGE)
        if event == StateEvent.EXIT_INTENT and e == EvaluationState.IDLE and h == HealthState.READY and g.get("intent_valid", False):
            return _result("SM-020", current, event, _state(current, evaluation=EvaluationState.EXIT_CANDIDATE), Action.HOLD, "EXIT_CANDIDATE", PriorityClass.P3_STRATEGIC_EXIT)
        if event == StateEvent.PROTECTIVE_TRIGGER and g.get("authoritative", False):
            return _result("SM-021", current, event, _state(current, evaluation=EvaluationState.EXIT_CANDIDATE), Action.HOLD, "PROTECTIVE_INVALIDATION", PriorityClass.P1_PROTECTIVE_EXIT)
        if e == EvaluationState.EXIT_CANDIDATE and event == StateEvent.RISK_REJECTED and not g.get("protective", False):
            return _result("SM-022", current, event, _state(current, evaluation=EvaluationState.IDLE), Action.HOLD, "EXIT_REJECTED", PriorityClass.P3_STRATEGIC_EXIT)
        if e == EvaluationState.EXIT_CANDIDATE and event == StateEvent.DECISION_RECORDED and g.get("exit_valid", False):
            priority = PriorityClass.P1_PROTECTIVE_EXIT if g.get("protective", False) else PriorityClass.P3_STRATEGIC_EXIT
            return _result("SM-023", current, event, _state(current, PositionState.EXIT_PENDING, EvaluationState.IDLE), Action.EXIT_LONG, g.get("reason", "POLICY_INVALIDATED"), priority)
        if event == StateEvent.POSITION_SYNC_FLAT and g.get("authoritative", False):
            return _result("SM-027", current, event, _state(current, PositionState.FLAT, EvaluationState.COOLDOWN, HealthState.DEGRADED), Action.HOLD, "POSITION_ANOMALY", PriorityClass.P0_RECONCILIATION_BLOCK)

    if p == PositionState.EXIT_PENDING:
        if event == StateEvent.EXIT_PARTIAL and g.get("authoritative", False) and g.get("residual", 0) > 0:
            return _result("SM-024", current, event, current, Action.HOLD, "PENDING_FEEDBACK", PriorityClass.P5_NO_CHANGE)
        if event == StateEvent.EXIT_FILLED and g.get("authoritative", False) and g.get("residual") == 0:
            return _result("SM-025", current, event, _state(current, PositionState.FLAT, EvaluationState.COOLDOWN), Action.HOLD, "EXIT_FILLED", PriorityClass.P5_NO_CHANGE)
        if event in {StateEvent.EXECUTION_REJECTED, StateEvent.EXECUTION_CANCELLED, StateEvent.DECISION_EXPIRED} and g.get("residual", 0) > 0:
            return _result("SM-026", current, event, _state(current, PositionState.LONG, EvaluationState.EXIT_CANDIDATE, HealthState.DEGRADED), Action.HOLD, "PROTECTIVE_INVALIDATION", PriorityClass.P1_PROTECTIVE_EXIT)

    if p == PositionState.FLAT and event == StateEvent.POSITION_SYNC_LONG and g.get("authoritative", False) and g.get("quantity", 0) > 0:
        return _result("SM-028", current, event, _state(current, PositionState.LONG, EvaluationState.IDLE, HealthState.BLOCKED), Action.HOLD, "POSITION_ANOMALY", PriorityClass.P0_RECONCILIATION_BLOCK)

    return _result("SM-030", current, event, current, Action.HOLD, "NO_STATE_CHANGE", PriorityClass.P5_NO_CHANGE)


def resolve_precedence(candidates: Iterable[Transition]) -> Transition:
    """Select one transition by P0..P5, then deterministic version/hash tie-break."""
    values = tuple(candidates)
    if not values:
        raise ValueError("at least one candidate is required")
    return min(values, key=lambda item: (int(item.priority), item.state_before.version, sha256_id(item)))


PROHIBITED_TRANSITIONS: tuple[tuple[PositionState, PositionState], ...] = (
    (PositionState.UNKNOWN, PositionState.ENTRY_PENDING),
    (PositionState.FLAT, PositionState.LONG),
    (PositionState.LONG, PositionState.FLAT),
    (PositionState.ENTRY_PENDING, PositionState.ENTRY_PENDING),
)


def is_prohibited_direct_transition(before: SystemState, after: SystemState, event: StateEvent) -> bool:
    """Identify economic state jumps that lack authoritative feedback."""
    pair = (before.position, after.position)
    if pair == (PositionState.FLAT, PositionState.LONG):
        return event not in {StateEvent.POSITION_SYNC_LONG}
    if pair == (PositionState.LONG, PositionState.FLAT):
        return event not in {StateEvent.POSITION_SYNC_FLAT, StateEvent.EXIT_FILLED}
    if before.position == PositionState.UNKNOWN and after.evaluation == EvaluationState.ENTRY_CANDIDATE:
        return True
    return before.health != HealthState.READY and after.evaluation == EvaluationState.ENTRY_CANDIDATE
