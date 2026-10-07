"""Does the LLM form its own view, or echo the quantitative model it is shown?

The bake-off raised the question: on 4 of 6 scenarios the LLM's stated conviction equalled the
`p_largo` handed to it in the prompt, to four decimals. Six scenarios cannot settle that, so
this measures it on the agent's OWN memory, where `quant_p_long` and `conviction` are stored
side by side for every real deliberation it has ever made.

Why it matters more than which model to run
-------------------------------------------
Conviction is not decorative: it SCALES THE POSITION. The prompt tells the model so --
"0.50 es no lo se y da una posicion mediana; 0.85 dice que esta evidencia es mucho mejor que
la habitual y compromete una posicion grande". If the number is copied from the quantitative
advisor, then the LLM layer adds no information, its timing correlation must equal that of the
model it copies, and six independent measurements of zero timing edge get a mechanical
explanation rather than a mysterious one.

The prompt hands `p_largo` over explicitly, labelled "MODELO CUANTITATIVO (asesor entrenado
con 5 anos)". Deferring to a trained advisor is not obviously wrong -- which is exactly why
this has to be measured instead of asserted. The question is whether the LLM is deferring
SOMETIMES, which is judgement, or ALWAYS, which is a pass-through.

What is reported
----------------
- exact-copy rate: |conviction - quant_p_long| below a float tolerance
- near-copy rate at 0.01 and 0.05, because a model that rounds is still echoing
- the DISAGREEMENT distribution, which is where any independent signal would live
- whether the LLM ever overrides the direction the quantitative model implies, which is the
  strongest evidence of an independent view
- the same statistics split by whether the deliberation reasoned (`think=True`)

Usage, on the host that holds the agent's memory:
    PYTHONPATH=src:research .venv/bin/python -m research.llm_independence
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

MEMORY = Path("data/live/llm-agent-memory.sqlite3")
REPORT = Path("data/validation/llm-independence.json")
EXACT_TOLERANCE = 1e-9
"""Float equality. A match this tight is a copy, not a coincidence."""
NEAR_TOLERANCES = (0.01, 0.05)


@dataclass(frozen=True)
class Decision:
    decided_at: str
    regime: int | None
    quant_p_long: float
    conviction: float
    target_exposure: str
    expected_move_pct: float | None
    thinking: bool


def load(path: Path) -> list[Decision]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT decided_at, regime, quant_p_long, conviction, target_exposure,
               expected_move_pct, thinking
        FROM decisions
        WHERE quant_p_long IS NOT NULL AND conviction IS NOT NULL
        ORDER BY id
        """
    ).fetchall()
    connection.close()
    out: list[Decision] = []
    for row in rows:
        thinking = row["thinking"]
        out.append(
            Decision(
                decided_at=str(row["decided_at"]),
                regime=row["regime"],
                quant_p_long=float(row["quant_p_long"]),
                conviction=float(row["conviction"]),
                target_exposure=str(row["target_exposure"]),
                expected_move_pct=(
                    float(row["expected_move_pct"])
                    if row["expected_move_pct"] is not None
                    else None
                ),
                thinking=bool(thinking) and str(thinking) not in {"", "0", "None"},
            )
        )
    return out


