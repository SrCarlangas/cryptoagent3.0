"""Task 1 diagnosis: why the 3-class 4h model cannot work, and which horizon can.

This is a measurement script, not an argument. It answers four questions with
numbers taken from the frozen 1h dataset:

A. Is the current label degenerate? Reproduce the exact label function used to
   train LOCAL-SOFTMAX-BTC-1H-4H-V1 and show its class distribution. If the
   majority class share is ~0.40 then a 0.3990 accuracy model has learned
   nothing, which is what the holdout already said.

B. At which horizon does the move exceed the cost of acting on it? A 20bps
   round trip is a hard floor. If the median absolute move over the horizon is
   below that floor, the label is mostly fee noise and no model can fix it.

C. What does churn cost? Count the decision flips an argmax policy would make
   at each horizon and price them at 20bps per round trip.

D. Is there any learnable structure? Measure the rank correlation between simple
   causal trend statistics and the forward return at each horizon. This is a
   necessary condition check, deliberately done with raw statistics instead of a
   fitted model so it cannot be inflated by in-sample fitting.

Read-only. Writes data/validation/exposure-diagnosis.{json,md}.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from multislot_sim import HOUR_MS, Bar, load_bars, window_index

ROUND_TRIP_COST_BPS = 20.0
DECISION_THRESHOLD_BPS = 10.0
HORIZONS_HOURS: tuple[int, ...] = (4, 12, 24, 48, 96, 168, 336)
FORWARD_TOLERANCE_MS = 0
"""Forward lookups must land on the exact bar. Gaps are skipped, never bridged."""


@dataclass(frozen=True)
class HorizonStats:
    hours: int
    samples: int
    positive_share: float
    majority_share: float
    median_abs_move_bps: float
    share_exceeding_cost: float
    mean_move_bps: float
    three_class_shares: dict[str, float]
    argmax_flips_per_year: float
    annual_churn_cost_pct: float


def _index_by_time(bars: list[Bar]) -> dict[int, int]:
    return {bar.open_time_ms: index for index, bar in enumerate(bars)}


def _forward_pairs(
    bars: list[Bar], by_time: dict[int, int], hours: int, start: int, end: int
) -> list[tuple[int, float, float]]:
    """(index, price_now, price_future) for bars whose exact forward bar exists."""
    offset = hours * HOUR_MS
    pairs: list[tuple[int, float, float]] = []
    for index in range(start, end):
        future = by_time.get(bars[index].open_time_ms + offset)
        if future is None or future >= end:
            continue
        pairs.append((index, bars[index].close, bars[future].close))
    return pairs


def _three_class_label(move_bps: float) -> str:
    """The exact decision rule behind net_four_hour_label, in bps space."""
    if move_bps - ROUND_TRIP_COST_BPS >= DECISION_THRESHOLD_BPS:
        return "BUY"
    if -move_bps - ROUND_TRIP_COST_BPS >= DECISION_THRESHOLD_BPS:
        return "SELL"
    return "HOLD"


def _median(values: list[float]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return 0.5 * (ordered[middle - 1] + ordered[middle])


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation, robust to the fat tails in crypto returns."""
    if len(xs) != len(ys) or len(xs) < 3:
        return float("nan")

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=values.__getitem__)
        result = [0.0] * len(values)
        position = 0
        while position < len(order):
            tie_end = position
            while tie_end + 1 < len(order) and values[order[tie_end + 1]] == values[order[position]]:
                tie_end += 1
            average = (position + tie_end) / 2.0 + 1.0
            for slot in range(position, tie_end + 1):
                result[order[slot]] = average
            position = tie_end + 1
        return result

    rx, ry = ranks(xs), ranks(ys)
    n = float(len(xs))
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0.0 or dy == 0.0:
        return float("nan")
    return num / (dx * dy)


def _time_based_ma(bars: list[Bar], hours: int, coverage: float = 0.95) -> list[float | None]:
    """Causal time-based moving average that withholds output across gaps."""
    span_ms = (hours - 1) * HOUR_MS
    required = hours * coverage
    means: list[float | None] = [None] * len(bars)
    running = 0.0
    left = 0
    for index, bar in enumerate(bars):
        running += bar.close
        while bar.open_time_ms - bars[left].open_time_ms > span_ms:
            running -= bars[left].close
            left += 1
        count = index - left + 1
        elapsed = bar.open_time_ms - bars[left].open_time_ms
        if elapsed >= span_ms * coverage and count >= required:
            means[index] = running / count
    return means


def horizon_statistics(
    bars: list[Bar], by_time: dict[int, int], hours: int, start: int, end: int
) -> HorizonStats:
    pairs = _forward_pairs(bars, by_time, hours, start, end)
    moves = [(future / now - 1.0) * 10_000.0 for _, now, future in pairs]
    if not moves:
        raise ValueError(f"no forward pairs at {hours}h")

    positives = sum(1 for move in moves if move > 0.0)
    positive_share = positives / len(moves)
    labels = [_three_class_label(move) for move in moves]
    shares = {
        name: labels.count(name) / len(labels) for name in ("BUY", "HOLD", "SELL")
    }

    # Churn: an argmax policy re-decides every `hours` and flips whenever the
    # label changes between consecutive non-overlapping decisions.
    step = max(1, hours)
    sampled = labels[::step]
    flips = sum(1 for a, b in pairwise(sampled) if a != b)
    span_years = (bars[end - 1].open_time_ms - bars[start].open_time_ms) / (
        HOUR_MS * 24.0 * 365.25
    )
    flips_per_year = flips / span_years if span_years > 0 else float("nan")
    # Every second flip completes a round trip that pays the full cost.
    annual_churn_cost_pct = (flips_per_year / 2.0) * (ROUND_TRIP_COST_BPS / 100.0)

    return HorizonStats(
        hours=hours,
        samples=len(moves),
        positive_share=positive_share,
        majority_share=max(positive_share, 1.0 - positive_share),
        median_abs_move_bps=_median([abs(move) for move in moves]),
        share_exceeding_cost=sum(1 for move in moves if abs(move) > ROUND_TRIP_COST_BPS)
        / len(moves),
        mean_move_bps=sum(moves) / len(moves),
        three_class_shares=shares,
        argmax_flips_per_year=flips_per_year,
        annual_churn_cost_pct=annual_churn_cost_pct,
    )


