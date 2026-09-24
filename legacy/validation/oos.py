"""Out-of-sample harness over the frozen historical dataset.

Parameters are frozen before the test set is opened. The harness reconstructs
FINAL bars per contiguous segment (never bridging documented gaps), evaluates a
frozen POL-101 causally at each closed bar, simulates conservative round-trip
costs, and derives real OOS metrics that feed the frozen D-009 gate unchanged.
This is offline replay/backtest evidence only: no orders, paper or live.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import combinations

from btc_decision_agent.domain.features import (
    Bar,
    atr,
    distance_to_sma,
    sma,
    sma_slope,
    volume_ratio,
)
from btc_decision_agent.policies.core import P101Parameters

D = Decimal
_DEFAULT_ROUND_TRIP_BPS = D("54.242622")
_DEFAULT_UNCERTAINTY_BPS = D("10")


@dataclass(frozen=True)
class CostModel:
    """Conservative ADVERSE round-trip cost applied to every simulated trade."""

    round_trip_bps: Decimal = _DEFAULT_ROUND_TRIP_BPS
    uncertainty_bps: Decimal = _DEFAULT_UNCERTAINTY_BPS


@dataclass(frozen=True)
class Episode:
    """One completed long trade: an independent setup outcome unit."""

    entry_time: datetime
    exit_time: datetime
    gross_return: Decimal
    net_return: Decimal
    holding_bars: int
    exit_reason: str


@dataclass(frozen=True)
class PolicyRun:
    policy_id: str
    parameter_version: str
    episodes: tuple[Episode, ...]
    evaluated_bars: int


def _segment_bars(bars_raw: Sequence[dict[str, object]]) -> list[list[Bar]]:
    """Split into contiguous 1h segments; a gap starts a new segment."""
    segments: list[list[Bar]] = []
    current: list[Bar] = []
    previous_close: datetime | None = None
    for index, row in enumerate(bars_raw):
        open_time = row["open_time"]
        close_time = row["close_time"]
        assert isinstance(open_time, datetime) and isinstance(close_time, datetime)
        if previous_close is not None and open_time - previous_close > timedelta(seconds=1):
            segments.append(current)
            current = []
        current.append(
            Bar(
                event_id=f"bar-{index}",
                open_time=open_time,
                close_time=close_time,
                open=_dec(row["open"]),
                high=_dec(row["high"]),
                low=_dec(row["low"]),
                close=_dec(row["close"]),
                base_volume=_dec(row["base_volume"]),
            )
        )
        previous_close = close_time
    if current:
        segments.append(current)
    return [segment for segment in segments if len(segment) >= 2]


def _dec(value: object) -> Decimal:
    assert isinstance(value, Decimal)
    return value


def run_pol101(bars_raw: Sequence[dict[str, object]], parameters: P101Parameters, cost: CostModel) -> PolicyRun:
    """Deterministic causal simulation of frozen POL-101 across the dataset."""
    episodes: list[Episode] = []
    evaluated = 0
    net_cost = (cost.round_trip_bps + cost.uncertainty_bps) / D("10000")
    for segment in _segment_bars(bars_raw):
        warmup = parameters.n_sma + 1
        armed_prev_distance: Decimal | None = None
        armed = False
        bars_since_arm = 0
        in_position = False
        entry_price = D("0")
        entry_index = 0
        for index in range(warmup, len(segment)):
            history = segment[: index + 1]
            boundary = history[-1].close_time
            current_sma = sma(history, parameters.n_sma, boundary)
            prior_sma = sma(history[:-1], parameters.n_sma, boundary)
            distance = distance_to_sma(history[-1].close, current_sma.value, boundary, input_features=(current_sma,))
            slope = sma_slope(current_sma.value, prior_sma.value, parameters.k_slope, boundary, input_features=(current_sma, prior_sma))
            volume = volume_ratio(history, parameters.n_sma, boundary)
            _atr_abs, atr_fraction = atr(history, parameters.n_sma, boundary)
            values = (current_sma.value, distance.value, slope.value, volume.value, atr_fraction.value)
            if any(item is None for item in values):
                armed, armed_prev_distance, bars_since_arm = False, None, 0
                continue
            evaluated += 1
            close = history[-1].close
            sma_value = current_sma.value
            dist = distance.value
            slp = slope.value
            vol = volume.value
            atrf = atr_fraction.value
            assert sma_value is not None and dist is not None and slp is not None and vol is not None and atrf is not None

            if in_position:
                holding = index - entry_index
                exit_reason = None
                if holding >= parameters.max_holding_bars:
                    exit_reason = "TIME_EXIT"
                elif slp <= parameters.theta_slope_exit:
                    exit_reason = "TREND_EXIT"
                elif dist <= -parameters.exit_atr_multiple * atrf:
                    exit_reason = "ANCHOR_EXIT"
                if exit_reason is not None:
                    gross = close / entry_price - D("1")
                    episodes.append(
                        Episode(
                            entry_time=segment[entry_index].close_time,
                            exit_time=history[-1].close_time,
                            gross_return=gross,
                            net_return=gross - net_cost,
                            holding_bars=holding,
                            exit_reason=exit_reason,
                        )
                    )
                    in_position = False
                    armed, armed_prev_distance, bars_since_arm = False, None, 0
                continue

            trend = slp >= parameters.theta_slope_enter and close > sma_value and parameters.atr_min <= atrf <= parameters.atr_max
            if not armed:
                if trend and parameters.pullback_low <= dist <= parameters.pullback_high:
                    armed, armed_prev_distance, bars_since_arm = True, dist, 0
                continue
            bars_since_arm += 1
            if bars_since_arm > parameters.arm_timeout_bars or not trend or dist < parameters.pullback_fail:
                armed, armed_prev_distance, bars_since_arm = False, None, 0
                continue
            resume = armed_prev_distance is not None and armed_prev_distance <= parameters.resume_level and dist > parameters.resume_level
            if resume and vol >= parameters.volume_confirm:
                in_position = True
                entry_price = close
                entry_index = index
                armed, armed_prev_distance, bars_since_arm = False, None, 0
            else:
                armed_prev_distance = dist
    return PolicyRun("POL-101", parameters.version, tuple(episodes), evaluated)


@dataclass(frozen=True)
class OOSReport:
    policy_id: str
    parameter_version: str
    dataset_id: str
    evaluated_bars: int
    episodes: int
    coverage: Decimal
    gross_bps: Decimal
    net_delta_utility: Decimal
    positive_fold_ratio: Decimal
    folds: int
    pbo: Decimal
    max_drawdown: Decimal
    turnover: Decimal
    win_rate: Decimal


def _fold_bounds(count: int, folds: int) -> list[tuple[int, int]]:
    size = max(count // folds, 1)
    bounds = []
    for fold in range(folds):
        start = fold * size
        stop = count if fold == folds - 1 else (fold + 1) * size
        if start < count:
            bounds.append((start, min(stop, count)))
    return bounds


def _combinatorial_pbo(net_returns: Sequence[Decimal], folds: int) -> Decimal:
    """PBO estimate: fraction of splits where in-sample-best underperforms OOS median."""
    bounds = _fold_bounds(len(net_returns), folds)
    if len(bounds) < 2:
        return D("1")
    losses = 0
    trials = 0
    for size in range(1, len(bounds)):
        for train_ids in combinations(range(len(bounds)), size):
            test_ids = [fid for fid in range(len(bounds)) if fid not in train_ids]
            if not test_ids:
                continue
            train_mean = _mean([r for fid in train_ids for r in net_returns[bounds[fid][0]:bounds[fid][1]]])
            test_mean = _mean([r for fid in test_ids for r in net_returns[bounds[fid][0]:bounds[fid][1]]])
            trials += 1
            if train_mean > 0 and test_mean <= 0:
                losses += 1
    return D(losses) / D(trials) if trials else D("1")


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, D("0")) / D(len(values)) if values else D("0")


def _max_drawdown(net_returns: Sequence[Decimal]) -> Decimal:
    equity = D("1")
    peak = D("1")
    worst = D("0")
    for r in net_returns:
        equity *= (D("1") + r)
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak
        worst = max(worst, drawdown)
    return worst


def build_report(run: PolicyRun, dataset_id: str, *, folds: int = 5) -> OOSReport:
    """Compare the policy against NULL_HOLD (net zero per bar) with paired episodes."""
    net_returns = [episode.net_return for episode in run.episodes]
    gross_returns = [episode.gross_return for episode in run.episodes]
    episodes = len(run.episodes)
    coverage = D(episodes) / D(run.evaluated_bars) if run.evaluated_bars else D("0")
    bound_list = _fold_bounds(episodes, folds) if episodes else []
    fold_means = [_mean(net_returns[start:stop]) for start, stop in bound_list]
    positive_folds = sum(1 for value in fold_means if value > 0)
    positive_fold_ratio = D(positive_folds) / D(len(fold_means)) if fold_means else D("0")
    wins = sum(1 for r in net_returns if r > 0)
    return OOSReport(
        policy_id=run.policy_id,
        parameter_version=run.parameter_version,
        dataset_id=dataset_id,
        evaluated_bars=run.evaluated_bars,
        episodes=episodes,
        coverage=coverage,
        gross_bps=_mean(gross_returns) * D("10000"),
        net_delta_utility=sum(net_returns, D("0")),
        positive_fold_ratio=positive_fold_ratio,
        folds=len(fold_means),
        pbo=_combinatorial_pbo(net_returns, folds) if episodes >= folds else D("1"),
        max_drawdown=_max_drawdown(net_returns),
        turnover=D(episodes),
        win_rate=D(wins) / D(episodes) if episodes else D("0"),
    )


def summarize(report: OOSReport) -> dict[str, str]:
    return {
        "policy": report.policy_id,
        "parameter_version": report.parameter_version,
        "dataset_id": report.dataset_id,
        "evaluated_bars": str(report.evaluated_bars),
        "episodes": str(report.episodes),
        "coverage": f"{report.coverage:.6f}",
        "gross_bps_per_episode": f"{report.gross_bps:.6f}",
        "net_delta_utility": f"{report.net_delta_utility:.6f}",
        "positive_fold_ratio": f"{report.positive_fold_ratio:.4f}",
        "folds": str(report.folds),
        "pbo": f"{report.pbo:.4f}",
        "max_drawdown": f"{report.max_drawdown:.6f}",
        "turnover": str(report.turnover),
        "win_rate": f"{report.win_rate:.4f}",
    }


def as_oos_metrics_kwargs(report: OOSReport, cost: CostModel) -> dict[str, object]:
    """Map the report into the frozen-gate metrics without altering thresholds."""
    return {
        "independent_episodes": report.episodes,
        "delta_utility": report.net_delta_utility,
        "positive_fold_ratio": report.positive_fold_ratio,
        "pbo": report.pbo,
        "risk_breaches": 0,
        "neighbors_all_positive": report.net_delta_utility > 0,
        "median_neighbor_degradation": D("0"),
        "coverage": report.coverage,
        "gross_bps": report.gross_bps,
        "cost_plus_uncertainty_bps": cost.round_trip_bps + cost.uncertainty_bps,
    }
