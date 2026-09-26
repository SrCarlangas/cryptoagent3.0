"""What the agent's own declared numbers actually look like.

The owner asked for the agent to have more authority and for the gap to be closed from the
agent's side rather than by the playbook overriding it. Both need to know whether the
agent's declarations carry information at all.

Three things the playbook reads off the agent and acts on:

- CONVICTION gates deviation from the regime default and scales the position.
- EXPECTED MOVE gates entries against the round-trip cost.
- POSTURE selects the size, the stop and the trailing geometry.

If any of them is effectively constant, then the mechanism that reads it is decoration and
giving the agent more authority just amplifies a number that says nothing. This prints the
distributions, the association between what it declared and what happened, and how often it
lands exactly on a threshold, which is the signature of a model reciting the number it was
told about rather than estimating one.

Usage:
    python -m research.agent_calibration [report.json]
"""

from __future__ import annotations

import json
import statistics as stats
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from btc_decision_agent.application.llm_tools import EXPOSURE_INVESTED
from btc_decision_agent.application.regime_playbook import strategy_for


def _histogram(values: list[float], label: str, *, width: int = 46) -> None:
    if not values:
        print(f"  {label}: sin datos")
        return
    counts = Counter(round(value, 2) for value in values)
    top = max(counts.values())
    print(f"  {label}: {len(values)} valores, {len(counts)} distintos")
    for value, count in sorted(counts.items()):
        bar = "#" * max(1, round(count / top * width))
        print(f"    {value:>6.2f}  {count:>3}  {bar}")
    if len(counts) > 1:
        print(
            f"    media {stats.mean(values):.3f}  desv {stats.pstdev(values):.3f}  "
            f"min {min(values):.2f}  max {max(values):.2f}"
        )


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/validation/llm-agent-backtest.json")
    if not path.is_file():
        print(f"informe no encontrado: {path}")
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    trace: list[dict[str, Any]] = payload.get("trace") or []
    if not trace:
        print("traza vacia")
        return 1

    print("=" * 84)
    print(f"QUE DICE EL AGENTE, Y SI ESO LLEVA INFORMACION  ·  {path.name}")
    print(f"  {len(trace)} decisiones, agente {payload['llm_agent']['net_return_pct']:+.2f}%")
    print("=" * 84)
    print()
    _histogram([float(item["conviction"]) for item in trace], "CONVICCION")
    print()
    _histogram(
        [float(item["expected_move_pct"]) for item in trace], "MOVIMIENTO ESPERADO declarado (%)"
    )
    print()
    postures = Counter(item["posture"] for item in trace)
    print(f"  POSTURA: {dict(postures)}")

    print()
    print("  DISCRIMINACION: cuantos valores distintos usa de verdad")
    print("  Un modelo que dice siempre lo mismo no esta juzgando. Y como la postura y la")
    print("  conviccion son lo unico que el playbook lee para decidir el TAMANO, si ambas se")
    print("  colapsan el tamano se vuelve constante y la modulacion por regimen desaparece.")
    for label, values in (
        ("conviccion", [float(item["conviction"]) for item in trace]),
        ("mov. esperado", [float(item["expected_move_pct"]) for item in trace]),
    ):
        distinct = len({round(value, 2) for value in values})
        top = Counter(round(value, 2) for value in values).most_common(1)[0]
        print(
            f"    {label:<14} {distinct:>2} valores distintos, "
            f"el mas repetido {top[0]} en {top[1]}/{len(values)} = {top[1] / len(values):.0%}"
        )
    dominant = postures.most_common(1)[0]
    print(
        f"    {'postura':<14} {len(postures):>2} valores distintos, "
        f"la mas repetida {dominant[0]} en {dominant[1]}/{len(trace)} = {dominant[1] / len(trace):.0%}"
    )

    print()
    print("  LO QUE DECLARO CONTRA LO QUE PASO DESPUES")
    print("  Si la conviccion informa, las decisiones de alta conviccion deberian salir")
    print("  mejor que las de baja. Medido sobre el equity entre decisiones consecutivas.")
    buckets: dict[str, list[float]] = {"baja <0.6": [], "media 0.6-0.7": [], "alta >=0.7": []}
    for index in range(len(trace) - 1):
        item, following = trace[index], trace[index + 1]
        moved = (float(following["equity"]) / float(item["equity"]) - 1.0) * 100.0
        conviction = float(item["conviction"])
        key = "baja <0.6" if conviction < 0.6 else ("media 0.6-0.7" if conviction < 0.7 else "alta >=0.7")
        buckets[key].append(moved)
    for key, values in buckets.items():
        if not values:
            print(f"    {key:<16} sin datos")
            continue
        mean = stats.mean(values)
        error = stats.pstdev(values) / max(1, len(values) ** 0.5) if len(values) > 1 else 0.0
        effect = abs(mean) / error if error else 0.0
        print(
            f"    {key:<16} n={len(values):>3}  media {mean:+.2f}%  "
            f"ee {error:.2f}  efecto {effect:.1f}"
        )

    print()
    print("  DONDE EL AGENTE DISCREPA DEL PLAYBOOK")
    disagreements = 0
    for item in trace:
        default_in = strategy_for(item.get("regime")).default_exposure == EXPOSURE_INVESTED
        asked_in = item.get("agent_asked_for") == EXPOSURE_INVESTED
        if item.get("agent_asked_for") is not None and asked_in != default_in:
            disagreements += 1
    print(
        f"    pidio lo contrario a la exposicion por defecto en {disagreements}/{len(trace)} "
        f"= {disagreements / len(trace):.0%} de las decisiones"
    )
    forced = sum(1 for item in trace if item.get("choice_honoured") is False)
    print(f"    y el playbook le dio la vuelta en {forced} = {forced / len(trace):.0%}")
    print()
    print("  El efecto en la tabla anterior es |media| / error estandar. Por debajo de 1 no")
    print("  se distingue de cero: la conviccion declarada no predice el resultado, y darle")
    print("  mas autoridad a un numero que no informa solo amplifica ruido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
