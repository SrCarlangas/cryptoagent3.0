"""Event study on delisting announcements scored by the LOCAL model.

Closes the last open hypothesis as far as these data allow, and records honestly where the
experiment's DESIGN -- mine -- made part of it unrunnable.

What was pre-declared, and why it cannot be run
-----------------------------------------------
The declared bar was: the excess return must be MONOTONE in the model's impact score, and the
contrast between the negative-impact and positive-impact groups must reach |t| >= 2.

That test is unrunnable on this corpus, and the reason is a scoping mistake. The delisting
catalog was chosen because it is the highest-signal subset, but it is **uniformly negative by
construction**: of the 36 scored announcements naming an asset in the tradeable universe, 32
scored -2 and 4 scored -1. There is no positive group to contrast against, so monotonicity has
nothing to be monotone across. Recorded rather than quietly replaced with an easier test.

A second, related finding about the instrument: the model labelled 366 of 439 titles
`delisting` with impact -2 -- it agreed with what the catalog's own name already said. On this
subset its semantic judgement is **redundant with the label**, which is precisely the gap the
experiment was meant to probe.

What CAN be measured
--------------------
A one-sample event study: after a delisting announcement, does the asset underperform BTC over
the following 30 days? BTC is the benchmark so the common crypto beta cancels, and the window
starts the day AFTER the announcement so nothing is read before it was public.

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.delisting_event_study
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import UTC, datetime
from math import comb
from pathlib import Path

SCORES = Path("data/validation/announcement-scores-delisting.json")
PRICES = Path("data/history/cross-section-wide-1d.json")
HORIZON = 30
BENCHMARK = "BTCUSDT"


def load() -> tuple[dict[str, dict[str, float]], list[str]]:
    raw = json.loads(PRICES.read_text(encoding="utf-8"))
    closes = {
        symbol: {
            datetime.fromtimestamp(stamp / 1000, tz=UTC).strftime("%Y-%m-%d"): float(close)
            for stamp, close, _volume in rows
        }
        for symbol, rows in raw.items()
    }
    calendar = sorted({day for series in closes.values() for day in series})
    return closes, calendar


def forward(
    closes: dict[str, dict[str, float]], calendar: list[str], symbol: str, day: str
) -> float | None:
    """Log return over the HORIZON days strictly AFTER `day`. Causal by construction."""
    future = [item for item in calendar if item > day]
    if len(future) < HORIZON:
        return None
    first, last = future[0], future[HORIZON - 1]
    series = closes[symbol]
    if first not in series or last not in series or series[first] <= 0:
        return None
    return math.log(series[last] / series[first])


def standard_error(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    return math.sqrt(variance / len(values))


def sign_test(values: list[float]) -> tuple[int, int, float]:
    """Negatives, total, and the one-sided binomial p-value under a fair coin."""
    negatives = sum(1 for item in values if item < 0)
    total = len(values)
    if total == 0:
        return 0, 0, 1.0
    tail = sum(comb(total, k) for k in range(negatives, total + 1)) / 2**total
    return negatives, total, tail


def main() -> int:
    scored = json.loads(SCORES.read_text(encoding="utf-8"))
    closes, calendar = load()
    universe = {symbol[:-4]: symbol for symbol in closes}

    events: list[tuple[str, int, float, float, str]] = []
    for entry in scored["scores"].values():
        symbol = universe.get(entry["asset"])
        if symbol is None:
            continue
        day = datetime.fromtimestamp(entry["t"] / 1000, tz=UTC).strftime("%Y-%m-%d")
        asset_return = forward(closes, calendar, symbol, day)
        bench_return = forward(closes, calendar, BENCHMARK, day)
        if asset_return is None or bench_return is None:
            continue
        events.append((entry["asset"], int(entry["impact"]), asset_return, bench_return, day))

    print(f"modelo: {scored['model']}  ·  titulares puntuados: {len(scored['scores'])}  ·  "
          f"lotes con fallo: {len(scored['failures'])}")
    print(f"eventos utilizables (activo en el universo de {len(closes)} y 30d de futuro): "
          f"{len(events)}")
    spread = Counter(impact for _asset, impact, _a, _b, _d in events)
    print(f"reparto del impacto del modelo: {dict(sorted(spread.items()))}")
    print()
    print("LA PRUEBA DE MONOTONIA PRE-DECLARADA NO SE PUEDE CORRER.")
    print("  El catalogo de deslistados es negativo por construccion: no hay grupo positivo")
    print("  contra el que contrastar. Error de diseno mio al escoger ese catalogo, no un")
    print("  resultado del mercado. Y el modelo etiqueto 366 de 439 como delisting con")
    print("  impacto -2: en este subconjunto su juicio es REDUNDANTE con el nombre del")
    print("  catalogo, que es justo lo que el experimento debia distinguir.")
    print()

    excess = [asset - bench for _asset, _impact, asset, bench, _day in events]
    if len(excess) < 3:
        print("Muestra insuficiente para cualquier contraste. Nada que concluir.")
        return 1

    count = len(excess)
    mean = sum(excess) / count
    error = standard_error(excess)
    assert error is not None
    t_stat = mean / error if error > 0 else 0.0
    negatives, total, p_value = sign_test(excess)

    print("=== Lo unico medible: estudio de evento de una muestra ===")
    print("  hipotesis: tras un aviso de deslistado el activo rinde PEOR que BTC a 30 dias")
    print(f"  exceso medio (activo - BTC): {mean:+.2%}")
    print(f"  mediana:                     {sorted(excess)[count // 2]:+.2%}")
    print(f"  error estandar {error:.2%}  ->  t = {t_stat:+.2f}")
    print(f"  eventos con exceso negativo: {negatives}/{total} = {negatives / total:.0%}"
          f"   prueba de signo p = {p_value:.4f}")
    print(f"  peor {min(excess):+.1%}   mejor {max(excess):+.1%}")

    holds = t_stat <= -2.0 and p_value < 0.05
    print("\n  umbral declarado: t <= -2 Y signo consistente (p < 0,05)")
    print(f"  VEREDICTO: {'SOSTENIDA' if holds else 'NO SOSTENIDA'}")

    print("\n  los cinco peores eventos:")
    for asset, impact, asset_return, bench_return, day in sorted(
        events, key=lambda row: row[2] - row[3]
    )[:5]:
        print(
            f"    {asset:<8} {day}  impacto {impact:>2}  activo {asset_return:+.1%}  "
            f"BTC {bench_return:+.1%}  exceso {asset_return - bench_return:+.1%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