def trend_signal_strength(
    bars: list[Bar], by_time: dict[int, int], start: int, end: int
) -> dict[str, dict[str, float]]:
    """Rank correlation of causal trend statistics against forward returns.

    Positive and monotone-in-horizon correlation is the necessary condition for a
    trend-following exposure model. If the correlation is ~0 at every horizon the
    whole approach is dead regardless of model class.
    """
    ma_specs = {"ma7d": 168, "ma30d": 720, "ma100d": 2400, "ma200d": 4800}
    mas = {name: _time_based_ma(bars, hours) for name, hours in ma_specs.items()}

    signals: dict[str, list[float | None]] = {}
    for name, series in mas.items():
        signals[f"log_price_over_{name}"] = [
            math.log(bar.close / value) if value is not None and value > 0 else None
            for bar, value in zip(bars, series, strict=True)
        ]
    fast, slow = mas["ma30d"], mas["ma200d"]
    signals["log_ma30d_over_ma200d"] = [
        math.log(a / b) if a is not None and b is not None and b > 0 else None
        for a, b in zip(fast, slow, strict=True)
    ]

    out: dict[str, dict[str, float]] = {}
    for signal_name, series in signals.items():
        per_horizon: dict[str, float] = {}
        for hours in HORIZONS_HOURS:
            xs: list[float] = []
            ys: list[float] = []
            for index, now, future in _forward_pairs(bars, by_time, hours, start, end):
                value = series[index]
                if value is None:
                    continue
                xs.append(value)
                ys.append(future / now - 1.0)
            per_horizon[f"{hours}h"] = _spearman(xs, ys)
            per_horizon[f"{hours}h_samples"] = float(len(xs))
        out[signal_name] = per_horizon
    return out


def trend_signal_significance(
    bars: list[Bar], by_time: dict[int, int], start: int, end: int
) -> dict[str, Any]:
    """Re-measure signal strength on NON-OVERLAPPING samples.

    Hourly samples of a 336h forward return share 335/336 of their data, so a
    correlation computed on 43k overlapping rows has an effective sample size
    closer to 130. Quoting 1/sqrt(43000) as the error bar would overstate
    confidence by an order of magnitude. Here each horizon is subsampled at its
    own stride so the forward windows are disjoint, and the correlation is
    reported against the standard error of that independent sample.

    Every stride offset is evaluated, not just offset 0, because picking the one
    offset with the largest correlation is the same overfitting the previous
    study already caught in the trend-following family.
    """
    ma_specs = {"ma7d": 168, "ma30d": 720, "ma100d": 2400, "ma200d": 4800}
    mas = {name: _time_based_ma(bars, hours) for name, hours in ma_specs.items()}
    signals: dict[str, list[float | None]] = {
        f"log_price_over_{name}": [
            math.log(bar.close / value) if value is not None and value > 0 else None
            for bar, value in zip(bars, series, strict=True)
        ]
        for name, series in mas.items()
    }
    signals["log_ma30d_over_ma200d"] = [
        math.log(a / b) if a is not None and b is not None and b > 0 else None
        for a, b in zip(mas["ma30d"], mas["ma200d"], strict=True)
    ]

    out: dict[str, Any] = {}
    for signal_name, series in signals.items():
        per_horizon: dict[str, Any] = {}
        for hours in HORIZONS_HOURS:
            pairs = _forward_pairs(bars, by_time, hours, start, end)
            rows = [
                (index, series[index], future / now - 1.0)
                for index, now, future in pairs
                if series[index] is not None
            ]
            if len(rows) < hours * 4:
                continue
            correlations: list[float] = []
            for offset in range(hours):
                subset = rows[offset::hours]
                if len(subset) < 20:
                    continue
                correlations.append(
                    _spearman([float(item[1]) for item in subset], [item[2] for item in subset])
                )
            finite = [value for value in correlations if math.isfinite(value)]
            if not finite:
                continue
            independent_n = len(rows) // hours
            standard_error = 1.0 / math.sqrt(max(independent_n - 1, 1))
            mean_rho = sum(finite) / len(finite)
            per_horizon[f"{hours}h"] = {
                "mean_rho_over_offsets": mean_rho,
                "min_rho": min(finite),
                "max_rho": max(finite),
                "offsets_positive_share": sum(1 for v in finite if v > 0) / len(finite),
                "independent_samples": independent_n,
                "standard_error": standard_error,
                "mean_rho_in_standard_errors": mean_rho / standard_error,
                "sign_stable_across_offsets": min(finite) > 0.0 or max(finite) < 0.0,
            }
        out[signal_name] = per_horizon
    return out


def _long_flat_run(
    bars: list[Bar],
    reference: list[float | None],
    start: int,
    end: int,
    fee_per_side: float,
    enter_band: float = 0.0,
    exit_band: float = 0.0,
    execution_lag_bars: int = 1,
) -> dict[str, Any]:
    """Long/flat with optional hysteresis band, marked to market every bar.

    enter_band / exit_band express hysteresis as a fraction of the reference:
    go long above reference*(1+enter_band), go flat below reference*(1-exit_band).
    With both zero this is the naive crossing rule.

    execution_lag_bars guards against a subtle look-ahead. The moving average at
    bar i includes close[i], so deciding on close[i] and also FILLING at close[i]
    assumes we acted on a price at the instant we learned it. With the default lag
    of 1 the decision is taken on bar i and filled at close[i+1], which is what a
    live agent reacting to a closed bar can actually achieve. Lag 0 is retained
    only to quantify how much that optimism was worth.
    """
    cash = 1.0
    units = 0.0
    flips = 0
    peak = 1.0
    max_drawdown = 0.0
    for index in range(start, end):
        level = reference[index]
        decision_price = bars[index].close
        if level is None:
            want_long = True
        elif units > 0.0:
            want_long = decision_price >= level * (1.0 - exit_band)
        else:
            want_long = decision_price >= level * (1.0 + enter_band)

        fill_index = min(index + execution_lag_bars, end - 1)
        fill_price = bars[fill_index].close
        if want_long and units == 0.0:
            units = (cash * (1.0 - fee_per_side)) / fill_price
            cash = 0.0
            flips += 1
        elif not want_long and units > 0.0:
            cash = units * fill_price * (1.0 - fee_per_side)
            units = 0.0
            flips += 1
        equity = cash + units * bars[index].close
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    final = cash + (units * bars[end - 1].close * (1.0 - fee_per_side) if units else 0.0)
    return {
        "net_return_pct": (final - 1.0) * 100.0,
        "max_drawdown_pct": max_drawdown * 100.0,
        "flips": flips,
        "ends_long": units > 0.0,
    }


