"""Where the part of the move the agent did NOT capture went.

Why this is worth computing
---------------------------
Three exposure policies produced captures of 34%, 32% and 29% of a +184% advance, inside a
ten point band. Arguing about which policy is best is therefore arguing inside the noise.
The useful question is different: of the roughly 70% not captured, how much is the agent
choosing to be out of the market, how much is it being only partly invested while in, and
how much is timing, stops and commission?

That decomposition decides whether the gap is closable at all, and by what, and it needs no
model calls: the equity path already contains the answer.

How the effective exposure is recovered
---------------------------------------
Not from the recorded share, which is measured at the decision and says nothing about what
was held through the interval that follows, and not from the target, which is an intention.
It is inverted out of the equity path itself:

    equity_next / equity_now ~= 1 + f * (price_next / price_now - 1)

so f, the share of equity that was actually exposed across the interval, is

    f = (equity_ratio - 1) / (price_ratio - 1)

This is what the book DID, including every stop that fired mid-interval, which is exactly
what makes it the right quantity. Intervals where the price barely moved are dropped, since
the division becomes unstable and those intervals carry almost no information about exposure.

Usage:
    python -m research.capture_decomposition report.json [report.json ...]
"""

from __future__ import annotations

import json
import statistics as stats
import sys
from pathlib import Path
from typing import Any

MIN_PRICE_MOVE = 0.01
"""Intervals moving less than this are dropped: f is recovered by dividing by the move."""


def decompose(path: Path) -> dict[str, Any] | None:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    trace: list[dict[str, Any]] = payload.get("trace") or []
    if len(trace) < 5:
        return None
    agent = float(payload["llm_agent"]["net_return_pct"])
    hold = float(payload["buy_and_hold"]["net_return_pct"])

    exposures: list[float] = []
    out_of_market = 0
    for index in range(len(trace) - 1):
        now, following = trace[index], trace[index + 1]
        price_ratio = float(following["price"]) / float(now["price"])
        equity_ratio = float(following["equity"]) / float(now["equity"])
        if abs(price_ratio - 1.0) < MIN_PRICE_MOVE:
            continue
        exposure = (equity_ratio - 1.0) / (price_ratio - 1.0)
        # Clamp: values outside [0, 1.2] mean the interval is dominated by something other
        # than exposure, such as a stop filling far from the close.
        exposures.append(max(0.0, min(1.2, exposure)))
        if float(now["invested_share"]) <= 0.01:
            out_of_market += 1

    if not exposures:
        return None
    mean_exposure = stats.mean(exposures)

    # The unambiguous test of timing, which capture-over-exposure only gestures at: does the
    # exposure the agent actually held line up with the move that followed? Correlated with
    # the move it is in when the market rises and out when it falls. Near zero it has no
    # timing at all, whatever its exposure. Negative and its exposure is concentrated in the
    # worse stretches, which is worse than being under-invested because it is a decision.
    #
    # Measured against the move over the SAME interval the exposure was held, which is what
    # the exposure earned. The lead-one version would ask a different question, whether the
    # agent anticipates, and the equity path cannot answer it here.
    moves = []
    paired = []
    for index in range(len(trace) - 1):
        now, following = trace[index], trace[index + 1]
        price_ratio = float(following["price"]) / float(now["price"])
        if abs(price_ratio - 1.0) < MIN_PRICE_MOVE:
            continue
        moves.append(price_ratio - 1.0)
    paired = list(zip(exposures, moves, strict=True))
    if len(paired) > 2 and len({round(value, 6) for value, _ in paired}) > 1:
        correlation = stats.correlation([value for value, _ in paired], [m for _, m in paired])
    else:
        correlation = 0.0
    return {
        "name": path.stem,
        "agent": agent,
        "hold": hold,
        "capture": agent / hold if hold else 0.0,
        "mean_exposure": mean_exposure,
        "flat_decisions": out_of_market / max(1, len(trace) - 1),
        "usable_intervals": len(exposures),
        "commission": float(payload["llm_agent"].get("commission_paid_pct") or 0.0),
        "stop_exits": int(payload["llm_agent"]["stop_exits"]),
        "timing": correlation,
        "intervals": len(paired),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python -m research.capture_decomposition informe.json [...]")
        return 2
    results = [decompose(Path(argument)) for argument in sys.argv[1:]]
    usable = [result for result in results if result is not None]
    if not usable:
        print("ninguna traza utilizable")
        return 1

    print("=" * 104)
    print("A DONDE SE VA LA PARTE NO CAPTURADA")
    print("=" * 104)
    print(
        f"  {'corrida':<38} {'capt':>5} {'exposicion':>11} {'capt/expo':>10} "
        f"{'plano':>6} {'stops':>6} {'comision':>9} {'timing':>8}"
    )
    print("  " + "-" * 100)
    for result in usable:
        efficiency = result["capture"] / result["mean_exposure"] if result["mean_exposure"] else 0.0
        label = result["name"].replace("2026-09-2", "…2").replace("-60d-paso5", "")
        print(
            f"  {label[:38]:<38} {result['capture']:>4.0%} {result['mean_exposure']:>10.0%} "
            f"{efficiency:>9.0%} {result['flat_decisions']:>5.0%} {result['stop_exits']:>6} "
            f"{result['commission']:>8.2f}% {result['timing']:>+8.2f}"
        )
    print()
    print("  'exposicion' es la fraccion de capital que de verdad estuvo expuesta, despejada")
    print("  del propio camino del equity, asi que incluye los stops que saltaron a mitad de")
    print("  intervalo. Es el techo mecanico de lo que se podia capturar.")
    print()
    print("  'capt/expo' es lo que separa dos cosas que se confunden todo el rato: estar poco")
    print("  invertido y equivocarse con el momento. Por encima del 100% el agente estuvo")
    print("  expuesto en los tramos buenos y fuera en los malos, y su criterio de momento")
    print("  aporta. Por debajo, la exposicion que tuvo se gasto en los tramos peores.")
    print()
    print("  'timing' es la correlacion entre la exposicion que tuvo y el movimiento del")
    print("  precio en ese mismo intervalo. Positiva: estuvo dentro cuando subia y fuera")
    print("  cuando bajaba. Cerca de cero: no tiene criterio de momento, solo exposicion.")
    print("  Negativa: su exposicion se concentro en los tramos peores.")
    intervals = min(result["intervals"] for result in usable)
    error = 1.0 / max(1.0, intervals**0.5)
    print()
    print(
        f"  Con {intervals} intervalos utilizables el error estandar de esa correlacion es de "
        f"~{error:.2f},"
    )
    print(
        f"  asi que cualquier valor dentro de +-{2 * error:.2f} no se distingue de cero. Leer un"
    )
    print("  signo dentro de esa banda como criterio de momento seria inventarse una senal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
