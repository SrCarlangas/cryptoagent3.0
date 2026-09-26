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
"""DIRECTION changes per decision. The threshold is unchanged; what is counted is.

The project priced unbounded churn at 137% of capital per year, and a round trip is what
costs that. Once the playbook could scale a position, `switches` counted every order, so one
side of a trade was charged as if it were a full turn and an agent adding to a trend looked
like a churner. The best run reported 47% counting orders and 32% counting direction
changes, against the same 30% limit.

Counting differently would be a way to relax a criterion by the back door, so it is paired
with MAX_COMMISSION_PCT below, which measures the cost itself rather than a proxy for it.
Older reports have no direction_changes field; for those the criterion falls back to
`switches` so a historical verdict is never silently recomputed as a pass.
"""

MAX_COMMISSION_PCT = 6.0
"""Commission actually paid over the window, as a percentage of starting capital.

Derived from the criterion above rather than picked: 30% of decisions turning over the book
at a 20 bps round trip is 6% of capital across a 60 decision window. So this is the same
budget the switch rate always implied, measured directly from the fills instead of inferred
from a count. Whichever of the two binds first, the churn is capped.
"""

MIN_DRAWDOWN_ADVANTAGE_PP = 3.0
"""Percentage points of drawdown it must save versus buy and hold. This is the
effect that replicated across every earlier study, so it is the one demanded."""

MAX_RETURN_SHORTFALL_PP = 25.0
"""RETIRED. Kept so the record shows what the earlier runs were judged against.

It was a shortfall in absolute percentage points, and that made the same criterion
trivial on one window and near-impossible on another. Against a falling reference of
-12.86% a 25pp allowance is satisfied by almost anything. Against a rising reference of
+184.44% it demands +159.44%, which is a harder test than BEATING buy and hold on a flat
window, in a gate whose own docstring says beating buy and hold is not required.

Replaced by MIN_CAPTURE_OF_RISING_REFERENCE, which asks the same question in a form that
does not depend on the size of the window's move.
"""

MIN_CAPTURE_OF_RISING_REFERENCE = 0.50
"""Share of a RISING reference's move the agent must capture.

Changed at the owner's instruction, after a run, and that sequence is stated plainly
because it is the thing pre-registration exists to prevent. What justifies it is that the
previous form was broken rather than that the agent failed it: an absolute percentage-point
allowance is not comparable across windows, which is a defect in the instrument.

The threshold is derived, not chosen to fit. The playbook's own declared exposure sets the
mechanical expectation: at the allocations each regime declares, and invested for the share
of hours the playbook's defaults imply, a strategy captures roughly two thirds of a trend
before any timing skill enters. Requiring half of the move therefore leaves room for the
stops, the commission and the regimes the playbook deliberately sits out, and only bites
when the agent's timing actively destroys value rather than merely being partly invested.

Applied only when the reference RISES. When it falls, capturing a fraction of a loss is not
a virtue, and the criterion that matters there is capital preservation, which
MIN_DRAWDOWN_ADVANTAGE_PP already tests.

On the bull window used for development this demands +92.2% and the best measured run
reached +63.6%, so the agent FAILS it as written. That is recorded here rather than
adjusted.
"""

MIN_CAPTURE_OF_FALLBACK = 0.75
"""Share of what the numeric policy earned that the agent must also earn, when the policy
is positive. When the policy LOSES, the agent must not lose more than it does.

Same repair as above, same reason: the shortfall was in absolute percentage points, so the
criterion was trivial against a -12.50% policy and demanded +122% against a +132.06% one.

Set higher than the buy-and-hold capture, at 0.75 rather than 0.50, deliberately. Buy and
hold is a reference, not an alternative: nobody is proposing to run it, and a risk-managed
strategy is expected to trail it in a trend. The numeric policy IS the alternative, it is
already validated, and it is what the agent would displace. Trailing it badly is not a
tradeoff, it is a reason not to switch. The remaining 25% is the allowance for the policy's
own churn being cheap in a backtest and expensive in reality, which is the same argument the
retired 10pp threshold rested on, expressed as a fraction.

On the bull window this demands +99.0% against the policy's +132.06%, and the best measured
run reached +63.6%. The agent FAILS it as written.
"""

