"""Invariant tests for additive normative contract metadata."""

from __future__ import annotations

from datetime import timedelta

import pytest
from btc_decision_agent.application.decision import DecisionMachine
from pydantic import ValidationError
from tests.helpers import NEXT, NOW, D, portfolio, product, state

from btc_decision_agent.domain.contracts import (
    ClockBasis,
    CostEstimate,
    CostScenario,
    DecisionRecord,
    DeliveryClass,
    DeliveryMetadata,
    EventType,
    FeatureValue,
    FreshnessPolicy,
    FreshnessStatus,
    IntentType,
    LocalBookView,
    MarketContext,
    MarketEventV1,
    PortfolioState,
    ProductMandate,
    ProvenanceMetadata,
    QualifiedMarketFrame,
    QualityMetadata,
    QualityStatus,
    RiskMandate,
    Transport,
    TriggerType,
    Usage,
)
from btc_decision_agent.domain.contracts import (
    TestStatus as VerdictStatus,
)
from btc_decision_agent.domain.contracts import (
    TestVerdict as Verdict,
)
from btc_decision_agent.policies import NullHoldPolicy


def market_event(**changes: object) -> MarketEventV1:
    values: dict[str, object] = {
        "event_id": "event",
        "event_type": EventType.BBO_UPDATE,
        "source_contract_id": "S-04",
        "provider_contract_version": "v1",
        "transport": Transport.FIXTURE,
        "channel": "book",
        "symbol": "BTC/USDT",
        "connection_id": "connection-1",
        "precision_ref": "S-09",
        "raw_ref": "fixture:4",
        "event_time": None,
        "observed_at": NOW,
        "source_identity": {"update_id": 1},
        "sequence_first": 1,
        "sequence_last": 1,
        "payload": {"bid": D("100"), "ask": D("101")},
        "payload_hash": "payload",
        "provenance": ProvenanceMetadata(data_source="FIXTURE", transform_version="1"),
        "delivery_metadata": DeliveryMetadata(connection_id="connection-1"),
        "quality_metadata": QualityMetadata(),
    }
    values.update(changes)
    return MarketEventV1.model_validate(values)


def test_market_event_metadata_preserves_sequence_delivery_quality_and_provenance() -> None:
    event = market_event()
    assert (event.connection_id, event.precision_ref, event.raw_ref) == (
        "connection-1",
        "S-09",
        "fixture:4",
    )
    assert event.provenance.data_source == "FIXTURE"
    with pytest.raises(ValidationError):
        market_event(
            delivery_class=DeliveryClass.LATE,
            delivery_metadata=DeliveryMetadata(classification=DeliveryClass.ON_TIME),
        )
    with pytest.raises(ValidationError):
        market_event(
            quality=QualityStatus.BLOCKED,
            quality_metadata=QualityMetadata(status=QualityStatus.QUALIFIED),
        )


def test_frame_portfolio_feature_and_context_metadata_invariants() -> None:
    with pytest.raises(ValidationError):
        QualifiedMarketFrame(
            frame_id="frame",
            symbol="BTC/USDT",
            event_time_max=NOW,
            observed_at=NOW,
            event_ids=("e",),
            sequence_or_identity=("1", "1"),
            source_watermarks={"S-04": NOW},
            complete=True,
            freshness=FreshnessStatus.FRESH,
            quality=QualityStatus.QUALIFIED,
            bid=D("99"),
            ask=D("101"),
            bbo_event_id="e",
            bbo_observed_at=NOW,
        )
    with pytest.raises(ValidationError):
        PortfolioState(
            version="p",
            position="LONG",
            base_quantity=D("2"),
            reference_price=D("100"),
            available_cash=D("100"),
            equity=D("300"),
            exposure=D("199"),
            reconciled=True,
            observed_at=NOW,
        )
    feature = FeatureValue(
        feature_id="F-001",
        value=D("1"),
        unit="ratio",
        as_of_time=NOW,
        max_input_event_time=NOW,
        horizon="1h",
        window_definition="N=2",
        formula_hash="sha256:formula",
        source_watermarks={"S-03": NOW},
        conditional_profile_ref="profile:1",
        quality=QualityStatus.QUALIFIED,
    )
    with pytest.raises(ValidationError):
        MarketContext(
            version="context:1",
            frame_ref="frame",
            symbol="BTC/USDT",
            decision_time=NOW,
            horizon="1h",
            current_bar_id="bar",
            features=(feature,),
            volatility=D("-0.01"),
            liquidity=D("100"),
            quality=QualityStatus.QUALIFIED,
        )


