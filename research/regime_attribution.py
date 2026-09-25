"""Attribute a backtest's profit and loss to the regime that was active when decided.

Why this exists
---------------
The owner asked for the agent to be profitable in every regime. That cannot even be
discussed without measuring it, and nothing measured it: the report showed which
exposure each regime chose and never what that choice earned.

Why it is deliberately NOT a tuning loop
----------------------------------------
This reports per-regime results and their standard errors. It does not search for
parameters that make every regime green, and the standard errors are printed precisely
so that temptation is visible. With roughly 25 decisions per regime on a single window,
a per-regime mean is a very noisy quantity: moving playbook multipliers until all four
turn positive is curve fitting, and this project already has a long record of exactly
that failing out of sample. Of twenty signal/horizon pairs measured on non-overlapping
samples, none reached one standard error.

What a negative regime actually calls for
-----------------------------------------
If a regime has no edge, the honest response is to stop trading it, not to find
parameters that flatter it. The playbook already expresses that: set the regime's
default exposure to cash and require conviction to deviate. "Do not lose money in this
regime" is achievable. "Make money in this regime" may not be, and the difference
matters.

Reads data/validation/llm-agent-backtest.json, or any report given on the command line.

Usage:
    python -m research.regime_attribution [report.json ...]
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

DEFAULT_REPORT = "data/validation/llm-agent-backtest.json"
REGIME_NAMES = {
    0: "recuperacion lateral",
    1: "bajista profundo",
    2: "consolidacion",
    3: "alcista fuerte",
}


def attribute(trace: list[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    """Assign each interval's equity change to the regime that was active at its start.

    The interval between two decisions is credited to the decision that opened it,
    because that decision is what determined the exposure held through it. The final
    decision is dropped: it has no closing equity, and carrying it with a zero return
    would quietly bias the last regime toward zero.
    """
    has_invested = ["invested_share" in row for row in trace]
    buckets: dict[Any, list[float]] = defaultdict(list)
    invested: dict[Any, list[float]] = defaultdict(list)
    overrides: dict[Any, int] = defaultdict(int)

    for current, following in pairwise(trace):
        start, end = float(current["equity"]), float(following["equity"])
        if start <= 0:
            continue
        regime = current.get("regime")
        buckets[regime].append((end / start - 1.0) * 100.0)
        invested[regime].append(float(current.get("invested_share", 0.0)))
        if current.get("choice_honoured") is False:
            overrides[regime] += 1

    out: dict[Any, dict[str, Any]] = {}
    for regime, returns in buckets.items():
        count = len(returns)
        mean = sum(returns) / count
        if count > 1:
            variance = sum((value - mean) ** 2 for value in returns) / (count - 1)
            stderr = math.sqrt(variance / count)
        else:
            stderr = float("inf")
        # Compounded rather than summed: the intervals happen in sequence, and adding
        # percentages overstates a sequence of gains and understates a sequence of losses.
        compounded = 1.0
        for value in returns:
            compounded *= 1.0 + value / 100.0
        out[regime] = {
            "intervals": count,
            "total_return_pct": (compounded - 1.0) * 100.0,
            "mean_per_interval_pct": mean,
            "stderr_pct": stderr if math.isfinite(stderr) else None,
            "effect_in_standard_errors": (abs(mean) / stderr) if stderr > 0 and math.isfinite(stderr) else 0.0,
            "positive_share": sum(1 for value in returns if value > 0) / count,
            # None, not zero, when the report predates the field: a 0% invested share
            # and "the report cannot tell us" are different facts and must not look
            # the same in a table.
            "mean_invested_share": (
                sum(invested[regime]) / count if any(has_invested) else None
            ),
            "regime_overrode_agent": overrides[regime],
        }
    return out


def report_on(path: Path) -> int:
    if not path.is_file():
        print(f"informe no encontrado: {path}")
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    trace = payload.get("trace") or []
    if len(trace) < 3:
        print(f"{path}: traza demasiado corta para atribuir")
        return 1

    results = attribute(trace)
    window = payload.get("window", {})
    agent = payload.get("llm_agent", {})

    print("=" * 96)
    print(f"ATRIBUCION POR REGIMEN  ·  {path.name}")
    print("=" * 96)
    print(
        f"  ventana: dias {window.get('start_day_index')}-{window.get('end_day_index')} "
        f"({window.get('days')} dias, paso {window.get('step_days')}d)"
    )
    print(
        f"  agente: {agent.get('net_return_pct', 0.0):+.2f}%   "
        f"buy and hold: {payload.get('buy_and_hold', {}).get('net_return_pct', 0.0):+.2f}%   "
        f"cuantitativo: {payload.get('quant_policy', {}).get('net_return_pct', 0.0):+.2f}%"
    )
    print()
    header = (
        f"  {'regimen':<26} {'tramos':>7} {'total':>9} {'medio':>9} {'ee':>7} "
        f"{'efecto':>7} {'aciertos':>9} {'invertido':>10} {'impuesto':>9}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for regime in sorted(results, key=lambda value: (value is None, value)):
        data = results[regime]
        name = f"{regime} {REGIME_NAMES.get(regime, '?')}"
        stderr = data["stderr_pct"]
        stderr_text = f"{stderr:.2f}" if stderr is not None else "n/d"
        share = data["mean_invested_share"]
        share_text = f"{share:.0%}" if share is not None else "n/d"
        print(
            f"  {name:<26} {data['intervals']:>7} "
            f"{data['total_return_pct']:>+8.2f}% {data['mean_per_interval_pct']:>+8.2f}% "
            f"{stderr_text:>7} {data['effect_in_standard_errors']:>7.1f} "
            f"{data['positive_share']:>8.0%} {share_text:>10} "
            f"{data['regime_overrode_agent']:>9}"
        )
    print()
    print("  Lectura honesta de la columna 'efecto': es |media| / error estandar. Por")
    print("  debajo de 1 no se distingue de cero, asi que un regimen 'rentable' con")
    print("  efecto 0.4 no es un hallazgo, es ruido con signo. Ajustar parametros hasta")
    print("  que los cuatro regimenes salgan positivos en UNA ventana es exactamente el")
    print("  procedimiento que hizo perder a todas las versiones anteriores de este")
    print("  proyecto. Si un regimen no tiene ventaja, lo correcto es no operarlo:")
    print("  ponerle la liquidez como exposicion por defecto y exigir conviccion para")
    print("  desviarse. 'No perder dinero en este regimen' es alcanzable; 'ganar dinero")
    print("  en este regimen' puede no serlo.")
    return 0


def main() -> int:
    paths = [Path(value) for value in sys.argv[1:]] or [Path(DEFAULT_REPORT)]
    worst = 0
    for path in paths:
        worst = max(worst, report_on(path))
        print()
    return worst


if __name__ == "__main__":
    sys.exit(main())