MAX_SHORTFALL_VS_FALLBACK_PP = 10.0
"""RETIRED, for the same reason as MAX_RETURN_SHORTFALL_PP. Kept for the record.

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


def _capture_check(
    name: str,
    *,
    agent_return: float,
    reference_return: float,
    reference_name: str,
    minimum: float,
) -> tuple[str, bool, str]:
    """Compare against a reference in a way that does not depend on the window's size.

    Rising reference: the agent must capture at least `minimum` of its move. Falling
    reference: capturing a fraction of a loss is meaningless, so the test is simply that the
    agent did not lose more, and capital preservation is measured by the drawdown criterion.
    """
    if reference_return > 0.0:
        required = reference_return * minimum
        captured = agent_return / reference_return
        return (
            name,
            agent_return >= required,
            f"agente {agent_return:+.1f}% vs {reference_name} {reference_return:+.1f}% "
            f"= capturo {captured:.0%} (minimo {minimum:.0%}, es decir {required:+.1f}%)",
        )
    return (
        name,
        agent_return >= reference_return,
        f"agente {agent_return:+.1f}% vs {reference_name} {reference_return:+.1f}% "
        f"= referencia a la baja, basta no perder mas",
    )


def evaluate(report: dict[str, Any]) -> tuple[list[tuple[str, bool, str]], bool]:
    agent = report["llm_agent"]
    hold = report["buy_and_hold"]

    decisions = int(agent["decisions"])
    failures = int(agent["model_failures"])
    attempted = decisions + failures
    failure_rate = failures / attempted if attempted else 1.0
    long_share = float(agent["long_share"])
    minority = min(long_share, 1.0 - long_share)
    # Direction changes when the report measures them, and every order when it does not, so
    # an older report is never silently recomputed into a pass.
    if "direction_changes" in agent:
        turns = int(agent["direction_changes"])
        counting_note = ""
    else:
        turns = int(agent["switches"])
        counting_note = " [informe antiguo: cuenta ordenes, no viajes]"
    switch_rate = turns / decisions if decisions else 1.0
    commission = (
        float(agent["commission_paid_pct"]) if "commission_paid_pct" in agent else None
    )
    drawdown_saved = float(hold["max_drawdown_pct"]) - float(agent["max_drawdown_pct"])
    quant = report["quant_policy"]

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
            f"{turns} cambios de direccion en {decisions} decisiones = {switch_rate:.0%} "
            f"(limite {MAX_SWITCH_RATE:.0%}){counting_note}",
        ),
        (
            "la comision no se come el resultado",
            commission is not None and commission <= MAX_COMMISSION_PCT,
            (
                f"comision pagada {commission:.2f}% del capital "
                f"(limite {MAX_COMMISSION_PCT:.0f}%)"
                if commission is not None
                # A criterion that cannot be evaluated must not pass. Reporting 0.00% for a
                # field the report does not contain is the same class of lie as the
                # blocked_by_cost counter that showed 79 when the real value was 0.
                else "el informe no la mide: no se puede evaluar, asi que no pasa"
            ),
        ),
        (
            "preserva capital mejor que buy and hold",
            drawdown_saved >= MIN_DRAWDOWN_ADVANTAGE_PP,
            f"drawdown {agent['max_drawdown_pct']:.1f}% vs {hold['max_drawdown_pct']:.1f}% "
            f"= ahorra {drawdown_saved:+.1f}pp (minimo {MIN_DRAWDOWN_ADVANTAGE_PP:.0f}pp)",
        ),
        _capture_check(
            "captura una parte suficiente de lo que hizo buy and hold",
            agent_return=float(agent["net_return_pct"]),
            reference_return=float(hold["net_return_pct"]),
            reference_name="b&h",
            minimum=MIN_CAPTURE_OF_RISING_REFERENCE,
        ),
        _capture_check(
            "no es peor que el modelo que reemplaza",
            agent_return=float(agent["net_return_pct"]),
            reference_return=float(quant["net_return_pct"]),
            reference_name="fallback",
            minimum=MIN_CAPTURE_OF_FALLBACK,
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
