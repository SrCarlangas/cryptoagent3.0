from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from btc_decision_agent.adapters.ledger import JsonlDecisionLedger
from btc_decision_agent.application.offline_pipeline import (
    OfflineDecisionService,
    OfflinePipelineRequest,
)
from btc_decision_agent.application.services import DecisionPipeline
from tests.helpers import NEXT, NOW, D, idle_policy, params, portfolio, product, risk, state

from btc_decision_agent.domain.contracts import Action, RawMarketEvent
from btc_decision_agent.policies import TrendSetupState


def epoch_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def kline(index: int, open_at: datetime, close_at: datetime, high: str, low: str, close: str, volume: str) -> RawMarketEvent:
    values = [epoch_ms(open_at), low, high, low, close, volume, epoch_ms(close_at), "1000", 10]
    return RawMarketEvent(source_contract_id="S-03", channel=f"fixture:kline:{index}", observed_at=close_at + timedelta(milliseconds=100) if close_at < NOW else NOW, raw_payload={"symbol": "BTCUSDT", "interval": "1h", "kline": values}, raw_ref=f"fixture:bar:{index}")


def fixture_events(*, stale_bbo: bool = False, gap: bool = False, duplicate_bbo: bool = False, bbo_lag_ms: int = 0) -> tuple[RawMarketEvent, ...]:
    values = [("102", "99", "100", "10"), ("103", "100", "102", "12"), ("104", "100", "101", "8"), ("105", "101", "104", "15"), ("107", "103", "106", "20")]
    bars = []
    for index, (high, low, close, volume) in enumerate(values):
        open_at = NOW - timedelta(hours=5 - index)
        if gap and index == 3:
            open_at += timedelta(minutes=30)
        close_at = open_at + timedelta(hours=1)
        bars.append(kline(index, open_at, close_at, high, low, close, volume))
    observed = NOW - timedelta(seconds=3) if stale_bbo else NOW - timedelta(milliseconds=bbo_lag_ms)
    bbo = RawMarketEvent(source_contract_id="S-04", channel="fixture:bbo", observed_at=observed, raw_payload={"u": 100, "s": "BTCUSDT", "b": "105.90", "B": "2", "a": "106.10", "A": "2"}, raw_ref="fixture:bbo:100")
    return (*bars, bbo, bbo) if duplicate_bbo else (*bars, bbo)


def request(*, events: tuple[RawMarketEvent, ...] | None = None, observations=None) -> OfflinePipelineRequest:
    armed = replace(idle_policy(), state=TrendSetupState.PULLBACK_ARMED, setup_id="setup", armed_at_bar_id="bar-3", state_version="armed")
    return OfflinePipelineRequest(raw_events=events or fixture_events(), portfolio_observations=(portfolio(),) if observations is None else observations, system_state=state(), product_mandate=product(), risk_mandate=risk(), policy_state=armed, parameters=params(), evaluation_id="offline-eval-1", decision_time=NOW, expires_at=NEXT, quote_quantity=D("10"), reference_price=D("106"), stop_distance=D("4"))


def run(path: Path, pipeline_request: OfflinePipelineRequest):
    return OfflineDecisionService(DecisionPipeline(JsonlDecisionLedger(path))).evaluate(pipeline_request)


@pytest.mark.integration
def test_fixture_to_ledger_valid_entry_and_duplicate_export_suppression(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    first = run(ledger_path, request())
    second = run(ledger_path, request())
    assert first.export.decision.action == Action.ENTER_LONG
    assert first.export.exported
    assert first.export.record.completeness.value == "COMPLETE"
    assert {"frame", "context", "cost", "intent", "product_mandate", "risk_mandate", "portfolio", "system_state", "risk_verdict"} <= set(first.export.record.artifact_hashes)
    assert not second.export.exported
    assert second.export.status == "DUPLICATE_SUPPRESSED"
    assert len(ledger_path.read_bytes().splitlines()) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    ("pipeline_request", "reason"),
    [
        (request(events=fixture_events(stale_bbo=True)), "DATA_BLOCKED"),
        (request(events=fixture_events(gap=True)), "DATA_BLOCKED"),
        (request(observations=()), "STATE_UNKNOWN"),
    ],
)
def test_fixture_pipeline_fails_safe_for_stale_gap_and_restart(tmp_path: Path, pipeline_request: OfflinePipelineRequest, reason: str) -> None:
    result = run(tmp_path / f"{reason}-{id(pipeline_request)}.jsonl", pipeline_request)
    assert result.export.decision.action == Action.HOLD
    assert reason in result.export.decision.reason_codes
    assert result.export.decision.state_after.health.value == "BLOCKED"


