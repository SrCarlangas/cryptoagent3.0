"""Focused tests for the dependency-free local directional model and runtime vetoes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from btc_decision_agent.application.local_ml import (
    Direction,
    FeatureContext,
    LocalMLAgent,
    LocalSoftmaxModel,
    evidence_features,
    net_four_hour_label,
)
from btc_decision_agent.application.ml_training import (
    TrainingExample,
    purged_temporal_split,
    select_exact_five_years,
)

from btc_decision_agent.application.realtime_demo import (
    ConfidenceDecisionEngine,
    EnginePersistentState,
    EvidenceSnapshot,
    RealtimeParams,
    ReconciledPosition,
)
from btc_decision_agent.domain.contracts import Action, PositionState

D = Decimal
NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def _evidence(*, price: str = "100", qualified: bool = True) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        at=NOW,
        event_id="event-1",
        price=D(price),
        confidence=D("0.7"),
        grade="HIGH",
        expected_edge_bps=D("15"),
        spread_bps=D("2"),
        data_age_ms=100,
        coverage=D("1"),
        horizons={
            "5m": D("1"),
            "30m": D("2"),
            "4h": D("3"),
            "1d": D("4"),
            "7d": D("5"),
            "30d": D("6"),
        },
        flow_imbalance=D("0.1"),
        qualified=qualified,
        reason="QUALIFIED" if qualified else "DATA_STALE",
        structural_confidence=D("0.7"),
        tactical_confidence=D("0.6"),
        structural_return_bps=D("4"),
        tactical_return_bps=D("3"),
    )


def _flat() -> ReconciledPosition:
    return ReconciledPosition(PositionState.FLAT, D("0"), D("1000"), D("100"))


def test_model_json_roundtrip_and_probabilities(tmp_path: Path) -> None:
    model = LocalSoftmaxModel()
    features = [float(index) for index in range(22)]
    model.train_one(features, Direction.BUY)
    path = tmp_path / "model.json"
    model.save(path)
    loaded = LocalSoftmaxModel.load(path)
    prediction = loaded.predict(features)
    assert prediction.direction == Direction.BUY
    assert abs(sum(prediction.probabilities.values()) - 1.0) < 1e-12
    assert loaded.trained_examples == 1


def test_feature_projection_includes_portfolio_pnl_and_risk() -> None:
    values = evidence_features(
        _evidence(price="110"),
        FeatureContext(
            position_long=True,
            entry_price=D("100"),
            peak_equity=D("1200"),
            day_start_equity=D("1000"),
            equity=D("1100"),
            active_stop_price=D("99"),
            risk_per_trade_fraction=D("0.02"),
        ),
    )
    assert len(values) == 22
    assert values[16] == 1.0
    assert values[17] == 1000.0
    assert values[18] > 0
    assert values[19] == 0.1
    assert values[20] == 1000.0
    assert values[21] == 0.02


def test_four_hour_labels_are_net_of_round_trip_costs() -> None:
    assert net_four_hour_label(D("100"), D("101"), round_trip_cost_bps=D("20"), decision_threshold_bps=D("10"))[0] == Direction.BUY
    assert net_four_hour_label(D("100"), D("99"), round_trip_cost_bps=D("20"), decision_threshold_bps=D("10"))[0] == Direction.SELL
    assert net_four_hour_label(D("100"), D("100.2"), round_trip_cost_bps=D("20"), decision_threshold_bps=D("10"))[0] == Direction.HOLD


def test_runtime_fails_closed_without_model_and_model_drives_entry(tmp_path: Path) -> None:
    params = RealtimeParams(buy_persistence_seconds=0)
    assert ConfidenceDecisionEngine(params).evaluate(_evidence(), _flat()).reason == "MODEL_UNAVAILABLE"

    model = LocalSoftmaxModel()
    model.weights[0][0] = 10.0
    path = tmp_path / "model.json"
    model.save(path)
    engine = ConfidenceDecisionEngine(params, LocalMLAgent(path, allow_unpromoted=True))
    decision = engine.evaluate(_evidence(), _flat())
    assert decision.action == Action.ENTER_LONG
    assert decision.reason == "MODEL_BUY_CONFIRMED"
    assert decision.model_prediction is not None
    assert decision.model_prediction.direction == Direction.BUY


def test_breaker_and_stop_veto_model_direction(tmp_path: Path) -> None:
    model = LocalSoftmaxModel()
    model.weights[0][0] = 10.0
    path = tmp_path / "model.json"
    model.save(path)
    engine = ConfidenceDecisionEngine(RealtimeParams(), LocalMLAgent(path, allow_unpromoted=True))
    engine.import_state(
        EnginePersistentState(
            entry_price=D("100"),
            entry_at=NOW - timedelta(hours=2),
            high_since_entry=D("100"),
            peak_equity=D("2000"),
            day_start_equity=D("2000"),
            equity_day=NOW.date().isoformat(),
        )
    )
    long_position = ReconciledPosition(PositionState.LONG, D("1"), D("0"), D("90"))
    decision = engine.evaluate(_evidence(price="90"), long_position)
    assert decision.action == Action.EXIT_LONG
    assert decision.protective
    assert decision.reason in {"DAILY_LOSS_BREAKER", "DRAWDOWN_BREAKER"}
    assert decision.model_prediction is None


def test_online_delayed_label_is_persisted_with_experience(tmp_path: Path) -> None:
    path = tmp_path / "model.json"
    LocalSoftmaxModel().save(path)
    agent = LocalMLAgent(path, online_learning=True, allow_unpromoted=True)
    first = _evidence()
    agent.predict(first, FeatureContext())
    assert len(LocalSoftmaxModel.load(path).pending) == 1
    later = EvidenceSnapshot(**{**first.__dict__, "at": NOW + timedelta(hours=4), "event_id": "event-2", "price": D("101")})
    agent.predict(later, FeatureContext())
    persisted = LocalSoftmaxModel.load(path)
    assert persisted.trained_examples == 1
    assert len(persisted.pending) == 1
    experience_path = path.with_suffix(".experiences.jsonl")
    assert experience_path.read_text().count("\n") == 1
    row = json.loads(experience_path.read_text())
    assert row["feature_schema_version"] == "evidence-multisource/1.0.0"
    assert len(row["features"]) == 22
    assert row["status"] == "LABELED"
    assert row["update_id"]


def test_late_online_target_expires_instead_of_changing_horizon(tmp_path: Path) -> None:
    path = tmp_path / "model.json"
    LocalSoftmaxModel().save(path)
    agent = LocalMLAgent(path, online_learning=True, allow_unpromoted=True)
    agent.predict(_evidence(), FeatureContext())
    agent.observe_price(NOW + timedelta(hours=5), D("110"))
    persisted = LocalSoftmaxModel.load(path)
    assert persisted.trained_examples == 0
    assert not persisted.pending
    row = json.loads(path.with_suffix(".experiences.jsonl").read_text())
    assert row["status"] == "EXPIRED_TARGET_MISSING"
    assert row["label"] is None


def test_unpromoted_model_is_rejected_by_default(tmp_path: Path) -> None:
    path = tmp_path / "model.json"
    LocalSoftmaxModel().save(path)
    try:
        LocalMLAgent(path)
    except ValueError as error:
        assert "not promoted" in str(error)
    else:
        raise AssertionError("unpromoted model must fail closed")


def test_temporal_split_purges_overlapping_four_hour_labels() -> None:
    examples = [
        TrainingExample(
            at_ms=hour,
            label_at_ms=hour + 4,
            features=(0.0,) * 22,
            label=Direction.HOLD,
            net_opportunity_bps=D("0"),
        )
        for hour in range(100)
    ]
    train, holdout, purged = purged_temporal_split(examples, 0.2)
    assert holdout[0].at_ms == 80
    assert purged == 4
    assert train[-1].label_at_ms < holdout[0].at_ms


def test_exact_five_year_selection_uses_calendar_boundary() -> None:
    start = datetime(2021, 9, 16, 1, tzinfo=UTC)
    end_open = datetime(2026, 9, 16, 0, tzinfo=UTC)
    rows = (
        {"open_time": int((start - timedelta(hours=1)).timestamp() * 1000)},
        {"open_time": int(start.timestamp() * 1000)},
        {"open_time": int(end_open.timestamp() * 1000)},
    )
    selected, selected_start, selected_end = select_exact_five_years(rows)
    assert len(selected) == 2
    assert selected_start == start
    assert selected_end == datetime(2026, 9, 16, 1, tzinfo=UTC)
