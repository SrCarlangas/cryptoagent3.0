"""One line per decision: what the agent asked for, and what the system did with it.

Written because the interesting failures in this project have all been of the same kind: a
declared intent and a system that quietly did something else. Reading the decisions side by
side with their outcome is the cheapest way to catch the next one.

Usage:
    python -m research.show_trace [report.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

FIELDS = (
    "blocked_changes_by_cost",
    "blocked_exits_by_cost",
    "direction_changes",
    "size_adjustments",
    "commission_paid_pct",
    "entries",
    "exits",
    "scale_ups",
    "scale_downs",
    "stop_exits",
)


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/validation/llm-agent-backtest.json")
    if not path.is_file():
        print(f"informe no encontrado: {path}")
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    agent: dict[str, Any] = payload["llm_agent"]
    trace: list[dict[str, Any]] = payload.get("trace") or []

    window = payload["window"]
    print("=" * 108)
    print(f"{path.name}")
    print(
        f"  dias {window['start_day_index']}-{window['end_day_index']}, "
        f"{agent['decisions']} decisiones, paso {window['step_days']}d  ·  "
        f"agente {agent['net_return_pct']:+.2f}% (dd {agent['max_drawdown_pct']:.1f}%)  ·  "
        f"b&h {payload['buy_and_hold']['net_return_pct']:+.2f}%  ·  "
        f"cuant {payload['quant_policy']['net_return_pct']:+.2f}%"
    )
    print("=" * 108)
    for field in FIELDS:
        if field in agent:
            print(f"  {field:<26} {agent[field]}")
    if not trace:
        return 0
    print()
    print(
        f"  {'dia':>5} {'reg':>4} {'obs':>4} {'pidio':>11} {'conv':>5} {'post':>4} "
        f"{'ejecutado':>11} {'coste':>6} {'orden':>9} {'antes':>6} {'obj':>6} {'desp':>6} {'equity':>7}"
    )
    print("  " + "-" * 102)
    for item in trace:
        print(
            f"  {item['day_index']:>5} {item.get('regime', '?'):>4} "
            f"{item.get('regime_observed', '-'):>4} "
            f"{item.get('agent_asked_for', '?')!s:>11} {float(item['conviction']):>5.2f} "
            f"{str(item['posture'])[:3]:>4} {item['target']!s:>11} "
            f"{'si' if item['clears_cost'] else 'NO':>6} {item['adjustment']!s:>9} "
            f"{float(item['share_before']) * 100:>5.0f}% {float(item['share_target']) * 100:>5.0f}% "
            f"{float(item['invested_share']) * 100:>5.0f}% {float(item['equity']):>7.4f}"
        )
    overridden = [item for item in trace if item.get("choice_honoured") is False]
    print()
    print(
        f"  decisiones en las que el sistema NO ejecuto lo que el agente pidio: "
        f"{len(overridden)} (debe ser 0: la direccion es del agente)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