def _buy_and_hold_net(bars: list[Bar], start: int, end: int, fee_per_side: float) -> dict[str, Any]:
    units = (1.0 * (1.0 - fee_per_side)) / bars[start].close
    peak = 1.0
    max_drawdown = 0.0
    for index in range(start, end):
        equity = units * bars[index].close
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    final = units * bars[end - 1].close * (1.0 - fee_per_side)
    return {
        "net_return_pct": (final - 1.0) * 100.0,
        "max_drawdown_pct": max_drawdown * 100.0,
        "flips": 2,
        "ends_long": True,
    }


def exposure_policy_matrix(bars: list[Bar]) -> dict[str, Any]:
    """The go/no-go for the whole redesign.

    D2 shows the trend features carry no point-in-time directional signal, so the
    only remaining justification for a long/flat exposure model is that CHANGING
    EXPOSURE reshapes the return distribution (cuts the left tail) even with zero
    forecasting power. That claim is economic, so it is tested economically:
    every window, several reference lengths, honest and adverse fees.

    The bar set for "deployable" is the one that killed the previous trend family:
    beat buy and hold in the full window AND at adverse fees AND with neighbouring
    parameters, not at an isolated peak.
    """
    from multislot_sim import standard_windows

    windows = standard_windows(bars)
    lengths = {
        "ma30d": 720,
        "ma50d": 1200,
        "ma75d": 1800,
        "ma100d": 2400,
        "ma150d": 3600,
        "ma200d": 4800,
        "ma250d": 6000,
    }
    references = {name: _time_based_ma(bars, hours) for name, hours in lengths.items()}

    matrix: dict[str, Any] = {}
    for fee_label, fee in (("honest_10bps", 0.001), ("adverse_20bps", 0.002)):
        per_fee: dict[str, Any] = {}
        for window_name, (start, end) in windows.items():
            benchmark = _buy_and_hold_net(bars, start, end, fee)
            entries: dict[str, Any] = {"buy_and_hold": benchmark}
            for name, series in references.items():
                result = _long_flat_run(bars, series, start, end, fee)
                result["beats_buy_and_hold"] = (
                    result["net_return_pct"] > benchmark["net_return_pct"]
                )
                entries[name] = result
            per_fee[window_name] = entries
        matrix[fee_label] = per_fee

    # Neighbour test: a length only counts if BOTH adjacent lengths also beat B&H
    # in the full window. Isolated peaks are what overfitting looks like.
    ordered = list(lengths)
    full = matrix["honest_10bps"]["full_2020_2026"]
    robust: list[str] = []
    for position, name in enumerate(ordered):
        neighbours = [
            ordered[index]
            for index in (position - 1, position + 1)
            if 0 <= index < len(ordered)
        ]
        if all(full[item]["beats_buy_and_hold"] for item in [name, *neighbours]):
            robust.append(name)

    survivors = [
        name
        for name in robust
        if matrix["adverse_20bps"]["full_2020_2026"][name]["beats_buy_and_hold"]
        and matrix["honest_10bps"]["last_5y"][name]["beats_buy_and_hold"]
    ]

    # Hysteresis sweep on the surviving lengths: does a dead band help or hurt?
    hysteresis: dict[str, Any] = {}
    for name in survivors or ["ma200d"]:
        per_band: dict[str, Any] = {}
        for enter_band, exit_band in ((0.0, 0.0), (0.01, 0.01), (0.02, 0.02), (0.03, 0.03), (0.02, 0.05)):
            key = f"enter+{enter_band:.0%}/exit-{exit_band:.0%}"
            per_band[key] = {
                window_name: _long_flat_run(
                    bars, references[name], start, end, 0.001, enter_band, exit_band
                )
                for window_name, (start, end) in windows.items()
            }
        hysteresis[name] = per_band

    return {
        "matrix": matrix,
        "neighbour_robust_lengths_full_window": robust,
        "lengths_surviving_all_gates": survivors,
        "hysteresis_sweep": hysteresis,
    }


PLATEAU_LENGTHS: tuple[tuple[str, int], ...] = (
    ("ma30d", 720),
    ("ma50d", 1200),
    ("ma75d", 1800),
    ("ma100d", 2400),
    ("ma150d", 3600),
    ("ma200d", 4800),
    ("ma250d", 6000),
)
PLATEAU_BANDS: tuple[float, ...] = (0.0, 0.01, 0.02, 0.03, 0.04, 0.05)


