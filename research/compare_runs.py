"""Put archived runs side by side, so a difference can be judged against the spread.

Written because three exposure policies were tried on the same window and the results came
in at +63.60%, +59.51% and +53.08%. Read one at a time, each looked like a verdict on the
policy. Read together, they are a ten point band on a window where buy and hold made +184%,
which is the spread this measurement has rather than a ranking of the policies.

Usage:
    python -m research.compare_runs [pattern]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RUNS = Path("data/validation/runs")


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*.json"
    paths = sorted(RUNS.glob(pattern))
    if not paths:
        print(f"sin corridas que coincidan con {pattern} en {RUNS}")
        return 2

    print("=" * 112)
    print(f"CORRIDAS ARCHIVADAS  ·  {pattern}")
    print("=" * 112)
    header = (
        f"  {'corrida':<44} {'retorno':>8} {'b&h':>8} {'capt':>5} {'dd':>6} "
        f"{'stops':>6} {'invert':>7} {'apert':>6} {'ampl':>5} {'red':>4} {'dec':>4}"
    )
    print(header)
    print("  " + "-" * 108)
    rows: list[tuple[str, float, float]] = []
    for path in paths:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        agent = payload["llm_agent"]
        hold = payload["buy_and_hold"]["net_return_pct"]
        ret = float(agent["net_return_pct"])
        capture = ret / hold if hold else 0.0
        label = path.stem.replace("2026-09-2", "…2").replace("-60d-paso5", "")
        print(
            f"  {label[:44]:<44} {ret:+7.2f}% {hold:+7.1f}% {capture:>4.0%} "
            f"{float(agent['max_drawdown_pct']):5.1f}% {agent['stop_exits']:>6} "
            f"{float(agent['long_share']):>6.0%} {agent['entries']:>6} "
            f"{agent['scale_ups']:>5} {agent['scale_downs']:>4} {agent['decisions']:>4}"
        )
        rows.append((label, ret, hold))

    same_window = {round(hold, 2) for _label, _ret, hold in rows}
    if len(same_window) == 1 and len(rows) > 1:
        returns = [ret for _label, ret, _hold in rows]
        print()
        print(
            f"  Misma ventana en {len(rows)} corridas: de {min(returns):+.2f}% a "
            f"{max(returns):+.2f}%, una banda de {max(returns) - min(returns):.1f}pp."
        )
        print(
            "  CUIDADO al leer esa banda: solo mide ruido entre corridas que comparten la"
        )
        print(
            "  EJECUCION y cambian la politica de exposicion. Una corrida con otra geometria"
        )
        print(
            "  de stops pertenece a otra comparacion, y meterla aqui infla el rango y sirve"
        )
        print("  para descartar como ruido una mejora que fue real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
