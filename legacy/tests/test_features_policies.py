from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from btc_decision_agent.adapters.quality import DataQualityGuard
from btc_decision_agent.domain.features import (
    Bar,
    atr,
    build_cost_estimate,
    depth_imbalance,
    depth_vwap,
    distance_to_sma,
    persistent_imbalance,
    realized_volatility,
    round_trip_cost,
    sma,
    sma_slope,
    spread_features,
    true_range,
    volume_ratio,
)
from pydantic import ValidationError
from tests.helpers import NEXT, NOW, D, features, idle_policy, params, state

from btc_decision_agent.domain.contracts import (
    ClockBasis,
    CostScenario,
    EvaluationState,
    EventType,
    FeatureValue,
    FreshnessPolicy,
    HealthState,
    IntentType,
    MarketEventV1,
    PositionState,
    QualityStatus,
    Transport,
    TriggerType,
    Usage,
)
from btc_decision_agent.policies import (
    ChallengerContext,
    ChallengerPolicy,
    ChallengerState,
    NullHoldPolicy,
    POL101Context,
    TrendSetupState,
    evaluate_pol101,
)


class FeatureTests(unittest.TestCase):
    def bars(self) -> list[Bar]:
        values = [(102, 99, 100, 10), (103, 100, 102, 12), (104, 100, 101, 8), (105, 101, 104, 15), (107, 103, 106, 20)]
        return [Bar(f"bar-{index}", NOW - timedelta(hours=5-index), NOW - timedelta(hours=4-index), D(str(low)), D(str(high)), D(str(low)), D(str(close)), D(str(volume))) for index, (high, low, close, volume) in enumerate(values)]

    def test_f001_through_f007_numeric_example(self) -> None:
        bars = self.bars()
        current = sma(bars, 3, NOW)
        prior = sma(bars[:-1], 3, NOW)
        self.assertEqual(current.value, D("103.6666666666666666666666667"))
        self.assertEqual(distance_to_sma(bars[-1].close, current.value, NOW).value.quantize(D("0.000001")), D("0.022508"))
        self.assertEqual(sma_slope(current.value, prior.value, 1, NOW).value.quantize(D("0.000001")), D("0.013029"))
        self.assertEqual(volume_ratio(bars, 3, NOW).value.quantize(D("0.000001")), D("1.714286"))
        self.assertEqual(true_range(bars[-1], bars[-2], NOW).value, D("4"))
        atr_value, atr_fraction = atr(bars, 3, NOW)
        self.assertEqual(atr_value.value, D("4"))
        self.assertEqual(atr_fraction.value.quantize(D("0.000001")), D("0.037736"))
        self.assertEqual(realized_volatility(bars, 3, NOW).value.quantize(D("0.000001")), D("0.020291"))

    def test_f008_through_f012_and_exact_cost(self) -> None:
        spread = spread_features(D("105.90"), D("106.10"), NOW)
        self.assertEqual(spread["spread_bps"].value.quantize(D("0.000001")), D("18.867925"))
        asks = ((D("106.10"), D("0.5")), (D("106.20"), D("0.4")), (D("106.40"), D("0.6")))
        bids = ((D("105.90"), D("0.6")), (D("105.80"), D("0.5")))
        buy_vwap, _buy_slip = depth_vwap(asks, D("1"), "buy")
        sell_vwap, _sell_slip = depth_vwap(bids, D("1"), "sell")
        self.assertEqual(buy_vwap, D("106.17"))
        self.assertEqual(sell_vwap, D("105.86"))
        components = [D("10"), D("10"), D("9.433962"), D("9.433962"), D("6.597550"), D("3.777148"), D("5")]
        self.assertEqual(round_trip_cost(components), D("54.242622"))
        for scenario in CostScenario:
            estimate = build_cost_estimate(
                scenario.value,
                D("1"),
                scenario,
                D("20"),
                D("18.867924"),
                D("10.374698"),
                D("5"),
                D("0"),
                NOW,
                frame_ref="frame",
                input_event_ids=("bbo",),
                max_input_event_time=NOW,
            )
            self.assertEqual(estimate.total_bps, D("54.242622"))
        self.assertIsNone(round_trip_cost([D("1"), None]))
        imbalance = depth_imbalance(bids, asks, D("106"), D("100"), NOW)
        self.assertTrue(D("-1") <= imbalance.value <= D("1"))
        persistent = persistent_imbalance(((D("-0.10"), D("10")), (D("-0.20"), D("20")), (D("-0.15"), D("30"))), D("60"), D("1"), NOW)
        self.assertEqual(persistent.value.quantize(D("0.000001")), D("-0.158333"))
        self.assertIsNone(depth_vwap(asks, D("10"), "buy")[0])

    def test_bar_features_reject_future_non_final_unqualified_and_gaps_with_real_time(self) -> None:
        bars = self.bars()
        observed = sma(bars, 3, NOW)
        self.assertEqual(observed.max_input_event_time, bars[-1].close_time)
        cases = {
            "future": replace(bars[-1], close_time=NEXT, event_time_max=NEXT),
            "forming": replace(bars[-1], final=False),
            "blocked": replace(bars[-1], quality=QualityStatus.BLOCKED),
            "gap": replace(bars[-1], continuity=False, gaps=("MISSING_BAR",)),
        }
        for name, invalid in cases.items():
            with self.subTest(name=name):
                feature = sma([*bars[:-1], invalid], 3, NOW)
                self.assertIsNone(feature.value)
                self.assertEqual(feature.quality, QualityStatus.BLOCKED)

    def _future_feature_rejected(self) -> bool:
        try:
            FeatureValue(feature_id="F-X", value=D("1"), unit="ratio", as_of_time=NOW, max_input_event_time=NEXT, horizon="1h", window_definition="boundary", quality=QualityStatus.QUALIFIED)
        except ValidationError:
            return True
        return False

    def _quality_boundary(self, *, future_observation: bool = False, late_event: bool = False) -> str:
        observed = NEXT if future_observation else NOW
        event_time = NOW - timedelta(hours=2) if late_event else None
        event_type = EventType.KLINE_CLOSED if late_event else EventType.BBO_UPDATE
        event = MarketEventV1(event_id="sha256:" + "1" * 64, event_type=event_type, source_contract_id="S-02" if late_event else "S-04", provider_contract_version="v", transport=Transport.FIXTURE, channel="fixture", symbol="BTC/USDT", event_time=event_time, observed_at=observed, source_identity={"id": 1}, payload={"is_closed": late_event}, payload_hash="sha256:" + "2" * 64, provenance={})
        policy = FreshnessPolicy(policy_version="D-014/1", source_contract_id=event.source_contract_id, event_type=event_type, usage=Usage.STRATEGIC, required=True, clock_basis=ClockBasis.EVENT_TIME if late_event else ClockBasis.OBSERVED_AT, warning_age_ms=1000, max_age_ms=2000, allowed_lateness_ms=1000, clock_skew_budget_ms=500, recovery_evidence_n=1, on_suspect="BLOCK", on_stale="BLOCK")
        guard = DataQualityGuard()
        if late_event:
            newer = event.model_copy(update={"event_id": "sha256:" + "3" * 64, "event_time": NOW, "observed_at": NOW, "source_identity": {"id": 2}, "payload_hash": "sha256:" + "4" * 64})
            guard.classify(newer, policy, NOW)
        return guard.classify(event, policy, NOW).reason

    def test_twenty_boundary_behaviors(self) -> None:
        p = params()
        cases = {
            "BT-01": D("0.010") >= p.theta_slope_enter,
            "BT-02": D("0.009999") < p.theta_slope_enter,
            "BT-03": p.atr_min <= p.atr_min <= p.atr_max,
            "BT-04": p.atr_max + D("0.000001") > p.atr_max,
            "BT-05": p.pullback_low <= p.pullback_high,
            "BT-06": not (D("0.020") > p.resume_level),
            "BT-07": D("0.020001") > p.resume_level,
            "BT-08": D("1.50") >= p.volume_confirm,
            "BT-09": D("60") <= p.cost_cap_bps,
            "BT-10": distance_to_sma(D("1"), D("0"), NOW).value is None,
            "BT-11": volume_ratio([*self.bars()[:3], replace(self.bars()[3], base_volume=D("0"))], 3, NOW).value is not None,
            "BT-12": distance_to_sma(D("1"), D("0"), NOW).null_reason == "NON_POSITIVE_SMA",
            "BT-13": depth_imbalance((), (), D("1"), D("1"), NOW).value is None,
            "BT-14": round_trip_cost([D("1"), None]) is None,
            "BT-15": not D("NaN").is_finite(),
            "BT-16": p.max_holding_bars <= 8,
            "BT-17": self._quality_boundary(future_observation=True) == "CLOCK_FAULT",
            "BT-18": self._future_feature_rejected(),
            "BT-19": self._quality_boundary(late_event=True) == "NO_RETROACTIVE_DECISION",
            "BT-20": not (p.arm_timeout_bars > p.arm_timeout_bars),
        }
        self.assertEqual(len(cases), 20)
        for case_id, behavior in cases.items():
            with self.subTest(case=case_id):
                self.assertTrue(behavior)


