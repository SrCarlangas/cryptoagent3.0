"""Local exposure agent: a learned, regime-aware, cost-aware trading policy.

This is an agent, not a rule set. Nothing here encodes "sell below the 200-day
average" or "wait 2% before re-entering". What it encodes is an objective and a
learning rule; the behaviour is whatever maximises that objective on the data.

How it satisfies each requirement
---------------------------------
Distinguishes regimes
    The policy is a mixture of experts. A learned gate maps the current market
    state to responsibilities over K latent regimes, and each regime holds its own
    action preferences. The gate is trained, not thresholded, so the regimes are
    discovered from five years of history rather than declared by a human. Every
    decision reports its regime responsibilities, so a non-deterministic agent is
    still fully explainable after the fact.

Adjusts in real time
    Inference runs on every market event, and learning continues in production:
    each decision is recorded, and when its outcome resolves the same gradient
    that trained it offline is applied online.

Decides buy / hold / sell on its own criterion
    The action space is the target exposure. Combined with the position the agent
    is actually holding, that yields BUY, HOLD or SELL. No layer above it may
    invent a directional decision; safety layers may only veto.

Always seeks maximum profitability
    The reward is the realised log return of the chosen exposure minus the fees
    that choice actually incurs. Summed over time, log return IS terminal wealth,
    so maximising expected reward is literally maximising profitability rather
    than a proxy such as direction accuracy. Because switching costs appear in the
    reward, reluctance to churn EMERGES from the economics; it is not a hard-coded
    dead band. The Task 1 diagnosis priced unbounded churn at 137% of capital per
    year, so this is the single most important property of the design.

Learning rule
    At each step the reward of BOTH actions is knowable after the fact: we observe
    the price move, so we know what holding would have earned and what standing
    aside would have avoided. That makes this a full-information contextual bandit
    rather than a bandit with a single observed outcome, so the exact expected-
    reward gradient is available and no high-variance REINFORCE sampling is
    needed. Training still rolls the agent through history on its own trajectory,
    because the reward depends on the position its own past choices produced.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from btc_decision_agent.application.exposure_features import (
    FEATURE_SCHEMA_VERSION,
    MARKET_FEATURE_NAMES,
)

POLICY_SCHEMA_VERSION = "exposure-regime-mixture/1.0.0"
DEFAULT_POLICY_VERSION = "LOCAL-EXPOSURE-AGENT-V1"
DEFAULT_REGIMES = 4

STATE_FEATURE_NAMES: tuple[str, ...] = (
    "position_long",
    "unrealized_log_return",
    "holding_progress",
    "round_trip_cost",
)
"""Portfolio state the policy conditions on.

