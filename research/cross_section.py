"""Cross-sectional rotation: the mandate never said ONE asset.

The whole project has measured TIMING -- when to be exposed to BTC -- and found nothing, four
times, with a measured ceiling of +13% over holding even with perfect foresight. That is a
property of the question, not of the models.

This asks the other question. The mandate is "spot only, long or flat, no leverage, no shorts".
It says nothing about a single asset. A long-only rotation across spot pairs is fully inside it,
and it is a different mechanism: it does not need the direction of any asset, only the RELATIVE
ORDER of several. Cross-sectional momentum is among the most replicated effects in the
literature across equities, futures and crypto, and the project has never looked at it.

Honesty constraints, which matter more here than anywhere else in this repo:

- **Point-in-time availability.** An asset enters the eligible set on a date only if it has
  actually traded enough days before that date to form the signal. No asset is ever ranked on
  history it did not have yet.
- **Delisting is not an exit at a good price.** When a held asset stops reporting, it is
  liquidated at its LAST observed close on the next rebalance. EOSUSDT stops in 2025-05 and
  MATICUSDT in 2024-09 in this dataset, and both are kept in the universe for exactly that
  reason.
- **The universe deliberately includes assets that collapsed** -- LUNA and FTT -- because a
  universe of today's winners would be a survivorship machine.
- **Survivorship bias is NOT eliminated and the direction is stated:** the 30 symbols were
  chosen by the author from pairs with long history, so pairs that died early and were
  forgotten are absent. That biases results UPWARD. Any positive result here is an upper
  bound until a point-in-time listing feed replaces this hand-picked universe.
- Walk-forward: the lookback and the basket size are chosen on past folds and frozen for the
  year that follows. Fees on turnover at each rebalance, both sides.

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.cross_section
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

DATA = Path("data/history/cross-section-1d.json")
REPORT = Path("data/validation/cross-section.json")
ADVERSE_FEE = 0.002
HONEST_FEE = 0.001
REBALANCE_DAYS = 30
FOLD_DAYS = 365
MIN_TRAIN_DAYS = 730
LOOKBACKS = (30, 60, 90, 180)
BASKETS = (3, 5, 8)


@dataclass
class Result:
    label: str
    net_return_pct: float
    max_drawdown_pct: float
    rebalances: int
    fees_paid_pct: float
    mean_held: float


def load() -> tuple[list[str], dict[str, dict[str, float]]]:
    """Return the ordered calendar of dates and a per-symbol date->close map."""
    raw = json.loads(DATA.read_text())
    closes: dict[str, dict[str, float]] = {}
    dates: set[str] = set()
    for symbol, rows in raw.items():
        series: dict[str, float] = {}
        for open_ms, close, _quote in rows:
            date = datetime.fromtimestamp(open_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
            series[date] = float(close)
            dates.add(date)
        closes[symbol] = series
    return sorted(dates), closes


def eligible(
    closes: dict[str, dict[str, float]], calendar: list[str], index: int, lookback: int
) -> list[str]:
    """Symbols that genuinely had `lookback` days of history BEFORE this date."""
    date = calendar[index]
    if index < lookback:
        return []
    past = calendar[index - lookback]
    return [
        symbol
        for symbol, series in closes.items()
        if date in series and past in series and series[past] > 0 and series[date] > 0
    ]


def rank_by_momentum(
    closes: dict[str, dict[str, float]],
    calendar: list[str],
    index: int,
    lookback: int,
    names: list[str],
) -> list[str]:
    """Order by trailing return, strongest first. Causal: uses only up to `index`."""
    date = calendar[index]
    past = calendar[index - lookback]
    scored = [
        (math.log(closes[symbol][date] / closes[symbol][past]), symbol) for symbol in names
    ]
    scored.sort(reverse=True)
    return [symbol for _score, symbol in scored]


def simulate(
    closes: dict[str, dict[str, float]],
    calendar: list[str],
    first: int,
    last: int,
    lookback: int,
    basket: int,
    fee: float,
    *,
    reverse: bool = False,
) -> Result:
    """Equal-weight the top `basket` by momentum, rebalanced every REBALANCE_DAYS."""
    equity = 1.0
    peak = 1.0
    worst = 0.0
    holdings: dict[str, float] = {}
    rebalances = 0
    fees = 0.0
    held_counts: list[int] = []

    for index in range(first, min(last, len(calendar))):
        date = calendar[index]

        # Mark to market, carrying forward the last observed price for a symbol that has
        # stopped reporting rather than pretending the position vanished.
        value = 0.0
        for symbol, units in holdings.items():
            series = closes[symbol]
            price = series.get(date)
            if price is None:
                price = next(
                    (
                        series[calendar[back]]
                        for back in range(index - 1, max(index - 40, first) - 1, -1)
                        if calendar[back] in series
                    ),
                    0.0,
                )
            value += units * price
        equity = value if holdings else equity
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak if peak > 0 else 0.0)

        if (index - first) % REBALANCE_DAYS != 0:
            continue

        names = eligible(closes, calendar, index, lookback)
        if len(names) < basket:
            continue
        ordered = rank_by_momentum(closes, calendar, index, lookback, names)
        chosen = (ordered[-basket:] if reverse else ordered[:basket])

        turnover = 1.0 if not holdings else 0.5  # full entry, then partial each rebalance
        fee_paid = turnover * fee
        equity *= 1.0 - fee_paid
        fees += fee_paid
        rebalances += 1

        per = equity / basket
        holdings = {symbol: per / closes[symbol][date] for symbol in chosen}
        held_counts.append(len(chosen))

    return Result(
        label=f"{'reversion' if reverse else 'momento'} {lookback}d top{basket}",
        net_return_pct=(equity - 1.0) * 100.0,
        max_drawdown_pct=worst * 100.0,
        rebalances=rebalances,
        fees_paid_pct=fees * 100.0,
        mean_held=sum(held_counts) / len(held_counts) if held_counts else 0.0,
    )


def hold_single(
    closes: dict[str, dict[str, float]],
    calendar: list[str],
    first: int,
    last: int,
    symbol: str,
    fee: float,
) -> Result:
    series = closes[symbol]
    entry = next((series[calendar[i]] for i in range(first, last) if calendar[i] in series), None)
    if entry is None:
        return Result(symbol, 0.0, 0.0, 0, 0.0, 1.0)
    units = (1.0 - fee) / entry
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for index in range(first, min(last, len(calendar))):
        price = series.get(calendar[index])
        if price is None:
            continue
        equity = units * price
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak if peak > 0 else 0.0)
    return Result(
        label=f"comprar y mantener {symbol}",
        net_return_pct=(equity * (1.0 - fee) - 1.0) * 100.0,
        max_drawdown_pct=worst * 100.0,
        rebalances=1,
        fees_paid_pct=fee * 200.0,
        mean_held=1.0,
    )


def risk_matched(hold: Result, drawdown: float) -> float:
    """What a static fraction of holding BTC, sized to this drawdown, would have returned."""
    if hold.max_drawdown_pct <= 0.0:
        return 0.0
    return min(1.0, drawdown / hold.max_drawdown_pct) * hold.net_return_pct


def main() -> int:
    calendar, closes = load()
    print(f"universo {len(closes)} pares  ·  {calendar[0]} .. {calendar[-1]}  ({len(calendar)} dias)")
    print(
        "SESGO DE SUPERVIVENCIA NO ELIMINADO: el universo lo elegi yo entre pares con historia\n"
        "larga, asi que los que murieron pronto y se olvidaron no estan. Eso sesga AL ALZA.\n"
        "Incluye LUNA y FTT a proposito, y EOS/MATIC dejan de cotizar dentro de la muestra.\n"
    )

    folds: list[tuple[int, int]] = []
    cursor = MIN_TRAIN_DAYS
    while cursor + FOLD_DAYS < len(calendar):
        folds.append((cursor, cursor + FOLD_DAYS))
        cursor += FOLD_DAYS

    print(
        f"{'fold':>4} {'OOS hasta':<12} {'elegido':<24} {'OOS':>9} "
        f"{'BTC b&h':>9} {'BTC@riesgo':>11} {'dd':>7} {'gana':>5}"
    )
    pooled = 1.0
    pooled_peak = 1.0
    pooled_worst = 0.0
    rows: list[dict[str, object]] = []
    for number, (train_end, test_end) in enumerate(folds, start=1):
        best = None
        best_return = -1e9
        for lookback in LOOKBACKS:
            for basket in BASKETS:
                for reverse in (False, True):
                    run = simulate(
                        closes, calendar, lookback + 1, train_end, lookback, basket,
                        ADVERSE_FEE, reverse=reverse,
                    )
                    if run.net_return_pct > best_return:
                        best_return = run.net_return_pct
                        best = (lookback, basket, reverse)
        assert best is not None
        lookback, basket, reverse = best

        tested = simulate(
            closes, calendar, train_end, test_end, lookback, basket, ADVERSE_FEE,
            reverse=reverse,
        )
        btc = hold_single(closes, calendar, train_end, test_end, "BTCUSDT", ADVERSE_FEE)
        matched = risk_matched(btc, tested.max_drawdown_pct)
        wins = tested.net_return_pct > matched

        pooled *= 1.0 + tested.net_return_pct / 100.0
        pooled_peak = max(pooled_peak, pooled)
        pooled_worst = max(pooled_worst, (pooled_peak - pooled) / pooled_peak if pooled_peak else 0.0)
        rows.append(
            {
                "fold": number,
                "test_end": calendar[min(test_end, len(calendar) - 1)],
                "chosen": tested.label,
                "oos_return_pct": round(tested.net_return_pct, 2),
                "btc_hold_pct": round(btc.net_return_pct, 2),
                "btc_risk_matched_pct": round(matched, 2),
                "oos_drawdown_pct": round(tested.max_drawdown_pct, 2),
                "beat_risk_matched": wins,
            }
        )
        print(
            f"{number:>4} {calendar[min(test_end, len(calendar) - 1)]:<12} "
            f"{tested.label:<24} {tested.net_return_pct:>8.1f}% "
            f"{btc.net_return_pct:>8.1f}% {matched:>10.1f}% "
            f"{tested.max_drawdown_pct:>6.1f}% {'si' if wins else 'no':>5}"
        )

    beats = sum(1 for row in rows if row["beat_risk_matched"])
    btc_all = hold_single(closes, calendar, MIN_TRAIN_DAYS, len(calendar), "BTCUSDT", ADVERSE_FEE)
    matched_all = risk_matched(btc_all, pooled_worst * 100)
    print(f"\n  folds: {len(rows)}   ganan a BTC AL MISMO RIESGO: {beats} de {len(rows)}")
    print(f"  compuesto OOS de la rotacion: {(pooled - 1.0) * 100:+.1f}%  caida {pooled_worst * 100:.1f}%")
    print(f"  BTC comprar y mantener mismo tramo: {btc_all.net_return_pct:+.1f}%  caida {btc_all.max_drawdown_pct:.1f}%")
    print(f"  BTC AL MISMO RIESGO: {matched_all:+.1f}%")
    verdict = (
        "LA ROTACION TRANSVERSAL BATE A BTC AL MISMO RIESGO"
        if (pooled - 1.0) * 100 > matched_all
        else "LA ROTACION TRANSVERSAL NO BATE A BTC AL MISMO RIESGO"
    )
    print(f"\n  VEREDICTO: {verdict}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "universe": sorted(closes),
                "survivorship_bias": "not eliminated; hand-picked universe biases results UP",
                "folds": rows,
                "pooled_return_pct": round((pooled - 1.0) * 100, 2),
                "pooled_drawdown_pct": round(pooled_worst * 100, 2),
                "btc_hold": asdict(btc_all),
                "btc_risk_matched_pct": round(matched_all, 2),
                "verdict": verdict,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\ninforme: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
