"""Pre-registered gate deciding whether the LLM agent may hold order authority.

These criteria are written and committed BEFORE the backtest result is read. That
ordering is the whole point: a gate defined after seeing the number is not a gate,
it is a justification. The script exits 0 only if every criterion passes.

What is deliberately NOT required
---------------------------------
Beating buy and hold is not a criterion. Three independent studies in this project
established that a reliable timing edge is not present in this asset and window: of
twenty signal/horizon pairs measured on non-overlapping samples, none reached one
standard error, and parameter choices that beat buy and hold in sample turned
negative out of sample. Requiring an edge would either reject every honest agent or
push us to keep searching until noise looked like signal.

What IS required is that the agent is not broken, not degenerate, not a churner, and
that it preserves capital in the falling leg, which is the one effect that has
replicated in every study here.

Usage:
    python -m scripts.gate_llm_agent [--report path]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_REPORT = "data/validation/llm-agent-backtest.json"

# --- pre-registered thresholds ------------------------------------------------
MAX_MODEL_FAILURE_RATE = 0.05
"""Above this the model is unreliable, regardless of what it earned."""

MIN_DECISIONS = 50
"""Fewer than this and the sample says nothing about behaviour."""

MIN_MINORITY_SHARE = 0.05
"""Both exposures must appear. A constant agent is either buy and hold in
disguise or a machine that never invests; neither needs an LLM."""

MAX_SWITCH_RATE = 0.30
"""Switches per decision. The project priced unbounded churn at 137% of capital
per year, so an agent that flips on a third of its decisions is disqualified
whatever its return."""

MIN_DRAWDOWN_ADVANTAGE_PP = 3.0
"""Percentage points of drawdown it must save versus buy and hold. This is the
effect that replicated across every earlier study, so it is the one demanded."""

MAX_RETURN_SHORTFALL_PP = 25.0
"""How far below buy and hold the net return may fall. Not beating buy and hold is
acceptable and expected; being crushed by it is not."""

MAX_SHORTFALL_VS_FALLBACK_PP = 10.0
"""How far below the numeric fallback the agent may fall.

ADDED AFTER THE FIRST RUN, AND THE FIRST RUN WOULD HAVE FAILED IT.

The original six criteria compared the agent to buy and hold and never to the policy
it displaces, which was a hole: an agent can clear every bar above and still be worse
than the thing it replaced. The first run showed exactly that, with the agent at
-25.46% against the fallback's -12.50% and a worse drawdown too, a shortfall of
12.96pp.

Stating the sequence plainly because it is the whole point of pre-registration: this
criterion did not gate that approval and cannot be used to revoke it retroactively.
It gates every run from now on.

