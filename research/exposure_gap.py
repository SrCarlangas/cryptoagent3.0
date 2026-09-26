"""Where the intended exposure is lost between the plan and the book.

The bull window run reached +23.23% on replay while holding a position 81% of the hours,
and forcing it to stay invested the whole time reached +88.07% at 94% of hours. Thirteen
points more exposure time cannot explain sixty-five points of return, so the difference
has to be SIZE rather than presence, or WHEN the size is on.

This walks the recorded trace and prints, per regime, the target share the plan asked for,
the share the book actually had, and every decision where a target went unmet, with the
reason available. No model, no simulation: just the numbers the run wrote down.

Usage:
    python -m research.exposure_gap [report.json]
"""

from __future__ import annotations

import json
import statistics as stats
import sys
from collections import Counter
from pathlib import Path
from typing import Any


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

    window = payload["window"]
    print("=" * 96)
    print(f"DONDE SE PIERDE LA EXPOSICION  ·  {path.name}")
    print(
        f"  dias {window['start_day_index']}-{window['end_day_index']}, "
        f"{len(trace)} decisiones, paso {window['step_days']}d  ·  "
        f"agente {payload['llm_agent']['net_return_pct']:+.2f}%, "
        f"comprar y mantener {payload['buy_and_hold']['net_return_pct']:+.2f}%"
    )
    print("=" * 96)
    print(
        f"  {'reg':>3} {'n':>3} {'objetivo':>9} {'antes':>8} {'despues':>8} "
        f"{'postura':>12} {'ordenes'}"
    )
    print("  " + "-" * 82)
    for regime in sorted({int(item["regime"]) for item in trace if item.get("regime") is not None}):
        rows = [item for item in trace if item.get("regime") == regime]
        target = stats.mean(float(item["share_target"]) for item in rows)
        before = stats.mean(float(item["share_before"]) for item in rows)
        after = stats.mean(float(item["invested_share"]) for item in rows)
        posture = Counter(item["posture"] for item in rows).most_common(1)[0]
        orders = dict(Counter(item["adjustment"] for item in rows))
        print(
            f"  {regime:>3} {len(rows):>3} {target * 100:>8.1f}% {before * 100:>7.1f}% "
            f"{after * 100:>7.1f}% {posture[0][:3]:>9}x{posture[1]:<3} {orders}"
        )
    print()
    print("  'antes' es la cuota al decidir, 'despues' la cuota tras el intervalo. La caida")
    print("  entre una y otra es lo que se llevaron los stops; la distancia entre 'objetivo'")
    print("  y 'antes' es lo que nunca se llego a comprar.")

    unmet = [
        item
        for item in trace
        if float(item["share_target"]) - float(item["share_before"]) > 0.15
        and item["adjustment"] != "COMPRAR"
    ]
    print()
    print(f"  DECISIONES CON OBJETIVO SIN CUBRIR (hueco > banda muerta): {len(unmet)}")
    for item in unmet:
        print(
            f"    dia {item['day_index']} r{item['regime']} {item['posture'][:3]} "
            f"conv {item['conviction']:.2f} antes {float(item['share_before']) * 100:.0f}% "
            f"objetivo {float(item['share_target']) * 100:.0f}% "
            f"orden={item['adjustment']} cubre_coste={item['clears_cost']} "
            f"eleccion_respetada={item.get('choice_honoured')}"
        )

    capped = [
        item
        for item in trace
        if item.get("plan")
        and float(item["share_target"]) > 0
        and float(item["share_target"])
        < float(item["plan"]["allocation_fraction"]) - 0.005
    ]
    print()
    print(f"  DECISIONES DONDE EL TOPE DE RIESGO RECORTO EL OBJETIVO: {len(capped)}")
    for item in capped[:12]:
        plan = item["plan"]
        risk = float(plan["risk_per_trade_fraction"])
        stop = float(plan["stop_loss_fraction"])
        print(
            f"    dia {item['day_index']} r{item['regime']} {item['posture'][:3]} "
            f"asignacion {float(plan['allocation_fraction']) * 100:.0f}% -> "
            f"objetivo {float(item['share_target']) * 100:.0f}% "
            f"(riesgo {risk * 100:.1f}% / stop {stop * 100:.1f}% = {risk / stop * 100:.0f}%)"
        )
    if len(capped) > 12:
        print(f"    ... y {len(capped) - 12} mas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