The position matters because the reward of an action depends on whether acting
requires paying a fee. Without it the agent could not learn that staying put is
usually cheaper than being right.
"""

POLICY_FEATURE_NAMES: tuple[str, ...] = (*MARKET_FEATURE_NAMES, *STATE_FEATURE_NAMES)


class ExposureAction(str, Enum):
    """What the agent chooses: how much of the book should be exposed."""

    TARGET_FLAT = "TARGET_FLAT"
    TARGET_LONG = "TARGET_LONG"


ACTIONS: tuple[ExposureAction, ...] = (ExposureAction.TARGET_FLAT, ExposureAction.TARGET_LONG)


class TradeDecision(str, Enum):
    """What that choice means given the position actually held."""

    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


def decision_for(action: ExposureAction, position_long: bool) -> TradeDecision:
    if action == ExposureAction.TARGET_LONG:
        return TradeDecision.HOLD if position_long else TradeDecision.BUY
    return TradeDecision.SELL if position_long else TradeDecision.HOLD


@dataclass(frozen=True)
class PortfolioState:
    """Everything about our own book that the policy is allowed to see."""

    position_long: bool = False
    unrealized_log_return: float = 0.0
    holding_hours: int = 0
    round_trip_cost_bps: float = 20.0

    def features(self) -> list[float]:
        return [
            1.0 if self.position_long else 0.0,
            self.unrealized_log_return,
            # Compressed so a position held for weeks does not dominate the scale.
            math.log1p(max(self.holding_hours, 0)) / 10.0,
            self.round_trip_cost_bps / 100.0,
        ]


@dataclass
class OnlineNormalizer:
    """Causal Welford normalizer; updated only by training observations."""

    count: int = 0
    means: list[float] = field(default_factory=lambda: [0.0] * len(POLICY_FEATURE_NAMES))
    m2: list[float] = field(default_factory=lambda: [0.0] * len(POLICY_FEATURE_NAMES))

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
        out: list[float] = []
        for index, value in enumerate(values):
            variance = self.m2[index] / (self.count - 1) if self.count > 1 else 1.0
            scale = math.sqrt(max(variance, 1e-12))
            out.append(max(-8.0, min(8.0, (value - self.means[index]) / scale)))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"count": self.count, "means": self.means, "m2": self.m2}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> OnlineNormalizer:
        means = [float(value) for value in raw["means"]]
        m2 = [float(value) for value in raw["m2"]]
        if len(means) != len(POLICY_FEATURE_NAMES) or len(m2) != len(POLICY_FEATURE_NAMES):
            raise ValueError("persisted normalizer feature schema mismatch")
        return cls(count=int(raw["count"]), means=means, m2=m2)


@dataclass(frozen=True)
class PolicyDecision:
    """An auditable record of one decision."""

    action: ExposureAction
    decision: TradeDecision
    action_probabilities: dict[str, float]
    regime_responsibilities: list[float]
    dominant_regime: int
    confidence: float
    policy_version: str
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    policy_schema_version: str = POLICY_SCHEMA_VERSION


def _softmax(logits: Sequence[float]) -> list[float]:
    largest = max(logits)
    exps = [math.exp(max(-60.0, min(60.0, value - largest))) for value in logits]
    total = sum(exps)
    return [value / total for value in exps]


@dataclass
class RegimeMixturePolicy:
    """Mixture-of-experts policy over target exposure.

    gate[k]      : regime logit weights, shape (regimes, features + 1)
    experts[k][a]: action logit weights per regime, shape (regimes, actions, features + 1)

    Action logits are the responsibility-weighted sum of the per-regime action
    logits, so the agent can hold genuinely different criteria in different market
    conditions and blend them smoothly rather than snapping at a threshold.
    """

    policy_version: str = DEFAULT_POLICY_VERSION
    regimes: int = DEFAULT_REGIMES
    learning_rate: float = 0.05
    l2: float = 1e-5
    init_seed: int = 20260924
    init_scale: float = 0.05
    gate: list[list[float]] = field(default_factory=list)
    experts: list[list[list[float]]] = field(default_factory=list)
    normalizer: OnlineNormalizer = field(default_factory=OnlineNormalizer)
    trained_steps: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        width = len(POLICY_FEATURE_NAMES) + 1
        # Symmetry breaking is mandatory, not cosmetic. If every expert starts
        # identical it receives an identical gradient, so all regimes stay the same
        # function forever, the gate sees no reason to prefer one over another, and
        # the mixture silently degenerates into a single averaged expert. Random
        # initialisation from a fixed seed keeps it reproducible while letting the
        # regimes specialise.
        generator = random.Random(self.init_seed)
        if not self.gate:
            self.gate = [
                [generator.gauss(0.0, self.init_scale) for _ in range(width)]
                for _ in range(self.regimes)
            ]
        if not self.experts:
            self.experts = [
                [
                    [generator.gauss(0.0, self.init_scale) for _ in range(width)]
                    for _ in ACTIONS
                ]
                for _ in range(self.regimes)
            ]
        self._validate_shape()

    def _validate_shape(self) -> None:
        width = len(POLICY_FEATURE_NAMES) + 1
        if len(self.gate) != self.regimes or any(len(row) != width for row in self.gate):
            raise ValueError("gate shape mismatch")
        if len(self.experts) != self.regimes:
            raise ValueError("expert count mismatch")
        for expert in self.experts:
            if len(expert) != len(ACTIONS) or any(len(row) != width for row in expert):
                raise ValueError("expert shape mismatch")

    def _forward(
        self, normalized: Sequence[float]
    ) -> tuple[list[float], list[float], list[list[float]], list[float]]:
        """Return (augmented input, responsibilities, per-regime logits, action probs)."""
        augmented = [1.0, *normalized]
        gate_logits = [
            sum(w * x for w, x in zip(row, augmented, strict=True)) for row in self.gate
        ]
        responsibilities = _softmax(gate_logits)
        regime_logits = [
            [sum(w * x for w, x in zip(row, augmented, strict=True)) for row in expert]
            for expert in self.experts
        ]
        mixed = [
            sum(
                responsibilities[k] * regime_logits[k][a]
                for k in range(self.regimes)
            )
            for a in range(len(ACTIONS))
        ]
        return augmented, responsibilities, regime_logits, _softmax(mixed)

    def decide(
        self,
        features: Sequence[float],
        state: PortfolioState,
        *,
        explore_with: random.Random | None = None,
    ) -> PolicyDecision:
        """Choose a target exposure.

        Production inference is deterministic (argmax) so every order is
        reproducible from the journal. Training passes an RNG to sample instead,
        which is what lets the agent discover alternatives to its current habit.
        """
        normalized = self.normalizer.transform(features)
        _augmented, responsibilities, _regime_logits, probabilities = self._forward(normalized)
        if explore_with is not None:
            draw = explore_with.random()
            cumulative = 0.0
            index = len(ACTIONS) - 1
            for candidate, probability in enumerate(probabilities):
                cumulative += probability
                if draw <= cumulative:
                    index = candidate
                    break
        else:
            index = max(range(len(ACTIONS)), key=probabilities.__getitem__)
        action = ACTIONS[index]
        return PolicyDecision(
            action=action,
            decision=decision_for(action, state.position_long),
            action_probabilities={
                item.value: probabilities[i] for i, item in enumerate(ACTIONS)
            },
            regime_responsibilities=responsibilities,
            dominant_regime=max(range(self.regimes), key=responsibilities.__getitem__),
            confidence=probabilities[index],
            policy_version=self.policy_version,
        )

    def update(self, features: Sequence[float], rewards: Sequence[float]) -> float:
        """One exact expected-reward gradient ascent step.

        `rewards[a]` is the net log return that action `a` would have produced from
        this state, fees included. Both are knowable after the outcome, so the
        gradient is exact rather than sampled.

        Returns the expected reward under the pre-update policy, which is the
        quantity being maximised and therefore the thing to watch during training.
        """
        if len(rewards) != len(ACTIONS):
            raise ValueError("reward vector must cover every action")
        if any(not math.isfinite(value) for value in rewards):
            raise ValueError("non-finite reward")

        self.normalizer.update(features)
        normalized = self.normalizer.transform(features)
        augmented, responsibilities, regime_logits, probabilities = self._forward(normalized)

        expected = sum(p * r for p, r in zip(probabilities, rewards, strict=True))
        # dJ/d(action logit i) for J = sum_i pi_i R_i
        delta = [
            probabilities[i] * (rewards[i] - expected) for i in range(len(ACTIONS))
        ]

        # Experts: dJ/dW[k][a] = delta[a] * responsibility[k] * x
        for k in range(self.regimes):
            weight = responsibilities[k]
            for a in range(len(ACTIONS)):
                scale = self.learning_rate * delta[a] * weight
                row = self.experts[k][a]
                for i, value in enumerate(augmented):
                    penalty = 0.0 if i == 0 else self.l2 * row[i]
                    row[i] += scale * value - self.learning_rate * penalty

        # Gate: dJ/du[k] = sum_a delta[a] * regime_logits[k][a], then softmax jacobian
        gate_signal = [
            sum(delta[a] * regime_logits[k][a] for a in range(len(ACTIONS)))
            for k in range(self.regimes)
        ]
        baseline = sum(
            responsibilities[k] * gate_signal[k] for k in range(self.regimes)
        )
        for k in range(self.regimes):
            scale = self.learning_rate * responsibilities[k] * (gate_signal[k] - baseline)
            row = self.gate[k]
            for i, value in enumerate(augmented):
                penalty = 0.0 if i == 0 else self.l2 * row[i]
                row[i] += scale * value - self.learning_rate * penalty

        self.trained_steps += 1
        return expected

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_schema_version": POLICY_SCHEMA_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_names": list(POLICY_FEATURE_NAMES),
            "actions": [item.value for item in ACTIONS],
            "policy_version": self.policy_version,
            "regimes": self.regimes,
            "learning_rate": self.learning_rate,
            "l2": self.l2,
            "init_seed": self.init_seed,
            "init_scale": self.init_scale,
            "gate": self.gate,
            "experts": self.experts,
            "normalizer": self.normalizer.to_dict(),
            "trained_steps": self.trained_steps,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> RegimeMixturePolicy:
        if raw.get("policy_schema_version") != POLICY_SCHEMA_VERSION:
            raise ValueError("unsupported exposure policy schema")
        if tuple(raw.get("feature_names", ())) != POLICY_FEATURE_NAMES:
            raise ValueError("exposure policy feature schema mismatch")
        if tuple(raw.get("actions", ())) != tuple(item.value for item in ACTIONS):
            raise ValueError("exposure policy action schema mismatch")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("exposure policy metadata must be an object")
        policy = cls(
            policy_version=str(raw["policy_version"]),
            regimes=int(raw["regimes"]),
            learning_rate=float(raw["learning_rate"]),
            l2=float(raw["l2"]),
            init_seed=int(raw.get("init_seed", 0)),
            init_scale=float(raw.get("init_scale", 0.05)),
            gate=[[float(v) for v in row] for row in raw["gate"]],
            experts=[
                [[float(v) for v in row] for row in expert] for expert in raw["experts"]
            ],
            normalizer=OnlineNormalizer.from_dict(raw["normalizer"]),
            trained_steps=int(raw["trained_steps"]),
            metadata=dict(metadata),
        )
        return policy

    @classmethod
    def load(cls, path: str | Path) -> RegimeMixturePolicy:
        raw: object = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("exposure policy JSON must be an object")
        return cls.from_dict(raw)

    def save(self, path: str | Path) -> None:
        """Atomic write: temp file, fsync, rename, fsync directory."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        payload = json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        handle = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)


