from pathlib import Path

from btc_decision_agent.observability.snapshot import project
from tests.test_offline_pipeline import request, run


def test_observability_projects_authority_policy_context_and_freshness_versions(tmp_path: Path) -> None:
    result = run(tmp_path / "ledger.jsonl", request())
    snapshot = project(
        state=result.export.decision.state_after,
        source_health={"S-04": "READY", "S-03": "READY"},
        source_freshness={"S-04": "FRESH", "S-03": "FRESH"},
        decision=result.export.decision,
        intent=result.policy_result.candidate_intent,
        verdict=result.verdict,
        portfolio=result.artifacts["portfolio"],
        cost=result.cost,
        market_context=result.context,
        ledger_record_id=result.export.record.record_id,
        replay_ref="fixture-replay-1",
    )
    assert snapshot.product_mandate_version == request().product_mandate.version
    assert snapshot.risk_mandate_version == request().risk_mandate.version
    assert (snapshot.policy_id, snapshot.policy_version) == ("POL-101", "1.0.0")
    assert snapshot.market_context_version == result.context.version
    assert snapshot.portfolio_reconciled
    assert snapshot.risk_decision == "APPROVED"
    assert snapshot.health_by_source == (("S-03", "READY"), ("S-04", "READY"))
    assert snapshot.freshness_by_source == (("S-03", "FRESH"), ("S-04", "FRESH"))
