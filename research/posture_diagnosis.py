"""Is the agent's posture a judgement, or a habit?

The participation gap traced back to posture: 14 of 19 entries were DEFENSIVA, and in a
bull regime that halves the position. Before changing the playbook's posture ranges, the
question is whether posture responds to anything at all.

It matters because the two answers call for opposite fixes. If posture tracks the state,
the ranges are wrong and should become regime-specific like every other parameter. If
posture is a near-constant habit, widening the ranges would paper over a prompt problem,
and the fix belongs in the prompt or in making the cost of timidity explicit.

Usage:
    python -m research.posture_diagnosis [report.json]
"""

from __future__ import annotations

import collections
import json
import statistics
import sys
from itertools import pairwise
from pathlib import Path

DEFAULT_REPORT = "data/validation/llm-agent-backtest.json"
POSTURES = ("DEFENSIVA", "NEUTRAL", "AGRESIVA")


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPORT)
    if not path.is_file():
        print(f"informe no encontrado: {path}")
        return 2
    trace = json.loads(path.read_text(encoding="utf-8")).get("trace") or []
    if len(trace) < 10:
        print("traza demasiado corta")
        return 1

    counts = collections.Counter(item["posture"] for item in trace)
    total = len(trace)
    print("=" * 78)
    print(f"DIAGNOSTICO DE POSTURA  ·  {path.name}  ·  {total} decisiones")
    print("=" * 78)
    print("\n1. reparto global")
    for posture, count in counts.most_common():
        print(f"   {posture:<10} {count:>3}  ({count / total:.0%})")

    print("\n2. postura por regimen")
    by_regime: dict[object, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    for item in trace:
        by_regime[item["regime"]][item["posture"]] += 1
    for regime in sorted(by_regime, key=lambda value: (value is None, value)):
        bucket = by_regime[regime]
        subtotal = sum(bucket.values())
        row = "  ".join(
            f"{name[:3]}={bucket[name]}({bucket[name] / subtotal:.0%})" for name in POSTURES
        )
        print(f"   regimen {regime} (n={subtotal:>2}): {row}")

    print("\n3. responde a la conviccion declarada")
    for posture in POSTURES:
        values = [item["conviction"] for item in trace if item["posture"] == posture]
        if values:
            print(
                f"   {posture:<10} conviccion media {statistics.mean(values):.3f} "
                f"(min {min(values):.2f}  max {max(values):.2f}, n={len(values)})"
            )

    print("\n4. responde a la tendencia del precio")
    first = trace[0]["price"]
    for posture in POSTURES:
        values = [item["price"] / first for item in trace if item["posture"] == posture]
        if values:
            print(
                f"   {posture:<10} precio medio {statistics.mean(values):.2f}x el inicial "
                f"(n={len(values)})"
            )

    print("\n5. es una costumbre o una decision")
    dominant, dominant_count = counts.most_common(1)[0]
    sequence = [item["posture"] for item in trace]
    switches = sum(1 for a, b in pairwise(sequence) if a != b)
    print(f"   postura dominante {dominant} en el {dominant_count / total:.0%} de las decisiones")
    print(
        f"   cambios de postura entre decisiones consecutivas: {switches} de "
        f"{len(sequence) - 1} ({switches / (len(sequence) - 1):.0%})"
    )
    print()
    if dominant_count / total >= 0.60 and switches / (len(sequence) - 1) <= 0.35:
        print("   LECTURA: la postura se comporta como una costumbre, no como un juicio.")
        print("   Ensanchar las horquillas por regimen taparia un sesgo del prompt en vez")
        print("   de corregirlo: el modelo seguiria eligiendo lo mismo y solo cambiaria lo")
        print("   que ese mismo significa. El arreglo pertenece al prompt.")
    else:
        print("   LECTURA: la postura responde al estado, asi que la horquilla global es")
        print("   lo que esta mal y debe pasar a ser propia de cada regimen, como el stop")
        print("   y el riesgo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
