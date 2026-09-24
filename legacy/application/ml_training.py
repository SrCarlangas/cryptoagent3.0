"""Causal batch training and temporal evaluation for the local softmax model."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from btc_decision_agent.application.local_ml import (
    CLASSES,
    FEATURE_NAMES,
    Direction,
    LocalSoftmaxModel,
    net_four_hour_label,
)

from btc_decision_agent.adapters.backfill import HistoricalDataset

D = Decimal
HOUR_MS = 3_600_000
FOUR_HOURS = 4
THIRTY_DAYS = 24 * 30
_DEFAULT_COST_BPS = D("20")
_DEFAULT_THRESHOLD_BPS = D("10")


@dataclass(frozen=True)
class TrainingExample:
    at_ms: int
    label_at_ms: int
    features: tuple[float, ...]
    label: Direction
    net_opportunity_bps: Decimal


def _subtract_calendar_years(moment: datetime, years: int) -> datetime:
    try:
        return moment.replace(year=moment.year - years)
    except ValueError:
        return moment.replace(year=moment.year - years, day=28)


def select_exact_five_years(rows: Sequence[dict[str, Any]]) -> tuple[tuple[dict[str, Any], ...], datetime, datetime]:
    if not rows:
        raise ValueError("historical dataset is empty")
    ordered = sorted(rows, key=lambda row: int(row["open_time"]))
    end = datetime.fromtimestamp((int(ordered[-1]["open_time"]) + HOUR_MS) / 1000, tz=UTC)
    start = _subtract_calendar_years(end, 5)
    selected = tuple(
        row
        for row in ordered
        if int(row["open_time"]) >= int(start.timestamp() * 1000)
        and int(row["open_time"]) + HOUR_MS <= int(end.timestamp() * 1000)
    )
    if not selected:
        raise ValueError("no rows in five-year window")
    first = datetime.fromtimestamp(int(selected[0]["open_time"]) / 1000, tz=UTC)
    if first != start:
        raise ValueError(f"dataset cannot provide exact five-year boundary: expected {start}, got {first}")
    return selected, start, end


def _segments(rows: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    previous: int | None = None
    for row in rows:
        timestamp = int(row["open_time"])
        if previous is not None and timestamp - previous != HOUR_MS:
            segments.append(current)
            current = []
        current.append(row)
        previous = timestamp
    if current:
        segments.append(current)
    return segments


def _return_bps(current: Decimal, historic: Decimal) -> Decimal:
    return (current / historic - D("1")) * D("10000")


def _confidence(score: Decimal) -> Decimal:
    clipped = max(-4.0, min(4.0, float(score)))
    return D(str(1.0 / (1.0 + math.exp(-1.8 * clipped))))


def _historical_features(segment: Sequence[dict[str, Any]], index: int, cost_bps: Decimal) -> tuple[float, ...]:
    row = segment[index]
    close = D(str(row["close"]))
    open_price = D(str(row["open"]))
    high = D(str(row["high"]))
    low = D(str(row["low"]))
    intrabar = _return_bps(close, open_price)
    returns = {
        "4h": _return_bps(close, D(str(segment[index - 4]["close"]))),
        "1d": _return_bps(close, D(str(segment[index - 24]["close"]))),
        "7d": _return_bps(close, D(str(segment[index - 168]["close"]))),
        "30d": _return_bps(close, D(str(segment[index - 720]["close"]))),
    }
    structural_return = (
        returns["4h"] * D("0.25")
        + returns["1d"] * D("0.30")
        + returns["7d"] * D("0.30")
        + returns["30d"] * D("0.15")
    )
    tactical_return = intrabar * D("0.70") + returns["4h"] * D("0.30")
    structural_score = (
        max(D("-2"), min(D("2"), returns["4h"] / D("150"))) * D("0.25")
        + max(D("-2"), min(D("2"), returns["1d"] / D("300"))) * D("0.30")
        + max(D("-2"), min(D("2"), returns["7d"] / D("700"))) * D("0.30")
        + max(D("-2"), min(D("2"), returns["30d"] / D("1500"))) * D("0.15")
    )
    tactical_score = (
        max(D("-2"), min(D("2"), intrabar / D("50"))) * D("0.70")
        + max(D("-2"), min(D("2"), returns["4h"] / D("150"))) * D("0.30")
    )
    range_value = high - low
    flow_proxy = max(D("-1"), min(D("1"), (close - open_price) / range_value)) if range_value > 0 else D("0")
    values = (
        intrabar,
        intrabar,
        returns["4h"],
        returns["1d"],
        returns["7d"],
        returns["30d"],
        _confidence(structural_score),
        _confidence(tactical_score + flow_proxy * D("0.20")),
        structural_return,
        tactical_return,
        tactical_return - cost_bps - D("10"),
        flow_proxy,
        D("0"),
        D("1"),
        D("1"),
        D("3600"),
        D("0"),
        D("0"),
        D("0"),
        D("0"),
        D("0"),
        D("0.02"),
    )
    if len(values) != len(FEATURE_NAMES):
        raise AssertionError("historical feature schema mismatch")
    return tuple(float(value) for value in values)


def build_examples(
    rows: Sequence[dict[str, Any]],
    *,
    round_trip_cost_bps: Decimal,
    decision_threshold_bps: Decimal,
) -> tuple[list[TrainingExample], dict[str, int]]:
    examples: list[TrainingExample] = []
    segment_count = 0
    skipped_short = 0
    for segment in _segments(rows):
        segment_count += 1
        if len(segment) <= THIRTY_DAYS + FOUR_HOURS:
            skipped_short += len(segment)
            continue
        for index in range(THIRTY_DAYS, len(segment) - FOUR_HOURS):
            entry = D(str(segment[index]["close"]))
            future = D(str(segment[index + FOUR_HOURS]["close"]))
            label, net_bps = net_four_hour_label(
                entry,
                future,
                round_trip_cost_bps=round_trip_cost_bps,
                decision_threshold_bps=decision_threshold_bps,
            )
            examples.append(
                TrainingExample(
                    at_ms=int(segment[index]["open_time"]) + HOUR_MS,
                    label_at_ms=int(segment[index + FOUR_HOURS]["open_time"]) + HOUR_MS,
                    features=_historical_features(segment, index, round_trip_cost_bps),
                    label=label,
                    net_opportunity_bps=net_bps,
                )
            )
    return examples, {
        "contiguous_segments": segment_count,
        "rows_skipped_in_short_segments": skipped_short,
    }


def _metrics(model: LocalSoftmaxModel, examples: Sequence[TrainingExample]) -> dict[str, Any]:
    confusion = {actual.value: {predicted.value: 0 for predicted in CLASSES} for actual in CLASSES}
    total_loss = 0.0
    correct = 0
    for example in examples:
        prediction = model.predict(example.features)
        confusion[example.label.value][prediction.direction.value] += 1
        correct += int(prediction.direction == example.label)
        total_loss -= math.log(max(prediction.probabilities[example.label.value], 1e-15))
    per_class: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    for direction in CLASSES:
        name = direction.value
        true_positive = confusion[name][name]
        false_positive = sum(confusion[actual.value][name] for actual in CLASSES if actual != direction)
        false_negative = sum(confusion[name][predicted.value] for predicted in CLASSES if predicted != direction)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        per_class[name] = {"precision": precision, "recall": recall, "f1": f1, "support": sum(confusion[name].values())}
    count = len(examples)
    return {
        "examples": count,
        "accuracy": correct / count if count else 0.0,
        "macro_f1": sum(f1_values) / len(f1_values),
        "log_loss": total_loss / count if count else 0.0,
        "confusion_matrix": confusion,
        "per_class": per_class,
    }


def purged_temporal_split(
    examples: Sequence[TrainingExample], holdout_fraction: float
) -> tuple[list[TrainingExample], list[TrainingExample], int]:
    if not 0.05 <= holdout_fraction <= 0.5:
        raise ValueError("holdout_fraction must be between 0.05 and 0.5")
    split = int(len(examples) * (1.0 - holdout_fraction))
    holdout = list(examples[split:])
    if not holdout:
        raise ValueError("temporal holdout is empty")
    candidates = examples[:split]
    train = [example for example in candidates if example.label_at_ms < holdout[0].at_ms]
    return train, holdout, len(candidates) - len(train)


def train_from_dataset(
    dataset_directory: str | Path,
    model_path: str | Path,
    report_json_path: str | Path,
    report_md_path: str | Path,
    *,
    round_trip_cost_bps: Decimal = _DEFAULT_COST_BPS,
    decision_threshold_bps: Decimal = _DEFAULT_THRESHOLD_BPS,
    holdout_fraction: float = 0.20,
    learning_rate: float = 0.0003,
    l2: float = 0.0001,
) -> dict[str, Any]:
    if not 0.05 <= holdout_fraction <= 0.5:
        raise ValueError("holdout_fraction must be between 0.05 and 0.5")
    manifest, all_rows = HistoricalDataset(dataset_directory).load()
    rows, window_start, window_end = select_exact_five_years(all_rows)
    examples, segment_stats = build_examples(
        rows,
        round_trip_cost_bps=round_trip_cost_bps,
        decision_threshold_bps=decision_threshold_bps,
    )
    if len(examples) < 100:
        raise ValueError("insufficient causal examples")
    train_examples, holdout_examples, purged_examples = purged_temporal_split(
        examples, holdout_fraction
    )
    model = LocalSoftmaxModel(learning_rate=learning_rate, l2=l2)
    train_counts = Counter(example.label.value for example in train_examples)
    class_weights = {
        name: len(train_examples) / (len(CLASSES) * count)
        for name, count in train_counts.items()
    }
    cumulative_loss = 0.0
    for example in train_examples:
        cumulative_loss += model.train_one(
            example.features,
            example.label,
            sample_weight=class_weights[example.label.value],
        )
    holdout_counts = Counter(example.label.value for example in holdout_examples)
    majority_accuracy = max(holdout_counts.values()) / len(holdout_examples)
    holdout_metrics = _metrics(model, holdout_examples)
    uniform_log_loss = math.log(len(CLASSES))
    promoted = (
        holdout_metrics["accuracy"] > majority_accuracy
        and holdout_metrics["log_loss"] < uniform_log_loss
    )
    report: dict[str, Any] = {
        "schema_version": "local-softmax-training-report/1.0.0",
        "created_at": datetime.now(tz=UTC).isoformat(),
        "model_version": model.model_version,
        "feature_schema_version": "evidence-multisource/1.0.0",
        "dataset": {
            "dataset_id": manifest.dataset_id,
            "content_hash": manifest.content_hash,
            "source_rows": manifest.row_count,
            "selected_rows": len(rows),
            "window_start": window_start.isoformat(),
            "window_end_exclusive": window_end.isoformat(),
            "window_years": 5,
            "interval": manifest.interval,
            "gap_count_manifest": manifest.gap_count,
            **segment_stats,
        },
        "label": {
            "horizon_hours": 4,
            "round_trip_cost_bps": format(round_trip_cost_bps, "f"),
            "decision_threshold_bps": format(decision_threshold_bps, "f"),
            "definition": "BUY if 4h return minus costs reaches threshold; SELL if inverse return minus costs reaches threshold; otherwise HOLD",
        },
        "split": {
            "type": "temporal_no_shuffle",
            "train_examples": len(train_examples),
            "purged_train_examples": purged_examples,
            "purge_rule": "training label_at must be strictly before holdout_start",
            "holdout_examples": len(holdout_examples),
            "train_end": datetime.fromtimestamp(train_examples[-1].at_ms / 1000, tz=UTC).isoformat(),
            "holdout_start": datetime.fromtimestamp(holdout_examples[0].at_ms / 1000, tz=UTC).isoformat(),
            "train_class_counts": dict(sorted(train_counts.items())),
            "holdout_class_counts": dict(sorted(holdout_counts.items())),
        },
        "optimization": {
            "algorithm": "causal_online_sgd_single_pass",
            "learning_rate": learning_rate,
            "l2": l2,
            "class_weighting": "inverse_frequency_from_training_partition",
            "class_weights": dict(sorted(class_weights.items())),
            "mean_prequential_train_log_loss": cumulative_loss / len(train_examples),
        },
        "holdout": holdout_metrics,
        "baseline": {
            "majority_class_accuracy": majority_accuracy,
            "uniform_log_loss": uniform_log_loss,
        },
        "promotion": {
            "status": "PROMOTED" if promoted else "REJECTED",
            "criteria": "accuracy > majority baseline and log_loss < uniform baseline",
        },
        "limitations": [
            "The 1h dataset has no historical BBO spread or aggTrade order flow; spread is missing and flow uses a signed-candle proxy.",
            "The 1h dataset cannot reproduce 5m/30m runtime features; both use the completed 1h candle return proxy.",
            "Historical portfolio position, PnL, stop distance and breaker state are unavailable and use neutral values.",
            "This is multi-source tabular evidence, not visual multimodal learning, and holdout metrics do not establish live trading profitability.",
        ],
    }
    model.metadata = {
        "trained_at": report["created_at"],
        "dataset_id": manifest.dataset_id,
        "training_window_start": window_start.isoformat(),
        "training_window_end_exclusive": window_end.isoformat(),
        "holdout_metrics": report["holdout"],
        "promotion_status": report["promotion"]["status"],
        "promotion_criteria": report["promotion"]["criteria"],
        "historical_modalities": "1h OHLCV proxies; no BBO/aggTrade/portfolio history",
    }
    model.save(model_path)
    json_target = Path(report_json_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    holdout = report["holdout"]
    markdown = f"""# Local softmax training report