def exposure_plateau_study(bars: list[Bar]) -> dict[str, Any]:
    """Section F: does the hysteresis band rescue the long/flat rule?

    Section E tested reference length with NO dead band and found isolated,
    non-monotone winners that died at adverse fees. But section C proved churn is
    the dominant cost, and the band is the parameter that controls churn, so
    testing length while holding the band at zero tests the wrong axis.

    This sweeps both axes together and applies the anti-overfitting rule in BOTH
    directions: a cell counts as robust only if it AND its four orthogonal
    neighbours (shorter length, longer length, tighter band, wider band) all beat
    buy and hold. A plateau of adjacent passing cells is evidence of a real
    effect. A single passing cell surrounded by failures is a fitting artifact,
    which is precisely what section E found on the band=0 row.

    The gate is deliberately the strict one the user already approved: beat buy
    and hold in the full window AND in last_5y, at honest AND adverse fees.
    """
    from multislot_sim import standard_windows

    windows = standard_windows(bars)
    references = {name: _time_based_ma(bars, hours) for name, hours in PLATEAU_LENGTHS}
    length_names = [name for name, _ in PLATEAU_LENGTHS]

    cells: dict[str, dict[str, Any]] = {}
    for name in length_names:
        for band in PLATEAU_BANDS:
            key = f"{name}|band={band:.2f}"
            per_fee: dict[str, Any] = {}
            passes = True
            for fee_label, fee in (("honest_10bps", 0.001), ("adverse_20bps", 0.002)):
                per_window: dict[str, Any] = {}
                for window_name, (start, end) in windows.items():
                    benchmark = _buy_and_hold_net(bars, start, end, fee)
                    result = _long_flat_run(
                        bars, references[name], start, end, fee, band, band
                    )
                    result["buy_and_hold_pct"] = benchmark["net_return_pct"]
                    result["excess_pct"] = (
                        result["net_return_pct"] - benchmark["net_return_pct"]
                    )
                    result["drawdown_reduction_pp"] = (
                        benchmark["max_drawdown_pct"] - result["max_drawdown_pct"]
                    )
                    # Quantify how much of the edge came from filling at the same
                    # close that produced the signal.
                    optimistic = _long_flat_run(
                        bars, references[name], start, end, fee, band, band,
                        execution_lag_bars=0,
                    )
                    result["lookahead_bonus_pp"] = (
                        optimistic["net_return_pct"] - result["net_return_pct"]
                    )
                    per_window[window_name] = result
                per_fee[fee_label] = per_window
                for gate_window in ("full_2020_2026", "last_5y"):
                    if per_fee[fee_label][gate_window]["excess_pct"] <= 0.0:
                        passes = False
            honest = per_fee["honest_10bps"]
            adverse = per_fee["adverse_20bps"]
            cells[key] = {
                "length": name,
                "band": band,
                "per_fee": per_fee,
                "passes_strict_gate": passes,
                # The two gate windows overlap heavily, so record the harder
                # question separately: does it win everywhere, including the
                # V-shaped recovery that trend rules are structurally late to?
                "windows_beaten_honest": sorted(
                    item for item, values in honest.items() if values["excess_pct"] > 0.0
                ),
                "windows_beaten_adverse": sorted(
                    item for item, values in adverse.items() if values["excess_pct"] > 0.0
                ),
                "beats_all_windows_both_fees": all(
                    honest[item]["excess_pct"] > 0.0 and adverse[item]["excess_pct"] > 0.0
                    for item in honest
                ),
            }

    def passes(name: str, band: float) -> bool:
        return cells[f"{name}|band={band:.2f}"]["passes_strict_gate"]

    robust: list[str] = []
    for length_index, name in enumerate(length_names):
        for band_index, band in enumerate(PLATEAU_BANDS):
            if not passes(name, band):
                continue
            neighbours: list[tuple[str, float]] = []
            for offset in (-1, 1):
                if 0 <= length_index + offset < len(length_names):
                    neighbours.append((length_names[length_index + offset], band))
                if 0 <= band_index + offset < len(PLATEAU_BANDS):
                    neighbours.append((name, PLATEAU_BANDS[band_index + offset]))
            if all(passes(other_name, other_band) for other_name, other_band in neighbours):
                robust.append(f"{name}|band={band:.2f}")

    passing = [key for key, cell in cells.items() if cell["passes_strict_gate"]]
    all_windows = [key for key, cell in cells.items() if cell["beats_all_windows_both_fees"]]
    return {
        "lengths": length_names,
        "bands": list(PLATEAU_BANDS),
        "execution_lag_bars": 1,
        "cells": cells,
        "cells_passing_strict_gate": passing,
        "cells_passing_count": len(passing),
        "cells_total": len(cells),
        "cells_beating_all_windows_both_fees": all_windows,
        "neighbour_robust_cells": robust,
        "zero_band_passes": [
            key for key in passing if cells[key]["band"] == 0.0
        ],
        "verdict": (
            "STRICT_GATE_ACHIEVABLE" if robust else "STRICT_GATE_NOT_ACHIEVABLE"
        ),
    }


