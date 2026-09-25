"""Tests for the LLM agent dashboard and the daily summary.

The property that matters most is that the page reports truthfully. Two failures
would be expensive and silent:

  Attributing a decision to the LLM when the numeric fallback made it. An operator
  reading a dashboard titled "LLM agent" would conclude the model is working while
  it is in fact down.

  Showing a green decision chain when a layer actually vetoed. A dashboard that
  decorates rather than reports is worse than no dashboard.

Both are asserted below, along with the read-only guarantee: the dashboard runs
under a sandbox that mounts the data directory read-only, so it must never need to
write to the memory database it reports on.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from btc_decision_agent.application.llm_memory import AgentMemory
from btc_decision_agent.application.llm_tools import (
    EXPOSURE_CASH,
    EXPOSURE_INVESTED,
)
from btc_decision_agent.observability.journal import ActivityJournal
from btc_decision_agent.observability.llm_agent_dashboard import (
    LLM_AGENT_PAGE,
    build_state,
    classify_origin,
    equity_series,
    parse_reason,
    recent_deliberations,
    stage_states,
    track_record_view,
)

D = Decimal
NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def _entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "at": NOW.isoformat(),
        "venue": "DEMO",
        "interval": "adaptive",
        "action": "HOLD",
        "reason": "AGENT_HOLD_R0_C85_F",
        "position_before": "LONG",
        "position_after": "LONG",
        "price": "84000",
        "usdt_free": "400",
        "btc_qty": "0.05",
        "strategy_version": "EXPOSURE-AGENT-V1",
        "directional_model_version": "LLM-EXPOSURE-AGENT-V1",
        "confidence_model": "EXPOSURE-AGENT-V1",
    }
    base.update(overrides)
    return base


def _journal(tmp_path: Path, entries: list[dict[str, Any]]) -> ActivityJournal:
    path = tmp_path / "activity.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for entry in entries:
            stream.write(json.dumps(entry) + "\n")
    return ActivityJournal(str(path))


def _memory(tmp_path: Path, *, decisions: int = 3) -> Path:
    path = tmp_path / "mem.sqlite3"
    memory = AgentMemory(path)
    for index in range(decisions):
        memory.record(
            decided_at=NOW + timedelta(minutes=index),
            event_id=f"ev-{index}",
            features=[0.01] * 19,
            regime=0,
            # Below 0.5, so the advisor says PLANO while the agent says LARGO.
            quant_p_long=0.42,
            target_exposure=EXPOSURE_INVESTED,
            exposure_before=EXPOSURE_CASH,
            derived_order="BUY" if index == 0 else "HOLD",
            conviction=0.8,
            expected_move_pct=1.5,
            reason=f"razonamiento numero {index}",
            thinking="penso a fondo" if index == 0 else "",
            price=D("84000"),
            acted=index == 0,
        )
    return path


class TestOriginAttribution:
    """Who decided is the question the page exists to answer."""

    def test_llm_reason_is_attributed_to_the_llm(self) -> None:
        assert classify_origin("AGENT_HOLD_R0_C85_F") == "LLM"
        assert classify_origin("AGENT_BUY_R3_C90_D") == "LLM"

    def test_sustained_verdict_is_distinguished_from_a_fresh_one(self) -> None:
        # Re-affirming a verdict is not the same as inferring a new one, and the
        # difference tells an operator whether the model is actually answering.
        assert classify_origin("AGENT_VERDICT_UNCHANGED") == "LLM_SOSTENIDO"

    def test_fallback_is_never_credited_to_the_llm(self) -> None:
        assert classify_origin("FALLBACK_QUANT_HOLD") == "FALLBACK"
        assert classify_origin("FALLBACK_QUANT_ENTER_LONG") == "FALLBACK"

    def test_veto_before_the_agent_is_not_credited_to_anyone(self) -> None:
        assert classify_origin("PERCEPTION_INSUFFICIENT") == "VETADO"
        assert classify_origin("DATA_STALE") == "VETADO"

    def test_origin_counts_separate_llm_from_fallback(self, tmp_path: Path) -> None:
        entries = [
            _entry(reason="FALLBACK_QUANT_HOLD"),
            _entry(reason="FALLBACK_QUANT_HOLD"),
            _entry(reason="AGENT_HOLD_R0_C85_F"),
            _entry(reason="AGENT_VERDICT_UNCHANGED"),
            _entry(reason="DATA_STALE"),
        ]
        state = build_state(_journal(tmp_path, entries))
        assert state["origin_counts"] == {
            "FALLBACK": 2,
            "LLM": 1,
            "LLM_SOSTENIDO": 1,
            "VETADO": 1,
        }

    def test_last_llm_verdict_is_tracked_separately_from_last_seen(
        self, tmp_path: Path
    ) -> None:
        # Alive but not answering: the newest entry is a fallback, so the page must
        # still show when the model last spoke for itself.
        entries = [
            _entry(at=(NOW - timedelta(hours=2)).isoformat(), reason="AGENT_HOLD_R0_C85_F"),
            _entry(at=NOW.isoformat(), reason="FALLBACK_QUANT_HOLD"),
        ]
        state = build_state(_journal(tmp_path, entries))
        assert state["origin"] == "FALLBACK"
        assert state["last_llm_at"] == (NOW - timedelta(hours=2)).isoformat()
        assert state["last_seen"] == NOW.isoformat()


class TestEquitySeries:
    """A miscalculated comparison is worse than no comparison.

    The chart is illustrative, but an illustration that flatters the agent is still a
    false claim, so the arithmetic is pinned here.
    """

    def _series(self, prices: list[str], books: list[tuple[str, str]]) -> dict[str, Any]:
        entries = [
            _entry(
                at=(NOW + timedelta(minutes=index)).isoformat(),
                price=price,
                usdt_free=usdt,
                btc_qty=btc,
            )
            for index, (price, (usdt, btc)) in enumerate(zip(prices, books, strict=True))
        ]
        return equity_series(entries, points=100)

    def test_buy_and_hold_pays_the_entry_commission(self) -> None:
        # Fully invested the whole way, so the only gap left is the commission buy and
        # hold pays at entry. Comparing a net result against a gross one would hand the
        # agent a free advantage.
        series = self._series(["100", "100"], [("0", "1"), ("0", "1")])
        assert series["available"] is True
        assert series["agent_pct"] == 0.0
        assert series["hold_pct"] == -0.1  # 10 bps
        assert series["difference_pp"] == 0.1

    def test_tracks_the_agent_beating_the_asset_by_being_out_of_it(self) -> None:
        # Starts invested, sells at 100, price then halves. The agent keeps its cash.
        series = self._series(
            ["100", "100", "50"], [("0", "1"), ("100", "0"), ("100", "0")]
        )
        assert series["agent_pct"] == 0.0
        assert series["hold_pct"] == pytest.approx(-50.05, abs=0.01)
        assert series["difference_pp"] > 49.0

    def test_tracks_the_agent_losing_to_the_asset(self) -> None:
        # Sells at 100 and the price then doubles, so it misses the whole move.
        series = self._series(
            ["100", "100", "200"], [("0", "1"), ("100", "0"), ("100", "0")]
        )
        assert series["agent_pct"] == 0.0
        assert series["hold_pct"] == pytest.approx(99.8, abs=0.05)
        assert series["difference_pp"] < -99.0

    def test_both_lines_are_rebased_to_one_hundred(self) -> None:
        series = self._series(["80000", "81000"], [("0", "0.05"), ("0", "0.05")])
        assert series["points"][0]["agent"] == 100.0
        # Hold starts one commission below, by construction.
        assert series["points"][0]["hold"] == pytest.approx(99.9, abs=0.01)

    def test_downsamples_instead_of_returning_every_record(self) -> None:
        # The journal grows by roughly 17k rows a day; shipping all of them to the
        # browser every five seconds would be wasteful.
        prices = ["80000"] * 1000
        books = [("0", "0.05")] * 1000
        series = equity_series(
            [
                _entry(at=(NOW + timedelta(seconds=5 * i)).isoformat(), price=p, btc_qty=b, usdt_free=u)
                for i, (p, (u, b)) in enumerate(zip(prices, books, strict=True))
            ],
            points=50,
        )
        assert series["samples"] == 1000
        assert len(series["points"]) <= 55

    def test_a_single_record_is_reported_as_insufficient(self) -> None:
        series = equity_series([_entry()], points=10)
        assert series["available"] is False
        assert series["reason"]

    def test_empty_journal_does_not_crash(self) -> None:
        assert equity_series([], points=10)["available"] is False


class TestExposureVocabulary:
    """The two exposure names live in one place and must not drift.

    They appear in the JSON schema the model is constrained to, in the prompt that
    explains them, in the memory rows, in the dashboard and in the Slack summary. A
    mismatch between the schema and the prompt would make the model emit a value the
    parser rejects, which surfaces as the fallback quietly taking over.
    """

    def test_schema_and_prompt_agree_with_the_constants(self) -> None:
        from btc_decision_agent.application.llm_agent import SYSTEM_PROMPT, VERDICT_SCHEMA
        from btc_decision_agent.application.llm_tools import EXPOSURE_VALUES

        enum = VERDICT_SCHEMA["properties"]["exposicion_objetivo"]["enum"]
        assert enum == list(EXPOSURE_VALUES)
        for value in EXPOSURE_VALUES:
            assert value in SYSTEM_PROMPT, f"el prompt no explica {value}"

    def test_the_retired_vocabulary_is_gone(self) -> None:
        from btc_decision_agent.application.llm_agent import SYSTEM_PROMPT, VERDICT_SCHEMA

        enum = VERDICT_SCHEMA["properties"]["exposicion_objetivo"]["enum"]
        assert "LARGO" not in enum
        assert "PLANO" not in enum
        # "largo plazo" is legitimate prose, so only the standalone tokens are barred.
        assert not re.search(r"\bPLANO\b", SYSTEM_PROMPT)
        assert not re.search(r"\bLARGO\b", SYSTEM_PROMPT)

    def test_dashboard_and_summary_use_the_constants(self) -> None:
        from btc_decision_agent.application.llm_tools import EXPOSURE_CASH, EXPOSURE_INVESTED

        assert EXPOSURE_INVESTED == "INVERTIDO"
        assert EXPOSURE_CASH == "EN LIQUIDEZ"


class TestReasonParsing:
    def test_reads_regime_conviction_and_depth(self) -> None:
        parsed = parse_reason("AGENT_BUY_R3_C90_D")
        assert parsed["regime"] == 3
        assert parsed["conviction"] == 0.90
        assert parsed["deliberated"] is True

    def test_fast_pass_is_not_reported_as_deliberated(self) -> None:
        assert parse_reason("AGENT_HOLD_R0_C85_F")["deliberated"] is False

    def test_below_cost_is_flagged(self) -> None:
        parsed = parse_reason("AGENT_BUY_R3_C90_D_BELOW_COST")
        assert parsed["below_cost"] is True

    def test_empty_reason_does_not_crash(self) -> None:
        parsed = parse_reason("")
        assert parsed["regime"] is None
        assert parsed["conviction"] is None


class TestStageStates:
    def test_agent_decision_passes_every_layer(self) -> None:
        stages = stage_states(_entry(action="ENTER_LONG", reason="AGENT_BUY_R3_C90_D"))
        assert [item["state"] for item in stages] == ["pass"] * 6

    def test_data_gate_blocks_and_later_layers_stay_idle(self) -> None:
        stages = {item["id"]: item["state"] for item in stage_states(_entry(reason="DATA_STALE"))}
        assert stages["INTERRUPTORES"] == "pass"
        assert stages["DATOS"] == "block"
        assert stages["PERCEPCION"] == "idle"
        assert stages["AGENTE LLM"] == "idle"

    def test_perception_gate_blocks_before_the_agent(self) -> None:
        stages = {
            item["id"]: item["state"]
            for item in stage_states(_entry(reason="PERCEPTION_INSUFFICIENT"))
        }
        assert stages["DATOS"] == "pass"
        assert stages["PERCEPCION"] == "block"
        assert stages["AGENTE LLM"] == "idle"

    def test_cost_block_still_credits_the_agent(self) -> None:
        # The agent did decide; the commission is what stopped the order.
        stages = {
            item["id"]: item["state"]
            for item in stage_states(_entry(reason="AGENT_BUY_R3_C90_D_BELOW_COST"))
        }
        assert stages["AGENTE LLM"] == "pass"
        assert stages["COSTE Y CADENCIA"] == "block"

    def test_protective_stop_blocks_early(self) -> None:
        stages = {
            item["id"]: item["state"] for item in stage_states(_entry(reason="PROTECTIVE_STOP"))
        }
        assert stages["STOP EXCHANGE"] == "block"
        assert stages["AGENTE LLM"] == "idle"

    def test_dry_run_prefix_is_ignored(self) -> None:
        stages = {
            item["id"]: item["state"]
            for item in stage_states(_entry(reason="DRY_RUN:PERCEPTION_INSUFFICIENT"))
        }
        assert stages["PERCEPCION"] == "block"

    def test_no_activity_is_all_idle(self) -> None:
        assert all(item["state"] == "idle" for item in stage_states(None))


class TestDeliberations:
    def test_surfaces_the_agents_own_words_newest_first(self, tmp_path: Path) -> None:
        rows = recent_deliberations(_memory(tmp_path, decisions=3))
        assert len(rows) == 3
        assert rows[0]["reason"] == "razonamiento numero 2"

    def test_flags_when_the_agent_overrode_the_advisor(self, tmp_path: Path) -> None:
        # The advisor's p_long is 0.42 (PLANO) while the agent chose LARGO.
        rows = recent_deliberations(_memory(tmp_path, decisions=1))
        assert rows[0]["quant_says"] == EXPOSURE_CASH
        assert rows[0]["target_exposure"] == EXPOSURE_INVESTED
        assert rows[0]["overrode_quant"] is True

    def test_marks_the_deliberated_pass(self, tmp_path: Path) -> None:
        rows = recent_deliberations(_memory(tmp_path, decisions=3))
        assert rows[-1]["deliberated"] is True  # index 0 carried thinking
        assert rows[0]["deliberated"] is False

    def test_missing_memory_is_empty_not_an_error(self, tmp_path: Path) -> None:
        assert recent_deliberations(tmp_path / "nope.sqlite3") == []

    def test_corrupt_memory_is_empty_not_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.sqlite3"
        path.write_text("no soy una base de datos", encoding="utf-8")
        assert recent_deliberations(path) == []


class TestTrackRecordView:
    def test_reports_the_same_gate_the_agent_obeys(self, tmp_path: Path) -> None:
        view = track_record_view(_memory(tmp_path, decisions=3))
        assert view["available"] is True
        assert view["error"] is None
        # Mirrors llm_memory, so the page cannot advertise a looser gate.
        assert view["min_samples"] == 8
        assert view["min_effect"] == 1.5
        assert view["stats"]["decisiones_totales"] == 3

    def test_missing_memory_is_reported_not_silently_empty(self, tmp_path: Path) -> None:
        view = track_record_view(tmp_path / "nope.sqlite3")
        assert view["available"] is False
        assert view["error"] is not None

    def test_does_not_write_to_the_memory_database(self, tmp_path: Path) -> None:
        """The sandbox mounts data read-only, so a write here means a dead panel."""
        path = _memory(tmp_path, decisions=2)
        before = path.stat().st_mtime_ns
        track_record_view(path)
        recent_deliberations(path)
        assert path.stat().st_mtime_ns == before

    def test_read_only_memory_refuses_to_write(self, tmp_path: Path) -> None:
        path = _memory(tmp_path, decisions=1)
        memory = AgentMemory(path, read_only=True)
        assert memory.stats()["decisiones_totales"] == 1
        with pytest.raises(sqlite3.OperationalError):
            memory.record(
                decided_at=NOW,
                event_id="nope",
                features=[0.0] * 19,
                regime=0,
                quant_p_long=0.5,
                target_exposure=EXPOSURE_INVESTED,
                exposure_before=EXPOSURE_CASH,
                derived_order="BUY",
                conviction=0.9,
                expected_move_pct=1.0,
                reason="no deberia poder",
                thinking="",
                price=D("84000"),
                acted=True,
            )

    def test_read_only_memory_requires_an_existing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            AgentMemory(tmp_path / "nope.sqlite3", read_only=True)


class TestOrderAuthority:
    """Claiming authority the agent does not have is the worst failure here."""

    def test_reads_the_recorded_flag(self, tmp_path: Path) -> None:
        shadow = build_state(_journal(tmp_path, [_entry(order_authority=False)]))
        assert shadow["order_authority"] is False
        live = build_state(_journal(tmp_path, [_entry(order_authority=True)]))
        assert live["order_authority"] is True

    def test_a_holding_shadow_agent_is_not_reported_as_live(self, tmp_path: Path) -> None:
        # The DRY_RUN prefix is only applied to entries that wanted to trade, so a
        # shadow agent that spent the day holding carries no prefix at all. Inferring
        # from the reason alone would call this live.
        state = build_state(_journal(tmp_path, [_entry(reason="AGENT_VERDICT_UNCHANGED", order_authority=False)]))
        assert state["order_authority"] is False

    def test_unknown_when_the_journal_predates_the_field(self, tmp_path: Path) -> None:
        state = build_state(_journal(tmp_path, [_entry()]))
        assert state["order_authority"] is None

    def test_dry_run_prefix_still_understood_on_old_rows(self, tmp_path: Path) -> None:
        state = build_state(_journal(tmp_path, [_entry(reason="DRY_RUN:AGENT_BUY_R0_C85_F")]))
        assert state["order_authority"] is False


class TestStandingVerdict:
    def test_carries_the_last_real_verdict_through_reaffirmations(self, tmp_path: Path) -> None:
        # 29 of every 30 minutes look like this: a verdict held, not re-inferred.
        entries = [
            _entry(at=(NOW - timedelta(minutes=5)).isoformat(), reason="AGENT_HOLD_R3_C90_D"),
            _entry(at=NOW.isoformat(), reason="AGENT_VERDICT_UNCHANGED"),
        ]
        state = build_state(_journal(tmp_path, entries))
        assert state["active_regime"] == 3
        assert state["conviction"] == 0.90
        assert state["deliberated"] is True
        assert state["standing_verdict_at"] == (NOW - timedelta(minutes=5)).isoformat()

    def test_agent_version_survives_entries_that_omit_it(self, tmp_path: Path) -> None:
        entries = [
            _entry(directional_model_version="LLM-EXPOSURE-AGENT-V1"),
            _entry(at=(NOW + timedelta(minutes=1)).isoformat(), directional_model_version=None),
        ]
        state = build_state(_journal(tmp_path, entries))
        assert state["agent_version"] == "LLM-EXPOSURE-AGENT-V1"


class TestBuildState:

    def test_computes_equity_from_the_book(self, tmp_path: Path) -> None:
        state = build_state(_journal(tmp_path, [_entry()]))
        # 400 USDT + 0.05 BTC * 84000 = 4600
        assert state["equity"] is not None
        assert abs(float(state["equity"]) - 4600.0) < 1e-6

    def test_counts_orders(self, tmp_path: Path) -> None:
        entries = [
            _entry(),
            _entry(
                at=(NOW + timedelta(minutes=1)).isoformat(),
                action="ENTER_LONG",
                reason="AGENT_BUY_R3_C90_D",
                order_side="BUY",
                order_base_qty="0.05",
                order_avg_price="84000",
            ),
        ]
        state = build_state(_journal(tmp_path, entries))
        assert state["order_count"] == 1
        assert state["buys"] == 1
        assert state["sells"] == 0

    def test_target_exposure_comes_from_the_agents_own_verdict(self, tmp_path: Path) -> None:
        state = build_state(_journal(tmp_path, [_entry()]), _memory(tmp_path, decisions=1))
        assert state["target_exposure"] == EXPOSURE_INVESTED
        assert state["latest_deliberation"]["reason"] == "razonamiento numero 0"

    def test_empty_journal_does_not_crash(self, tmp_path: Path) -> None:
        state = build_state(_journal(tmp_path, []))
        assert state["evaluations"] == 0
        assert state["active_regime"] is None
        assert all(item["state"] == "idle" for item in state["stages"])

    def test_page_javascript_has_no_broken_string_literals(self) -> None:
        """A syntax error in the page script freezes the entire dashboard silently.

        The page is a plain Python string, so writing a single backslash-n inside a
        JavaScript string emits a real newline and breaks the literal. The server
        still returns 200 and the page still renders its static skeleton, so the
        only symptom is that nothing ever updates. That shipped once.

        Counting quotes per line catches exactly that class of bug without needing a
        JavaScript engine in the test environment.
        """
        script = re.search(r"<script>(.*?)</script>", LLM_AGENT_PAGE, re.S)
        assert script is not None
        body = script.group(1)
        offenders = []
        for number, line in enumerate(body.splitlines(), 1):
            without_escapes = re.sub(r"\\.", "", line)
            if without_escapes.count("'") % 2:
                offenders.append((number, line.strip()[:70]))
        assert not offenders, f"literales de cadena partidos: {offenders}"

    def test_page_and_api_both_forbid_caching(self) -> None:
        """A cached page keeps running old JavaScript against the current API, which
        is indistinguishable from a frozen dashboard."""
        import inspect

        from btc_decision_agent.observability import llm_agent_dashboard

        source = inspect.getsource(llm_agent_dashboard._Handler.do_GET)
        # Both branches must set it, not just the JSON one.
        assert source.count("Cache-Control") >= 2

    def test_page_shows_a_connection_heartbeat(self) -> None:
        """Most values legitimately change only every 30 minutes, so without a
        heartbeat a healthy page is visually identical to a dead one."""
        assert 'id="live"' in LLM_AGENT_PAGE
        assert "en vivo" in LLM_AGENT_PAGE
        assert "SIN CONEXION" in LLM_AGENT_PAGE
        # A stalled agent and a broken connection are different problems.
        assert "el agente no avanza" in LLM_AGENT_PAGE

    def test_page_is_about_the_llm_agent_not_the_numeric_policy(self) -> None:
        # The previous dashboard's subject was the numeric policy's own conviction.
        assert "RAZONAMIENTO DEL AGENTE" in LLM_AGENT_PAGE
        assert "QUIEN DECIDIO" in LLM_AGENT_PAGE
        assert "CALIBRACION" in LLM_AGENT_PAGE
        assert "PATRONES MEDIDOS EN SU HISTORIAL" in LLM_AGENT_PAGE
        # And it must say out loud when it is not the order authority.
        assert "SOMBRA (sin ordenes)" in LLM_AGENT_PAGE


class TestDailySummary:
    def test_summary_counts_orders_and_real_vetoes(self) -> None:
        from scripts.daily_summary import build_summary

        entries = [
            _entry(at=(NOW - timedelta(hours=2)).isoformat()),
            _entry(at=(NOW - timedelta(hours=1)).isoformat(), reason="DATA_STALE"),
            _entry(
                at=(NOW - timedelta(minutes=30)).isoformat(),
                action="ENTER_LONG",
                reason="AGENT_BUY_R3_C90_D",
                order_side="BUY",
                order_base_qty="0.05",
                order_avg_price="84000",
                fees_usdt="4.2",
            ),
        ]
        summary = build_summary(entries, hours=24, now=NOW)
        assert summary["orders"] == 1
        assert len(summary["buys"]) == 1
        assert summary["vetoes"] == {"DATA_STALE": 1}
        assert summary["fees_usdt"] == "4.2"

    def test_fallback_is_not_counted_as_a_veto(self) -> None:
        """The old report called this a veto, which reads as "a layer blocked the
        agent" when the truth is "the model did not answer". Different reactions."""
        from scripts.daily_summary import build_summary

        entries = [
            _entry(reason="FALLBACK_QUANT_HOLD"),
            _entry(reason="FALLBACK_QUANT_HOLD"),
            _entry(reason="AGENT_HOLD_R0_C85_F"),
            _entry(reason="DATA_STALE"),
        ]
        summary = build_summary(entries, hours=24, now=NOW)
        assert summary["vetoes"] == {"DATA_STALE": 1}
        assert summary["decided_by_fallback"] == 2
        assert summary["decided_by_llm"] == 1
        assert summary["vetoed"] == 1

    def test_shadow_mode_is_announced(self) -> None:
        from scripts.daily_summary import build_summary, render

        summary = build_summary([_entry(order_authority=False)], hours=24, now=NOW)
        assert "SOMBRA" in render(summary)

    def test_order_authority_is_not_announced_as_shadow(self) -> None:
        from scripts.daily_summary import build_summary, render

        summary = build_summary([_entry(order_authority=True)], hours=24, now=NOW)
        assert "SOMBRA" not in render(summary)

    def test_reports_the_agents_verdict_and_override(self, tmp_path: Path) -> None:
        from scripts.daily_summary import build_summary, render

        summary = build_summary(
            [_entry(order_authority=True)],
            memory_path=_memory(tmp_path, decisions=2),
            hours=24,
            now=NOW,
        )
        assert summary["target_exposure"] == EXPOSURE_INVESTED
        assert summary["advisor_says"] == EXPOSURE_CASH
        assert summary["overrode_advisor"] is True
        message = render(summary)
        assert f"Veredicto: {EXPOSURE_INVESTED}" in message
        assert "contradicho" in message
        assert "Historial medido: 2 decisiones" in message

    def test_summary_excludes_entries_outside_the_window(self) -> None:
        from scripts.daily_summary import build_summary

        entries = [
            _entry(at=(NOW - timedelta(days=5)).isoformat(), order_side="BUY"),
            _entry(at=(NOW - timedelta(hours=1)).isoformat()),
        ]
        summary = build_summary(entries, hours=24, now=NOW)
        assert summary["orders"] == 0
        assert summary["evaluations"] == 1

    def test_summary_marks_a_dead_process_as_stale(self) -> None:
        from scripts.daily_summary import build_summary, render

        summary = build_summary(
            [_entry(at=(NOW - timedelta(hours=3)).isoformat())], hours=24, now=NOW
        )
        assert summary["stale"] is True
        assert "posiblemente caido" in render(summary)

    def test_names_the_model_so_the_reader_knows_who_decided(self) -> None:
        from scripts.daily_summary import build_summary, render

        summary = build_summary([_entry(order_authority=True)], hours=24, now=NOW)
        assert "qwen3:30b-a3b" in render(summary)

    def test_render_stays_short(self, tmp_path: Path) -> None:
        from scripts.daily_summary import build_summary, render

        # The fullest realistic message: shadow warning, an order, a verdict and
        # learning all present at once.
        summary = build_summary(
            [
                _entry(
                    order_authority=False,
                    order_side="BUY",
                    order_base_qty="0.05",
                    order_avg_price="84000",
                    fees_usdt="4.2",
                )
            ],
            memory_path=_memory(tmp_path, decisions=2),
            hours=24,
            now=NOW,
        )
        # Conciseness is the stated requirement, so it is asserted.
        assert len(render(summary).splitlines()) <= 10