def action_rewards(
    forward_log_return: float,
    *,
    position_long: bool,
    fee_per_side: float,
) -> list[float]:
    """Net log reward of each action, in the canonical action order.

    Holding long earns the market move. Standing flat earns nothing. Either one
    pays a fee only if it requires changing the current position. This function is
    the entire economic specification of the agent, which is why it lives in one
    place and is shared by training, evaluation and online learning.
    """
    if not math.isfinite(forward_log_return):
        raise ValueError("forward log return must be finite")
    if not 0.0 <= fee_per_side < 1.0:
        raise ValueError("fee_per_side must be in [0, 1)")
    switch_cost = math.log(1.0 - fee_per_side)
    flat = 0.0 if not position_long else switch_cost
    long = forward_log_return + (0.0 if position_long else switch_cost)
    rewards = {ExposureAction.TARGET_FLAT: flat, ExposureAction.TARGET_LONG: long}
    return [rewards[action] for action in ACTIONS]


@dataclass
class PendingStep:
    """A decision awaiting its outcome, so learning can continue in production."""

    observed_at: str
    event_id: str
    price: str
    features: list[float]
    position_long: bool

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PendingStep:
        return cls(
            observed_at=str(raw["observed_at"]),
            event_id=str(raw["event_id"]),
            price=str(raw["price"]),
            features=[float(value) for value in raw["features"]],
            position_long=bool(raw["position_long"]),
        )