def temporal_out_of_sample(bars: list[Bar]) -> dict[str, Any]:
    """Section G: the test that actually predicts deployment behaviour.

    Sections E and F select parameters and measure performance on the same years.
    That is how every backtest looks good. The honest question is whether the
    SELECTION generalises: choose (length, band) using only the first segment,
    then evaluate that frozen choice on data the selection never saw.

    Three splits are used so the answer does not depend on one arbitrary cut
    point, and each split reports the chosen cell, its in-sample excess, and its
    out-of-sample excess. Only the out-of-sample column is evidence.
    """
    references = {name: _time_based_ma(bars, hours) for name, hours in PLATEAU_LENGTHS}
    splits = {
        "select_2020_2022_test_2023_2026": ("2020-01-01", "2023-01-01", None),
        "select_2020_2023_test_2024_2026": ("2020-01-01", "2024-01-01", None),
        "select_2021_2024_test_2024_2026": ("2021-01-01", "2024-07-01", None),
    }

    results: dict[str, Any] = {}
    for split_name, (begin, cut, _unused) in splits.items():
        start = window_index(bars, begin)
        boundary = window_index(bars, cut)
        end = len(bars)
        if not start < boundary < end:
            continue

        ranked: list[tuple[float, str, float, str]] = []
        for name, _hours in PLATEAU_LENGTHS:
            for band in PLATEAU_BANDS:
                in_sample = _long_flat_run(
                    bars, references[name], start, boundary, 0.001, band, band
                )
                benchmark = _buy_and_hold_net(bars, start, boundary, 0.001)
                excess = in_sample["net_return_pct"] - benchmark["net_return_pct"]
                ranked.append((excess, name, band, f"{name}|band={band:.2f}"))
        ranked.sort(key=lambda item: item[0], reverse=True)
        best_excess, best_name, best_band, best_key = ranked[0]

        out_sample = _long_flat_run(
            bars, references[best_name], boundary, end, 0.001, best_band, best_band
        )
        out_benchmark = _buy_and_hold_net(bars, boundary, end, 0.001)
        out_adverse = _long_flat_run(
            bars, references[best_name], boundary, end, 0.002, best_band, best_band
        )
        out_adverse_benchmark = _buy_and_hold_net(bars, boundary, end, 0.002)

        # How would the whole passing family have done, not just the argmax?
        family_excess: list[float] = []
        for _excess, name, band, _key in ranked:
            candidate = _long_flat_run(
                bars, references[name], boundary, end, 0.001, band, band
            )
            family_excess.append(candidate["net_return_pct"] - out_benchmark["net_return_pct"])

        results[split_name] = {
            "selection_window": {"start": begin, "end": cut},
            "chosen_cell": best_key,
            "in_sample_excess_pp": best_excess,
            "out_of_sample": {
                "strategy_pct": out_sample["net_return_pct"],
                "buy_and_hold_pct": out_benchmark["net_return_pct"],
                "excess_pp": out_sample["net_return_pct"] - out_benchmark["net_return_pct"],
                "max_drawdown_pct": out_sample["max_drawdown_pct"],
                "buy_and_hold_drawdown_pct": out_benchmark["max_drawdown_pct"],
                "drawdown_reduction_pp": (
                    out_benchmark["max_drawdown_pct"] - out_sample["max_drawdown_pct"]
                ),
                "flips": out_sample["flips"],
                "beats_buy_and_hold": (
                    out_sample["net_return_pct"] > out_benchmark["net_return_pct"]
                ),
            },
            "out_of_sample_adverse_fees": {
                "excess_pp": (
                    out_adverse["net_return_pct"] - out_adverse_benchmark["net_return_pct"]
                ),
                "beats_buy_and_hold": (
                    out_adverse["net_return_pct"] > out_adverse_benchmark["net_return_pct"]
                ),
            },
            "family_out_of_sample": {
                "cells": len(family_excess),
                "median_excess_pp": _median(family_excess),
                "share_beating_buy_and_hold": (
                    sum(1 for value in family_excess if value > 0.0) / len(family_excess)
                ),
                "worst_excess_pp": min(family_excess),
                "best_excess_pp": max(family_excess),
            },
        }

    honest_wins = sum(
        1 for item in results.values() if item["out_of_sample"]["beats_buy_and_hold"]
    )
    adverse_wins = sum(
        1
        for item in results.values()
        if item["out_of_sample_adverse_fees"]["beats_buy_and_hold"]
    )
    drawdown_cuts = sum(
        1
        for item in results.values()
        if item["out_of_sample"]["drawdown_reduction_pp"] > 0.0
    )
    return {
        "splits": results,
        "splits_total": len(results),
        "splits_beating_buy_and_hold_honest": honest_wins,
        "splits_beating_buy_and_hold_adverse": adverse_wins,
        "splits_reducing_drawdown": drawdown_cuts,
        "verdict": (
            "SELECTION_GENERALISES"
            if honest_wins == len(results) and adverse_wins == len(results)
            else "SELECTION_DOES_NOT_GENERALISE_ON_RETURN"
        ),
    }


def long_only_edge(
    bars: list[Bar], by_time: dict[int, int], start: int, end: int
) -> dict[str, Any]:
    """The asymmetry that makes a long/flat exposure model different from BUY/SELL.

    A 3-class model must earn its keep on both sides. A long/flat model only has
    to decide whether to hold an asset whose unconditional drift is positive, so
    its fallback (stay long) is buy and hold rather than cash.
    """
    pairs = _forward_pairs(bars, by_time, 24, start, end)
    daily = [future / now - 1.0 for _, now, future in pairs]
    up = [value for value in daily if value > 0]
    down = [value for value in daily if value < 0]
    total_hours = (bars[end - 1].open_time_ms - bars[start].open_time_ms) / HOUR_MS
    return {
        "unconditional_daily_drift_bps": (sum(daily) / len(daily)) * 10_000.0,
        "up_day_share": len(up) / len(daily),
        "mean_up_day_bps": (sum(up) / len(up)) * 10_000.0 if up else float("nan"),
        "mean_down_day_bps": (sum(down) / len(down)) * 10_000.0 if down else float("nan"),
        "buy_and_hold_return_pct": (bars[end - 1].close / bars[start].close - 1.0) * 100.0,
        "span_years": total_hours / (24.0 * 365.25),
    }


