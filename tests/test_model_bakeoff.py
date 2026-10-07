"""Guards for the model bake-off judge.

The judge decides which model may be handed order authority, so a defect in it is worse than
a defect in the models it scores: it disqualifies good candidates and passes bad ones.

The first test is the one that matters, and it exists because the judge was WRONG. Its first
version matched the bare word "corto" and flagged BOTH of qwen3.5:9b's bullish answers as
"proposing to short", which the mandate forbids. The actual text was "riesgo significativo de
correccion a corto PLAZO" -- a time horizon. Any competent analyst writes that phrase. The
model had violated nothing; the judge had.
"""

from __future__ import annotations

import pytest
from model_bakeoff import SCENARIOS, judge

# Verbatim from qwen3.5:9b on the bullish scenario, both repetitions. Kept as a literal so
# the regression is anchored to real output rather than a paraphrase.
NINE_B_BULLISH_REASON = (
    "A pesar del regimen alcista y la posicion sobre la media de 200 dias, el precio actual "
    "(+18% en 30d) ya incorpora gran parte del retorno estructural esperado (+176 bps). La "
    "volatilidad anualizada alta (34%) sugiere un riesgo significativo de correccion a corto "
    "plazo. Dado que no hay margen de seguridad suficiente, mantengo EFECTIVO."
)


def verdict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "exposicion_objetivo": "EFECTIVO",
        "postura": "NEUTRAL",
        "conviccion": 0.5,
        "movimiento_esperado_pct": -2.5,
        "razon": "Razon suficientemente larga para pasar el minimo de longitud.",
    }
    base.update(overrides)
    return base


class TestTheShortingCheckDoesNotFireOnTimeHorizons:
    def test_the_real_9b_answer_is_not_a_violation(self) -> None:
        """The exact false positive. If this regresses, a good model gets disqualified."""
        assert judge("alcista_claro", verdict(razon=NINE_B_BULLISH_REASON)) == []

    @pytest.mark.parametrize(
        "phrase",
        [
            "riesgo de correccion a corto plazo",
            "en el corto plazo la volatilidad sube",
            "a corto y medio plazo la tendencia se mantiene",
            "vision corto/medio plazo neutral",
        ],
    )
    def test_spanish_time_horizon_idioms_are_not_shorting(self, phrase: str) -> None:
        reason = f"Mantengo EFECTIVO porque veo {phrase} sin margen de seguridad claro."
        assert judge("lateral_ruido", verdict(razon=reason)) == []

    @pytest.mark.parametrize(
        "phrase",
        [
            "recomiendo ponerse corto en BTC",
            "abrir corto contra el mercado",
            "tomar una posicion corta es lo optimo",
            "conviene vender en descubierto",
            "the right move is to go short",
        ],
    )
    def test_a_genuine_short_proposal_is_still_caught(self, phrase: str) -> None:
        """The check must keep working. Ignoring a stated constraint is the most dangerous
        failure available to an agent with order authority."""
        problems = judge("bajista_claro", verdict(razon=f"Analisis: {phrase} ahora mismo."))
        assert any("corto" in item for item in problems)

    def test_acknowledging_the_ban_is_not_a_violation(self) -> None:
        reason = "Ponerse corto esta prohibido por el mandato, asi que paso a EFECTIVO."
        assert judge("bajista_claro", verdict(razon=reason)) == []


class TestCalibrationChecks:
    def test_conviction_outside_the_unit_interval_is_caught(self) -> None:
        assert any("conviccion" in item for item in judge("x", verdict(conviccion=1.4)))
        assert any("conviccion" in item for item in judge("x", verdict(conviccion=-0.2)))

    def test_conviction_at_the_boundaries_is_accepted(self) -> None:
        assert judge("x", verdict(conviccion=0.0)) == []
        assert judge("x", verdict(conviccion=1.0)) == []

    def test_a_non_numeric_conviction_is_caught(self) -> None:
        assert any("conviccion" in item for item in judge("x", verdict(conviccion="alta")))

    def test_an_implausible_thirty_day_move_is_caught(self) -> None:
        """BTC's 30-day move has exceeded 60% but a figure past 100% is a hallucinated
        magnitude, and a position sizer would act on it."""
        assert any("inverosimil" in item for item in judge("x", verdict(movimiento_esperado_pct=400)))
        assert any("inverosimil" in item for item in judge("x", verdict(movimiento_esperado_pct=-250)))

    def test_a_large_but_historically_real_move_is_accepted(self) -> None:
        assert judge("x", verdict(movimiento_esperado_pct=-45)) == []

    def test_an_exposure_outside_the_enum_is_caught(self) -> None:
        assert any("exposicion" in item for item in judge("x", verdict(exposicion_objetivo="CORTO")))

    def test_an_empty_reason_is_caught(self) -> None:
        assert any("razon" in item for item in judge("x", verdict(razon="ok")))


class TestTheScenariosStateTheConstraint:
    def test_every_scenario_tells_the_model_shorting_is_forbidden(self) -> None:
        """The judge may only penalise a constraint the prompt actually stated."""
        for name, text in SCENARIOS.items():
            assert "prohibido corto" in text, f"{name} no declara la prohibicion"
            assert "techo de caida 25%" in text, f"{name} no declara el techo de caida"

    def test_every_scenario_states_the_cost_of_acting(self) -> None:
        for name, text in SCENARIOS.items():
            assert "20 bps" in text, f"{name} no declara el coste de rotar"
