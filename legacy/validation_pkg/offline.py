"""Purged/embargoed walk-forward preparation and frozen-gate evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class TimedSample:
    sample_id: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class WalkForwardFold:
    train_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    purged_ids: tuple[str, ...]
    embargoed_ids: tuple[str, ...]


def prepare_walk_forward(samples: Sequence[TimedSample], *, train_size: int, test_size: int, purge: timedelta, embargo: timedelta) -> tuple[WalkForwardFold, ...]:
    """Prepare folds only; this function never reads outcomes or tunes parameters."""
    if train_size <= 0 or test_size <= 0 or purge < timedelta(0) or embargo < timedelta(0):
        raise ValueError("invalid walk-forward configuration")
    ordered = sorted(samples, key=lambda item: (item.start, item.sample_id))
    folds: list[WalkForwardFold] = []
    cursor = train_size
    while cursor + test_size <= len(ordered):
        train_candidates = ordered[cursor - train_size : cursor]
        test = ordered[cursor : cursor + test_size]
        test_start, test_end = test[0].start, max(item.end for item in test)
        kept, purged_ids = [], []
        for item in train_candidates:
            if item.end >= test_start - purge:
                purged_ids.append(item.sample_id)
            else:
                kept.append(item.sample_id)
        embargoed = tuple(item.sample_id for item in ordered[cursor + test_size :] if item.start <= test_end + embargo)
        folds.append(WalkForwardFold(tuple(kept), tuple(item.sample_id for item in test), tuple(purged_ids), embargoed))
        cursor += test_size
    return tuple(folds)


@dataclass(frozen=True)
class FrozenOOSGate:
    version: str = "D-009/1.0.0"
    n_min: int = 100
    margin_min: Decimal = Decimal("0.01")
    positive_fold_ratio_min: Decimal = Decimal("0.70")
    pbo_max: Decimal = Decimal("0.20")
    neighbor_degradation_max: Decimal = Decimal("0.25")
    coverage_min: Decimal = Decimal("0.01")
    coverage_max: Decimal = Decimal("0.30")


@dataclass(frozen=True)
class OOSMetrics:
    independent_episodes: int
    delta_utility: Decimal
    positive_fold_ratio: Decimal
    pbo: Decimal
    risk_breaches: int
    neighbors_all_positive: bool
    median_neighbor_degradation: Decimal
    coverage: Decimal
    gross_bps: Decimal
    cost_plus_uncertainty_bps: Decimal


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]
    gate_version: str


def evaluate_frozen_gate(metrics: OOSMetrics, gate: FrozenOOSGate | None = None) -> GateResult:
    """Evaluate supplied offline evidence without modifying or optimizing the gate."""
    selected_gate = gate if gate is not None else FrozenOOSGate()
    reasons: list[str] = []
    if metrics.independent_episodes < selected_gate.n_min:
        reasons.append("INSUFFICIENT_EFFECTIVE_SAMPLE")
    if metrics.delta_utility < selected_gate.margin_min:
        reasons.append("DELTA_UTILITY_BELOW_MARGIN")
    if metrics.positive_fold_ratio < selected_gate.positive_fold_ratio_min:
        reasons.append("FOLD_STABILITY_FAIL")
    if metrics.pbo >= selected_gate.pbo_max:
        reasons.append("PBO_FAIL")
    if metrics.risk_breaches:
        reasons.append("RISK_MANDATE_BREACH")
    if not metrics.neighbors_all_positive or metrics.median_neighbor_degradation > selected_gate.neighbor_degradation_max:
        reasons.append("PARAMETER_NEIGHBOR_INSTABILITY")
    if not selected_gate.coverage_min <= metrics.coverage <= selected_gate.coverage_max:
        reasons.append("COVERAGE_OUTSIDE_GATE")
    if metrics.gross_bps <= metrics.cost_plus_uncertainty_bps:
        reasons.append("GROSS_DOES_NOT_CLEAR_COST")
    return GateResult(not reasons, tuple(reasons), selected_gate.version)
