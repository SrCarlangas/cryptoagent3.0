"""Guards for the agent's own calibration feedback.

Two defects were measured on 312 live deliberations (`research/llm_independence.py`) and both
are encoded here.

1. A hit rate was shown to the model with NO NULL beside it. The agent chose INVERTIDO in
   99.7% of decisions, so "acertaste 51%" was very nearly just the rate at which BTC rose.
   This project refuses to report a number without its comparator everywhere else; the
   agent's own feedback loop was the one place that did.
2. Nothing measured whether the agent USED its conviction range. It declared 0.75 in 82.4% of
   decisions and never below 0.58, while the prompt tells it that a number declared almost
   always has stopped informing. The instruction existed; the measurement did not.

These tests assert the arithmetic of the lift and of the dispersion, not the wording.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from btc_decision_agent.application.llm_memory import AgentMemory, render_memory_block

BASE = datetime(2026, 10, 1, tzinfo=UTC)
ENTRY = Decimal("80000")
UP = Decimal("84000")
"""+5% on the entry, so an INVERTIDO decision resolves POSITIVE."""
DOWN = Decimal("76000")
"""-5% on the entry, so an INVERTIDO decision resolves NEGATIVE."""


def memory_with(rows: list[tuple[float, float]], path: Path) -> AgentMemory:
    """Build a memory whose resolved outcomes carry the requested SIGNS.

    Uses the real API rather than hand-written SQL: decisions are recorded with a
    one-hour horizon and resolved by `resolve_pending`, which signs the outcome by the
    exposure the agent chose. One call resolves every pending decision at a single
    price, so the rows are grouped by desired sign and resolved in two passes.
    """
    memory = AgentMemory(path, horizon_hours=1)
    index = 0
    for wanted_positive, resolution_price in ((True, UP), (False, DOWN)):
        group = [item for item in rows if (item[1] > 0) is wanted_positive]
        if not group:
            continue
        decided_at = BASE + timedelta(days=index + 1)
        for conviction, _realized in group:
            memory.record(
                decided_at=decided_at,
                event_id=f"e{index}",
                features=[0.1, 0.2, 0.3],
                regime=3,
                quant_p_long=0.56,
                target_exposure="INVERTIDO",
                exposure_before="INVERTIDO",
                derived_order="HOLD",
                conviction=conviction,
                expected_move_pct=3.5,
                reason="prueba de calibracion",
                thinking="",
                price=ENTRY,
                acted=False,
                horizon_hours=1,
            )
            index += 1
        memory.resolve_pending(decided_at + timedelta(hours=2), resolution_price)
    return memory


class TestEveryHitRateCarriesItsNull:
    def test_the_base_rate_is_the_agents_own_unconditional_hit_rate(self, tmp_path: Path) -> None:
        """Six decisions, three with a positive outcome. The null is 50%."""
        rows = [(0.6, 1.0), (0.6, -1.0), (0.75, 1.0), (0.75, -1.0), (0.9, 1.0), (0.9, -1.0)]
        result = memory_with(rows, tmp_path / "m.sqlite3").calibration()
        assert result["tasa_base_propia"] == pytest.approx(0.5)

    def test_a_bucket_matching_the_base_rate_has_zero_lift(self, tmp_path: Path) -> None:
        """The decisive case: conviction that predicts nothing must read as nothing.

        All three buckets hit 50%, so every lift is 0.00 and no conviction level is
        distinguishable from always being in the market.
        """
        rows = [(0.6, 1.0), (0.6, -1.0), (0.75, 1.0), (0.75, -1.0), (0.9, 1.0), (0.9, -1.0)]
        buckets = memory_with(rows, tmp_path / "m.sqlite3").calibration()["buckets"]
        for name, data in buckets.items():
            assert data["ventaja_sobre_tasa_base"] == pytest.approx(0.0), name

    def test_a_genuinely_predictive_bucket_shows_positive_lift(self, tmp_path: Path) -> None:
        rows = [
            (0.9, 1.0),
            (0.9, 1.0),
            (0.9, 1.0),
            (0.9, 1.0),
            (0.6, -1.0),
            (0.6, -1.0),
            (0.6, -1.0),
            (0.6, -1.0),
        ]
        result = memory_with(rows, tmp_path / "m.sqlite3").calibration()
        assert result["tasa_base_propia"] == pytest.approx(0.5)
        assert result["buckets"]["0.85-1.0"]["ventaja_sobre_tasa_base"] == pytest.approx(0.5)
        assert result["buckets"]["0.5-0.7"]["ventaja_sobre_tasa_base"] == pytest.approx(-0.5)

    def test_the_measured_live_inversion_is_reproduced(self, tmp_path: Path) -> None:
        """Live: 0.7-0.85 hit 51% over 51 cases, 0.85-1.0 hit 31% over 29.

        Higher conviction performed WORSE. Reduced here to the same proportions, the lift
        of the high bucket must come out negative -- the arithmetic that makes the
        overconfidence visible instead of merely stated.
        """
        rows = [(0.75, 1.0)] * 26 + [(0.75, -1.0)] * 25 + [(0.9, 1.0)] * 9 + [(0.9, -1.0)] * 20
        result = memory_with(rows, tmp_path / "m.sqlite3").calibration()
        mid = result["buckets"]["0.7-0.85"]
        high = result["buckets"]["0.85-1.0"]
        assert mid["acierto"] == pytest.approx(26 / 51, abs=1e-3)
        assert high["acierto"] == pytest.approx(9 / 29, abs=1e-3)
        assert high["acierto"] < mid["acierto"], "higher conviction did worse"
        assert high["ventaja_sobre_tasa_base"] < 0.0

    def test_the_block_shows_the_base_rate_to_the_model(self, tmp_path: Path) -> None:
        rows = [(0.75, 1.0), (0.75, -1.0), (0.9, 1.0), (0.9, -1.0)]
        block = render_memory_block(memory_with(rows, tmp_path / "m.sqlite3"), [0.1, 0.2, 0.3])
        assert "TU TASA BASE" in block
        assert "ventaja sobre tu tasa base" in block


class TestConvictionDispersionIsMeasured:
    def test_a_constant_conviction_is_reported_as_such(self, tmp_path: Path) -> None:
        rows = [(0.75, 1.0)] * 10
        dispersion = memory_with(rows, tmp_path / "m.sqlite3").calibration()["dispersion"]
        assert dispersion["valores_distintos"] == 1
        assert dispersion["valor_modal"] == 0.75
        assert dispersion["cuota_modal"] == pytest.approx(1.0)
        assert dispersion["minimo"] == dispersion["maximo"] == 0.75

    def test_the_measured_live_share_is_reproduced(self, tmp_path: Path) -> None:
        """82.4% at 0.75, range [0.58, 0.85], five distinct values."""
        rows = (
            [(0.75, 1.0)] * 257
            + [(0.85, -1.0)] * 35
            + [(0.70, 1.0)] * 13
            + [(0.80, 1.0)] * 4
            + [(0.58, 1.0)] * 3
        )
        assert len(rows) == 312
        dispersion = memory_with(rows, tmp_path / "m.sqlite3").calibration()["dispersion"]
        assert dispersion["n"] == 312
        assert dispersion["valores_distintos"] == 5
        assert dispersion["cuota_modal"] == pytest.approx(257 / 312, abs=1e-4)
        assert dispersion["cuota_modal"] > 0.82
        assert dispersion["minimo"] == 0.58
        assert dispersion["maximo"] == 0.85

    def test_a_degenerate_conviction_triggers_the_warning_in_the_block(self, tmp_path: Path) -> None:
        rows = [(0.75, 1.0)] * 9 + [(0.85, -1.0)]
        block = render_memory_block(memory_with(rows, tmp_path / "m.sqlite3"), [0.1, 0.2, 0.3])
        assert "ATENCION" in block
        assert "casi siempre el mismo numero" in block

    def test_a_well_spread_conviction_does_not_trigger_the_warning(self, tmp_path: Path) -> None:
        """The warning must not fire on an agent that IS using its range, or it becomes
        noise the model learns to ignore."""
        rows = [(0.2, 1.0), (0.35, -1.0), (0.5, 1.0), (0.65, -1.0), (0.8, 1.0), (0.95, -1.0)]
        block = render_memory_block(memory_with(rows, tmp_path / "m.sqlite3"), [0.1, 0.2, 0.3])
        assert "tu uso del rango de conviccion" in block
        assert "ATENCION" not in block

    def test_the_warning_threshold_is_a_majority(self, tmp_path: Path) -> None:
        """Exactly half is not 'almost always' and must not warn; a clear majority must."""
        half = [(0.75, 1.0)] * 5 + [(0.6, 1.0), (0.7, 1.0), (0.8, 1.0), (0.85, 1.0), (0.9, 1.0)]
        assert "ATENCION" not in render_memory_block(
            memory_with(half, tmp_path / "a.sqlite3"), [0.1, 0.2, 0.3]
        )
        majority = [(0.75, 1.0)] * 6 + [(0.6, 1.0), (0.7, 1.0), (0.8, 1.0), (0.85, 1.0)]
        assert "ATENCION" in render_memory_block(
            memory_with(majority, tmp_path / "b.sqlite3"), [0.1, 0.2, 0.3]
        )


class TestNoRegressionOnEmptyMemory:
    def test_an_empty_memory_still_renders(self, tmp_path: Path) -> None:
        memory = AgentMemory(tmp_path / "memory.sqlite3", horizon_hours=24)
        block = render_memory_block(memory, [0.1, 0.2, 0.3])
        assert "primera decision" in block

    def test_unresolved_decisions_do_not_produce_a_base_rate(self, tmp_path: Path) -> None:
        """A base rate from zero resolved outcomes would be an invented number."""
        memory = AgentMemory(tmp_path / "memory.sqlite3", horizon_hours=24)
        memory.record(
            decided_at=BASE,
            event_id="e0",
            features=[0.1, 0.2, 0.3],
            regime=3,
            quant_p_long=0.56,
            target_exposure="INVERTIDO",
            exposure_before="INVERTIDO",
            derived_order="HOLD",
            conviction=0.75,
            expected_move_pct=3.5,
            reason="prueba",
            thinking="",
            price=ENTRY,
            acted=False,
        )
        result = memory.calibration()
        assert result["total_resueltas"] == 0
        assert result["tasa_base_propia"] is None
        assert result["buckets"] == {}

    def test_dispersion_counts_unresolved_decisions_too(self, tmp_path: Path) -> None:
        """A defect in my own fix, encoded.

        Dispersion is about what the agent DECLARED and needs no outcome. Scoping it to
        resolved decisions threw away 231 of 312 live observations and halved the measured
        degeneracy -- 42% modal share on the resolved subset against 82.4% on everything
        the agent had said -- so the warning would not have fired on an agent that was
        plainly repeating itself.

        Here: ten decisions declared at 0.75, none resolved. Dispersion must still see ten.
        """
        memory = AgentMemory(tmp_path / "memory.sqlite3", horizon_hours=24)
        for index in range(10):
            memory.record(
                decided_at=BASE + timedelta(minutes=index),
                event_id=f"e{index}",
                features=[0.1, 0.2, 0.3],
                regime=3,
                quant_p_long=0.56,
                target_exposure="INVERTIDO",
                exposure_before="INVERTIDO",
                derived_order="HOLD",
                conviction=0.75,
                expected_move_pct=3.5,
                reason="prueba",
                thinking="",
                price=ENTRY,
                acted=False,
            )
        result = memory.calibration()
        assert result["total_resueltas"] == 0, "nothing resolved yet"
        dispersion = result["dispersion"]
        assert dispersion["n"] == 10, "dispersion must not depend on resolution"
        assert dispersion["cuota_modal"] == pytest.approx(1.0)
