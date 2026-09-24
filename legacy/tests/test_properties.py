"""Property-based evidence for deterministic domain invariants."""

from __future__ import annotations

from decimal import Decimal

import pytest
from btc_decision_agent.domain.risk import conservative_size, quantize_down
from btc_decision_agent.domain.state_machine import StateEvent, transition
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.helpers import D, portfolio, risk, state

from btc_decision_agent.domain.canonical import canonical_json, sha256_id
from btc_decision_agent.domain.contracts import EvaluationState, HealthState, PositionState

FINITE_DECIMALS = st.decimals(
    min_value=Decimal("-100000"),
    max_value=Decimal("100000"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
)
POSITIVE_DECIMALS = st.decimals(
    min_value=Decimal("0.00000001"),
    max_value=Decimal("100000"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
)
VALID_STATES = (
    state(PositionState.UNKNOWN, EvaluationState.IDLE, HealthState.BLOCKED),
    state(),
    state(PositionState.FLAT, EvaluationState.IDLE, HealthState.DEGRADED),
    state(PositionState.FLAT, EvaluationState.IDLE, HealthState.BLOCKED),
    state(PositionState.FLAT, EvaluationState.ENTRY_CANDIDATE, HealthState.READY),
    state(PositionState.FLAT, EvaluationState.COOLDOWN, HealthState.READY),
    state(PositionState.ENTRY_PENDING),
    state(PositionState.LONG),
    state(PositionState.LONG, EvaluationState.EXIT_CANDIDATE, HealthState.READY),
    state(PositionState.EXIT_PENDING),
)


@pytest.mark.property
@given(st.dictionaries(st.text(min_size=1, max_size=12), FINITE_DECIMALS, max_size=12))
@settings(max_examples=100)
def test_canonicalization_is_order_invariant_and_repeatable(values: dict[str, Decimal]) -> None:
    forward = dict(values.items())
    reversed_order = dict(reversed(tuple(values.items())))
    assert canonical_json(forward) == canonical_json(reversed_order)
    assert sha256_id(forward) == sha256_id(reversed_order)
    assert canonical_json(forward) == canonical_json(forward)


@pytest.mark.property
@given(value=POSITIVE_DECIMALS, step=POSITIVE_DECIMALS)
@settings(max_examples=150)
def test_quantize_down_never_rounds_up(value: Decimal, step: Decimal) -> None:
    quantity = quantize_down(value, step)
    assert Decimal("0") <= quantity <= value
    assert quantity % step == 0
    assert value - quantity < step


@pytest.mark.property
@given(current=st.sampled_from(VALID_STATES), event=st.sampled_from(tuple(StateEvent)))
@settings(max_examples=200)
def test_state_transitions_are_total_and_deterministic(current, event: StateEvent) -> None:
    first = transition(current, event)
    second = transition(current, event)
    assert first == second
    assert first.action is not None
    assert first.rule_id.startswith("SM-")


@pytest.mark.property
@given(
    reference_price=st.decimals(min_value=D("1"), max_value=D("100000"), places=4),
    stop_distance=st.decimals(min_value=D("0.01"), max_value=D("10000"), places=4),
    adverse_buffer=st.decimals(min_value=D("0"), max_value=D("1000"), places=4),
    cost_fraction=st.decimals(min_value=D("0"), max_value=D("0.1"), places=6),
    available_cash=st.decimals(min_value=D("10"), max_value=D("100000"), places=2),
)
@settings(max_examples=150)
def test_conservative_sizing_is_deterministic_and_never_exceeds_a_bound(
    reference_price: Decimal,
    stop_distance: Decimal,
    adverse_buffer: Decimal,
    cost_fraction: Decimal,
    available_cash: Decimal,
) -> None:
    mandate = risk()
    current = portfolio().model_copy(update={"available_cash": available_cash})
    first = conservative_size(
        mandate,
        current,
        reference_price,
        stop_distance,
        adverse_buffer,
        cost_fraction,
    )
    second = conservative_size(
        mandate,
        current,
        reference_price,
        stop_distance,
        adverse_buffer,
        cost_fraction,
    )
    assert first == second
    quantity, _ = first
    if quantity is None:
        return
    loss_per_unit = stop_distance + adverse_buffer
    assert quantity <= mandate.risk_per_decision * mandate.capital / loss_per_unit
    assert quantity <= mandate.max_exposure / reference_price
    assert quantity <= available_cash / (reference_price * (D("1") + cost_fraction))
    assert quantity % mandate.step_size == 0
