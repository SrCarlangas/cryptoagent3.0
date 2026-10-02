"""Pre-registered gate deciding whether the LLM agent may hold order authority.

These criteria are written and committed BEFORE the backtest result is read. That
ordering is the whole point: a gate defined after seeing the number is not a gate,
it is a justification. The script exits 0 only if every criterion passes.

The product this gate now scores
--------------------------------
REWRITTEN 2026-10-01 around the pivot declared in advance in `roadmap.md`: the product is
not "beat buy and hold", it is **buy and hold with the drawdown cut**. Four independent
measurements of the timing correlation (+0.01, +0.02, -0.11, +0.03, standard error 0.15)
say the momentum edge that "beat buy and hold" requires is not there, and a gate that
demands it would either reject every honest agent or push the search until noise looked
like signal.

The rewrite does NOT relax anything. It closes a hole. The old gate compared the agent to
RAW buy and hold, so simply being less exposed counted as a win on drawdown -- but holding
less BTC achieves exactly that trade with no skill whatever. A constant 0.6x position
delivers roughly 0.6x the return and 0.6x the drawdown for free. So the null hypothesis for
"buy and hold with the tail cut" is **static de-risking**, and the agent is now scored
against a buy and hold DE-LEVERAGED TO THE AGENT'S OWN DRAWDOWN. Two criteria are added and
none is removed or loosened.

Measured against the runs that exist, the new gate is STRICTER on the window that matters:
on the bull window the retired capture criterion demanded +92.2% and the new one demands
+125.4%. The agent reached +68.94%. It FAILS, and that is recorded here rather than tuned.

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
"""RETIRED 2026-10-01, superseded by MIN_REGIME_EXPOSURE_SPREAD. Kept for the record, and
still used as a fallback for older reports whose trace carries no regime field, so a
historical verdict is never silently recomputed.

Original intent, which the replacement keeps: both exposures must appear, because a constant
agent is either buy and hold in disguise or a machine that never invests, and neither needs
an LLM.

Why it was wrong. Within-window minority share counts DECISIONS, not conditioning, so a
handful of decisions in a rarely-visited regime satisfies it without the agent having
discriminated at all. Measured on the bear window: the agent showed a 12% minority and
passed, but that 12% came from **4 decisions** in regimes r2 and r3 (3 and 1 decisions, at
78% and 95% exposure). In the two regimes it actually saw -- r0 with 40 decisions at 2.9%
exposure and r1 with 16 at 0.0% -- its exposure differed by **2.9%**. It was flat, and the
criterion reported discrimination.

This also corrects a looser claim made when the repair was proposed: the defect is not that
the criterion "punishes a correct constant answer". It is that minority share is not evidence
of conditioning in either direction."""

MIN_DECISIONS_PER_REGIME = 5
"""Decisions a regime needs before its mean exposure may carry the criterion.

A regime visited once or twice has a mean exposure that is one decision, not a behaviour. On
the bear window r3 appeared exactly once at 95% exposure, and allowing that to count is how a
flat agent looked discriminating."""

MIN_REGIME_EXPOSURE_SPREAD = 0.30
"""ADDED 2026-10-01. Required gap between the agent's most and least exposed regime.

Discrimination is conditioning, so it is measured ACROSS the regimes the agent actually saw
rather than as a headcount within the window. A constant agent has a spread of zero no matter
how its decisions are distributed.

Derived, not fitted. Exposure per decision lies in [0, 1] with a standard deviation around
0.4 at these allocations; with roughly 15 decisions in a regime the standard error of its
mean is about 0.10, so the standard error of the difference between two regime means is about
0.15. A 0.30 requirement is therefore about two standard errors -- the point at which a gap
stops being explicable as sampling noise. The number was committed from that argument before
either archived run was measured against it.

Requires at least two regimes with MIN_DECISIONS_PER_REGIME decisions. Fewer than two and the
criterion CANNOT BE EVALUATED, so it fails: a window that never made the agent choose is not
evidence that it chooses well, which is the asymmetry `handover.md` section 3 already warned
about when it said the bear window's approval was not symmetric with the bull window's
rejection.

Measured consequences on the archived runs:
- Bull window: r0 0.0% (11 decisions), r2 71.6% (21), r3 84.5% (28). Spread 84.5%, PASSES.
  The agent genuinely conditions on its own regime labels there.
- Bear window: only r0 (40 decisions, 2.9%) and r1 (16, 0.0%) clear the decision floor.
  Spread 2.9%, FAILS. The old criterion passed this window at 12%."""

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
effect that replicated across every earlier study, so it is the one demanded.

Unchanged at 3.0. It is kept as a FLOOR rather than raised, because on a window whose
reference barely falls, any absolute pp threshold is either trivial or impossible -- the
same defect that retired MAX_RETURN_SHORTFALL_PP. The binding test is now the scale-free
ratio below, and this remains only so a window with a tiny reference drawdown cannot be
passed by a ratio alone."""

