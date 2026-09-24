"""Local, dependency-free online softmax direction model.

The model consumes multi-source numeric evidence; it is not a visual or multimodal
model. Persistence is a single atomic JSON document and online outcomes are also
appended to an audit-friendly JSONL experience file.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Protocol

D = Decimal
_ZERO = D("0")
_DEFAULT_COST_BPS = D("20")
_DEFAULT_THRESHOLD_BPS = D("10")
MODEL_SCHEMA_VERSION = "local-softmax/1.0.0"
FEATURE_SCHEMA_VERSION = "evidence-multisource/1.0.0"
DEFAULT_MODEL_VERSION = "LOCAL-SOFTMAX-BTC-1H-4H-V1"


class Direction(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


CLASSES: tuple[Direction, ...] = (Direction.BUY, Direction.HOLD, Direction.SELL)
FEATURE_NAMES: tuple[str, ...] = (
    "return_5m_bps",
    "return_30m_bps",
    "return_4h_bps",
    "return_1d_bps",
    "return_7d_bps",
    "return_30d_bps",
    "structural_confidence",
    "tactical_confidence",
    "structural_return_bps",
    "tactical_return_bps",
    "expected_edge_bps",
    "flow_imbalance",
    "spread_bps",
    "spread_missing",
    "coverage",
    "data_age_seconds",
    "position_long",
    "unrealized_pnl_bps",
    "drawdown_fraction",
    "daily_pnl_fraction",
    "stop_distance_bps",
    "risk_per_trade_fraction",
)


class SnapshotLike(Protocol):
    @property
    def price(self) -> Decimal: ...

    @property
    def horizons(self) -> Mapping[str, Decimal]: ...

    @property
    def structural_confidence(self) -> Decimal: ...

    @property
    def tactical_confidence(self) -> Decimal: ...

    @property
    def structural_return_bps(self) -> Decimal: ...

    @property
    def tactical_return_bps(self) -> Decimal: ...

    @property
    def expected_edge_bps(self) -> Decimal: ...

    @property
    def flow_imbalance(self) -> Decimal: ...

    @property
    def spread_bps(self) -> Decimal | None: ...

    @property
    def coverage(self) -> Decimal: ...

    @property
    def data_age_ms(self) -> int: ...

    @property
    def at(self) -> datetime: ...

    @property
    def event_id(self) -> str: ...


@dataclass(frozen=True)
class FeatureContext:
    position_long: bool = False
    entry_price: Decimal | None = None
    peak_equity: Decimal | None = None
    day_start_equity: Decimal | None = None
    equity: Decimal | None = None
    active_stop_price: Decimal | None = None
    risk_per_trade_fraction: Decimal = _ZERO


@dataclass(frozen=True)
class DirectionPrediction:
    direction: Direction
    probabilities: dict[str, float]
    confidence: float
    model_version: str
    feature_schema_version: str = FEATURE_SCHEMA_VERSION


@dataclass
class OnlineNormalizer:
    """Causal Welford normalizer; state is updated only by training observations."""

    count: int = 0
    means: list[float] = field(default_factory=lambda: [0.0] * len(FEATURE_NAMES))
    m2: list[float] = field(default_factory=lambda: [0.0] * len(FEATURE_NAMES))

    def update(self, values: Sequence[float]) -> None:
        if len(values) != len(self.means):
            raise ValueError("normalizer feature length mismatch")
        self.count += 1
        for index, value in enumerate(values):
            delta = value - self.means[index]
            self.means[index] += delta / self.count
            self.m2[index] += delta * (value - self.means[index])

    def transform(self, values: Sequence[float]) -> list[float]:
        if len(values) != len(self.means):
            raise ValueError("normalizer feature length mismatch")
        transformed: list[float] = []
        for index, value in enumerate(values):
            variance = self.m2[index] / (self.count - 1) if self.count > 1 else 1.0
            scale = math.sqrt(max(variance, 1e-12))
            transformed.append(max(-8.0, min(8.0, (value - self.means[index]) / scale)))
        return transformed

    def to_dict(self) -> dict[str, Any]:
        return {"count": self.count, "means": self.means, "m2": self.m2}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> OnlineNormalizer:
        means = [float(value) for value in raw["means"]]
        m2 = [float(value) for value in raw["m2"]]
        if len(means) != len(FEATURE_NAMES) or len(m2) != len(FEATURE_NAMES):
            raise ValueError("persisted normalizer feature schema mismatch")
        return cls(count=int(raw["count"]), means=means, m2=m2)


@dataclass
class PendingExample:
    observed_at: str
    event_id: str
    price: str
    features: list[float]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PendingExample:
        return cls(
            observed_at=str(raw["observed_at"]),
            event_id=str(raw["event_id"]),
            price=str(raw["price"]),
            features=[float(value) for value in raw["features"]],
        )


@dataclass
class LocalSoftmaxModel:
    """Three-class linear softmax trained with causal stochastic gradient descent."""

    model_version: str = DEFAULT_MODEL_VERSION
    learning_rate: float = 0.03
    l2: float = 0.0001
    weights: list[list[float]] = field(
        default_factory=lambda: [[0.0] * (len(FEATURE_NAMES) + 1) for _ in CLASSES]
    )
    normalizer: OnlineNormalizer = field(default_factory=OnlineNormalizer)
    trained_examples: int = 0
    pending: list[PendingExample] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def _probabilities(self, normalized: Sequence[float]) -> list[float]:
        augmented = [1.0, *normalized]
        logits = [sum(weight * value for weight, value in zip(row, augmented, strict=True)) for row in self.weights]
        maximum = max(logits)
        exps = [math.exp(max(-50.0, min(50.0, value - maximum))) for value in logits]
        total = sum(exps)
        return [value / total for value in exps]

    def predict(self, features: Sequence[float]) -> DirectionPrediction:
        probabilities = self._probabilities(self.normalizer.transform(features))
        index = max(range(len(CLASSES)), key=probabilities.__getitem__)
        return DirectionPrediction(
            direction=CLASSES[index],
            probabilities={direction.value: probabilities[i] for i, direction in enumerate(CLASSES)},
            confidence=probabilities[index],
            model_version=self.model_version,
        )

    def train_one(
        self,
        features: Sequence[float],
        label: Direction,
        *,
        sample_weight: float = 1.0,
    ) -> float:
        if not math.isfinite(sample_weight) or sample_weight <= 0:
            raise ValueError("sample_weight must be positive and finite")
        self.normalizer.update(features)
        normalized = self.normalizer.transform(features)
        probabilities = self._probabilities(normalized)
        target_index = CLASSES.index(label)
        augmented = [1.0, *normalized]
        for class_index, row in enumerate(self.weights):
            error = sample_weight * (
                probabilities[class_index] - (1.0 if class_index == target_index else 0.0)
            )
            for feature_index, value in enumerate(augmented):
                penalty = 0.0 if feature_index == 0 else self.l2 * row[feature_index]
                row[feature_index] -= self.learning_rate * (error * value + penalty)
        self.trained_examples += 1
        return -math.log(max(probabilities[target_index], 1e-15))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MODEL_SCHEMA_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "classes": [item.value for item in CLASSES],
            "model_version": self.model_version,
            "learning_rate": self.learning_rate,
            "l2": self.l2,
            "weights": self.weights,
            "normalizer": self.normalizer.to_dict(),
            "trained_examples": self.trained_examples,
            "pending": [item.to_dict() for item in self.pending],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> LocalSoftmaxModel:
        if raw.get("schema_version") != MODEL_SCHEMA_VERSION:
            raise ValueError("unsupported local model schema")
        if tuple(raw.get("feature_names", ())) != FEATURE_NAMES:
            raise ValueError("local model feature schema mismatch")
        if tuple(raw.get("classes", ())) != tuple(item.value for item in CLASSES):
            raise ValueError("local model class schema mismatch")
        weights = [[float(value) for value in row] for row in raw["weights"]]
        if len(weights) != len(CLASSES) or any(len(row) != len(FEATURE_NAMES) + 1 for row in weights):
            raise ValueError("local model weight shape mismatch")
        metadata_raw = raw.get("metadata", {})
        if not isinstance(metadata_raw, dict):
            raise ValueError("local model metadata must be an object")
        return cls(
            model_version=str(raw["model_version"]),
            learning_rate=float(raw["learning_rate"]),
            l2=float(raw["l2"]),
            weights=weights,
            normalizer=OnlineNormalizer.from_dict(raw["normalizer"]),
            trained_examples=int(raw["trained_examples"]),
            pending=[PendingExample.from_dict(item) for item in raw.get("pending", [])],
            metadata=dict(metadata_raw),
        )

    @classmethod
    def load(cls, path: str | Path) -> LocalSoftmaxModel:
        raw: object = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("local model JSON must be an object")
        return cls.from_dict(raw)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        payload = json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def evidence_features(snapshot: SnapshotLike, context: FeatureContext) -> list[float]:
    """Project an EvidenceSnapshot plus portfolio/risk state into the fixed schema."""
    equity = context.equity
    drawdown = (
        max(D("0"), (context.peak_equity - equity) / context.peak_equity)
        if equity is not None and context.peak_equity is not None and context.peak_equity > 0
        else D("0")
    )
    daily_pnl = (
        (equity / context.day_start_equity) - D("1")
        if equity is not None and context.day_start_equity is not None and context.day_start_equity > 0
        else D("0")
    )
    unrealized = (
        (snapshot.price / context.entry_price - D("1")) * D("10000")
        if context.position_long and context.entry_price is not None and context.entry_price > 0
        else D("0")
    )
    stop_distance = (
        (snapshot.price - context.active_stop_price) / snapshot.price * D("10000")
        if context.active_stop_price is not None and snapshot.price > 0
        else D("0")
    )
    spread = snapshot.spread_bps if snapshot.spread_bps is not None else D("0")
    values = [
        snapshot.horizons.get("5m", D("0")),
        snapshot.horizons.get("30m", D("0")),
        snapshot.horizons.get("4h", D("0")),
        snapshot.horizons.get("1d", D("0")),
        snapshot.horizons.get("7d", D("0")),
        snapshot.horizons.get("30d", D("0")),
        snapshot.structural_confidence,
        snapshot.tactical_confidence,
        snapshot.structural_return_bps,
        snapshot.tactical_return_bps,
        snapshot.expected_edge_bps,
        snapshot.flow_imbalance,
        spread,
        D("1") if snapshot.spread_bps is None else D("0"),
        snapshot.coverage,
        D(snapshot.data_age_ms) / D("1000"),
        D("1") if context.position_long else D("0"),
        unrealized,
        drawdown,
        daily_pnl,
        stop_distance,
        context.risk_per_trade_fraction,
    ]
    if any(not value.is_finite() for value in values):
        raise ValueError("non-finite local model feature")
    return [float(value) for value in values]


def net_four_hour_label(
    entry_price: Decimal,
    future_price: Decimal,
    *,
    round_trip_cost_bps: Decimal,
    decision_threshold_bps: Decimal,
) -> tuple[Direction, Decimal]:
    if entry_price <= 0 or future_price <= 0:
        raise ValueError("label prices must be positive")
    raw_return = (future_price / entry_price - D("1")) * D("10000")
    buy_net = raw_return - round_trip_cost_bps
    sell_net = -raw_return - round_trip_cost_bps
    if buy_net >= decision_threshold_bps:
        return Direction.BUY, buy_net
    if sell_net >= decision_threshold_bps:
        return Direction.SELL, sell_net
    return Direction.HOLD, max(buy_net, sell_net)


class LocalMLAgent:
    """Runtime prediction plus optional persistent four-hour delayed learning."""

    LABEL_DELAY: ClassVar[timedelta] = timedelta(hours=4)
    LABEL_TOLERANCE: ClassVar[timedelta] = timedelta(minutes=5)
    PENDING_CADENCE: ClassVar[timedelta] = timedelta(hours=1)

    def __init__(
        self,
        path: str | Path,
        *,
        online_learning: bool = False,
        round_trip_cost_bps: Decimal = _DEFAULT_COST_BPS,
        decision_threshold_bps: Decimal = _DEFAULT_THRESHOLD_BPS,
        experience_path: str | Path | None = None,
        allow_unpromoted: bool = False,
    ) -> None:
        self.path = Path(path)
        self.model = LocalSoftmaxModel.load(self.path)
        if not allow_unpromoted and self.model.metadata.get("promotion_status") != "PROMOTED":
            raise ValueError("local model is not promoted by temporal holdout gates")
        self.online_learning = online_learning
        self.round_trip_cost_bps = round_trip_cost_bps
        self.decision_threshold_bps = decision_threshold_bps
        self.experience_path = Path(experience_path) if experience_path else self.path.with_suffix(".experiences.jsonl")

    @property
    def model_version(self) -> str:
        return self.model.model_version

    def predict(self, snapshot: SnapshotLike, context: FeatureContext) -> DirectionPrediction:
        self.observe_price(snapshot.at, snapshot.price)
        features = evidence_features(snapshot, context)
        prediction = self.model.predict(features)
        if self.online_learning and self._should_enqueue(snapshot.at):
            self.model.pending.append(
                PendingExample(
                    snapshot.at.isoformat(),
                    snapshot.event_id,
                    format(snapshot.price, "f"),
                    features,
                )
            )
            self.model.save(self.path)
        return prediction

    def observe_price(self, observed_at: datetime, price: Decimal) -> None:
        """Resolve exact-horizon labels even when a safety veto skips prediction."""
        if self.online_learning and self._resolve(observed_at, price):
            self.model.save(self.path)

    def _should_enqueue(self, observed_at: datetime) -> bool:
        if not self.model.pending:
            return True
        return (
            observed_at - datetime.fromisoformat(self.model.pending[-1].observed_at)
            >= self.PENDING_CADENCE
        )

    def _update_id(self, pending: PendingExample) -> str:
        identity = f"{self.model.model_version}:{pending.event_id}:{pending.observed_at}"
        return hashlib.sha256(identity.encode()).hexdigest()

    def _experience_ids(self) -> set[str]:
        if not self.experience_path.exists():
            return set()
        identifiers: set[str] = set()
        for line in self.experience_path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict) and isinstance(raw.get("update_id"), str):
                identifiers.add(raw["update_id"])
        return identifiers

    def _resolve(self, now: datetime, price: Decimal) -> bool:
        retained: list[PendingExample] = []
        outcomes: list[tuple[PendingExample, Direction | None, Decimal | None, str]] = []
        for pending in self.model.pending:
            observed_at = datetime.fromisoformat(pending.observed_at)
            age = now - observed_at
            if age < self.LABEL_DELAY:
                retained.append(pending)
                continue
            if age - self.LABEL_DELAY > self.LABEL_TOLERANCE:
                outcomes.append((pending, None, None, "EXPIRED_TARGET_MISSING"))
                continue
            resolved_label, resolved_net_bps = net_four_hour_label(
                D(pending.price),
                price,
                round_trip_cost_bps=self.round_trip_cost_bps,
                decision_threshold_bps=self.decision_threshold_bps,
            )
            outcomes.append((pending, resolved_label, resolved_net_bps, "LABELED"))
        if not outcomes:
            return False

        existing_ids = self._experience_ids()
        self.experience_path.parent.mkdir(parents=True, exist_ok=True)
        with self.experience_path.open("a", encoding="utf-8") as stream:
            for pending, label, net_bps, status in outcomes:
                update_id = self._update_id(pending)
                if update_id in existing_ids:
                    continue
                row = {
                    "schema_version": "local-ml-experience/1.1.0",
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "feature_names": list(FEATURE_NAMES),
                    "features": pending.features,
                    "update_id": update_id,
                    "status": status,
                    "event_id": pending.event_id,
                    "observed_at": pending.observed_at,
                    "target_at": (datetime.fromisoformat(pending.observed_at) + self.LABEL_DELAY).isoformat(),
                    "resolved_at": now.isoformat(),
                    "entry_price": pending.price,
                    "resolution_price": format(price, "f"),
                    "label": label.value if label is not None else None,
                    "net_opportunity_bps": format(net_bps, "f") if net_bps is not None else None,
                    "model_version": self.model.model_version,
                }
                stream.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

        # The experience row is a write-ahead record. If a crash occurs before
        # the checkpoint, the still-pending item is deterministically reapplied
        # on restart without appending a duplicate update_id.
        for pending, label, _net_bps, _status in outcomes:
            if label is not None:
                self.model.train_one(pending.features, label)
        self.model.pending = retained
        return True


__all__ = [
    "CLASSES",
    "DEFAULT_MODEL_VERSION",
    "FEATURE_NAMES",
    "FEATURE_SCHEMA_VERSION",
    "Direction",
    "DirectionPrediction",
    "FeatureContext",
    "LocalMLAgent",
    "LocalSoftmaxModel",
    "OnlineNormalizer",
    "evidence_features",
    "net_four_hour_label",
]