def summarise(decisions: list[Decision], label: str) -> dict[str, object]:
    if not decisions:
        print(f"\n--- {label}: sin decisiones ---")
        return {"n": 0}

    gaps = [item.conviction - item.quant_p_long for item in decisions]
    exact = sum(1 for gap in gaps if abs(gap) <= EXACT_TOLERANCE)
    near = {
        tolerance: sum(1 for gap in gaps if abs(gap) <= tolerance)
        for tolerance in NEAR_TOLERANCES
    }
    total = len(decisions)

    # The direction the quantitative model implies, versus what the LLM chose. Overriding it
    # is the strongest available evidence of an independent view: a pass-through cannot do it.
    overrides = [
        item
        for item in decisions
        if (item.quant_p_long >= 0.5) != (item.target_exposure == "INVERTIDO")
    ]

    print(f"\n--- {label} ---")
    print(f"  decisiones                     {total:,}")
    print(f"  COPIA EXACTA de p_largo        {exact:,}  ({exact / total:.1%})")
    for tolerance, count in near.items():
        print(f"  dentro de +-{tolerance:<5}            {count:,}  ({count / total:.1%})")
    print(f"  diferencia media               {statistics.mean(gaps):+.4f}")
    print(f"  diferencia mediana             {statistics.median(gaps):+.4f}")
    if total > 1:
        print(f"  desviacion de la diferencia    {statistics.stdev(gaps):.4f}")
    print(f"  mayor desacuerdo               {max(gaps, key=abs):+.4f}")
    print(
        f"  contradice la direccion del cuantitativo  {len(overrides):,}  "
        f"({len(overrides) / total:.1%})"
    )
    print(f"  reparto de exposicion elegida  {dict(Counter(i.target_exposure for i in decisions))}")
    convictions = Counter(round(item.conviction, 2) for item in decisions)
    print(f"  convicciones mas repetidas     {convictions.most_common(5)}")

    return {
        "n": total,
        "exact_copies": exact,
        "exact_copy_rate": exact / total,
        "near_copies": {str(k): v for k, v in near.items()},
        "mean_gap": statistics.mean(gaps),
        "median_gap": statistics.median(gaps),
        "stdev_gap": statistics.stdev(gaps) if total > 1 else None,
        "largest_disagreement": max(gaps, key=abs),
        "direction_overrides": len(overrides),
        "direction_override_rate": len(overrides) / total,
        "exposure_mix": dict(Counter(i.target_exposure for i in decisions)),
        "most_common_convictions": convictions.most_common(5),
    }


def degeneracy(decisions: list[Decision]) -> dict[str, object]:
    """Does conviction and the forecast carry information, or are they near-constants?

    This is the measurement that matters, and it was not the one this module was written to
    make. The copying hypothesis from the bake-off did NOT generalise -- but looking for it
    surfaced something worse: the conviction that SCALES THE POSITION barely moves, and the
    forecast never changes sign.

    The prompt itself names this failure: "si declaras casi siempre el mismo numero, ese
    numero ha dejado de informar y el tamano deja de responder a lo que ves". So this is not
    an external standard being imposed; it is the model's own instruction, measured.
    """
    total = len(decisions)
    convictions = Counter(round(item.conviction, 2) for item in decisions)
    modal_value, modal_count = convictions.most_common(1)[0]
    moves = [item.expected_move_pct for item in decisions if item.expected_move_pct is not None]
    exposures = Counter(item.target_exposure for item in decisions)
    modal_exposure, modal_exposure_count = exposures.most_common(1)[0]

    print("\n--- ¿INFORMA la conviccion, o es una constante? ---")
    print(f"  valores distintos de conviccion usados   {len(convictions)}")
    print(f"  valor modal                              {modal_value} en {modal_count}/{total} ({modal_count / total:.1%})")
    print(f"  rango usado                              [{min(convictions)}, {max(convictions)}]")
    print(f"  nunca declara por debajo de              {min(convictions)}  (el prompt dice que 0.50 es 'no lo se')")
    print(f"  exposicion modal                         {modal_exposure} en {modal_exposure_count}/{total} ({modal_exposure_count / total:.1%})")
    if moves:
        negatives = sum(1 for value in moves if value < 0)
        print(f"  pronosticos NEGATIVOS                    {negatives}/{len(moves)} ({negatives / len(moves):.1%})")
        print(f"  rango del pronostico                     [{min(moves):+.2f}%, {max(moves):+.2f}%]")
        print(f"  valores distintos de pronostico          {len(set(round(v, 2) for v in moves))}")
    return {
        "distinct_convictions": len(convictions),
        "modal_conviction": modal_value,
        "modal_conviction_share": modal_count / total,
        "conviction_range": [min(convictions), max(convictions)],
        "modal_exposure": modal_exposure,
        "modal_exposure_share": modal_exposure_count / total,
        "negative_forecasts": sum(1 for value in moves if value < 0),
        "forecast_count": len(moves),
        "forecast_range": [min(moves), max(moves)] if moves else None,
        "distinct_forecasts": len({round(value, 2) for value in moves}),
    }


