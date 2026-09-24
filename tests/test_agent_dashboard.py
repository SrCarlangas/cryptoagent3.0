"""Tests for the exposure agent dashboard and the daily summary.

The property that matters most here is that the decision path is reported
truthfully: a green chain must mean the agent's decision actually reached
execution, and a blocked stage must name the layer that really stopped it. A
dashboard that decorates rather than reports is worse than no dashboard.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from btc_decision_agent.observability.agent_dashboard import (
    AGENT_PAGE,
    build_state,
    stage_states,
)
from btc_decision_agent.observability.journal import ActivityJournal

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def _entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "at": NOW.isoformat(),
        "venue": "DEMO",
        "interval": "adaptive",
        "action": "HOLD",
        "reason": "AGENT_HOLD_R3_P58",
        "position_before": "FLAT",
        "position_after": "FLAT",
        "price": "84000",
        "usdt_free": "4600",
        "btc_qty": "0",
        "strategy_version": "EXPOSURE-AGENT-V1",
        "online_learning": True,
    }
    base.update(overrides)
    return base


def _journal(tmp_path: Path, entries: list[dict[str, Any]]) -> ActivityJournal:
    path = tmp_path / "activity.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for entry in entries:
            stream.write(json.dumps(entry) + "\n")
    return ActivityJournal(str(path))


class TestStageStates:
    def test_agent_decision_passes_every_gate(self) -> None:
        stages = stage_states(_entry(action="ENTER_LONG", reason="AGENT_ENTER_LONG_R3_P61"))
        assert [item["state"] for item in stages] == ["pass"] * 6

    def test_data_gate_blocks_and_later_stages_stay_idle(self) -> None:
        stages = {item["id"]: item["state"] for item in stage_states(_entry(reason="DATA_STALE"))}
        assert stages["BREAKER"] == "pass"
        assert stages["PROTECTIVE_STOP"] == "pass"
        assert stages["DATA"] == "block"
        assert stages["PERCEPTION"] == "idle"
        assert stages["AGENT"] == "idle"

    def test_perception_gate_blocks(self) -> None:
        stages = {
            item["id"]: item["state"]
            for item in stage_states(_entry(reason="PERCEPTION_INSUFFICIENT"))
        }
        assert stages["DATA"] == "pass"
        assert stages["PERCEPTION"] == "block"
        assert stages["AGENT"] == "idle"

    def test_cadence_block_still_credits_the_agent(self) -> None:
        stages = {
            item["id"]: item["state"]
            for item in stage_states(_entry(reason="AGENT_ENTER_LONG_R0_P58_AWAITING_CADENCE"))
        }
        # The agent did decide; only the commit frequency held it back.
        assert stages["AGENT"] == "pass"
        assert stages["CADENCE"] == "block"

    def test_protective_stop_blocks_early(self) -> None:
        stages = {
            item["id"]: item["state"] for item in stage_states(_entry(reason="PROTECTIVE_STOP"))
        }
        assert stages["PROTECTIVE_STOP"] == "block"
        assert stages["AGENT"] == "idle"

    def test_dry_run_prefix_is_ignored(self) -> None:
        stages = {
            item["id"]: item["state"]
            for item in stage_states(_entry(reason="DRY_RUN:PERCEPTION_INSUFFICIENT"))
        }
        assert stages["PERCEPTION"] == "block"

    def test_no_activity_is_all_idle(self) -> None:
        assert all(item["state"] == "idle" for item in stage_states(None))


class TestBuildState:
    def test_reads_regime_and_conviction_from_reason(self, tmp_path: Path) -> None:
        state = build_state(_journal(tmp_path, [_entry()]))
        assert state["active_regime"] == 3
        assert state["conviction"] == 0.58

    def test_probabilities_override_the_parsed_conviction(self, tmp_path: Path) -> None:
        entry = _entry(model_probabilities={"TARGET_FLAT": "0.4", "TARGET_LONG": "0.6"})
        state = build_state(_journal(tmp_path, [entry]))
        assert state["conviction"] == 0.6

    def test_counts_orders_and_equity(self, tmp_path: Path) -> None:
        entries = [
            _entry(),
            _entry(
                at=(NOW + timedelta(minutes=1)).isoformat(),
                action="ENTER_LONG",
                reason="AGENT_ENTER_LONG_R3_P61",
                order_side="BUY",
                order_base_qty="0.05",
                order_avg_price="84000",
                position_after="LONG",
                usdt_free="400",
                btc_qty="0.05",
            ),
        ]
        state = build_state(_journal(tmp_path, entries))
        assert state["order_count"] == 1
        assert state["buys"] == 1
        assert state["sells"] == 0
        assert state["position"] == "LONG"
        # 400 USDT + 0.05 BTC * 84000 = 4600
        assert state["equity"] is not None
        assert abs(float(state["equity"]) - 4600.0) < 1e-6

    def test_empty_journal_does_not_crash(self, tmp_path: Path) -> None:
        state = build_state(_journal(tmp_path, []))
        assert state["evaluations"] == 0
        assert state["active_regime"] is None
        assert all(item["state"] == "idle" for item in state["stages"])

    def test_policy_metadata_is_surfaced(self, tmp_path: Path) -> None:
        policy = tmp_path / "policy.json"
        policy.write_text(
            json.dumps(
                {
                    "policy_version": "LOCAL-EXPOSURE-AGENT-V1",
                    "regimes": 4,
                    "trained_steps": 7292,
                    "metadata": {
                        "promotion_status": "PROMOTED",
                        "promotion_evidence": {
                            "seed_stability_mean_pct": 42.42,
                            "chosen_config": "cadence=24h",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        state = build_state(_journal(tmp_path, [_entry()]), policy)
        assert state["promotion_status"] == "PROMOTED"
        assert state["regimes"] == 4
        assert state["trained_steps"] == 7292
        assert state["expected_oos_return_pct"] == 42.42

    def test_page_does_not_reference_the_retired_pipeline(self) -> None:
        # The old dashboard described six departments of a deterministic pipeline.
        for gone in ("RESEARCH LAB", "STRATEGY DEV", "TRADING DESK", "MARKET DATA"):
            assert gone not in AGENT_PAGE
        assert "LEARNED REGIMES" in AGENT_PAGE
        assert "DECISION PATH" in AGENT_PAGE


class TestDailySummary:
    def test_summary_counts_orders_and_flags_vetoes(self, tmp_path: Path) -> None:
        from scripts.daily_summary import build_summary

        entries = [
            _entry(at=(NOW - timedelta(hours=2)).isoformat()),
            _entry(
                at=(NOW - timedelta(hours=1)).isoformat(),
                reason="DATA_STALE",
                model_direction=None,
            ),
            _entry(
                at=(NOW - timedelta(minutes=30)).isoformat(),
                action="ENTER_LONG",
                reason="AGENT_ENTER_LONG_R3_P61",
                order_side="BUY",
                order_base_qty="0.05",
                order_avg_price="84000",
                fees_usdt="4.2",
                position_after="LONG",
            ),
        ]
        summary = build_summary(entries, {}, hours=24, now=NOW)
        assert summary["orders"] == 1
        assert len(summary["buys"]) == 1
        assert summary["vetoes"] == {"DATA_STALE": 1}
        assert summary["fees_usdt"] == "4.2"

    def test_summary_excludes_entries_outside_the_window(self, tmp_path: Path) -> None:
        from scripts.daily_summary import build_summary

        entries = [
            _entry(at=(NOW - timedelta(days=5)).isoformat(), order_side="BUY"),
            _entry(at=(NOW - timedelta(hours=1)).isoformat()),
        ]
        summary = build_summary(entries, {}, hours=24, now=NOW)
        assert summary["orders"] == 0
        assert summary["evaluations"] == 1

    def test_summary_marks_a_dead_process_as_stale(self, tmp_path: Path) -> None:
        from scripts.daily_summary import build_summary, render

        entries = [_entry(at=(NOW - timedelta(hours=3)).isoformat())]
        summary = build_summary(entries, {}, hours=24, now=NOW)
        assert summary["stale"] is True
        assert "posiblemente caido" in render(summary)

    def test_render_stays_short(self, tmp_path: Path) -> None:
        from scripts.daily_summary import build_summary, render

        summary = build_summary([_entry()], {}, hours=24, now=NOW)
        message = render(summary)
        # Conciseness is the stated requirement, so it is asserted.
        assert len(message.splitlines()) <= 10