def test_cost_and_mandate_ranges_and_gates_are_conservative() -> None:
    with pytest.raises(ValidationError):
        CostEstimate(
            version="cost:1",
            frame_ref="frame",
            action="ENTER_LONG",
            base_quantity=D("1"),
            scenario=CostScenario.ADVERSE,
            horizon="1h",
            source="L2",
            fee_bps=D("1"),
            cross_bps=D("1"),
            depth_slippage_bps=D("1"),
            impact_bps=D("1"),
            other_bps=D("1"),
            total_bps=D("5"),
            conservative_lower_bps=D("6"),
            conservative_upper_bps=D("10"),
            quality=QualityStatus.QUALIFIED,
            as_of_time=NOW,
            max_input_event_time=NOW,
            input_event_ids=("event",),
        )
    with pytest.raises(ValidationError):
        ProductMandate(
            version="product:1",
            restrictions=("SPOT",),
            capabilities=("SPOT",),
            valid_from=NOW,
            valid_until=NEXT,
            authored_by="human",
        )
    with pytest.raises(ValidationError):
        RiskMandate(
            version="risk:1",
            authored_by="human",
            authored_at=NOW,
            capital=D("1000"),
            risk_per_decision=D("0.01"),
            max_exposure=D("500"),
            daily_loss_max=D("10"),
            drawdown_max=D("100"),
            min_notional=D("10"),
            step_size=D("0.001"),
            valid_from=NOW,
            valid_until=NEXT,
            liquidity_gates=("L2_REQUIRED",),
            data_quality_gates=("L2_REQUIRED",),
        )


def test_decision_record_test_freshness_and_book_refs_are_explicit() -> None:
    intent = NullHoldPolicy().evaluate("eval", "state", NOW, NEXT)
    decision = DecisionMachine().decide(
        evaluation_id="eval",
        state=state(),
        portfolio=portfolio(),
        product_mandate=product(),
        risk_verdict=None,
        intent=intent,
        trigger_type=TriggerType.STRATEGIC_EVALUATION,
        event_time_max=NOW,
        decision_time=NOW,
        expires_at=NEXT,
    )
    assert decision.intent_ref == intent.intent_id
    assert intent.intent_type == IntentType.NO_INTENT
    with pytest.raises(ValidationError):
        DecisionRecord(
            record_id="record:1",
            decision=decision,
            artifact_hashes={},
            transition_rule="SM-030",
            recorded_at=NOW,
            previous_record_hash=None,
            record_hash="hash",
        )
    with pytest.raises(ValidationError):
        Verdict(
            obligation_id="OB-1",
            component_id="contracts",
            test_id="test_contracts",
            status=VerdictStatus.PASS,
            evidence_refs=("same", "same"),
            reason="duplicate evidence is ambiguous",
            evaluated_at=NOW,
        )
    with pytest.raises(ValidationError):
        FreshnessPolicy(
            policy_version="D-014/1",
            source_contract_id="S-04",
            event_type=EventType.BBO_UPDATE,
            usage=Usage.COST,
            required=True,
            clock_basis=ClockBasis.OBSERVED_AT,
            warning_age_ms=100,
            max_age_ms=200,
            allowed_lateness_ms=10,
            clock_skew_budget_ms=10,
            recovery_evidence_n=2,
            recovery_rule="CONSECUTIVE_QUALIFIED",
            on_suspect="BLOCK",
            on_stale="BLOCK",
            decision_refs=("D-1", "D-1"),
        )
    book = LocalBookView(
        book_generation_id="book:1",
        symbol="BTC/USDT",
        metadata_version="S-09/1",
        last_update_id=1,
        bids=((D("100"), D("1")),),
        asks=((D("101"), D("1")),),
        snapshot_limit=100,
        event_time_max=NOW,
        observed_at=NOW + timedelta(milliseconds=1),
        sync_status="LIVE",
        quality=QualityStatus.QUALIFIED,
    )
    assert (book.best_bid, book.best_ask) == (D("100"), D("101"))
    with pytest.raises(ValidationError):
        LocalBookView.model_validate({**book.model_dump(), "best_bid": D("99")})