def main() -> int:
    if not MEMORY.exists():
        print(f"no existe {MEMORY}")
        return 2
    decisions = load(MEMORY)
    if not decisions:
        print("la memoria no tiene decisiones con ambos campos; nada que comparar")
        return 2

    print("=" * 76)
    print("¿EL LLM OPINA, O REPITE AL MODELO CUANTITATIVO QUE LE ENSENAN?")
    print("=" * 76)
    print(f"fuente: {MEMORY}")
    print(f"ventana: {decisions[0].decided_at[:19]} -> {decisions[-1].decided_at[:19]}")
    print()
    print("La conviccion ESCALA LA POSICION; no es decorativa. Si se copia del asesor")
    print("cuantitativo, la capa LLM no aporta informacion y su correlacion de timing")
    print("tiene que ser la del modelo que copia.")

    report: dict[str, object] = {"source": str(MEMORY)}
    report["todas"] = summarise(decisions, "TODAS las deliberaciones")
    reasoned = [item for item in decisions if item.thinking]
    cheap = [item for item in decisions if not item.thinking]
    if reasoned and cheap:
        report["razonadas"] = summarise(reasoned, "solo las RAZONADAS (think=True)")
        report["baratas"] = summarise(cheap, "solo las BARATAS (think=False)")
    report["degeneracion"] = degeneracy(decisions)

    overall = report["todas"]
    assert isinstance(overall, dict)
    degen = report["degeneracion"]
    assert isinstance(degen, dict)
    rate = float(overall["exact_copy_rate"])  # type: ignore[arg-type]
    modal_share = float(degen["modal_conviction_share"])  # type: ignore[arg-type]
    exposure_share = float(degen["modal_exposure_share"])  # type: ignore[arg-type]

    print("\n" + "=" * 76)
    print("LECTURA")
    if rate >= 0.5:
        print(f"  El {rate:.0%} de las convicciones es COPIA EXACTA de p_largo: la capa LLM")
        print("  hereda el tamano en vez de decidirlo. Cambiar de modelo NO lo arregla.")
    else:
        print(f"  COPIA: solo el {rate:.1%} son copias exactas de p_largo. La hipotesis del")
        print("  bake-off (4 de 6 escenarios) NO GENERALIZA en produccion. Descartada.")
        mean_gap = float(overall["mean_gap"])  # type: ignore[arg-type]
        print(f"  En su lugar el LLM es sistematicamente {mean_gap:+.2f} MAS alcista que su")
        print("  asesor: no lo repite, lo desvia siempre en la misma direccion.")
    print()
    if modal_share >= 0.5 or exposure_share >= 0.95:
        print("  PERO aparece algo PEOR: la conviccion y la direccion son casi CONSTANTES.")
        print(f"    conviccion modal en el {modal_share:.0%} de las decisiones")
        print(f"    exposicion modal en el {exposure_share:.0%}")
        print(f"    pronosticos negativos: {degen['negative_forecasts']}/{degen['forecast_count']}")
        print("  Una conviccion casi constante no escala nada y una direccion casi constante")
        print("  no es una decision. Esto explica MECANICAMENTE las seis mediciones de")
        print("  correlacion de timing en cero: un agente que dice lo mismo siempre ES")
        print("  comprar-y-mantener, y su correlacion con el momento de mercado debe ser cero.")
    print("=" * 76)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"informe: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
