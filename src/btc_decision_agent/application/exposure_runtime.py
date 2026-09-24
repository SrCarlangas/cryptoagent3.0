"""Live wiring for the exposure agent: sole directional authority, vetoed by safety.

Division of responsibility, which is the point of this module:

The AGENT decides direction. Nothing else in the system may originate a BUY or a
SELL. There is no moving-average rule, no threshold ladder and no hand-written
trend test anywhere in this path.

The DETERMINISTIC LAYERS may only veto or protect. They can refuse to act, force a
protective exit, or abstain when data is untrustworthy, but they can never invent a
directional opinion. That asymmetry is what keeps the agent in charge while still
bounding the damage a bad model can do.

Fidelity to what was validated
------------------------------
The walk-forward result was produced by an agent that re-decided at a fixed cadence
and filled on the next bar. Live, market events arrive many times per second, and
letting the policy commit on every tick would be a different system from the one
measured, with far more switching. So the commit cadence is read from the trained
model's own metadata and enforced here: the agent still PERCEIVES and reports
continuously, which is what real-time means, but it commits on the cadence it was
trained and validated at.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from btc_decision_agent.application.exposure_agent import (
    PendingStep,
    PolicyDecision,
    PortfolioState,
    RegimeMixturePolicy,
    TradeDecision,
    action_rewards,
    compose_features,
    update_identity,
)
from btc_decision_agent.application.exposure_features import (
    MIN_DAILY_HISTORY,
    market_features_from_decimal,
)
from btc_decision_agent.application.realtime_demo import (
    EvidenceSnapshot,
    ProtectiveDecisionEngine,
    RealtimeDecision,
    RealtimeParams,
    ReconciledPosition,
)
from btc_decision_agent.domain.contracts import Action, PositionState

D = Decimal
DEFAULT_CADENCE_HOURS = 24
DEFAULT_ROUND_TRIP_COST_BPS = D("20")


class InsufficientPerception(Exception):
    """Raised when the agent lacks the daily history its features require."""


class ExposureAgentRuntime:
    """Loads the trained policy and turns evidence into a BUY/HOLD/SELL decision."""

    def __init__(
        self,
        path: str | Path,
        *,
        online_learning: bool = False,
        round_trip_cost_bps: Decimal = DEFAULT_ROUND_TRIP_COST_BPS,
        experience_path: str | Path | None = None,
        allow_unpromoted: bool = False,
    ) -> None:
        self.path = Path(path)
        self.policy = RegimeMixturePolicy.load(self.path)
        status = self.policy.metadata.get("promotion_status")
        if not allow_unpromoted and status != "PROMOTED":
            raise ValueError(
                f"exposure policy is not promoted (status={status!r}); "
                "refusing to grant order authority"
            )
        self.online_learning = online_learning
        self.round_trip_cost_bps = round_trip_cost_bps
        self.experience_path = (
            Path(experience_path)
            if experience_path
            else self.path.with_suffix(".experiences.jsonl")
        )
        self._pending: list[PendingStep] = []
        self._last_commit: datetime | None = None

    @property
    def policy_version(self) -> str:
        return self.policy.policy_version

    @property
    def cadence(self) -> timedelta:
        """Commit cadence, taken from the configuration the model was trained with."""
        config = self.policy.metadata.get("selection", {})
        hours = DEFAULT_CADENCE_HOURS
        if isinstance(config, dict):
            chosen = config.get("chosen_config")
            if isinstance(chosen, str) and "cadence=" in chosen:
                token = chosen.split("cadence=")[1].split("h")[0]
                if token.isdigit():
                    hours = int(token)
        return timedelta(hours=hours)

    @property
    def fee_per_side(self) -> float:
        return float(self.round_trip_cost_bps) / 2.0 / 10_000.0

    def perceive(
        self,
        daily_closes: tuple[Decimal, ...],
        price: Decimal,
        *,
        position_long: bool,
        entry_price: Decimal | None,
        holding_hours: int,
    ) -> tuple[list[float], PortfolioState]:
        """Build the exact feature vector the policy was trained on."""
        if len(daily_closes) < MIN_DAILY_HISTORY:
            raise InsufficientPerception(
                f"need {MIN_DAILY_HISTORY} completed daily closes, have {len(daily_closes)}"
            )
        market = market_features_from_decimal(daily_closes, price)
        state = PortfolioState(
            position_long=position_long,
            unrealized_log_return=(
                math.log(float(price) / float(entry_price))
                if position_long and entry_price is not None and entry_price > 0
                else 0.0
            ),
            holding_hours=holding_hours,
            round_trip_cost_bps=float(self.round_trip_cost_bps),
        )
        return compose_features(market, state), state

    def decide(
        self, features: list[float], state: PortfolioState
    ) -> PolicyDecision:
        """Deterministic inference: no exploration in production, ever.

        A sampled action would make the same evidence produce different orders on
        different runs, which would make the journal unauditable.
        """
        return self.policy.decide(features, state)

    def may_commit(self, now: datetime) -> bool:
        """Whether the trained cadence allows acting on a change of opinion now."""
        return self._last_commit is None or now - self._last_commit >= self.cadence

    def note_commit(self, now: datetime) -> None:
        self._last_commit = now

    def observe(
        self,
        now: datetime,
        event_id: str,
        price: Decimal,
        features: list[float],
        *,
        position_long: bool,
    ) -> None:
        """Record a step for later learning and resolve any step that has matured.

        Learning continues in production: once a recorded decision is old enough
        for its outcome to be known, the same exact gradient used offline is
        applied to the live weights.
        """
        if not self.online_learning:
            return
        if self._resolve(now, price):
            self.policy.save(self.path)
        if not self._pending or now - datetime.fromisoformat(
            self._pending[-1].observed_at
        ) >= self.cadence:
            self._pending.append(
                PendingStep(
                    observed_at=now.isoformat(),
                    event_id=event_id,
                    price=format(price, "f"),
                    features=list(features),
                    position_long=position_long,
                )
            )
            self.policy.save(self.path)

    def _resolve(self, now: datetime, price: Decimal) -> bool:
        """Apply learning for steps whose reward horizon has elapsed."""
        tolerance = self.cadence / 10
        retained: list[PendingStep] = []
        resolved: list[tuple[PendingStep, list[float], float]] = []
        for step in self._pending:
            observed_at = datetime.fromisoformat(step.observed_at)
            age = now - observed_at
            if age < self.cadence:
                retained.append(step)
                continue
            if age - self.cadence > tolerance:
                # The outcome bar was missed, so the reward would cover the wrong
                # interval. Discard rather than learn from a mismeasured horizon.
                continue
            entry = D(step.price)
            if entry <= 0 or price <= 0:
                continue
            forward = math.log(float(price) / float(entry))
            rewards = action_rewards(
                forward,
                position_long=step.position_long,
                fee_per_side=self.fee_per_side,
            )
            resolved.append((step, rewards, forward))
        if not resolved:
            self._pending = retained
            return False

        self.experience_path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._experience_ids()
        with self.experience_path.open("a", encoding="utf-8") as stream:
            for step, rewards, forward in resolved:
                identity = update_identity(self.policy.policy_version, step)
                if identity in existing:
                    continue
                stream.write(
                    json.dumps(
                        {
                            "schema_version": "exposure-experience/1.0.0",
                            "update_id": identity,
                            "observed_at": step.observed_at,
                            "resolved_at": now.isoformat(),
                            "event_id": step.event_id,
                            "entry_price": step.price,
                            "resolution_price": format(price, "f"),
                            "position_long": step.position_long,
                            "forward_log_return": forward,
                            "reward_flat": rewards[0],
                            "reward_long": rewards[1],
                            "policy_version": self.policy.policy_version,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                )
            stream.flush()
            os.fsync(stream.fileno())

        for step, rewards, _forward in resolved:
            self.policy.update(step.features, rewards)
        self._pending = retained
        return True

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

    def explain(self, outcome: PolicyDecision) -> dict[str, Any]:
        """Auditable record of why the agent chose what it chose."""
        return {
            "policy_version": outcome.policy_version,
            "decision": outcome.decision.value,
            "target_exposure": outcome.action.value,
            "confidence": outcome.confidence,
            "p_long": outcome.action_probabilities.get("TARGET_LONG"),
            "dominant_regime": outcome.dominant_regime,
            "regime_responsibilities": outcome.regime_responsibilities,
            "trained_steps": self.policy.trained_steps,
        }


def agent_reason(outcome: PolicyDecision) -> str:
    """Reason code carrying the agent's own view, for the activity journal."""
    if outcome.decision == TradeDecision.BUY:
        stem = "AGENT_ENTER_LONG"
    elif outcome.decision == TradeDecision.SELL:
        stem = "AGENT_EXIT_LONG"
    else:
        stem = "AGENT_HOLD"
    return f"{stem}_R{outcome.dominant_regime}_P{round(outcome.confidence * 100)}"


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