@pytest.mark.integration
def test_bbo_clock_and_identity_remain_causal_before_decision_boundary(tmp_path: Path) -> None:
    expected_bbo_time = NOW - timedelta(milliseconds=500)
    result = run(tmp_path / "bbo-clock.jsonl", request(events=fixture_events(bbo_lag_ms=500)))
    spread = next(feature for feature in result.context.features if feature.feature_id == "F-008")

    assert result.frame.event_time_max == NOW
    assert result.frame.observed_at == NOW
    assert result.frame.bbo_event_id == result.events[-1].event_id
    assert result.frame.bbo_observed_at == expected_bbo_time
    assert result.context.decision_time == NOW
    assert result.context.frame_ref == result.frame.frame_id
    assert spread.input_event_ids == (result.frame.bbo_event_id,)
    assert spread.max_input_event_time == expected_bbo_time
    assert result.cost.as_of_time == expected_bbo_time
    assert result.cost.max_input_event_time == expected_bbo_time
    assert result.cost.input_event_ids == (result.frame.bbo_event_id,)
    assert result.cost.frame_ref == result.frame.frame_id
    assert result.verdict.decision.value == "APPROVED"
    assert result.export.decision.action == Action.ENTER_LONG


@pytest.mark.integration
@pytest.mark.parametrize("bar_count", [0, 1])
def test_insufficient_history_records_complete_blocked_hold(tmp_path: Path, bar_count: int) -> None:
    source = fixture_events()
    bars = source[:-1][:bar_count]
    result = run(tmp_path / f"insufficient-{bar_count}.jsonl", request(events=(*bars, source[-1])))

    assert result.export.decision.action == Action.HOLD
    assert "CONTEXT_INSUFFICIENT" in result.export.decision.reason_codes
    assert "DATA_BLOCKED" in result.export.decision.reason_codes
    assert result.export.record.completeness.value == "COMPLETE"
    assert result.export.exported
    assert result.context.current_bar_id == (result.bars[-1].event_id if result.bars else None)
    assert result.context.quality.value == "BLOCKED"
    assert len((tmp_path / f"insufficient-{bar_count}.jsonl").read_bytes().splitlines()) == 1
    assert JsonlDecisionLedger(tmp_path / f"insufficient-{bar_count}.jsonl").records()[0].record_hash == result.export.record.record_hash


@pytest.mark.integration
def test_duplicate_delivery_is_audited_without_blocking_valid_bbo(tmp_path: Path) -> None:
    result = run(tmp_path / "duplicate-delivery.jsonl", request(events=fixture_events(duplicate_bbo=True)))
    assert result.export.decision.action == Action.ENTER_LONG
    assert result.export.exported
    assert result.deliveries[-1].classification.value == "DUPLICATE"
    assert not result.deliveries[-1].apply


@pytest.mark.replay
def test_complete_pipeline_replay_produces_identical_ledger_bytes(tmp_path: Path) -> None:
    first_path = tmp_path / "run-a" / "ledger.jsonl"
    second_path = tmp_path / "run-b" / "ledger.jsonl"
    first = run(first_path, request())
    second = run(second_path, request())
    assert first.export.record.record_hash == second.export.record.record_hash
    assert first_path.read_bytes() == second_path.read_bytes()
    assert JsonlDecisionLedger(first_path).records()[0].canonical_bytes() == JsonlDecisionLedger(second_path).records()[0].canonical_bytes()