MAX_DRAWDOWN_RATIO = 0.60
"""ADDED 2026-10-01. The agent's drawdown as a fraction of the reference's.

The primary claim of the pivoted product is the tail cut, so the pivot cannot be allowed to
make the gate cheaper: the claim now has to be demonstrated in a form that does not depend
on how far the window happened to fall. Cutting the drawdown to at most three fifths of buy
and hold's is what "materially cut" has to mean to be worth a sentence in a product
description.

Derived rather than chosen: at 0.60 the agent must do strictly better than the de-risking
that criterion MIN_CAPTURE_OF_RISK_MATCHED_HOLD prices, because a static 0.60x position
also pays 0.60x of the return, and the pair of criteria together therefore demand a cut in
risk AND retention of return beyond what static sizing gives. Either alone is passable by
simply holding less.

On the bull window this demands at most 12.0% against buy and hold's 20.0%; the best run
measured 17.0% and FAILS. On the bear window it demands at most 23.7% against 39.5% and the
run measured 6.1%, which passes comfortably."""

MIN_CAPTURE_OF_RISK_MATCHED_HOLD = 1.00
"""ADDED 2026-10-01. Share of a RISK-MATCHED buy and hold the agent must earn.

This is the criterion that makes the pivot honest, and it is the one the old gate lacked.

"Buy and hold with the drawdown cut" is not an achievement by itself: holding a constant
fraction f of BTC delivers approximately f times the return and f times the drawdown, with
no forecasting, no model and no LLM. So the benchmark is constructed to match the agent's
OWN realised risk:

    f               = agent_drawdown / reference_drawdown
    risk_matched    = f * reference_return

and the agent must at least MATCH that, net of the commission it paid and a one-shot static
holder did not. Falling short means a passive investor who simply held less BTC would have
done better at the same risk, which is a reason not to run an agent at all, not a tradeoff.

Set to 1.00 rather than a fraction, and the first draft of this rewrite got that wrong. At
0.80 the gate would have approved an agent delivering 80% of what static sizing gives for
free -- a product strictly dominated by doing nothing. A tolerance below 1.00 has no
defensible size, because any shortfall against a free alternative is a shortfall. The real
tolerance the agent deserves is the commission a static holder avoids, so that is what is
granted, measured from the run instead of chosen.

Applied only when the reference RISES, for the same reason as the retired criterion it
replaces: capturing a fraction of a loss is not a virtue, and the falling leg is tested by
the drawdown criteria.

Measured consequences, stated before any new run:
- Bull window: f = 16.99/20.00 = 0.85, risk-matched = +156.6%, requirement = +154.9% after
  the 1.68% commission allowance. The best run reached +68.94% and FAILS. The retired
  criterion demanded +92.2%, so this is HARDER by 63 percentage points.
- Bear window: f = 6.1/39.5 = 0.154, risk-matched = -1.98%, requirement = -2.34% after the
  0.36% commission allowance. The agent returned -2.39% and FAILS BY 0.05pp -- a tie. Its
  celebrated bear result is approximately what static de-risking to the same drawdown
  produces by itself, which is the single most important thing this rewrite surfaces and the
  reason the criterion had to apply in the falling leg too."""

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
"""RETIRED 2026-10-01, superseded by MIN_CAPTURE_OF_RISK_MATCHED_HOLD. Kept for the record.

Retired because it compared against RAW buy and hold, which ignores the risk the agent
actually took and so could be satisfied, or failed, for reasons that have nothing to do with
skill. Its replacement is strictly harder on the development window (+125.4% required
against this one's +92.2%), so this is a repair of the instrument and not a relaxation.

Original rationale follows, unchanged.

Share of a RISING reference's move the agent must capture.

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


def _risk_matched_check(
    *,
    agent_return: float,
    agent_drawdown: float,
    reference_return: float,
    reference_drawdown: float,
    minimum: float,
    commission_pct: float | None,
) -> tuple[str, bool, str]:
    """Score the agent against a buy and hold de-leveraged to the agent's own drawdown.

    This is the null hypothesis of the pivoted product: holding a constant fraction of BTC
    cuts the drawdown by roughly that fraction and costs roughly that fraction of the
    return, with no model involved. An agent that does not beat it is not delivering "buy
    and hold with the tail cut", it is delivering a more expensive way to hold less.

    Applied in BOTH legs, and that symmetry is deliberate. The retired capture criterion
    skipped the falling leg on the grounds that capturing a share of a loss is no virtue,
    which is true of RAW buy and hold but false of a risk-matched one: losing more than a
    static position of the same realised risk means the deciding added nothing. Skipping it
    is what allowed the bear window to be approved on a basis that static de-risking
    reproduces for free.
    """
    name = "bate a comprar y mantener con el MISMO riesgo"
    if reference_drawdown <= 0.0:
        # Cannot be evaluated, so it must not pass.
        return (name, False, "la referencia no reporta caida: criterio no evaluable, FALLA")

    fraction = agent_drawdown / reference_drawdown
    risk_matched = fraction * reference_return

    # One formula, both legs. A static f-sized position earns f times a rising reference and
    # loses f times a falling one, so "at least match it" is the same inequality either way.
    # The only concession is the commission the agent paid and a one-shot holder did not.
    allowance = commission_pct or 0.0
    required = risk_matched * minimum - allowance
    verb = "habria dado" if reference_return > 0.0 else "habria perdido"
    return (
        name,
        agent_return >= required,
        f"a su caida de {agent_drawdown:.1f}% ({fraction:.2f}x la de la referencia) un "
        f"comprar-y-mantener estatico {verb} {risk_matched:+.1f}%; el agente "
        f"{agent_return:+.1f}% (limite {required:+.1f}%, que ya le concede "
        f"{allowance:.2f}% de comision que el estatico no paga)",
    )


def _discrimination_check(
    trace: list[dict[str, Any]] | None,
    long_share: float,
    minority: float,
) -> tuple[str, bool, str]:
    """Does the agent's exposure actually CONDITION on its regime, or is it merely varied?

    Measured as the gap between the most and least exposed regime, counting only regimes with
    enough decisions to describe a behaviour. Falls back to the retired within-window minority
    share when a report predates the trace format, so an old verdict is never silently
    recomputed into a different answer.
    """
    name = "discrimina: la exposicion depende del regimen"
    if not trace or "regime" not in trace[0] or "share_target" not in trace[0]:
        return (
            name,
            minority >= MIN_MINORITY_SHARE,
            f"INVERTIDO {long_share:.0%} / EN LIQUIDEZ {1 - long_share:.0%}, minoria "
            f"{minority:.0%} (minimo {MIN_MINORITY_SHARE:.0%}) "
            "[informe antiguo: sin regimenes en la traza, criterio retirado]",
        )

    shares: dict[int, list[float]] = {}
    for entry in trace:
        shares.setdefault(int(entry["regime"]), []).append(float(entry["share_target"]))
    usable = {
        regime: sum(values) / len(values)
        for regime, values in shares.items()
        if len(values) >= MIN_DECISIONS_PER_REGIME
    }
    detail = " ".join(
        f"r{regime}={sum(values) / len(values):.0%}({len(values)})"
        for regime, values in sorted(shares.items())
    )
    if len(usable) < 2:
        # Cannot be evaluated, so it must not pass.
        return (
            name,
            False,
            f"{detail} — solo {len(usable)} regimen con >= "
            f"{MIN_DECISIONS_PER_REGIME} decisiones: criterio no evaluable, FALLA",
        )

    spread = max(usable.values()) - min(usable.values())
    return (
        name,
        spread >= MIN_REGIME_EXPOSURE_SPREAD,
        f"{detail} — diferencia entre el regimen mas y menos expuesto {spread:.0%} "
        f"(minimo {MIN_REGIME_EXPOSURE_SPREAD:.0%}, solo cuentan regimenes con >= "
        f"{MIN_DECISIONS_PER_REGIME} decisiones)",
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
        _discrimination_check(report.get("trace"), long_share, minority),
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
        (
            "recorta la caida de forma material, no marginal",
            float(hold["max_drawdown_pct"]) > 0.0
            and float(agent["max_drawdown_pct"])
            <= MAX_DRAWDOWN_RATIO * float(hold["max_drawdown_pct"]),
            f"caida {float(agent['max_drawdown_pct']):.1f}% vs b&h "
            f"{float(hold['max_drawdown_pct']):.1f}% = "
            f"{float(agent['max_drawdown_pct']) / float(hold['max_drawdown_pct']):.2f}x "
            f"(limite {MAX_DRAWDOWN_RATIO:.2f}x, es decir "
            f"{MAX_DRAWDOWN_RATIO * float(hold['max_drawdown_pct']):.1f}%)"
            if float(hold["max_drawdown_pct"]) > 0.0
            else "la referencia no reporta caida: criterio no evaluable, FALLA",
        ),
        _risk_matched_check(
            agent_return=float(agent["net_return_pct"]),
            agent_drawdown=float(agent["max_drawdown_pct"]),
            reference_return=float(hold["net_return_pct"]),
            reference_drawdown=float(hold["max_drawdown_pct"]),
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=commission,
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