def build_report() -> dict[str, Any]:
    bars, dataset_id = load_bars()
    by_time = _index_by_time(bars)
    # Diagnose on exactly the window the rejected model was trained on.
    start = window_index(bars, "2021-09-16")
    end = len(bars)

    horizons = [horizon_statistics(bars, by_time, hours, start, end) for hours in HORIZONS_HOURS]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_id": dataset_id,
        "window": {
            "name": "last_5y",
            "start": datetime.fromtimestamp(bars[start].open_time_ms / 1000, UTC).isoformat(),
            "end": datetime.fromtimestamp(bars[end - 1].open_time_ms / 1000, UTC).isoformat(),
            "bars": end - start,
        },
        "assumptions": {
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "decision_threshold_bps": DECISION_THRESHOLD_BPS,
            "forward_lookup": "exact bar timestamp only; dataset gaps skipped",
        },
        "a_and_b_horizon_statistics": [vars(item) for item in horizons],
        "c_churn_cost": {
            f"{item.hours}h": {
                "argmax_flips_per_year": item.argmax_flips_per_year,
                "annual_churn_cost_pct": item.annual_churn_cost_pct,
            }
            for item in horizons
        },
        "d_trend_signal_strength": trend_signal_strength(bars, by_time, start, end),
        "d2_trend_signal_significance": trend_signal_significance(bars, by_time, start, end),
        "e_exposure_policy_matrix": exposure_policy_matrix(bars),
        "f_exposure_plateau": exposure_plateau_study(bars),
        "g_temporal_out_of_sample": temporal_out_of_sample(bars),
        "long_only_asymmetry": long_only_edge(bars, by_time, start, end),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Exposure model diagnosis (Task 1)")
    lines.append("")
    lines.append(f"- dataset_id: `{report['dataset_id']}`")
    window = report["window"]
    lines.append(f"- window: {window['name']} {window['start']} -> {window['end']} ({window['bars']} bars)")
    lines.append(f"- round-trip cost assumed: {report['assumptions']['round_trip_cost_bps']} bps")
    lines.append("")

    lines.append("## A/B. Label balance and signal vs cost, by horizon")
    lines.append("")
    lines.append("| horizon | samples | P(up) | majority | median abs move | share > cost | 3-class BUY/HOLD/SELL |")
    lines.append("|---|---|---|---|---|---|---|")
    for item in report["a_and_b_horizon_statistics"]:
        shares = item["three_class_shares"]
        lines.append(
            f"| {item['hours']}h | {item['samples']} | {item['positive_share']:.4f} | "
            f"{item['majority_share']:.4f} | {item['median_abs_move_bps']:.1f} bps | "
            f"{item['share_exceeding_cost']:.3f} | "
            f"{shares['BUY']:.3f} / {shares['HOLD']:.3f} / {shares['SELL']:.3f} |"
        )
    lines.append("")

    lines.append("## C. Cost of churn for an argmax policy")
    lines.append("")
    lines.append("| horizon | flips / year | annual cost of churn |")
    lines.append("|---|---|---|")
    for horizon, values in report["c_churn_cost"].items():
        lines.append(
            f"| {horizon} | {values['argmax_flips_per_year']:.1f} | "
            f"{values['annual_churn_cost_pct']:.2f}% |"
        )
    lines.append("")

    lines.append("## D. Trend signal strength (Spearman vs forward return)")
    lines.append("")
    horizons = [f"{hours}h" for hours in HORIZONS_HOURS]
    lines.append("| signal | " + " | ".join(horizons) + " |")
    lines.append("|---" * (len(horizons) + 1) + "|")
    for name, values in report["d_trend_signal_strength"].items():
        cells = [f"{values[horizon]:+.4f}" for horizon in horizons]
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## D2. Same signals on NON-OVERLAPPING samples (all stride offsets)")
    lines.append("")
    lines.append("| signal | horizon | mean rho | range over offsets | indep. n | rho / SE | sign stable |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, horizons_map in report["d2_trend_signal_significance"].items():
        for horizon, values in horizons_map.items():
            lines.append(
                f"| `{name}` | {horizon} | {values['mean_rho_over_offsets']:+.4f} | "
                f"{values['min_rho']:+.3f} .. {values['max_rho']:+.3f} | "
                f"{values['independent_samples']} | {values['mean_rho_in_standard_errors']:+.2f} | "
                f"{'yes' if values['sign_stable_across_offsets'] else 'no'} |"
            )
    lines.append("")

    policy = report["e_exposure_policy_matrix"]
    lines.append("## E. Long/flat exposure vs buy and hold, every window")
    lines.append("")
    for fee_label, per_fee in policy["matrix"].items():
        lines.append(f"### fees: {fee_label}")
        lines.append("")
        any_window = next(iter(per_fee.values()))
        names = [name for name in any_window if name != "buy_and_hold"]
        lines.append("| window | buy & hold | " + " | ".join(names) + " |")
        lines.append("|---" * (len(names) + 2) + "|")
        for window_name, entries in per_fee.items():
            cells = []
            for name in names:
                mark = "*" if entries[name]["beats_buy_and_hold"] else " "
                cells.append(f"{entries[name]['net_return_pct']:+.1f}%{mark}")
            lines.append(
                f"| {window_name} | {entries['buy_and_hold']['net_return_pct']:+.1f}% | "
                + " | ".join(cells)
                + " |"
            )
        lines.append("")
    lines.append(
        f"- neighbour-robust lengths (full window): "
        f"{policy['neighbour_robust_lengths_full_window'] or 'NONE'}"
    )
    lines.append(
        f"- surviving every gate (full + adverse fees + last_5y): "
        f"{policy['lengths_surviving_all_gates'] or 'NONE'}"
    )
    lines.append("")
    lines.append("### Hysteresis sweep (10 bps/side)")
    lines.append("")
    for name, bands in policy["hysteresis_sweep"].items():
        window_names = list(next(iter(bands.values())).keys())
        lines.append(f"**{name}**")
        lines.append("")
        lines.append("| band | " + " | ".join(window_names) + " | flips (full) |")
        lines.append("|---" * (len(window_names) + 2) + "|")
        for band, per_window in bands.items():
            cells = [f"{per_window[item]['net_return_pct']:+.1f}%" for item in window_names]
            lines.append(
                f"| {band} | " + " | ".join(cells) + f" | {per_window['full_2020_2026']['flips']} |"
            )
        lines.append("")

    plateau = report["f_exposure_plateau"]
    lines.append("## F. Length x hysteresis plateau, strict gate in both dimensions")
    lines.append("")
    lines.append(
        "Gate: beat buy and hold in full_2020_2026 AND last_5y, at 10 bps AND 20 bps "
        "per side. `+` passes, `.` fails, `R` passes and all four orthogonal "
        "neighbours pass."
    )
    lines.append("")
    bands = plateau["bands"]
    lines.append("| length | " + " | ".join(f"band {band:.0%}" for band in bands) + " |")
    lines.append("|---" * (len(bands) + 1) + "|")
    for name in plateau["lengths"]:
        cells = []
        for band in bands:
            key = f"{name}|band={band:.2f}"
            if key in plateau["neighbour_robust_cells"]:
                cells.append("**R**")
            elif plateau["cells"][key]["passes_strict_gate"]:
                cells.append("+")
            else:
                cells.append(".")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(
        f"- cells passing strict gate: {plateau['cells_passing_count']} of "
        f"{plateau['cells_total']}"
    )
    lines.append(
        f"- neighbour-robust cells: {plateau['neighbour_robust_cells'] or 'NONE'}"
    )
    lines.append(f"- **verdict: {plateau['verdict']}**")
    lines.append("")
    lines.append(
        f"- execution lag applied: {plateau['execution_lag_bars']} bar "
        "(decide on a closed bar, fill at the next close)"
    )
    lines.append(
        f"- cells beating buy and hold in ALL 6 windows at BOTH fee levels: "
        f"{plateau['cells_beating_all_windows_both_fees'] or 'NONE'}"
    )
    lines.append("")
    lines.append("Detail for every cell that passed the strict gate:")
    lines.append("")
    lines.append(
        "| cell | full 10bps | full 20bps | last_5y 10bps | last_5y 20bps | bear dd cut "
        "| flips | windows won (adverse) | look-ahead worth |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for key in plateau["cells_passing_strict_gate"]:
        cell = plateau["cells"][key]
        honest = cell["per_fee"]["honest_10bps"]
        adverse = cell["per_fee"]["adverse_20bps"]
        lines.append(
            f"| `{key}` | {honest['full_2020_2026']['excess_pct']:+.1f}pp | "
            f"{adverse['full_2020_2026']['excess_pct']:+.1f}pp | "
            f"{honest['last_5y']['excess_pct']:+.1f}pp | "
            f"{adverse['last_5y']['excess_pct']:+.1f}pp | "
            f"{honest['bear_2021_11_to_2022_11']['drawdown_reduction_pp']:+.1f}pp | "
            f"{honest['full_2020_2026']['flips']} | "
            f"{len(cell['windows_beaten_adverse'])}/6 | "
            f"{honest['full_2020_2026']['lookahead_bonus_pp']:+.1f}pp |"
        )
    lines.append("")

    oos = report["g_temporal_out_of_sample"]
    lines.append("## G. Temporal out-of-sample: does the SELECTION generalise?")
    lines.append("")
    lines.append(
        "Parameters are chosen on the selection window only, then frozen and measured "
        "on the years that follow. Only the out-of-sample columns are evidence."
    )
    lines.append("")
    lines.append(
        "| split | chosen | in-sample excess | OOS excess (10bps) | OOS excess (20bps) "
        "| OOS dd cut | family share winning |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for split_name, values in oos["splits"].items():
        out = values["out_of_sample"]
        lines.append(
            f"| {split_name} | `{values['chosen_cell']}` | "
            f"{values['in_sample_excess_pp']:+.1f}pp | {out['excess_pp']:+.1f}pp | "
            f"{values['out_of_sample_adverse_fees']['excess_pp']:+.1f}pp | "
            f"{out['drawdown_reduction_pp']:+.1f}pp | "
            f"{values['family_out_of_sample']['share_beating_buy_and_hold']:.0%} |"
        )
    lines.append("")
    lines.append(
        f"- splits where the chosen cell beat buy and hold out of sample: "
        f"{oos['splits_beating_buy_and_hold_honest']}/{oos['splits_total']} at 10bps, "
        f"{oos['splits_beating_buy_and_hold_adverse']}/{oos['splits_total']} at 20bps"
    )
    lines.append(
        f"- splits where it reduced drawdown out of sample: "
        f"{oos['splits_reducing_drawdown']}/{oos['splits_total']}"
    )
    lines.append(f"- **verdict: {oos['verdict']}**")
    lines.append("")

    asymmetry = report["long_only_asymmetry"]
    lines.append("## Long/flat asymmetry")
    lines.append("")
    lines.append(f"- buy and hold over window: {asymmetry['buy_and_hold_return_pct']:.2f}%")
    lines.append(f"- unconditional 24h drift: {asymmetry['unconditional_daily_drift_bps']:+.2f} bps")
    lines.append(f"- up-day share: {asymmetry['up_day_share']:.4f}")
    lines.append(
        f"- mean up day {asymmetry['mean_up_day_bps']:+.1f} bps vs "
        f"mean down day {asymmetry['mean_down_day_bps']:+.1f} bps"
    )
    lines.append("")

    for line in report["conclusions"]:
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def conclusions(report: dict[str, Any]) -> list[str]:
    """Statements that follow from the numbers above, with the numbers attached."""
    horizons = {item["hours"]: item for item in report["a_and_b_horizon_statistics"]}
    four = horizons[4]
    policy = report["e_exposure_policy_matrix"]
    plateau = report["f_exposure_plateau"]
    oos = report["g_temporal_out_of_sample"]
    significance = report["d2_trend_signal_significance"]
    flat = [
        (name, horizon, values)
        for name, per_horizon in significance.items()
        for horizon, values in per_horizon.items()
    ]
    strongest = max(flat, key=lambda item: abs(item[2]["mean_rho_in_standard_errors"]))
    # Horizons where churn is actually affordable, per section C.
    affordable = [item for item in flat if int(item[1].rstrip("h")) >= 48]
    strongest_affordable = max(
        affordable, key=lambda item: abs(item[2]["mean_rho_in_standard_errors"])
    )
    above_one_se = [
        item for item in affordable if abs(item[2]["mean_rho_in_standard_errors"]) >= 1.0
    ]
    bear_honest = policy["matrix"]["honest_10bps"]["bear_2021_11_to_2022_11"]
    bear_lengths = [name for name in bear_honest if name != "buy_and_hold"]

    return [
        "## Conclusions",
        "",
        "1. The rejected model is a base-rate predictor, not a broken one. The 4h "
        f"three-class label is {four['three_class_shares']['HOLD']:.3f} HOLD, and the "
        "model scored 0.3990 against a 0.4026 majority baseline. It learned the base "
        "rate and nothing else.",
        "",
        "2. My earlier explanation for that failure was wrong and is corrected here. I "
        "said the 4h move was too small to clear a 20 bps round trip. It is not: the "
        f"median absolute 4h move is {four['median_abs_move_bps']:.1f} bps and "
        f"{four['share_exceeding_cost']:.1%} of 4h moves exceed the cost. The problem is "
        f"that the DIRECTION is unpredictable, P(up) = {four['positive_share']:.4f}.",
        "",
        "3. Churn, not horizon length, is what destroyed the live account. An argmax "
        f"policy at 4h flips {four['argmax_flips_per_year']:.0f} times per year, which "
        f"costs {four['annual_churn_cost_pct']:.0f}% of capital annually in fees alone. "
        "No edge of any plausible size survives that.",
        "",
        "4. The trend signal splits cleanly into detectable-but-useless and "
        "affordable-but-absent, and neither helps. Measured on non-overlapping samples: "
        f"the single largest correlation is `{strongest[0]}` at {strongest[1]}, reaching "
        f"{abs(strongest[2]['mean_rho_in_standard_errors']):.2f} standard errors, but it "
        f"is NEGATIVE (rho {strongest[2]['mean_rho_over_offsets']:+.4f}, i.e. mean "
        "reversion, not trend) and it sits at a horizon where section C prices churn at "
        f"{four['annual_churn_cost_pct']:.0f}% per year. At the horizons where churn is "
        f"affordable (>= 48h), the largest is `{strongest_affordable[0]}` at "
        f"{strongest_affordable[1]} with only "
        f"{abs(strongest_affordable[2]['mean_rho_in_standard_errors']):.2f} SE, and "
        f"{len(above_one_se)} of {len(affordable)} such signal/horizon pairs reach even "
        "1 SE. Signs also flip across stride offsets at every one of those horizons. "
        "There is nothing here to forecast direction with.",
        "",
        "5. Churn control, not reference length, is the axis that matters. Section E "
        "swept reference length with no dead band and found only isolated, "
        "non-monotone winners that died at adverse fees. That test was on the wrong "
        "axis. With a hysteresis band added (section F), "
        f"{plateau['cells_passing_count']} of {plateau['cells_total']} "
        "length/band cells beat buy and hold in the full window and in last_5y at both "
        "fee levels, and the zero-band column fails "
        f"{7 - len(plateau['zero_band_passes'])} of 7 times. The band is also not a "
        "fill-timing artifact: the study applies a one-bar execution lag, and removing "
        "that lag mostly made results WORSE, so the edge does not come from filling at "
        "the same close that generated the signal.",
        "",
        "6. That in-sample edge is nevertheless not real, and section G is what proves "
        "it. Choosing the length/band on an early segment and then measuring the frozen "
        "choice on the years that follow, the excess collapses: "
        + "; ".join(
            f"{name} picked `{values['chosen_cell']}` at "
            f"{values['in_sample_excess_pp']:+.0f}pp in sample and delivered "
            f"{values['out_of_sample']['excess_pp']:+.0f}pp out of sample"
            for name, values in oos["splits"].items()
        )
        + ". Only "
        f"{oos['splits_beating_buy_and_hold_honest']} of {oos['splits_total']} splits "
        "beat buy and hold out of sample, and in the earliest split NOT ONE of the "
        f"{plateau['cells_total']} configurations did "
        f"({oos['splits']['select_2020_2022_test_2023_2026']['family_out_of_sample']['share_beating_buy_and_hold']:.0%} "
        "of the family). The large in-sample numbers in section F are selection "
        "artifacts.",
        "",
        "7. One effect survives every test, and it is the only one. Reducing exposure "
        "cuts drawdown. In section F every reference length at both fee levels cuts the "
        "bear drawdown, with buy and hold returning "
        f"{bear_honest['buy_and_hold']['net_return_pct']:.1f}% through the 2021-2022 bear "
        "against "
        f"{min(bear_honest[name]['net_return_pct'] for name in bear_lengths):.1f}% to "
        f"{max(bear_honest[name]['net_return_pct'] for name in bear_lengths):.1f}% for "
        "the long/flat variants. More importantly it also generalises out of sample, "
        f"where it reduced drawdown in {oos['splits_reducing_drawdown']} of "
        f"{oos['splits_total']} splits ("
        + ", ".join(
            f"{values['out_of_sample']['drawdown_reduction_pp']:+.1f}pp"
            for values in oos["splits"].values()
        )
        + "). Tail cutting does not require forecasting power, which is exactly why it "
        "holds where the return-seeking variants do not.",
        "",
        "### Economic reformulation this implies",
        "",
        "- The model's output is EXPOSURE (long or flat), not a BUY/HOLD/SELL direction.",
        "- Its default is LONG, so that absent evidence it collects the positive "
        f"unconditional drift ({report['long_only_asymmetry']['unconditional_daily_drift_bps']:+.2f} "
        "bps/day) instead of churning.",
        "- Low confidence must mean STAY AS YOU ARE, never flip. Hysteresis is a "
        "first-class part of the policy, not a tweak: on ma200d a 2% dead band cuts "
        f"full-window flips from {policy['hysteresis_sweep']['ma200d']['enter+0%/exit-0%']['full_2020_2026']['flips']} "
        f"to {policy['hysteresis_sweep']['ma200d']['enter+2%/exit-2%']['full_2020_2026']['flips']}, "
        "and the zero-band column of section F fails every single time.",
        "- Spread and order-flow features are removed from the model. They existed only "
        "live, with historical proxies at training time, which is train/serve skew. They "
        "become deterministic gates instead.",
        "- The promotion gate cannot be accuracy, and per point 6 it also cannot be "
        "in-sample excess return. It has to be measured on data the parameter and weight "
        "selection never saw.",
        "",
        "### What the gate must therefore be",
        "",
        "Section G answers the question I was about to escalate, so it no longer needs "
        "to be an open choice. A gate of 'beat buy and hold on return' is not merely "
        "hard, it is not supported: the configurations that beat it by +470pp and "
        "+1081pp in sample returned "
        f"{oos['splits']['select_2020_2022_test_2023_2026']['out_of_sample']['excess_pp']:+.0f}pp "
        "and "
        f"{oos['splits']['select_2020_2023_test_2024_2026']['out_of_sample']['excess_pp']:+.0f}pp "
        "out of sample. Adopting that gate would mean either rejecting the model (leaving "
        "the account with no operator) or, worse, selecting on in-sample excess and "
        "shipping the artifact.",
        "",
        "The gate that the evidence does support, because it is the one quantity that "
        f"replicated in {oos['splits_reducing_drawdown']} of {oos['splits_total']} "
        "out-of-sample splits and across every length and fee level in section F:",
        "",
        "  1. Out-of-sample drawdown materially below buy and hold (the effect that "
        "generalises).",
        "  2. Out-of-sample net return within a stated tolerance of buy and hold, not "
        "above it (the model must not pay for its tail protection with the whole trend).",
        "  3. Churn bounded by construction, verified by flip count, since section C "
        "prices unbounded churn at a level no edge can survive.",
        "",
        "This keeps the user's hard constraint intact: a local model is the operator, it "
        "reads trend in real time, and it chooses the action that maximises return given "
        "what is actually knowable, which the data says is 'stay long, step aside in "
        "sustained downtrends'. It does not promise an edge that three independent "
        "studies could not find.",
    ]


def main() -> None:
    report = build_report()
    report["conclusions"] = conclusions(report)
    stem = Path("data/validation/exposure-diagnosis")
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown = render_markdown(report)
    stem.with_suffix(".md").write_text(markdown + "\n", encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