def update_identity(policy_version: str, step: PendingStep) -> str:
    identity = f"{policy_version}:{step.event_id}:{step.observed_at}"
    return hashlib.sha256(identity.encode()).hexdigest()


def compose_features(
    market: Sequence[float], state: PortfolioState
) -> list[float]:
    """Join market perception with portfolio state in the frozen schema order."""
    values = [*market, *state.features()]
    if len(values) != len(POLICY_FEATURE_NAMES):
        raise ValueError("composed feature vector does not match the policy schema")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("non-finite policy feature")
    return values


def unrealized_log_return(price: Decimal, entry_price: Decimal | None) -> float:
    if entry_price is None or entry_price <= 0 or price <= 0:
        return 0.0
    return math.log(float(price) / float(entry_price))


__all__ = [
    "ACTIONS",
    "DEFAULT_POLICY_VERSION",
    "DEFAULT_REGIMES",
    "POLICY_FEATURE_NAMES",
    "POLICY_SCHEMA_VERSION",
    "STATE_FEATURE_NAMES",
    "ExposureAction",
    "OnlineNormalizer",
    "PendingStep",
    "PolicyDecision",
    "PortfolioState",
    "RegimeMixturePolicy",
    "TradeDecision",
    "action_rewards",
    "compose_features",
    "decision_for",
    "unrealized_log_return",
    "update_identity",
]
