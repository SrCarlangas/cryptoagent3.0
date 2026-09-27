"""Was the regime label corroborated by the condition that defines the regime?

The finding that motivated this
------------------------------
On the falling window the agent was exposed only 6% of the time and still lost 13.90%,
slightly more than buy and hold. The attribution puts three quarters of that loss in seven
segments out of fifty-nine, all of them labelled regime 3, "alcista fuerte", in the middle of
a bear market: -10.39% with an effect of 1.3 standard errors, so not noise.

The mechanism is not subtle. Regime 3's strategy grants the largest allocation the playbook
allows, 90% at neutral posture, behind a wide stop, because its doctrine is an ESTABLISHED
uptrend where noise should not shake the position out. A mixture model over features can emit
that label on a violent bounce inside a downtrend, and when it does, the playbook hands a
failing bounce the largest position it has.

So the question is whether the label was accompanied by the condition its own doctrine names.
If regime 3 is being granted while price sits below its own long-run average, then the fix is
to require the defining condition rather than to shrink the allocation, which would be tuning.

This computes the features for every decision from the closes available at that moment, so
there is no lookahead: the same cutoff the backtest uses.

Usage:
    python -m research.regime_corroboration report.json [report.json ...]
"""

from __future__ import annotations

import json
import math
import statistics as stats
import sys
from pathlib import Path
from typing import Any

from multislot_sim import load_bars

from btc_decision_agent.application.exposure_features import (
    MARKET_FEATURE_NAMES,
    market_features,
)
from btc_decision_agent.application.exposure_training import build_daily_perception


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python -m research.regime_corroboration informe.json [...]")
        return 2
    bars, _ = load_bars()
    closes = build_daily_perception(bars).closes
    ma200 = MARKET_FEATURE_NAMES.index("log_price_over_ma200")
    ret90 = MARKET_FEATURE_NAMES.index("return_90d")

    print("=" * 96)
    print("ESTABA LA ETIQUETA CORROBORADA POR LA CONDICION QUE DEFINE EL REGIMEN?")
    print("=" * 96)
    for argument in sys.argv[1:]:
        path = Path(argument)
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        trace: list[dict[str, Any]] = payload.get("trace") or []
        if not trace:
            continue
        print()
        print(f"  {path.stem}   agente {payload['llm_agent']['net_return_pct']:+.2f}%")
        print(
            f"    {'reg':>4} {'n':>4} {'sobre ma200':>12} {'ret 90d medio':>14} "
            f"{'n por debajo de ma200':>22}"
        )
        print("    " + "-" * 60)
        grouped: dict[int, list[tuple[float, float]]] = {}
        for item in trace:
            regime = item.get("regime")
            if regime is None:
                continue
            day = int(item["day_index"])
            vector = market_features(closes[:day], closes[day])
            over = (math.exp(vector[ma200]) - 1.0) * 100.0
            ninety = (math.exp(vector[ret90]) - 1.0) * 100.0
            grouped.setdefault(int(regime), []).append((over, ninety))
        for regime in sorted(grouped):
            rows = grouped[regime]
            below = sum(1 for over, _ in rows if over < 0)
            print(
                f"    {regime:>4} {len(rows):>4} "
                f"{stats.mean(over for over, _ in rows):>11.1f}% "
                f"{stats.mean(n for _, n in rows):>13.1f}% "
                f"{below:>13} de {len(rows)}"
            )
    print()
    print("  'sobre ma200' es el precio contra su media de 200 dias, que es la condicion que")
    print("  la doctrina del regimen 3 invoca cuando dice 'tendencia alcista establecida'. Si")
    print("  el regimen 3 se concede con el precio POR DEBAJO de esa media, la etiqueta y la")
    print("  doctrina no hablan de lo mismo, y el playbook le esta dando a un rebote fallido")
    print("  la posicion mas grande que tiene.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