__all__ = [
    "DEFAULT_CADENCE_HOURS",
    "DEFAULT_ROUND_TRIP_COST_BPS",
    "ExposureAgentEngine",
    "ExposureAgentRuntime",
    "InsufficientPerception",
    "agent_reason",
    "utc_now",
]


class ExposureAgentEngine(ProtectiveDecisionEngine):
    """Decision engine whose ONLY directional source is the local exposure agent.

    It reuses the protective machinery of the V4 engine deliberately rather than
    reimplementing it: the circuit breakers, the exchange-side stop tracking, the
    equity bookkeeping and the position restoration are all safety code that has
    already been exercised in production, and duplicating it would be the riskiest
    part of this change.

    What is NOT inherited is the direction. V4 decided direction from hand-written
    confidence thresholds; this engine asks the agent and does what it says, unless
    a safety layer forbids acting at all.

    Guard order, strictest first:
      1. circuit breakers        -> may force EXIT, never an entry
      2. exchange protective stop -> may force EXIT
      3. data quality gate        -> abstain on untrustworthy evidence
      4. perception sufficiency   -> abstain without 200 completed daily closes
      5. the agent                -> the only step that can originate a direction
      6. commit cadence          -> holds the agent to the frequency it was validated at
    """

    def __init__(
        self,
        params: RealtimeParams,
        agent: ExposureAgentRuntime,
    ) -> None:
        super().__init__(params)
        self.agent = agent
        self._last_explanation: dict[str, Any] = {}

    @property
    def last_explanation(self) -> dict[str, Any]:
        """Why the most recent decision was taken; surfaced for the dashboard."""
        return dict(self._last_explanation)

    def _holding_hours(self, now: datetime) -> int:
        entry_at = self.state.entry_at
        if entry_at is None:
            return 0
        return max(int((now - entry_at).total_seconds() // 3600), 0)

    def evaluate(
        self, evidence: EvidenceSnapshot, position: ReconciledPosition
    ) -> RealtimeDecision:
        self.restore_position(position, now=evidence.at)
        self.update_equity(position.equity, evidence.at)
        now = evidence.at
        is_long = position.state == PositionState.LONG

        # 1. Circuit breakers. These can only flatten or hold.
        breaker = self.breaker_reason(position.equity)
        if breaker is not None:
            self._reset_candidate()
            self._last_explanation = {"veto": breaker}
            return RealtimeDecision(
                Action.EXIT_LONG if is_long else Action.HOLD, breaker, evidence, is_long
            )

        # 2. Protective stop, tracked against the exchange-side order.
        if is_long:
            high = max(self._state.high_since_entry or evidence.price, evidence.price)
            self._state = replace(
                self._state, high_since_entry=high, position_base_qty=position.btc_qty
            )
            active_stop = self._active_stop(evidence.price)
            if active_stop is not None and evidence.price <= active_stop:
                self._reset_candidate()
                self._last_explanation = {"veto": "PROTECTIVE_STOP"}
                return RealtimeDecision(
                    Action.EXIT_LONG,
                    "PROTECTIVE_STOP",
                    replace(evidence, active_stop_price=active_stop),
                    True,
                )

        # 3. Data quality. Acting on stale or unpriced evidence is never allowed.
        if not evidence.qualified:
            self._reset_candidate()
            self._last_explanation = {"veto": evidence.reason}
            return RealtimeDecision(Action.HOLD, evidence.reason, evidence)

        # 4. Perception sufficiency. Abstaining is correct here: a 200-day feature
        #    computed from 40 days is a different feature with the same name.
        try:
            features, state = self.agent.perceive(
                evidence.daily_closes,
                evidence.price,
                position_long=is_long,
                entry_price=self._state.entry_price,
                holding_hours=self._holding_hours(now),
            )
        except InsufficientPerception as error:
            self._reset_candidate()
            self._last_explanation = {"veto": "PERCEPTION_INSUFFICIENT", "detail": str(error)}
            return RealtimeDecision(Action.HOLD, "PERCEPTION_INSUFFICIENT", evidence)

        # 5. The agent decides. This is the only place a direction is created.
        outcome = self.agent.decide(features, state)
        self.agent.observe(
            now, evidence.event_id, evidence.price, features, position_long=is_long
        )
        self._last_explanation = self.agent.explain(outcome)
        reason = agent_reason(outcome)

        if outcome.decision == TradeDecision.HOLD:
            self._reset_candidate()
            return RealtimeDecision(Action.HOLD, reason, evidence, agent_decision=outcome)

        # 6. Commit cadence. The agent re-decides continuously, but it acts at the
        #    frequency it was trained and measured at, so live behaviour matches the
        #    walk-forward evidence instead of being a higher-frequency variant of it.
        if not self.agent.may_commit(now):
            return RealtimeDecision(
                Action.HOLD,
                f"{reason}_AWAITING_CADENCE",
                evidence,
                agent_decision=outcome,
            )

        self.agent.note_commit(now)
        self._reset_candidate()
        if outcome.decision == TradeDecision.BUY:
            return RealtimeDecision(
                Action.ENTER_LONG, reason, evidence, agent_decision=outcome
            )
        return RealtimeDecision(
            Action.EXIT_LONG, reason, evidence, True, agent_decision=outcome
        )