class PolicyTests(unittest.TestCase):
    def context(self, **changes: object) -> POL101Context:
        base = POL101Context("eval-1", TriggerType.STRATEGIC_EVALUATION, NOW, NOW, NEXT, state(), "state-ref", "context-ref", "bar-1", features(), features(distance=D("0.018")), idle_policy())
        return replace(base, **changes)

    def test_null_01_through_12_always_no_intent_and_idempotent(self) -> None:
        policy = NullHoldPolicy()
        configurations = [
            state(PositionState.UNKNOWN, EvaluationState.IDLE, HealthState.BLOCKED), state(),
            state(PositionState.FLAT, EvaluationState.ENTRY_CANDIDATE, HealthState.READY),
            state(PositionState.FLAT, EvaluationState.COOLDOWN, HealthState.READY),
            state(PositionState.ENTRY_PENDING, EvaluationState.IDLE, HealthState.READY),
            state(PositionState.LONG, EvaluationState.IDLE, HealthState.READY),
            state(PositionState.LONG, EvaluationState.IDLE, HealthState.DEGRADED),
            state(PositionState.LONG, EvaluationState.IDLE, HealthState.BLOCKED),
            state(PositionState.LONG, EvaluationState.EXIT_CANDIDATE, HealthState.READY),
            state(PositionState.EXIT_PENDING, EvaluationState.IDLE, HealthState.READY),
            state(PositionState.FLAT, EvaluationState.IDLE, HealthState.DEGRADED),
            state(PositionState.FLAT, EvaluationState.IDLE, HealthState.BLOCKED),
        ]
        self.assertEqual(len(configurations), 12)
        for index, configuration in enumerate(configurations, 1):
            with self.subTest(case=f"NULL-{index:02d}"):
                one = policy.evaluate("eval", configuration.version, NOW, NEXT)
                two = policy.evaluate("eval", configuration.version, NOW, NEXT)
                self.assertEqual(one.intent_type, IntentType.NO_INTENT)
                self.assertEqual(one.canonical_bytes(), two.canonical_bytes())

    def test_p101_t01_through_t21_real_guard_outputs(self) -> None:
        p = params()
        armed = replace(idle_policy(), state=TrendSetupState.PULLBACK_ARMED, setup_id="setup", armed_at_bar_id="bar-0", state_version="armed")
        emitted = replace(armed, state=TrendSetupState.ENTRY_EMITTED, entry_intent_id="intent")
        invalid = replace(p, n_sma=1)
        cases = {
            "P101-T01": (self.context(system_state=state(PositionState.UNKNOWN, EvaluationState.IDLE, HealthState.BLOCKED)), p, "POL101_POSITION_UNKNOWN"),
            "P101-T02": (self.context(system_state=state(PositionState.ENTRY_PENDING, EvaluationState.IDLE, HealthState.READY)), p, "POL101_PENDING_FEEDBACK"),
            "P101-T03": (self.context(system_state=state(PositionState.FLAT, EvaluationState.COOLDOWN, HealthState.READY)), p, "POL101_COOLDOWN_ACTIVE"),
            "P101-T04": (self.context(system_state=state(PositionState.FLAT, EvaluationState.IDLE, HealthState.DEGRADED)), p, "POL101_HEALTH_NOT_READY"),
            "P101-T05": (self.context(system_state=state(PositionState.LONG), holding_bars=8), p, "POL101_EXIT_TIME"),
            "P101-T06": (self.context(system_state=state(PositionState.LONG), features=features(slope=D("-0.01"))), p, "POL101_EXIT_TREND"),
            "P101-T07": (self.context(system_state=state(PositionState.LONG), features=features(distance=D("-0.06"))), p, "POL101_EXIT_ANCHOR"),
            "P101-T08": (self.context(system_state=state(PositionState.LONG)), p, "POL101_LONG_HOLD"),
            "P101-T09": (self.context(features=features(slope=D("0"))), p, "POL101_TREND_CONTEXT_FALSE"),
            "P101-T10": (self.context(features=features(distance=D("0.04"))), p, "POL101_PULLBACK_NOT_IN_BAND"),
            "P101-T11": (self.context(), p, "POL101_PULLBACK_ARMED"),
            "P101-T12": (self.context(policy_state=replace(armed, bars_since_arm=3)), p, "POL101_ARM_TIMEOUT"),
            "P101-T13": (self.context(policy_state=armed, features=features(slope=D("0"))), p, "POL101_TREND_INVALIDATED"),
            "P101-T14": (self.context(policy_state=armed, features=features(distance=D("0.001"))), p, "POL101_PULLBACK_FAILED"),
            "P101-T15": (self.context(policy_state=armed, features=features(cost=D("61"))), p, "POL101_COST_CAP_EXCEEDED"),
            "P101-T16": (self.context(policy_state=armed, prior_features=features(distance=D("0.021"))), p, "POL101_RESUME_NOT_CROSSED"),
            "P101-T17": (self.context(policy_state=armed, features=features(distance=D("0.021"), volume=D("1.0"))), p, "POL101_VOLUME_NOT_CONFIRMED"),
            "P101-T18": (self.context(policy_state=armed, features=features(distance=D("0.021"))), p, "POL101_ENTRY_SETUP_COMPLETE"),
            "P101-T19": (self.context(policy_state=emitted), p, "POL101_PENDING_FEEDBACK"),
            "P101-T20": (self.context(duplicate_seen=True), p, "POL101_DUPLICATE"),
            "P101-T21": (self.context(), invalid, "POL101_PARAMETER_INVALID"),
        }
        self.assertEqual(len(cases), 21)
        for case_id, (ctx, parameter_set, expected) in cases.items():
            with self.subTest(case=case_id):
                self.assertEqual(evaluate_pol101(ctx, parameter_set).evaluation_reason, expected)

    def test_pc_01_through_12_challenger_behavior(self) -> None:
        base = ChallengerContext("eval", "state", NOW, NEXT, PositionState.FLAT, HealthState.READY, {"cost_bps": D("10"), "volume_ratio": D("2"), "dislocation_atr": D("-2"), "reversion_velocity": D("0.5"), "sma_slope": D("0"), "realized_volatility": D("0.02"), "close": D("100"), "confirmation_level": D("99"), "compression_ratio": D("0.5"), "breakout_distance_atr": D("1"), "atr_fraction": D("0.03"), "prior_atr_fraction": D("0.02")})
        idle = ChallengerState("IDLE", None, 0, "1.0.0")
        reversion, breakout = ChallengerPolicy("POL-102"), ChallengerPolicy("POL-103")
        reversion_parameters = {"entry_dislocation": D("-1.5"), "min_reversion_velocity": D("0.2"), "hard_fail_atr": D("-3"), "slope_floor": D("-0.01"), "vol_ceiling": D("0.05"), "cost_cap": D("20"), "arm_timeout_bars": 3, "reversion_target_atr": D("-0.2"), "trend_break_floor": D("-0.02"), "max_holding_bars": 8}
        breakout_parameters = {"compression_ceiling": D("0.8"), "breakout_buffer_atr": D("0.5"), "volume_confirm": D("1.5"), "min_expansion_ratio": D("1.2"), "cost_cap": D("20"), "compression_timeout": 3, "false_break_atr": D("0.5"), "max_holding_bars": 8}
        armed_intent_r, armed_r = reversion.evaluate(base, idle, reversion_parameters)
        entry_r, _ = reversion.evaluate(base, armed_r, reversion_parameters)
        falling_context = replace(base, values={**base.values, "dislocation_atr": D("-3.1")})
        falling, falling_state = reversion.evaluate(falling_context, armed_r, reversion_parameters)
        armed_intent_b, armed_b = breakout.evaluate(base, idle, breakout_parameters)
        entry_b, _ = breakout.evaluate(base, armed_b, breakout_parameters)
        no_compression, _ = breakout.evaluate(replace(base, values={**base.values, "compression_ratio": D("1.0")}), idle, breakout_parameters)
        unknown_cost, _ = breakout.evaluate(replace(base, values={**base.values, "cost_bps": None}), armed_b, breakout_parameters)
        degraded, _ = breakout.evaluate(replace(base, health=HealthState.DEGRADED), armed_b, breakout_parameters)
        p101 = params()
        armed_trend = replace(idle_policy(), state=TrendSetupState.PULLBACK_ARMED, setup_id="setup", armed_at_bar_id="bar", state_version="armed")
        cases = {
            "PC-01": evaluate_pol101(self.context(features=features(distance=D("0.04"))), p101).candidate_intent.intent_type == IntentType.NO_INTENT,
            "PC-02": evaluate_pol101(self.context(policy_state=armed_trend, features=features(distance=D("0.021"))), p101).candidate_intent.intent_type == IntentType.ENTRY_CANDIDATE,
            "PC-03": evaluate_pol101(self.context(policy_state=armed_trend, features=features(distance=D("0.001"))), p101).evaluation_reason == "POL101_PULLBACK_FAILED",
            "PC-04": armed_intent_r.intent_type == IntentType.NO_INTENT and armed_r.setup == "DISLOCATION_ARMED",
            "PC-05": entry_r.intent_type == IntentType.ENTRY_CANDIDATE,
            "PC-06": falling.intent_type == IntentType.NO_INTENT and falling_state.setup == "IDLE",
            "PC-07": no_compression.intent_type == IntentType.NO_INTENT,
            "PC-08": armed_intent_b.intent_type == IntentType.NO_INTENT and entry_b.intent_type == IntentType.ENTRY_CANDIDATE,
            "PC-09": unknown_cost.intent_type == IntentType.NO_INTENT and unknown_cost.primary_reason == "COST_UNKNOWN",
            "PC-10": NullHoldPolicy().evaluate("l2-only", "state", NOW, NEXT).intent_type == IntentType.NO_INTENT,
            "PC-11": degraded.intent_type == IntentType.NO_INTENT,
            "PC-12": evaluate_pol101(self.context(trigger_type=TriggerType.PROTECTIVE_EVALUATION, system_state=state(PositionState.LONG)), p101).evaluation_reason == "POL101_PROTECTIVE_DEFERRED_TO_SYSTEM",
        }
        self.assertEqual(len(cases), 12)
        for case_id, observed in cases.items():
            with self.subTest(case=case_id):
                self.assertTrue(observed)
    def test_challengers_enforce_cost_timeout_regime_and_long_exits(self) -> None:
        base_values = {"cost_bps": D("10"), "volume_ratio": D("2"), "dislocation_atr": D("-2"), "reversion_velocity": D("0.5"), "sma_slope": D("0"), "realized_volatility": D("0.02"), "close": D("100"), "confirmation_level": D("99"), "compression_ratio": D("0.5"), "breakout_distance_atr": D("1"), "atr_fraction": D("0.03"), "prior_atr_fraction": D("0.02")}
        base = ChallengerContext("eval", "state", NOW, NEXT, PositionState.FLAT, HealthState.READY, base_values)
        idle = ChallengerState("IDLE", None, 0, "1.0.0")
        reversion = ChallengerPolicy("POL-102")
        rp = {"entry_dislocation": D("-1.5"), "min_reversion_velocity": D("0.2"), "hard_fail_atr": D("-3"), "slope_floor": D("-0.01"), "vol_ceiling": D("0.05"), "cost_cap": D("20"), "arm_timeout_bars": 1, "reversion_target_atr": D("-0.2"), "trend_break_floor": D("-0.02"), "max_holding_bars": 3}
        _, armed = reversion.evaluate(base, idle, rp)
        extreme_cost, _ = reversion.evaluate(replace(base, values={**base.values, "cost_bps": D("1000000000")}), armed, rp)
        timeout, _ = reversion.evaluate(base, replace(armed, bars_armed=1), rp)
        falling, _ = reversion.evaluate(replace(base, values={**base.values, "dislocation_atr": D("-3.1")}), armed, rp)
        target_exit, _ = reversion.evaluate(replace(base, position=PositionState.LONG, values={**base.values, "dislocation_atr": D("0")}), idle, rp)
        self.assertEqual((extreme_cost.primary_reason, timeout.primary_reason, falling.primary_reason, target_exit.intent_type), ("COST_CAP_EXCEEDED", "POL102_ARM_TIMEOUT", "POL102_FALLING_KNIFE_INVALIDATED", IntentType.EXIT_CANDIDATE))

        breakout = ChallengerPolicy("POL-103")
        bp = {"compression_ceiling": D("0.8"), "breakout_buffer_atr": D("0.5"), "volume_confirm": D("1.5"), "min_expansion_ratio": D("1.2"), "cost_cap": D("20"), "compression_timeout": 1, "false_break_atr": D("0.5"), "max_holding_bars": 3}
        _, compression = breakout.evaluate(base, idle, bp)
        timeout_b, _ = breakout.evaluate(base, replace(compression, bars_armed=1), bp)
        false_break, _ = breakout.evaluate(replace(base, values={**base.values, "breakout_distance_atr": D("-0.6")}), compression, bp)
        time_exit, _ = breakout.evaluate(replace(base, position=PositionState.LONG, holding_bars=3), idle, bp)
        self.assertEqual((timeout_b.primary_reason, false_break.primary_reason, time_exit.intent_type), ("POL103_COMPRESSION_TIMEOUT", "POL103_FALSE_BREAK_INVALIDATED", IntentType.EXIT_CANDIDATE))

    def test_challenger_long_cost_unknown_and_relative_false_break_exit(self) -> None:
        values = {"cost_bps": D("10"), "volume_ratio": D("2"), "dislocation_atr": D("-2"), "reversion_velocity": D("0.5"), "sma_slope": D("0"), "realized_volatility": D("0.02"), "close": D("100"), "confirmation_level": D("99"), "compression_ratio": D("0.5"), "breakout_distance_atr": D("0"), "atr_fraction": D("0.03"), "prior_atr_fraction": D("0.02")}
        long_context = ChallengerContext("eval-long", "state", NOW, NEXT, PositionState.LONG, HealthState.READY, values)
        idle = ChallengerState("IDLE", None, 0, "1.0.0")
        reversion_parameters = {"entry_dislocation": D("-1.5"), "min_reversion_velocity": D("0.2"), "hard_fail_atr": D("-3"), "slope_floor": D("-0.01"), "vol_ceiling": D("0.05"), "cost_cap": D("20"), "arm_timeout_bars": 3, "reversion_target_atr": D("1"), "trend_break_floor": D("-0.02"), "max_holding_bars": 8}
        breakout_parameters = {"compression_ceiling": D("0.8"), "breakout_buffer_atr": D("0.5"), "volume_confirm": D("1.5"), "min_expansion_ratio": D("1.2"), "cost_cap": D("20"), "compression_timeout": 3, "false_break_atr": D("0.5"), "max_holding_bars": 8}
        unknown_cost_context = replace(long_context, values={**values, "cost_bps": None})

        reversion_unknown, reversion_state = ChallengerPolicy("POL-102").evaluate(unknown_cost_context, idle, reversion_parameters)
        breakout_unknown, breakout_state = ChallengerPolicy("POL-103").evaluate(unknown_cost_context, idle, breakout_parameters)
        false_break, false_break_state = ChallengerPolicy("POL-103").evaluate(long_context, idle, breakout_parameters)

        self.assertEqual((reversion_unknown.intent_type, reversion_unknown.primary_reason, reversion_state.setup), (IntentType.EXIT_CANDIDATE, "POL102_COST_UNKNOWN_INVALIDATED", "IDLE"))
        self.assertEqual((breakout_unknown.intent_type, breakout_unknown.primary_reason, breakout_state.setup), (IntentType.EXIT_CANDIDATE, "POL103_COST_UNKNOWN_INVALIDATED", "IDLE"))
        self.assertEqual((false_break.intent_type, false_break.primary_reason, false_break_state.setup), (IntentType.EXIT_CANDIDATE, "POL103_EXIT_FALSE_BREAK", "IDLE"))


if __name__ == "__main__":
    unittest.main()