The 10pp threshold is derived rather than chosen to fit. The fallback switched 51
times against the agent's 5; at 20 bps a round trip that is roughly 10pp of
commission the fallback pays and the agent does not. So a gap up to 10pp can be
explained by the fallback's churn being cheap in a backtest and expensive in reality.
Beyond that the agent is simply worse, and reasons stop being explanations.
"""


def evaluate(report: dict[str, Any]) -> tuple[list[tuple[str, bool, str]], bool]:
    agent = report["llm_agent"]
    hold = report["buy_and_hold"]

    decisions = int(agent["decisions"])
    failures = int(agent["model_failures"])
    attempted = decisions + failures
    failure_rate = failures / attempted if attempted else 1.0
    long_share = float(agent["long_share"])
    minority = min(long_share, 1.0 - long_share)
    switch_rate = int(agent["switches"]) / decisions if decisions else 1.0
    drawdown_saved = float(hold["max_drawdown_pct"]) - float(agent["max_drawdown_pct"])
    shortfall = float(hold["net_return_pct"]) - float(agent["net_return_pct"])
    quant = report["quant_policy"]
    fallback_shortfall = float(quant["net_return_pct"]) - float(agent["net_return_pct"])

    checks: list[tuple[str, bool, str]] = [
        (
            "produce salida valida de forma fiable",
            failure_rate <= MAX_MODEL_FAILURE_RATE,
            f"fallos {failures}/{attempted} = {failure_rate:.1%} (limite {MAX_MODEL_FAILURE_RATE:.0%})",
        ),
        (
            "muestra suficiente para juzgar comportamiento",
            decisions >= MIN_DECISIONS,
            f"{decisions} decisiones (minimo {MIN_DECISIONS})",
        ),
        (
            "discrimina: usa ambas exposiciones",
            minority >= MIN_MINORITY_SHARE,
            f"INVERTIDO {long_share:.0%} / EN LIQUIDEZ {1 - long_share:.0%}, "
            f"minoria {minority:.0%} "
            f"(minimo {MIN_MINORITY_SHARE:.0%})",
        ),
        (
            "no sobreopera",
            switch_rate <= MAX_SWITCH_RATE,
            f"{agent['switches']} cambios en {decisions} decisiones = {switch_rate:.0%} "
            f"(limite {MAX_SWITCH_RATE:.0%})",
        ),
        (
            "preserva capital mejor que buy and hold",
            drawdown_saved >= MIN_DRAWDOWN_ADVANTAGE_PP,
            f"drawdown {agent['max_drawdown_pct']:.1f}% vs {hold['max_drawdown_pct']:.1f}% "
            f"= ahorra {drawdown_saved:+.1f}pp (minimo {MIN_DRAWDOWN_ADVANTAGE_PP:.0f}pp)",
        ),
        (
            "el retorno no queda destrozado por buy and hold",
            shortfall <= MAX_RETURN_SHORTFALL_PP,
            f"agente {agent['net_return_pct']:+.1f}% vs b&h {hold['net_return_pct']:+.1f}% "
            f"= deficit {shortfall:+.1f}pp (limite {MAX_RETURN_SHORTFALL_PP:.0f}pp)",
        ),
        (
            "no es peor que el modelo que reemplaza",
            fallback_shortfall <= MAX_SHORTFALL_VS_FALLBACK_PP,
            f"agente {agent['net_return_pct']:+.1f}% vs fallback {quant['net_return_pct']:+.1f}% "
            f"= deficit {fallback_shortfall:+.1f}pp "
            f"(limite {MAX_SHORTFALL_VS_FALLBACK_PP:.0f}pp) "
            f"[criterio anadido tras la primera pasada]",
        ),
    ]
    return checks, all(passed for _name, passed, _detail in checks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-registered gate for order authority.")
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args()

    path = Path(args.report)
    if not path.is_file():
        print(f"informe no encontrado: {path}")
        return 2
    report = json.loads(path.read_text(encoding="utf-8"))

    checks, passed = evaluate(report)
    agent = report["llm_agent"]
    quant = report["quant_policy"]
    hold = report["buy_and_hold"]

    print("=" * 74)
    print("GATE PRE-REGISTRADO PARA AUTORIDAD DE ORDENES")
    print("=" * 74)
    print(f"  modelo: {report['model']}   razonamiento: {report['think_enabled']}")
    print(f"  ventana: {report['window']['days']} dias, paso {report['window']['step_days']}d")
    print()
    print(f"  agente LLM          {agent['net_return_pct']:+8.2f}%   dd {agent['max_drawdown_pct']:5.2f}%   cambios {agent['switches']}")
    print(f"  modelo cuantitativo {quant['net_return_pct']:+8.2f}%   dd {quant['max_drawdown_pct']:5.2f}%   cambios {quant['switches']}")
    print(f"  buy and hold        {hold['net_return_pct']:+8.2f}%   dd {hold['max_drawdown_pct']:5.2f}%")
    print()
    for name, ok, detail in checks:
        print(f"  [{'PASA' if ok else 'FALLA'}] {name}")
        print(f"         {detail}")
    print()
    print(f"VEREDICTO: {'APROBADO' if passed else 'RECHAZADO'}")
    if not passed:
        print("No se otorga autoridad de ordenes.")
    else:
        print("Cumple los criterios fijados de antemano. Puede tomar autoridad de ordenes.")
        print("Recordatorio de evidencia: una ventana, una pasada. Esto demuestra que no")
        print("esta roto, no que tenga ventaja.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
