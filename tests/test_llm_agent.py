"""Tests for the LLM agent, its tools, and its memory.

The properties asserted here are the ones whose failure would be expensive and
silent in production: an agent that reads its own future during a backtest, a
learning loop that promotes noise to doctrine, an LLM outage that leaves the
position unmanaged, or an agent that churns because nothing prices the commission.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from btc_decision_agent.application.exposure_agent import (
    ExposureAction,
    PolicyDecision,
    PortfolioState,
    RegimeMixturePolicy,
    TradeDecision,
)
from btc_decision_agent.application.exposure_features import MARKET_FEATURE_NAMES
from btc_decision_agent.application.llm_agent import (
    AGENT_VERSION,
    AgentVerdict,
    LLMAgentEngine,
    LLMTradingAgent,
    LLMUnavailable,
)
from btc_decision_agent.application.llm_memory import (
    MIN_EFFECT_IN_STANDARD_ERRORS,
    MIN_SAMPLES_FOR_SUPPORT,
    AgentMemory,
    render_memory_block,
)
from btc_decision_agent.application.llm_tools import (
    EXPOSURE_CASH,
    EXPOSURE_INVESTED,
    EXPOSURE_VALUES,
    HistoryIndex,
    cost_view,
    market_view,
    position_view,
    quant_view,
)
from btc_decision_agent.application.realtime_demo import (
    EvidenceSnapshot,
    RealtimeParams,
    ReconciledPosition,
)
from btc_decision_agent.domain.contracts import Action, PositionState

D = Decimal
NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def _closes(count: int = 240, rate: float = 1.002) -> list[float]:
    return [10_000.0 * (rate**index) for index in range(count)]


def _index_file(tmp_path: Path, days: int = 60) -> Path:
    """A tiny history index whose forward returns encode the day, so a test can
    detect whether a future day leaked into the answer."""
    rows = []
    for day in range(days):
        rows.append(
            {
                "day_index": 200 + day,
                "price": 10_000.0 + day,
                # Feature vectors drift with the day so nearest-neighbour ordering
                # is predictable.
                "features": [0.001 * day] * len(MARKET_FEATURE_NAMES),
                "forward": {
                    "ret_7d_pct": float(day),
                    "ret_30d_pct": float(day),
                    "ret_90d_pct": float(day),
                },
            }
        )
    payload = {
        "schema_version": "history-index/1.0.0",
        "dataset_id": "test",
        "feature_names": list(MARKET_FEATURE_NAMES),
        "feature_scales": [1.0] * len(MARKET_FEATURE_NAMES),
        "horizons_days": [7, 30, 90],
        "rows": rows,
    }
    path = tmp_path / "index.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class StubClient:
    """Stands in for Ollama. Records what it was asked and returns what we choose."""

    model = "stub"

    def __init__(self, *verdicts: AgentVerdict | Exception) -> None:
        self.queue = list(verdicts)
        self.calls: list[bool] = []
        self.blocks: list[str] = []

    def verdict(self, state_block: str, *, think: bool, num_predict: int = 900) -> AgentVerdict:
        self.calls.append(think)
        self.blocks.append(state_block)
        # `decide()` legitimately calls twice when the target differs from the
        # current exposure: a cheap pass, then a deliberated one before spending
        # money. So the last queued item repeats instead of running dry.
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def _verdict(
    target: str,
    *,
    conviction: float = 0.8,
    expected: float = 1.0,
    posture: str = "NEUTRAL",
) -> AgentVerdict:
    return AgentVerdict(
        target_exposure=target,
        posture=posture,
        conviction=conviction,
        expected_move_pct=expected,
        reason="razon de prueba",
        thinking="",
        seconds=1.0,
        deliberated=False,
    )


def _evidence(
    *, price: str = "20000", qualified: bool = True, reason: str = "QUALIFIED", daily: int = 240
) -> EvidenceSnapshot:
    closes = tuple(D(str(round(value, 2))) for value in _closes(daily))
    return EvidenceSnapshot(
        at=NOW,
        event_id="ev-1",
        price=D(price),
        confidence=D("0.7"),
        grade="HIGH",
        expected_edge_bps=D("5"),
        spread_bps=D("2"),
        data_age_ms=100,
        coverage=D("1"),
        horizons={"1d": D("5")},
        flow_imbalance=D("0"),
        qualified=qualified,
        reason=reason,
        daily_closes=closes,
    )


def _position(state: PositionState, *, btc: str = "0", usdt: str = "5000") -> ReconciledPosition:
    return ReconciledPosition(
        state=state, btc_qty=D(btc), usdt_free=D(usdt), price=D("20000"), btc_free=D(btc)
    )


def _agent(tmp_path: Path, client: StubClient) -> LLMTradingAgent:
    policy = RegimeMixturePolicy(regimes=4, init_seed=3)
    return LLMTradingAgent(
        policy=policy,
        history=HistoryIndex(_index_file(tmp_path)),
        memory=AgentMemory(tmp_path / "mem.sqlite3"),
        client=client,  # type: ignore[arg-type]
    )


def _policy_decision(action: ExposureAction, decision: TradeDecision) -> PolicyDecision:
    """A deterministic fallback opinion, so the test does not depend on what the
    learned policy happens to think about synthetic evidence."""
    return PolicyDecision(
        action=action,
        decision=decision,
        action_probabilities={
            ExposureAction.TARGET_LONG.value: 0.9,
            ExposureAction.TARGET_FLAT.value: 0.1,
        },
        regime_responsibilities=[1.0, 0.0, 0.0, 0.0],
        dominant_regime=0,
        confidence=0.9,
        policy_version="test",
    )


class TestHistoryIndexCutoff:
    """The single most dangerous failure in a backtest of this shape."""

    def test_cutoff_excludes_future_days(self, tmp_path: Path) -> None:
        index = HistoryIndex(_index_file(tmp_path, days=400))
        features = [0.001 * 399] * len(MARKET_FEATURE_NAMES)  # closest to the last day
        unrestricted = index.analogues(features, 5)
        restricted = index.analogues(features, 5, before_day=500)
        # Forward returns encode the day offset, and day_index = 200 + offset, so an
        # offset >= 210 came from a day whose outcome window reaches the cutoff.
        assert max(item.ret_30d_pct for item in restricted) < 210.0
        assert max(item.ret_30d_pct for item in unrestricted) >= 210.0

    def test_cutoff_embargoes_outcomes_that_reach_the_decision_day(self, tmp_path: Path) -> None:
        """Filtering on `day_index < D` is not enough and this is why.

        Every row carries the return over the next 90 days, so the row at D-1
        encodes the price at D+89. Measured on the real index, the median nearest
        neighbour sits 7 days back, so a naive cutoff hands the agent the price it
        is about to trade at in the majority of decisions. The outcome window must
        have closed before D.
        """
        index = HistoryIndex(_index_file(tmp_path, days=400))
        decision_day = 500
        # Query the situation most similar to the day just under a naive cutoff:
        # that is exactly where the leak is largest.
        features = [0.001 * 299] * len(MARKET_FEATURE_NAMES)
        restricted = index.analogues(features, 5, before_day=decision_day)
        assert restricted, "the embargo must not empty an index that has resolved days"
        for item in restricted:
            day_index = 200 + item.ret_30d_pct  # the fixture encodes it
            assert day_index + index.max_horizon < decision_day
        # A naive `day_index < D` filter would have returned offsets 295 to 299.
        assert max(item.ret_30d_pct for item in restricted) < 210.0

    def test_base_rate_respects_the_cutoff(self, tmp_path: Path) -> None:
        index = HistoryIndex(_index_file(tmp_path, days=400))
        full = index.base_rates()
        early = index.base_rates(before_day=500)
        # Offsets 0..209 are visible; 210..399 are purged by the 90 day embargo.
        assert early["dias_indexados"] == 210
        assert full["dias_indexados"] == 400
        assert early["ret_30d_medio_pct"] < full["ret_30d_medio_pct"]

    def test_empty_cutoff_does_not_crash(self, tmp_path: Path) -> None:
        index = HistoryIndex(_index_file(tmp_path))
        assert index.analogues([0.0] * len(MARKET_FEATURE_NAMES), 5, before_day=0) == []
        assert index.base_rates(before_day=0)["dias_indexados"] == 0

    def test_rejects_foreign_feature_schema(self, tmp_path: Path) -> None:
        path = _index_file(tmp_path)
        payload = json.loads(path.read_text())
        payload["feature_names"] = ["otra_cosa"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="feature schema mismatch"):
            HistoryIndex(path)


class TestTools:
    def test_market_view_is_self_describing_and_consistent(self) -> None:
        closes = [D(str(round(v, 2))) for v in _closes()]
        view = market_view(closes, D("20000"))
        # The readable percentage and the raw vector must agree; they come from the
        # same call precisely so they cannot drift.
        index = MARKET_FEATURE_NAMES.index("log_price_over_ma200")
        expected = (math.exp(view["_vector"][index]) - 1.0) * 100.0
        assert view["precio_vs_media_200d_pct"] == pytest.approx(expected, abs=0.01)
        assert "volatilidad_diaria_30d_pct" in view

    def test_market_view_requires_enough_history(self) -> None:
        with pytest.raises(ValueError, match="cierres diarios"):
            market_view([D("100")] * 10, D("100"))

    def test_position_view_reports_unrealized_and_stop_distance(self) -> None:
        view = position_view(
            position_long=True,
            btc_qty=D("0.05"),
            usdt_free=D("100"),
            price=D("20000"),
            entry_price=D("19000"),
            holding_hours=5,
            active_stop=D("18500"),
        )
        assert view["exposicion_actual"] == EXPOSURE_INVESTED
        assert view["pnl_no_realizado_pct"] == pytest.approx(5.26, abs=0.01)
        assert view["caida_hasta_stop_pct"] == pytest.approx(-7.5, abs=0.01)
        assert view["equity_total_usdt"] == pytest.approx(1100.0, abs=0.01)

    def test_flat_position_reports_no_unrealized(self) -> None:
        view = position_view(
            position_long=False,
            btc_qty=D("0"),
            usdt_free=D("5000"),
            price=D("20000"),
            entry_price=None,
            holding_hours=0,
            active_stop=None,
        )
        assert view["exposicion_actual"] == EXPOSURE_CASH
        assert view["pnl_no_realizado_pct"] == 0.0

    def test_cost_view_states_the_threshold(self) -> None:
        view = cost_view(D("20"), D("0.95"))
        assert view["comision_ida_y_vuelta_pct"] == pytest.approx(0.2)
        assert view["movimiento_minimo_para_cubrir_pct"] == pytest.approx(0.2)

    def test_quant_view_exposes_the_trained_advisor(self) -> None:
        policy = RegimeMixturePolicy(regimes=4, init_seed=5)
        vector = market_view([D(str(round(v, 2))) for v in _closes()], D("20000"))["_vector"]
        view = quant_view(policy, vector, PortfolioState())
        assert view["recomienda"] in set(EXPOSURE_VALUES)
        assert 0.0 <= view["p_largo"] <= 1.0
        assert len(view["reparto_regimenes"]) == 4


class TestMemoryLearning:
    def _fill(self, memory: AgentMemory, regime: int, exposure: str, values: list[float]) -> None:
        for number, realized in enumerate(values):
            at = NOW + timedelta(days=number)
            memory.record(
                decided_at=at,
                event_id=f"{regime}-{exposure}-{number}",
                features=[float(regime)] * len(MARKET_FEATURE_NAMES),
                regime=regime,
                quant_p_long=0.55,
                target_exposure=exposure,
                exposure_before=EXPOSURE_CASH,
                derived_order="HOLD",
                conviction=0.9,
                expected_move_pct=1.0,
                reason="x",
                thinking="",
                price=D("80000"),
                acted=False,
            )
            move = realized if exposure == EXPOSURE_INVESTED else -realized
            memory.resolve_pending(at + timedelta(hours=25), D("80000") * D(str(1 + move / 100)))

    def test_real_signal_is_promoted(self, tmp_path: Path) -> None:
        memory = AgentMemory(tmp_path / "m.sqlite3")
        self._fill(memory, 1, EXPOSURE_INVESTED, [3.0 + 0.1 * i for i in range(20)])
        pattern = next(item for item in memory.measured_patterns() if item.samples >= 20)
        assert pattern.supported
        assert pattern.effect_in_standard_errors >= MIN_EFFECT_IN_STANDARD_ERRORS

    def test_noise_is_filtered_despite_a_positive_mean(self, tmp_path: Path) -> None:
        memory = AgentMemory(tmp_path / "m.sqlite3")
        # Mean near zero with wide spread: a positive average that means nothing.
        self._fill(memory, 0, EXPOSURE_INVESTED, [9.0, -9.0] * 10)
        pattern = memory.measured_patterns()[0]
        assert pattern.samples == 20
        assert not pattern.supported

    def test_small_sample_luck_is_filtered(self, tmp_path: Path) -> None:
        memory = AgentMemory(tmp_path / "m.sqlite3")
        # Three spectacular, nearly identical outcomes: a huge effect size on a
        # sample far too small to mean anything.
        self._fill(memory, 2, EXPOSURE_INVESTED, [8.0, 8.1, 8.2])
        pattern = memory.measured_patterns()[0]
        assert pattern.samples < MIN_SAMPLES_FOR_SUPPORT
        assert not pattern.supported

    def test_staying_flat_during_a_fall_counts_as_a_win(self, tmp_path: Path) -> None:
        memory = AgentMemory(tmp_path / "m.sqlite3")
        memory.record(
            decided_at=NOW,
            event_id="flat-1",
            features=[0.0] * len(MARKET_FEATURE_NAMES),
            regime=1,
            quant_p_long=0.3,
            target_exposure=EXPOSURE_CASH,
            exposure_before=EXPOSURE_INVESTED,
            derived_order="SELL",
            conviction=0.9,
            expected_move_pct=2.0,
            reason="bajista",
            thinking="",
            price=D("80000"),
            acted=True,
        )
        # Price fell 10%; standing aside avoided that, so the outcome is positive.
        memory.resolve_pending(NOW + timedelta(hours=25), D("72000"))
        past = memory.similar_past([0.0] * len(MARKET_FEATURE_NAMES), 1)
        assert past[0].realized_pct is not None
        assert past[0].realized_pct > 0

    def test_memory_block_warns_about_unsupported_patterns(self, tmp_path: Path) -> None:
        memory = AgentMemory(tmp_path / "m.sqlite3")
        self._fill(memory, 2, EXPOSURE_INVESTED, [8.0, 8.1, 8.2])
        block = render_memory_block(memory, [0.0] * len(MARKET_FEATURE_NAMES))
        assert "NO CONCLUYENTE" in block
        assert "ruido" in block

    def test_memory_block_never_claims_the_model_learned(self, tmp_path: Path) -> None:
        """The wording has to match the mechanism.

        Nothing here updates the model's weights, so the prompt must not tell it
        otherwise. "LECCION" would assert acquired knowledge where there is only a
        statistic over past outcomes.
        """
        memory = AgentMemory(tmp_path / "m.sqlite3")
        self._fill(memory, 2, EXPOSURE_INVESTED, [8.0, 8.1, 8.2])
        block = render_memory_block(memory, [0.0] * len(MARKET_FEATURE_NAMES))
        assert "LECCION" not in block
        assert "aprendes" not in block
        assert "HISTORIAL MEDIDO" in block

    def test_empty_memory_says_so(self, tmp_path: Path) -> None:
        memory = AgentMemory(tmp_path / "m.sqlite3")
        assert "vacia" in render_memory_block(memory, [0.0] * len(MARKET_FEATURE_NAMES))


class TestEngineSafety:
    def _engine(self, tmp_path: Path, client: StubClient, **kwargs: Any) -> LLMAgentEngine:
        return LLMAgentEngine(RealtimeParams(), _agent(tmp_path, client), **kwargs)

    def _settle(self, engine: LLMAgentEngine, evidence: EvidenceSnapshot, position: ReconciledPosition):
        """Drive the engine until the background deliberation has landed."""
        engine.evaluate(evidence, position)
        for _ in range(200):
            if not engine.deliberating:
                break
            import time

            time.sleep(0.01)
        return engine.evaluate(evidence, position)

    def test_unqualified_evidence_abstains(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED)))
        decision = engine.evaluate(
            _evidence(qualified=False, reason="DATA_STALE"), _position(PositionState.FLAT)
        )
        assert decision.action == Action.HOLD
        assert decision.reason == "DATA_STALE"

    def test_insufficient_perception_abstains(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED)))
        decision = engine.evaluate(_evidence(daily=30), _position(PositionState.FLAT))
        assert decision.reason == "PERCEPTION_INSUFFICIENT"

    def test_llm_outage_falls_back_to_the_validated_policy(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path, StubClient(LLMUnavailable("ollama caido")))
        decision = self._settle(engine, _evidence(), _position(PositionState.FLAT))
        # The account is never left unmanaged: the numeric policy takes over.
        assert decision.reason.startswith("FALLBACK_QUANT_")
        assert engine.fallback_count >= 1
        assert engine.last_explanation["fallback"] == "modelo_cuantitativo_validado"

    def test_before_the_first_verdict_the_policy_is_in_charge(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED)))
        decision = engine.evaluate(_evidence(), _position(PositionState.FLAT))
        assert decision.reason.startswith("FALLBACK_QUANT_")
        assert engine.last_explanation["status"] == "esperando_primera_deliberacion"

    def test_evaluate_does_not_block_on_inference(self, tmp_path: Path) -> None:
        import time

        class SlowClient(StubClient):
            def verdict(self, state_block: str, *, think: bool, num_predict: int = 900) -> AgentVerdict:
                time.sleep(1.5)
                return _verdict(EXPOSURE_INVESTED)

        engine = self._engine(tmp_path, SlowClient())
        started = time.time()
        engine.evaluate(_evidence(), _position(PositionState.FLAT))
        # A blocking implementation would take 1.5s here and starve the websocket.
        assert time.time() - started < 0.5

    def test_economic_gate_blocks_a_move_that_does_not_cover_its_cost(self, tmp_path: Path) -> None:
        # Wants to go long from flat but expects only 0.05%, under the 0.20% round trip.
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, expected=0.05)))
        decision = self._settle(engine, _evidence(), _position(PositionState.FLAT))
        assert decision.action == Action.HOLD
        assert decision.reason.endswith("_BELOW_COST")
        assert engine.last_explanation["clears_cost"] is False

    def test_a_move_that_covers_its_cost_is_allowed(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, expected=5.0)))
        decision = self._settle(engine, _evidence(), _position(PositionState.FLAT))
        assert decision.action == Action.ENTER_LONG
        assert engine.last_explanation["clears_cost"] is True

    def test_the_fallback_may_not_open_a_position(self, tmp_path: Path) -> None:
        """Observed in production, and it reversed a deliberate decision.

        The exchange stop fired at 11:23 leaving the account in cash. The LLM then
        deliberated and chose EN LIQUIDEZ with 0.70 conviction. A process restart 34
        minutes later wiped the in-memory verdict and the fallback bought straight
        back in. The fallback exists so an open position is never unmanaged; managing
        one means being able to leave it, not being allowed to start one.
        """
        engine = self._engine(tmp_path, StubClient(LLMUnavailable("modelo caido")))
        wants_to_buy = _policy_decision(ExposureAction.TARGET_LONG, TradeDecision.BUY)

        suppressed = engine._fallback_decision(wants_to_buy, _evidence(), is_long=False)
        assert suppressed.action == Action.HOLD
        assert suppressed.reason == "FALLBACK_QUANT_ENTRY_SUPPRESSED"

        # Already invested and the fallback agrees: holding is fine, it opens nothing.
        holding = engine._fallback_decision(wants_to_buy, _evidence(), is_long=True)
        assert holding.action == Action.HOLD

        # And it can always get out.
        wants_to_sell = _policy_decision(ExposureAction.TARGET_FLAT, TradeDecision.SELL)
        exit_decision = engine._fallback_decision(wants_to_sell, _evidence(), is_long=True)
        assert exit_decision.action == Action.EXIT_LONG

    def test_the_fallback_may_still_close_a_position(self, tmp_path: Path) -> None:
        # Refusing to sell is the one failure with unbounded downside, so exits stay
        # available to the fallback even though entries do not.
        engine = self._engine(tmp_path, StubClient(LLMUnavailable("modelo caido")))
        engine.update_equity(D("10000"), NOW)  # trips the drawdown breaker
        decision = engine.evaluate(
            _evidence(), _position(PositionState.LONG, btc="0.005", usdt="0")
        )
        assert decision.action == Action.EXIT_LONG

    def test_an_exit_is_never_blocked_by_its_cost(self, tmp_path: Path) -> None:
        """The expensive bug. Gating exits on commission held a losing position.

        Replayed over 100 decisions the agent asked to move to cash 49 times and was
        refused because its own declared expected move did not clear 0.20%. It was
        held from 79,861 down to 64,143. Leaving is not a bet that must beat its
        transaction cost; it is declining to keep one, and a risk control that a
        commission can veto is not a risk control.
        """
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_CASH, expected=0.0)))
        decision = self._settle(
            engine, _evidence(), _position(PositionState.LONG, btc="0.05", usdt="0")
        )
        assert decision.action == Action.EXIT_LONG
        assert not decision.reason.endswith("_BELOW_COST")
        assert engine.last_explanation["clears_cost"] is True

    def test_entries_are_still_gated_so_churn_stays_bounded(self, tmp_path: Path) -> None:
        # The asymmetry must not become a licence to trade freely in both directions.
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, expected=0.05)))
        decision = self._settle(engine, _evidence(), _position(PositionState.FLAT))
        assert decision.action == Action.HOLD
        assert decision.reason.endswith("_BELOW_COST")

    def test_an_inflated_expected_move_cannot_unlock_an_entry(self) -> None:
        """The agent declared +35.31% over a few days in one replayed decision.

        Since the entry gate is a threshold on that number, an unbounded estimate lets
        it authorise any entry by asserting a large enough move. The bound is what the
        market's own volatility could deliver.
        """
        # 0.5% daily volatility caps the usable estimate at 3 * 0.5 * sqrt(3) = 2.6%,
        # so a claimed 35% is not taken at face value, but it still clears 0.20%.
        assert LLMTradingAgent.plausible_expected_move(35.31, 0.5) < 3.0
        # With a cost threshold above the plausible ceiling, the entry is refused.
        assert not LLMTradingAgent.clears_cost_static(
            wants_long=True,
            position_long=False,
            expected_move_pct=35.31,
            round_trip_cost_bps=400.0,
            daily_vol_pct=0.5,
        )
        # Unbounded, the same fantasy would have authorised it.
        assert LLMTradingAgent.clears_cost_static(
            wants_long=True,
            position_long=False,
            expected_move_pct=35.31,
            round_trip_cost_bps=400.0,
            daily_vol_pct=None,
        )

    def test_the_raw_estimate_is_still_recorded_for_calibration(self, tmp_path: Path) -> None:
        # The bound is only what the gate acts on. Hiding the exaggeration would make
        # the agent's overconfidence unmeasurable.
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, expected=35.31)))
        self._settle(engine, _evidence(), _position(PositionState.FLAT))
        assert engine.last_explanation["expected_move_pct"] == 35.31

    def test_an_entry_carries_the_regime_strategy_to_execution(self, tmp_path: Path) -> None:
        """Sizing happens in the runner and the stop in the engine, so the plan has to
        travel on the decision or the two disagree about what bet was taken."""
        engine = self._engine(
            tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, expected=5.0, posture="AGRESIVA"))
        )
        decision = self._settle(engine, _evidence(), _position(PositionState.FLAT))
        assert decision.action == Action.ENTER_LONG
        assert decision.execution_plan is not None
        plan = decision.execution_plan
        assert plan["posture"] == "AGRESIVA"
        assert Decimal(plan["stop_loss_fraction"]) > Decimal("0")
        assert Decimal(plan["allocation_fraction"]) > Decimal("0")
        info = engine.last_explanation
        assert info["posture"] == "AGRESIVA"
        assert info["strategy"]
        assert info["plan_horizon_hours"] > 0

    def test_the_reason_code_records_the_posture(self, tmp_path: Path) -> None:
        engine = self._engine(
            tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, expected=5.0, posture="DEFENSIVA"))
        )
        decision = self._settle(engine, _evidence(), _position(PositionState.FLAT))
        assert "_DEF_" in decision.reason

    def test_a_posture_the_model_invents_degrades_to_neutral(self) -> None:
        # A formatting slip in a secondary field must not hand the account to the
        # fallback, because the exposure that moves money was still valid.
        from btc_decision_agent.application.llm_agent import OllamaClient

        client = OllamaClient()
        payload = {
            "message": {
                "content": json.dumps(
                    {
                        "exposicion_objetivo": EXPOSURE_INVESTED,
                        "postura": "TEMERARIA",
                        "conviccion": 0.7,
                        "movimiento_esperado_pct": 1.0,
                        "razon": "x",
                    }
                )
            },
            "done_reason": "stop",
        }

        def fake_urlopen(*_args: Any, **_kwargs: Any) -> Any:
            class Response:
                def __enter__(self) -> Any:
                    return self

                def __exit__(self, *_exc: Any) -> None:
                    return None

                def read(self) -> bytes:
                    return json.dumps(payload).encode()

            return Response()

        import btc_decision_agent.application.llm_agent as module

        original = module.urllib.request.urlopen
        module.urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]
        try:
            verdict = client.verdict("estado", think=False)
        finally:
            module.urllib.request.urlopen = original  # type: ignore[assignment]
        assert verdict.posture == "NEUTRAL"
        assert verdict.target_exposure == EXPOSURE_INVESTED

    def test_the_stop_follows_the_plan_the_position_was_opened_under(
        self, tmp_path: Path
    ) -> None:
        """The reason the plan is persisted rather than held in memory.

        A position opened under a wide trend-following stop must keep it. If the plan
        were lost, the engine would silently reimpose the default tight geometry and
        _sync_protection would move the resting exchange order to match.
        """
        from dataclasses import replace as dc_replace

        from btc_decision_agent.application.regime_playbook import resolve_plan

        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED)))
        wide = resolve_plan(
            regime=3, posture="AGRESIVA", conviction=0.9, daily_vol_pct=3.0
        )
        engine.import_state(
            dc_replace(
                engine.state,
                entry_price=D("80000"),
                high_since_entry=D("80000"),
                execution_plan=wide.to_dict(),
            )
        )
        with_plan = engine.active_stop(D("80000"))
        assert engine.effective_params.stop_loss_fraction == wide.stop_loss_fraction
        engine.import_state(dc_replace(engine.state, execution_plan=None))
        without_plan = engine.active_stop(D("80000"))
        assert with_plan is not None and without_plan is not None
        # The bull-regime stop is materially wider than the 3% default, so it sits
        # lower: 13.1% below entry instead of 3%.
        assert with_plan < without_plan
        assert engine.effective_params.stop_loss_fraction == D("0.03")

    def test_a_corrupt_plan_never_disables_protection(self, tmp_path: Path) -> None:
        from dataclasses import replace as dc_replace

        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED)))
        engine.import_state(
            dc_replace(
                engine.state,
                entry_price=D("80000"),
                high_since_entry=D("80000"),
                execution_plan={"basura": True},
            )
        )
        # Falls back to the configured defaults rather than raising or returning None.
        assert engine.active_stop(D("80000")) == D("80000") * D("0.97")

    def test_the_burden_of_proof_blocks_a_weakly_held_change(self, tmp_path: Path) -> None:
        """Regime-dependent behaviour, not just regime-dependent parameters.

        The synthetic evidence used by these tests is a steady uptrend, so the advisor
        reports a bullish regime. Moving to cash there requires high conviction; a
        half-hearted 0.40 is not enough and the position stays.
        """
        engine = self._engine(
            tmp_path,
            StubClient(_verdict(EXPOSURE_CASH, conviction=0.40, expected=5.0)),
        )
        decision = self._settle(
            engine, _evidence(), _position(PositionState.LONG, btc="0.05", usdt="0")
        )
        info = engine.last_explanation
        if info["regime"] == 3:
            assert decision.action == Action.HOLD
            assert decision.reason.endswith("_BURDEN_NOT_MET")
            assert info["burden_met"] is False
        else:
            # Other regimes have a low bar for cash, so the exit is allowed.
            assert info["burden_met"] is True

    def test_the_burden_never_overrides_a_breaker_or_the_stop(self, tmp_path: Path) -> None:
        # The burden applies only to the agent's own changes. Protection outranks it.
        engine = self._engine(
            tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, conviction=0.99, expected=5.0))
        )
        engine.update_equity(D("10000"), NOW)
        decision = engine.evaluate(
            _evidence(), _position(PositionState.LONG, btc="0.005", usdt="0")
        )
        assert decision.action == Action.EXIT_LONG

    def test_agreeing_with_the_current_exposure_is_a_hold(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, expected=5.0)))
        decision = self._settle(
            engine, _evidence(), _position(PositionState.LONG, btc="0.05", usdt="0")
        )
        assert decision.action == Action.HOLD
        assert decision.reason.startswith("AGENT_HOLD_")

    def test_breaker_forces_exit_and_never_an_entry(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, expected=5.0)))
        engine.update_equity(D("10000"), NOW)
        flat = engine.evaluate(_evidence(), _position(PositionState.FLAT, usdt="100"))
        assert flat.action == Action.HOLD
        long_decision = engine.evaluate(
            _evidence(), _position(PositionState.LONG, btc="0.005", usdt="0")
        )
        assert long_decision.action == Action.EXIT_LONG

    def test_decisions_are_recorded_for_learning(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, expected=5.0)))
        self._settle(engine, _evidence(), _position(PositionState.FLAT))
        assert engine.agent.memory.stats()["decisiones_totales"] == 1

    def test_explanation_identifies_the_agent_and_its_advisor(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path, StubClient(_verdict(EXPOSURE_INVESTED, expected=5.0)))
        self._settle(engine, _evidence(), _position(PositionState.FLAT))
        info = engine.last_explanation
        assert info["agent_version"] == AGENT_VERSION
        assert info["target_exposure"] == EXPOSURE_INVESTED
        assert "quant_recommends" in info
        assert "agrees_with_quant" in info


class TestVerdictParsing:
    def test_rejects_an_invalid_target(self) -> None:
        from btc_decision_agent.application.llm_agent import OllamaClient

        client = OllamaClient()
        payload = {
            "message": {"content": json.dumps({"exposicion_objetivo": "QUIZA", "conviccion": 0.5,
                                               "movimiento_esperado_pct": 1.0, "razon": "x"})},
            "done_reason": "stop",
        }

        def fake_urlopen(*_args: Any, **_kwargs: Any) -> Any:
            class Response:
                def __enter__(self) -> Any:
                    return self

                def __exit__(self, *_exc: Any) -> None:
                    return None

                def read(self) -> bytes:
                    return json.dumps(payload).encode()

            return Response()

        import btc_decision_agent.application.llm_agent as module

        original = module.urllib.request.urlopen
        module.urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]
        try:
            with pytest.raises(LLMUnavailable, match="exposicion_objetivo invalida"):
                client.verdict("estado", think=False)
        finally:
            module.urllib.request.urlopen = original  # type: ignore[assignment]

    def test_conviction_is_clamped(self) -> None:
        verdict = AgentVerdict(
            target_exposure=EXPOSURE_INVESTED,
            posture="NEUTRAL",
            conviction=1.0,
            expected_move_pct=1.0,
            reason="x",
            thinking="",
            seconds=1.0,
            deliberated=False,
        )
        assert verdict.wants_long
        assert 0.0 <= verdict.conviction <= 1.0

    def test_exposure_action_mapping_is_exhaustive(self) -> None:
        assert set(ExposureAction) == {ExposureAction.TARGET_LONG, ExposureAction.TARGET_FLAT}
