"""Guards for the independence / degeneracy reader.

This module retired one of my own hypotheses and replaced it with a worse finding, so its
arithmetic is asserted rather than its formatting.

The copying hypothesis came from 6 bake-off scenarios where the LLM's conviction equalled the
`p_largo` it was shown. On 312 real deliberations the exact-copy rate is 0.3%. The hypothesis
did not generalise and is recorded as refuted -- a reminder that six observations chosen by
hand are not evidence about a population.

What replaced it is measurable and worse: conviction sat at 0.75 in 82% of decisions, exposure
at INVERTIDO in 99.7%, and not one of 312 forecasts was negative. A conviction that does not
vary cannot scale a position, and that is a mechanical explanation for six independent
measurements of zero timing correlation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from llm_independence import EXACT_TOLERANCE, Decision, degeneracy, load, summarise


def decision(
    conviction: float,
    quant: float,
    exposure: str = "INVERTIDO",
    move: float | None = 3.5,
    thinking: bool = False,
) -> Decision:
    return Decision(
        decided_at="2026-10-01T00:00:00",
        regime=3,
        quant_p_long=quant,
        conviction=conviction,
        target_exposure=exposure,
        expected_move_pct=move,
        thinking=thinking,
    )


class TestCopyDetection:
    def test_an_exact_copy_is_detected(self) -> None:
        result = summarise([decision(0.5682, 0.5682)], "t")
        assert result["exact_copies"] == 1
        assert result["exact_copy_rate"] == pytest.approx(1.0)

    def test_a_tiny_float_difference_still_counts_as_a_copy(self) -> None:
        """Rounding to four decimals is still echoing, not deciding."""
        result = summarise([decision(0.5682, 0.5682 + EXACT_TOLERANCE / 2)], "t")
        assert result["exact_copies"] == 1

    def test_a_real_disagreement_is_not_a_copy(self) -> None:
        result = summarise([decision(0.75, 0.5682)], "t")
        assert result["exact_copies"] == 0
        assert result["mean_gap"] == pytest.approx(0.1818, abs=1e-4)

    def test_the_measured_production_gap_is_a_systematic_bullish_tilt(self) -> None:
        """Not an echo: the LLM sat ~0.19 ABOVE its advisor, always the same way.

        Hand-computed from the modal pair actually observed (0.75 against 0.5682).
        """
        assert pytest.approx(0.1818, abs=1e-4) == 0.75 - 0.5682

    def test_overriding_the_advisor_direction_is_counted(self) -> None:
        """p_long below 0.5 means the advisor leans flat; choosing INVERTIDO overrides it."""
        result = summarise([decision(0.75, 0.42, exposure="INVERTIDO")], "t")
        assert result["direction_overrides"] == 1

    def test_agreeing_with_the_advisor_direction_is_not_an_override(self) -> None:
        assert summarise([decision(0.75, 0.56, exposure="INVERTIDO")], "t")["direction_overrides"] == 0
        assert summarise([decision(0.3, 0.42, exposure="EN LIQUIDEZ")], "t")["direction_overrides"] == 0


class TestDegeneracyDetection:
    def test_a_constant_conviction_is_flagged_as_a_single_value(self) -> None:
        result = degeneracy([decision(0.75, 0.56) for _ in range(50)])
        assert result["distinct_convictions"] == 1
        assert result["modal_conviction_share"] == pytest.approx(1.0)

    def test_the_measured_production_shares_are_reproduced(self) -> None:
        """257 of 312 at 0.75, and 311 of 312 INVERTIDO. Asserted as arithmetic."""
        decisions = (
            [decision(0.75, 0.56) for _ in range(257)]
            + [decision(0.85, 0.56) for _ in range(35)]
            + [decision(0.70, 0.56) for _ in range(13)]
            + [decision(0.80, 0.56) for _ in range(4)]
            + [decision(0.58, 0.58) for _ in range(2)]
            + [decision(0.58, 0.58, exposure="EN LIQUIDEZ") for _ in range(1)]
        )
        assert len(decisions) == 312
        result = degeneracy(decisions)
        assert result["modal_conviction"] == 0.75
        assert result["modal_conviction_share"] == pytest.approx(257 / 312, abs=1e-4)
        assert result["modal_conviction_share"] > 0.82
        assert result["distinct_convictions"] == 5
        assert result["modal_exposure"] == "INVERTIDO"
        assert result["modal_exposure_share"] == pytest.approx(311 / 312, abs=1e-4)

    def test_never_forecasting_a_decline_is_counted(self) -> None:
        """0 of 312 negative. In a window where BTC fell, that is a directional bias."""
        result = degeneracy([decision(0.75, 0.56, move=value) for value in (0.5, 3.5, 12.0)])
        assert result["negative_forecasts"] == 0
        assert result["forecast_range"] == [0.5, 12.0]

    def test_a_negative_forecast_is_counted_when_present(self) -> None:
        result = degeneracy([decision(0.75, 0.56, move=value) for value in (-8.0, 3.5)])
        assert result["negative_forecasts"] == 1

    def test_a_varied_conviction_is_not_degenerate(self) -> None:
        result = degeneracy(
            [decision(value, 0.56) for value in (0.2, 0.35, 0.5, 0.65, 0.8, 0.95)]
        )
        assert result["distinct_convictions"] == 6
        assert result["modal_conviction_share"] < 0.2


class TestTheReaderIsReadOnlyAndRobust:
    def test_rows_missing_either_field_are_excluded(self, tmp_path: Path) -> None:
        """A decision without one side of the comparison cannot be compared, and counting it
        as zero would invent a disagreement."""
        database = tmp_path / "memory.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute(
            """
            CREATE TABLE decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, decided_at TEXT NOT NULL,
                event_id TEXT, features TEXT NOT NULL, regime INTEGER,
                quant_p_long REAL, target_exposure TEXT NOT NULL,
                exposure_before TEXT NOT NULL, derived_order TEXT NOT NULL,
                conviction REAL, expected_move_pct REAL, reason TEXT, thinking TEXT,
                price_at_decision TEXT
            )
            """
        )
        rows = [
            ("2026-10-01", "f", 3, 0.56, "INVERTIDO", "EN LIQUIDEZ", "BUY", 0.75, 3.5, "r", "", "1"),
            ("2026-10-02", "f", 3, None, "INVERTIDO", "INVERTIDO", "HOLD", 0.75, 3.5, "r", "", "1"),
            ("2026-10-03", "f", 3, 0.56, "INVERTIDO", "INVERTIDO", "HOLD", None, 3.5, "r", "", "1"),
        ]
        connection.executemany(
            "INSERT INTO decisions (decided_at, features, regime, quant_p_long,"
            " target_exposure, exposure_before, derived_order, conviction,"
            " expected_move_pct, reason, thinking, price_at_decision)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.commit()
        connection.close()

        loaded = load(database)
        assert len(loaded) == 1
        assert loaded[0].conviction == pytest.approx(0.75)

    def test_the_reader_opens_the_database_read_only(self, tmp_path: Path) -> None:
        """It reads the LIVE agent's memory. It must never be able to alter it."""
        import inspect

        import llm_independence

        source = inspect.getsource(llm_independence.load)
        assert "mode=ro" in source, "the live memory must be opened read-only"
