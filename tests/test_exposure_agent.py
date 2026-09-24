"""Tests for the local exposure agent and its runtime integration.

The properties asserted here are the ones that would be expensive to discover in
production: that the agent is genuinely the only source of direction, that safety
layers can veto but never invent a trade, that reluctance to churn comes from the
cost in the reward rather than from a hard-coded band, and that a persisted policy
reloads to bit-identical behaviour.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from btc_decision_agent.application.exposure_agent import (
    ACTIONS,
    POLICY_FEATURE_NAMES,
    ExposureAction,
    PortfolioState,
    RegimeMixturePolicy,
    TradeDecision,
    action_rewards,
    compose_features,
    decision_for,
)
from btc_decision_agent.application.exposure_features import (
    MARKET_FEATURE_NAMES,
    MIN_DAILY_HISTORY,
    market_features,
    market_features_from_decimal,
)
from btc_decision_agent.application.exposure_runtime import (
    ExposureAgentEngine,
    ExposureAgentRuntime,
    InsufficientPerception,
)
from btc_decision_agent.application.realtime_demo import (
    EvidenceSnapshot,
    RealtimeParams,
    ReconciledPosition,
)
from btc_decision_agent.domain.contracts import Action, PositionState

D = Decimal
NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def _rising_closes(count: int = MIN_DAILY_HISTORY, rate: float = 1.002) -> list[float]:
    return [10_000.0 * (rate**index) for index in range(count)]


def _evidence(
    *,
    price: str = "20000",
    qualified: bool = True,
    reason: str = "QUALIFIED",
    daily: tuple[Decimal, ...] | None = None,
    at: datetime = NOW,
) -> EvidenceSnapshot:
    closes = (
        daily
        if daily is not None
        else tuple(D(str(round(value, 2))) for value in _rising_closes())
    )
    return EvidenceSnapshot(
        at=at,
        event_id="event-1",
        price=D(price),
        confidence=D("0.7"),
        grade="HIGH",
        expected_edge_bps=D("15"),
        spread_bps=D("2"),
        data_age_ms=100,
        coverage=D("1"),
        horizons={"5m": D("1"), "1d": D("5")},
        flow_imbalance=D("0"),
        qualified=qualified,
        reason=reason,
        daily_closes=closes,
    )


def _position(state: PositionState, *, btc: str = "0", usdt: str = "5000") -> ReconciledPosition:
    return ReconciledPosition(
        state=state,
        btc_qty=D(btc),
        usdt_free=D(usdt),
        price=D("20000"),
        btc_free=D(btc),
    )


def _promoted_policy(tmp_path: Path, *, regimes: int = 3) -> Path:
    policy = RegimeMixturePolicy(regimes=regimes, init_seed=11)
    policy.metadata = {"promotion_status": "PROMOTED", "selection": {"chosen_config": "cadence=24h"}}
    path = tmp_path / "agent.json"
    policy.save(path)
    return path


class TestFeatures:
    def test_schema_length_matches_names(self) -> None:
        values = market_features(_rising_closes(), 12_000.0)
        assert len(values) == len(MARKET_FEATURE_NAMES)

    def test_rejects_short_history(self) -> None:
        with pytest.raises(ValueError, match="completed daily closes"):
            market_features(_rising_closes(MIN_DAILY_HISTORY - 1), 12_000.0)

    def test_rejects_non_positive_price(self) -> None:
        with pytest.raises(ValueError, match="positive and finite"):
            market_features(_rising_closes(), 0.0)

    def test_trend_direction_flips_sign(self) -> None:
        up = market_features(_rising_closes(rate=1.002), 20_000.0)
        down = market_features(_rising_closes(rate=0.998), 5_000.0)
        index = MARKET_FEATURE_NAMES.index("log_price_over_ma200")
        assert up[index] > 0 > down[index]

    def test_flat_market_volatility_ratio_is_neutral(self) -> None:
        values = market_features([100.0] * MIN_DAILY_HISTORY, 100.0)
        assert values[MARKET_FEATURE_NAMES.index("volatility_ratio_30_90")] == 1.0

    def test_decimal_wrapper_matches_float_path(self) -> None:
        closes = _rising_closes()
        floats = market_features(closes, 12_345.0)
        decimals = market_features_from_decimal(
            [D(str(value)) for value in closes], D("12345")
        )
        for left, right in zip(floats, decimals, strict=True):
            assert left == pytest.approx(right, rel=1e-12)


class TestRewards:
    def test_long_earns_move_and_pays_entry_only_when_flat(self) -> None:
        flat_rewards = action_rewards(0.05, position_long=False, fee_per_side=0.001)
        long_rewards = action_rewards(0.05, position_long=True, fee_per_side=0.001)
        long_index = ACTIONS.index(ExposureAction.TARGET_LONG)
        # Already long: collect the move with no fee. Flat: pay to get in.
        assert long_rewards[long_index] == pytest.approx(0.05)
        assert flat_rewards[long_index] == pytest.approx(0.05 + math.log(0.999))

    def test_staying_flat_is_free_but_exiting_costs(self) -> None:
        flat_index = ACTIONS.index(ExposureAction.TARGET_FLAT)
        assert action_rewards(0.0, position_long=False, fee_per_side=0.001)[flat_index] == 0.0
        assert action_rewards(
            0.0, position_long=True, fee_per_side=0.001
        )[flat_index] == pytest.approx(math.log(0.999))

    def test_rejects_invalid_inputs(self) -> None:
        with pytest.raises(ValueError):
            action_rewards(float("nan"), position_long=False, fee_per_side=0.001)
        with pytest.raises(ValueError):
            action_rewards(0.0, position_long=False, fee_per_side=1.0)


class TestDecisionMapping:
    def test_target_long_maps_to_buy_or_hold(self) -> None:
        assert decision_for(ExposureAction.TARGET_LONG, False) == TradeDecision.BUY
        assert decision_for(ExposureAction.TARGET_LONG, True) == TradeDecision.HOLD

    def test_target_flat_maps_to_sell_or_hold(self) -> None:
        assert decision_for(ExposureAction.TARGET_FLAT, True) == TradeDecision.SELL
        assert decision_for(ExposureAction.TARGET_FLAT, False) == TradeDecision.HOLD


class TestPolicy:
    def test_update_increases_expected_reward(self) -> None:
        policy = RegimeMixturePolicy(regimes=3, learning_rate=0.1, init_seed=5)
        features = compose_features(
            market_features(_rising_closes(), 20_000.0), PortfolioState()
        )
        rewards = action_rewards(0.05, position_long=False, fee_per_side=0.001)
        first = policy.update(features, rewards)
        for _ in range(40):
            latest = policy.update(features, rewards)
        assert latest > first

    def test_learns_to_prefer_the_better_action(self) -> None:
        policy = RegimeMixturePolicy(regimes=2, learning_rate=0.1, init_seed=3)
        features = compose_features(
            market_features(_rising_closes(), 20_000.0), PortfolioState()
        )
        # A persistently positive move should push the policy toward exposure.
        for _ in range(200):
            policy.update(
                features, action_rewards(0.04, position_long=False, fee_per_side=0.001)
            )
        outcome = policy.decide(features, PortfolioState())
        assert outcome.action == ExposureAction.TARGET_LONG

    def test_regimes_are_not_degenerate_after_init(self) -> None:
        policy = RegimeMixturePolicy(regimes=4, init_seed=42)
        # Symmetry must be broken at construction, otherwise every expert receives
        # an identical gradient forever and the mixture collapses.
        assert len({tuple(row) for expert in policy.experts for row in expert}) > 1

    def test_persistence_round_trip_is_behaviour_identical(self, tmp_path: Path) -> None:
        policy = RegimeMixturePolicy(regimes=3, init_seed=9)
        features = compose_features(
            market_features(_rising_closes(), 20_000.0), PortfolioState()
        )
        for _ in range(25):
            policy.update(features, action_rewards(0.01, position_long=False, fee_per_side=0.001))
        path = tmp_path / "policy.json"
        policy.save(path)
        reloaded = RegimeMixturePolicy.load(path)
        before = policy.decide(features, PortfolioState())
        after = reloaded.decide(features, PortfolioState())
        assert before.action == after.action
        assert before.confidence == pytest.approx(after.confidence, rel=1e-15)
        assert before.regime_responsibilities == pytest.approx(
            after.regime_responsibilities, rel=1e-15
        )

    def test_rejects_foreign_feature_schema(self, tmp_path: Path) -> None:
        policy = RegimeMixturePolicy(regimes=2)
        payload = policy.to_dict()
        payload["feature_names"] = list(POLICY_FEATURE_NAMES[:-1])
        with pytest.raises(ValueError, match="feature schema mismatch"):
            RegimeMixturePolicy.from_dict(payload)

    def test_inference_is_deterministic(self) -> None:
        policy = RegimeMixturePolicy(regimes=3, init_seed=2)
        features = compose_features(
            market_features(_rising_closes(), 20_000.0), PortfolioState()
        )
        first = policy.decide(features, PortfolioState())
        second = policy.decide(features, PortfolioState())
        assert first.action == second.action
        assert first.confidence == second.confidence


class TestRuntimeGuards:
    def test_refuses_unpromoted_policy(self, tmp_path: Path) -> None:
        policy = RegimeMixturePolicy(regimes=2)
        policy.metadata = {"promotion_status": "PENDING_REVIEW"}
        path = tmp_path / "unpromoted.json"
        policy.save(path)
        with pytest.raises(ValueError, match="not promoted"):
            ExposureAgentRuntime(path)

    def test_allows_unpromoted_when_explicitly_opted_in(self, tmp_path: Path) -> None:
        policy = RegimeMixturePolicy(regimes=2)
        policy.metadata = {"promotion_status": "PENDING_REVIEW"}
        path = tmp_path / "unpromoted.json"
        policy.save(path)
        assert ExposureAgentRuntime(path, allow_unpromoted=True) is not None

    def test_perception_requires_full_daily_history(self, tmp_path: Path) -> None:
        agent = ExposureAgentRuntime(_promoted_policy(tmp_path))
        with pytest.raises(InsufficientPerception):
            agent.perceive(
                tuple(D("100") for _ in range(MIN_DAILY_HISTORY - 1)),
                D("100"),
                position_long=False,
                entry_price=None,
                holding_hours=0,
            )

    def test_cadence_read_from_model_metadata(self, tmp_path: Path) -> None:
        agent = ExposureAgentRuntime(_promoted_policy(tmp_path))
        assert agent.cadence == timedelta(hours=24)


class TestEngineIsAgentDriven:
    def _engine(self, tmp_path: Path) -> ExposureAgentEngine:
        agent = ExposureAgentRuntime(_promoted_policy(tmp_path))
        return ExposureAgentEngine(RealtimeParams(), agent)

    def test_unqualified_evidence_abstains(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        decision = engine.evaluate(
            _evidence(qualified=False, reason="DATA_STALE"), _position(PositionState.FLAT)
        )
        assert decision.action == Action.HOLD
        assert decision.reason == "DATA_STALE"

    def test_insufficient_perception_abstains_rather_than_guessing(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        short = tuple(D("100") for _ in range(10))
        decision = engine.evaluate(
            _evidence(daily=short), _position(PositionState.FLAT)
        )
        assert decision.action == Action.HOLD
        assert decision.reason == "PERCEPTION_INSUFFICIENT"

    def test_every_action_is_attributed_to_the_agent(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        decision = engine.evaluate(_evidence(), _position(PositionState.FLAT))
        # Whatever it decides, the reason must name the agent and its regime, so no
        # order can ever be traced back to a hand-written rule.
        assert decision.reason.startswith("AGENT_")
        assert engine.last_explanation["policy_version"]
        assert "dominant_regime" in engine.last_explanation

    def test_breaker_forces_exit_and_never_an_entry(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        # Establish a peak, then collapse equity to trip the drawdown breaker.
        engine.update_equity(D("10000"), NOW)
        flat = engine.evaluate(
            _evidence(at=NOW + timedelta(seconds=1)),
            _position(PositionState.FLAT, usdt="100"),
        )
        assert flat.action == Action.HOLD
        long_decision = engine.evaluate(
            _evidence(at=NOW + timedelta(seconds=2)),
            _position(PositionState.LONG, btc="0.005", usdt="0"),
        )
        assert long_decision.action == Action.EXIT_LONG

    def test_cadence_holds_a_repeated_commit(self, tmp_path: Path) -> None:
        # Train the policy to actually want exposure, so this exercises the cadence
        # gate instead of skipping when an untrained policy happens to prefer flat.
        policy = RegimeMixturePolicy(regimes=3, learning_rate=0.1, init_seed=11)
        features = compose_features(
            market_features(_rising_closes(), 20_000.0), PortfolioState()
        )
        for _ in range(300):
            policy.update(
                features, action_rewards(0.04, position_long=False, fee_per_side=0.001)
            )
        policy.metadata = {
            "promotion_status": "PROMOTED",
            "selection": {"chosen_config": "cadence=24h"},
        }
        path = tmp_path / "trained.json"
        policy.save(path)
        engine = ExposureAgentEngine(RealtimeParams(), ExposureAgentRuntime(path))

        first = engine.evaluate(_evidence(), _position(PositionState.FLAT))
        assert first.action == Action.ENTER_LONG, "policy should want exposure after training"

        second = engine.evaluate(
            _evidence(at=NOW + timedelta(minutes=5)), _position(PositionState.FLAT)
        )
        assert second.action == Action.HOLD
        assert second.reason.endswith("AWAITING_CADENCE")

        # Once the cadence has elapsed the agent may act again.
        third = engine.evaluate(
            _evidence(at=NOW + timedelta(hours=25)), _position(PositionState.FLAT)
        )
        assert third.action == Action.ENTER_LONG
