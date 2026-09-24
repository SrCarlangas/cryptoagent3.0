"""Append-only, fsync-backed canonical JSONL decision ledger."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from btc_decision_agent.domain.canonical import canonical_json, sha256_id
from btc_decision_agent.domain.contracts import (
    Action,
    CandidateIntent,
    ContractModel,
    CostEstimate,
    Decision,
    DecisionRecord,
    MarketContext,
    PortfolioState,
    ProductMandate,
    QualifiedMarketFrame,
    RecordCompleteness,
    RiskMandate,
    RiskVerdict,
    SystemState,
)


class LedgerCollisionError(RuntimeError):
    """Raised when canonical identity/content or the hash chain conflicts."""


class LedgerIncompleteError(ValueError):
    """Raised before persistence when required immutable artifacts are absent."""


@dataclass(frozen=True)
class LedgerAppendResult:
    record: DecisionRecord
    inserted: bool


class JsonlDecisionLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._by_decision: dict[str, bytes] = {}
        self._records: dict[str, DecisionRecord] = {}
        self._last_hash: str | None = None
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        expected_previous: str | None = None
        for line_number, line in enumerate(self.path.read_bytes().splitlines(), 1):
            raw = json.loads(line)
            record = DecisionRecord.model_validate(raw)
            if record.previous_record_hash != expected_previous:
                raise LedgerCollisionError(f"broken ledger chain at line {line_number}")
            expected = self._record_hash(record.decision, record.artifact_hashes, record.transition_rule, record.recorded_at, record.previous_record_hash, record.completeness, record.outcome_ref)
            if record.record_hash != expected:
                raise LedgerCollisionError("ledger record hash mismatch")
            decision_bytes = record.decision.canonical_bytes()
            existing = self._by_decision.get(record.decision.decision_id)
            if existing is not None and existing != decision_bytes:
                raise LedgerCollisionError("decision identity collision")
            self._by_decision[record.decision.decision_id] = decision_bytes
            self._records[record.decision.decision_id] = record
            self._last_hash = record.record_hash
            expected_previous = record.record_hash

    @staticmethod
    def _record_hash(decision: Decision, artifacts: dict[str, str], rule: str, recorded_at: datetime, previous: str | None, completeness: RecordCompleteness = RecordCompleteness.COMPLETE, outcome_ref: str | None = None) -> str:
        return sha256_id({"decision": decision, "artifact_hashes": artifacts, "transition_rule": rule, "completeness": completeness, "outcome_ref": outcome_ref, "recorded_at": recorded_at, "previous_record_hash": previous})

    @staticmethod
    def _required_artifacts(decision: Decision) -> set[str]:
        required = {"product_mandate", "portfolio", "system_state", "intent"}
        if decision.action == Action.ENTER_LONG:
            required.update({"frame", "context", "cost", "risk_mandate", "risk_verdict"})
        elif decision.action == Action.EXIT_LONG:
            if decision.priority_class.value == 1:
                required.add("risk_mandate")
            else:
                required.add("context")
        elif decision.risk_verdict_ref is not None:
            required.update({"cost", "risk_mandate", "risk_verdict"})
        if decision.market_context_ref is not None:
            required.update({"frame", "context"})
        if decision.cost_estimate_ref is not None:
            required.update({"frame", "cost"})
        return required

    @classmethod
    def _hash_artifacts(cls, decision: Decision, artifacts: Mapping[str, ContractModel]) -> dict[str, str]:
        missing = cls._required_artifacts(decision) - set(artifacts)
        if missing:
            raise LedgerIncompleteError(f"missing required decision artifacts: {sorted(missing)}")
        if any(not isinstance(artifact, ContractModel) for artifact in artifacts.values()):
            raise LedgerIncompleteError("ledger artifacts must be immutable contract objects")
        cls._validate_bindings(decision, artifacts)
        return dict(sorted((name, artifact.canonical_hash()) for name, artifact in artifacts.items()))

    @staticmethod
    def _validate_bindings(decision: Decision, artifacts: Mapping[str, ContractModel]) -> None:
        expected_types: dict[str, type[ContractModel]] = {
            "frame": QualifiedMarketFrame,
            "context": MarketContext,
            "cost": CostEstimate,
            "intent": CandidateIntent,
            "product_mandate": ProductMandate,
            "risk_mandate": RiskMandate,
            "portfolio": PortfolioState,
            "system_state": SystemState,
            "risk_verdict": RiskVerdict,
        }
        for name, expected in expected_types.items():
            artifact = artifacts.get(name)
            if artifact is not None and not isinstance(artifact, expected):
                raise LedgerIncompleteError(f"artifact {name} has wrong contract type")
        frame = artifacts.get("frame")
        intent = artifacts.get("intent")
        context = artifacts.get("context")
        cost = artifacts.get("cost")
        verdict = artifacts.get("risk_verdict")
        product = artifacts.get("product_mandate")
        portfolio = artifacts.get("portfolio")
        system = artifacts.get("system_state")
        mandate = artifacts.get("risk_mandate")
        checks = (
            (isinstance(intent, CandidateIntent) and decision.intent_ref == intent.intent_id, "intent"),
            (isinstance(product, ProductMandate) and decision.product_mandate_version == product.version, "product mandate"),
            (isinstance(portfolio, PortfolioState) and decision.target_position.portfolio_state_version == portfolio.version, "portfolio"),
            (isinstance(system, SystemState) and decision.state_before.version == system.version, "system state"),
            (decision.market_context_ref is None or (isinstance(context, MarketContext) and decision.market_context_ref == context.version), "context"),
            (decision.cost_estimate_ref is None or (isinstance(cost, CostEstimate) and decision.cost_estimate_ref == cost.version), "cost"),
            (decision.risk_verdict_ref is None or (isinstance(verdict, RiskVerdict) and decision.risk_verdict_ref == verdict.verdict_id), "risk verdict"),
            (decision.risk_mandate_version is None or (isinstance(mandate, RiskMandate) and decision.risk_mandate_version == mandate.version), "risk mandate"),
        )
        failed = [name for valid, name in checks if not valid]
        if failed:
            raise LedgerIncompleteError(f"artifact binding mismatch: {', '.join(failed)}")
        if isinstance(context, MarketContext):
            if not isinstance(frame, QualifiedMarketFrame) or context.frame_ref != frame.frame_id:
                raise LedgerIncompleteError("artifact binding mismatch: context frame")
            frame_event_ids = set(frame.event_ids)
            feature_input_ids = {
                event_id
                for feature in context.features
                for event_id in feature.input_event_ids
            }
            if not feature_input_ids <= frame_event_ids:
                raise LedgerIncompleteError("artifact binding mismatch: feature input events")
            if context.current_bar_id is not None and context.current_bar_id not in frame_event_ids:
                raise LedgerIncompleteError("artifact binding mismatch: current bar")
        if isinstance(cost, CostEstimate):
            if not isinstance(frame, QualifiedMarketFrame) or cost.frame_ref != frame.frame_id:
                raise LedgerIncompleteError("artifact binding mismatch: cost frame")
            if not set(cost.input_event_ids) <= set(frame.event_ids):
                raise LedgerIncompleteError("artifact binding mismatch: cost input events")

    def append(self, decision: Decision, artifacts: Mapping[str, ContractModel], transition_rule: str, recorded_at: datetime, *, outcome_ref: str | None = None) -> LedgerAppendResult:
        if not transition_rule:
            raise LedgerIncompleteError("transition rule is required")
        artifact_hashes = self._hash_artifacts(decision, artifacts)
        decision_bytes = decision.canonical_bytes()
        existing = self._by_decision.get(decision.decision_id)
        if existing is not None:
            if existing != decision_bytes:
                raise LedgerCollisionError("same decision_id has different canonical content")
            record = self._records[decision.decision_id]
            if record.artifact_hashes != artifact_hashes:
                raise LedgerCollisionError("duplicate decision has different artifact manifest")
            return LedgerAppendResult(record, False)
        completeness = RecordCompleteness.COMPLETE
        record_hash = self._record_hash(decision, artifact_hashes, transition_rule, recorded_at, self._last_hash, completeness, outcome_ref)
        record = DecisionRecord(record_id=sha256_id({"decision_id": decision.decision_id, "recorded_at": recorded_at}), decision=decision, artifact_hashes=artifact_hashes, transition_rule=transition_rule, completeness=completeness, outcome_ref=outcome_ref, recorded_at=recorded_at, previous_record_hash=self._last_hash, record_hash=record_hash)
        line = canonical_json(record) + b"\n"
        with self.path.open("ab") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        self._by_decision[decision.decision_id] = decision_bytes
        self._records[decision.decision_id] = record
        self._last_hash = record_hash
        return LedgerAppendResult(record, True)

    def records(self) -> tuple[DecisionRecord, ...]:
        return tuple(self._records.values())
