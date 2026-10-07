"""Measure what the live agent actually did, from its own activity log.

This reads `data/live/llm-agent-activity.jsonl` -- the record the running service writes on every
decision -- and answers the only question that matters about a live system: did it beat the thing
it would have been trivial to do instead?

Honesty constraints, matching the research harness:

- equity is marked to market on every logged decision: `btc_qty * price + usdt_free + usdt_locked`
- the benchmark is buy and hold from the FIRST logged price, which is the alternative that needed
  no agent, no model and no server
- a risk-matched comparison is also reported, because beating buy and hold by holding less BTC is
  not skill -- it is just less exposure, and the rewritten gate exists because the old one fell
  for exactly that
- drawdown is computed on the equity curve the capital actually felt, not on closing marks
- orders are counted from the log rather than assumed from the action field

Usage, on the server where the log lives:
    PYTHONPATH=src:research .venv/bin/python -m research.live_performance
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LOG = Path("data/live/llm-agent-activity.jsonl")


@dataclass
class Snapshot:
    at: datetime
    price: float
    equity: float
    btc_value: float
    allocation: float
    action: str
    position: str
    venue: str


def as_float(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def read_snapshots(path: Path) -> tuple[list[Snapshot], int, dict[str, int]]:
    """Every decision with a usable mark, plus how many records were unusable and why."""
    snapshots: list[Snapshot] = []
    skipped = 0
    actions: dict[str, int] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            price = as_float(record.get("price"))
            stamp = record.get("at")
            if price <= 0.0 or not stamp:
                skipped += 1
                continue
            action = str(record.get("action", "?"))
            actions[action] = actions.get(action, 0) + 1
            btc = as_float(record.get("btc_qty"))
            cash = as_float(record.get("usdt_free")) + as_float(record.get("usdt_locked"))
            btc_value = btc * price
            equity = btc_value + cash
            if equity <= 0.0:
                skipped += 1
                continue
            snapshots.append(
                Snapshot(
                    at=datetime.fromisoformat(str(stamp)),
                    price=price,
                    equity=equity,
                    btc_value=btc_value,
                    allocation=btc_value / equity,
                    action=action,
                    position=str(record.get("position_after", "?")),
                    venue=str(record.get("venue", "?")),
                )
            )
    return snapshots, skipped, actions


def max_drawdown(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak)
    return worst


def main() -> int:
    if not LOG.exists():
        print(f"no existe {LOG}")
        return 2

    snapshots, skipped, actions = read_snapshots(LOG)
    if len(snapshots) < 2:
        print("registro insuficiente para medir")
        return 2

    first, last = snapshots[0], snapshots[-1]
    span_days = (last.at - first.at).total_seconds() / 86400.0

    agent_equity = [snap.equity for snap in snapshots]
    agent_return = last.equity / first.equity - 1.0
    agent_drawdown = max_drawdown(agent_equity)

    # Buy and hold: all capital into BTC at the first logged price, then nothing.
    hold_equity = [first.equity * snap.price / first.price for snap in snapshots]
    hold_return = hold_equity[-1] / hold_equity[0] - 1.0
    hold_drawdown = max_drawdown(hold_equity)

    # Risk-matched hold: the SAME drawdown as the agent realised, by holding a constant
    # fraction of buy and hold. This is the comparator the rewritten gate uses, because the
    # old gate compared against raw buy and hold -- so simply holding less BTC counted as a win.
    fraction = min(1.0, agent_drawdown / hold_drawdown) if hold_drawdown > 0 else 1.0
    matched_equity = [first.equity * (1.0 + fraction * (value / first.equity - 1.0)) for value in hold_equity]
    matched_return = matched_equity[-1] / matched_equity[0] - 1.0

    allocations = [snap.allocation for snap in snapshots]
    mean_allocation = sum(allocations) / len(allocations)

    print("=" * 74)
    print("RENDIMIENTO DEL AGENTE VIVO, desde su propio registro")
    print("=" * 74)
    print(f"  venue                 {last.venue}")
    print(f"  decisiones registradas {len(snapshots):,} (descartadas sin marca utilizable: {skipped:,})")
    print(f"  desde                 {first.at:%Y-%m-%d %H:%M} UTC")
    print(f"  hasta                 {last.at:%Y-%m-%d %H:%M} UTC")
    print(f"  periodo               {span_days:.1f} dias")
    print()
    print(f"  precio BTC inicial    {first.price:>12,.2f}")
    print(f"  precio BTC final      {last.price:>12,.2f}   ({last.price / first.price - 1.0:+.2%})")
    print()
    print("--- resultado ---")
    print(f"  capital inicial       {first.equity:>12,.2f} USDT")
    print(f"  capital final         {last.equity:>12,.2f} USDT")
    print(f"  AGENTE                {agent_return:>+11.2%}   caida maxima {agent_drawdown:.2%}")
    print(f"  comprar y mantener    {hold_return:>+11.2%}   caida maxima {hold_drawdown:.2%}")
    print(f"  diferencia            {agent_return - hold_return:>+11.2%}")
    print()
    print("--- comparacion al MISMO riesgo (el comparador del gate reescrito) ---")
    print(f"  fraccion de B&H que iguala la caida del agente: {fraction:.3f}")
    print(f"  B&H desapalancado a ese riesgo: {matched_return:+.2%}")
    # A RATIO of returns silently inverts its meaning once they go negative: an agent at
    # -1.12% against a null at -0.98% divides to 1.15, which reads as "capturing 1.15x"
    # while the agent in fact lost MORE. Report the signed DIFFERENCE, which cannot lie
    # about direction, and show the ratio only where both sides are gains.
    edge = agent_return - matched_return
    print(f"  DIFERENCIA del agente sobre ese nulo: {edge:+.2%}")
    if agent_return > 0 and matched_return > 0:
        print(f"  captura: {agent_return / matched_return:.2f}x  (gate exige >= 1.00)")
    else:
        print("  captura: NO DEFINIDA con retornos no positivos; usa la diferencia")
    print(f"  veredicto: {'supera' if edge > 0 else 'NO supera'} a no hacer nada al mismo riesgo")
    print()
    print("--- exposicion ---")
    print(f"  asignacion media a BTC   {mean_allocation:.1%}")
    print(f"  asignacion minima        {min(allocations):.1%}")
    print(f"  asignacion maxima        {max(allocations):.1%}")
    print("  recomendacion medida     18.0%  (research/static_frontier.py)")
    print()
    print("--- actividad ---")
    for name, count in sorted(actions.items(), key=lambda item: -item[1]):
        print(f"  {name:<18} {count:>7,}  ({count / sum(actions.values()):.1%})")

    changes = sum(
        1
        for before, after in itertools.pairwise(snapshots)
        if before.position != after.position
    )
    print(f"  cambios de posicion {changes:>7,}")
    print()

    # The only decisions the agent actually took. With 100% HOLD everywhere else, these are
    # the entire evidential content of the live run: everything else is the asset's own path.
    transitions = [
        (before, after)
        for before, after in itertools.pairwise(snapshots)
        if before.position != after.position
    ]
    if transitions:
        print("--- las unicas decisiones reales, una por una ---")
        for before, after in transitions:
            print(
                f"  {after.at:%Y-%m-%d %H:%M}  {before.position:>5} -> {after.position:<5} "
                f"precio {after.price:>10,.2f}  accion {after.action}"
            )
        print()
        print("--- coste de esas decisiones: ¿estar fuera ayudo o costo? ---")
        flat_spans: list[tuple[Snapshot, Snapshot]] = []
        opened: Snapshot | None = None
        for before, after in transitions:
            if before.position == "LONG" and after.position != "LONG":
                opened = after
            elif opened is not None and after.position == "LONG":
                flat_spans.append((opened, after))
                opened = None
        if opened is not None:
            flat_spans.append((opened, last))
        for start, end in flat_spans:
            move = end.price / start.price - 1.0
            hours = (end.at - start.at).total_seconds() / 3600.0
            verdict = "EVITO una caida" if move < 0 else "se PERDIO una subida"
            print(
                f"  fuera {hours:>6.1f} h desde {start.at:%m-%d %H:%M}: "
                f"BTC {move:+.2%}  ->  {verdict} de {abs(move):.2%}"
            )
        if not flat_spans:
            print("  nunca estuvo fuera del mercado de forma medible")
    print()
    print("--- lectura ---")
    if abs(mean_allocation - 1.0) < 0.10:
        print("  La asignacion media esta cerca del 100%: el agente es, en la practica,")
        print("  comprar y mantener. Su resultado y su riesgo son los del activo.")
    if changes == 0:
        print("  CERO cambios de posicion en todo el periodo: no esta ejerciendo criterio")
        print("  direccional, solo manteniendo. El resultado NO es evidencia sobre el modelo.")
    annual = (1.0 + agent_return) ** (365.0 / span_days) - 1.0 if span_days > 1 else float("nan")
    if not math.isnan(annual):
        print(f"  retorno anualizado (extrapolacion de {span_days:.0f} dias, NO una expectativa): {annual:+.1%}")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