- Model: `{model.model_version}`
- Dataset: `{manifest.dataset_id}`
- Exact source window: `{window_start.isoformat()}` to `{window_end.isoformat()}` (end exclusive), **5 calendar years**
- Temporal split: {len(train_examples):,} train / {len(holdout_examples):,} holdout, no shuffle; {purged_examples} boundary examples purged
- Promotion: **{report['promotion']['status']}** ({report['promotion']['criteria']})
- Labels: 4h opportunity net of {round_trip_cost_bps} bps round-trip costs; HOLD band {decision_threshold_bps} bps

## Holdout metrics

- Accuracy: {holdout['accuracy']:.6f}
- Macro F1: {holdout['macro_f1']:.6f}
- Log loss: {holdout['log_loss']:.6f}
- Majority baseline accuracy: {majority_accuracy:.6f}
- Uniform baseline log loss: {uniform_log_loss:.6f}

## Limitations

""" + "\n".join(f"- {item}" for item in report["limitations"]) + "\n"
    md_target = Path(report_md_path)
    md_target.parent.mkdir(parents=True, exist_ok=True)
    md_target.write_text(markdown, encoding="utf-8")
    return report


__all__ = [
    "TrainingExample",
    "build_examples",
    "purged_temporal_split",
    "select_exact_five_years",
    "train_from_dataset",
]
