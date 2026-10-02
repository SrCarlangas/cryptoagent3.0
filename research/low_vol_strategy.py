"""Does the low-volatility factor become money? IC -0.16 tested against the gate.

`research/cross_section_ic.py` found the first two-sigma signal in this project's history:
within the crypto cross-section, low 30-day volatility ranks assets at **t = -5.23** and average
traded volume at **t = +2.74**, both robust to survivorship (stronger among survivors alone) and
to excluding catastrophic periods. Momentum, the family this project actually built on, is not
significant at any horizon.

**An information coefficient is not a return.** An IC of -0.16 is strong by quant standards --
equity factors run 0.02 to 0.05 -- but turning a ranking into P&L requires portfolio
construction, costs, and the 25% drawdown cap. "Low volatility" inside crypto still means very
high volatility in absolute terms, so the cap is the binding question rather than an afterthought.

Tested exactly as everything else in this project:

- **walk-forward**: the basket size and the weighting are chosen on past folds and frozen
- **adverse fees** of 20 bps per side on turnover
- **against BTC AT EQUAL RISK**, the rewritten gate's comparator: a static fraction of BTC sized
  to the strategy's own realised drawdown is free, so beating raw BTC is not the test
- **the monthly spread** as the unit of observation, with the effect floor of 1.0, a sign test,
  and the effect recomputed after dropping the single best period
- **the 25% cap applied to BOTH arms** via a cash overlay, because a comparison at unequal risk
  is not a comparison

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.low_vol_strategy
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cross_section import ADVERSE_FEE, FOLD_DAYS, MIN_TRAIN_DAYS, REBALANCE_DAYS, load
from cross_section_ic import WARMUP, signals_for
from cross_section_monthly import sign_test, standard_error

REPORT = Path("data/validation/low-vol-strategy.json")
EFFECT_FLOOR = 1.0
DRAWDOWN_CAP = 25.0
BASKETS = (3, 5, 8, 12)
WEIGHTINGS = ("igual", "inversa_vol")


@dataclass
class Period:
    start: str
    end: str
    strategy: float
    btc: float

    @property
    def spread(self) -> float:
        return self.strategy - self.btc


def periods_for(
    closes: dict[str, dict[str, float]],
    volumes: dict[str, dict[str, float]],
    calendar: list[str],
    first: int,
    last: int,
    basket: int,
    weighting: str,
    fee: float,
) -> list[Period]:
    """Hold the `basket` LOWEST-volatility eligible assets, rebalanced each period."""
    out: list[Period] = []
    index = max(first, WARMUP)
    while index + REBALANCE_DAYS <= min(last, len(calendar) - 1):
        start_date = calendar[index]
        end_date = calendar[index + REBALANCE_DAYS]

        scored: list[tuple[float, str]] = []
        for symbol in closes:
            values = signals_for(closes, volumes, calendar, index, symbol)
            if values is None:
                continue
            scored.append((values["volatilidad_30d"], symbol))
        if len(scored) < basket:
            index += REBALANCE_DAYS
            continue
        scored.sort()  # ascending volatility: the factor says low vol ranks better
        chosen = scored[:basket]

        if weighting == "inversa_vol":
            raw = [(1.0 / vol if vol > 0 else 0.0, symbol) for vol, symbol in chosen]
            total = sum(weight for weight, _ in raw)
            weights = [(weight / total, symbol) for weight, symbol in raw] if total > 0 else []
        else:
            weights = [(1.0 / basket, symbol) for _vol, symbol in chosen]

        legs: list[tuple[float, float]] = []
        for weight, symbol in weights:
            series = closes[symbol]
            entry = series.get(start_date)
            exit_price = series.get(end_date)
            if entry is None or entry <= 0:
                continue
            if exit_price is None:
                exit_price = next(
                    (
                        series[calendar[back]]
                        for back in range(index + REBALANCE_DAYS - 1, index - 1, -1)
                        if calendar[back] in series
                    ),
                    entry,
                )
            legs.append((weight, exit_price / entry - 1.0))
        if not legs:
            index += REBALANCE_DAYS
            continue

        gross = sum(weight * move for weight, move in legs) / sum(w for w, _ in legs)
        btc_series = closes["BTCUSDT"]
        btc_entry = btc_series.get(start_date)
        btc_exit = btc_series.get(end_date)
        if btc_entry and btc_exit:
            out.append(
                Period(
                    start=start_date,
                    end=end_date,
                    strategy=gross - fee,
                    btc=btc_exit / btc_entry - 1.0,
                )
            )
        index += REBALANCE_DAYS
    return out


def compound(returns: list[float], exposure: float = 1.0) -> tuple[float, float]:
    """Total return and max drawdown of a sequence, at a constant exposure fraction."""
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value * exposure
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak if peak > 0 else 0.0)
    return (equity - 1.0) * 100.0, worst * 100.0


def exposure_for_cap(returns: list[float], cap: float) -> float:
    """Largest constant exposure whose drawdown stays within `cap`. Bisection."""
    low, high = 0.0, 1.0
    if compound(returns, 1.0)[1] <= cap:
        return 1.0
    for _ in range(40):
        mid = (low + high) / 2
        if compound(returns, mid)[1] <= cap:
            low = mid
        else:
            high = mid
    return low


def main() -> int:
    calendar, closes = load()
    raw = json.loads(Path("data/history/cross-section-1d.json").read_text())
    from datetime import UTC, datetime

    volumes = {
        symbol: {
            datetime.fromtimestamp(row[0] / 1000, tz=UTC).strftime("%Y-%m-%d"): float(row[2])
            for row in rows
        }
        for symbol, rows in raw.items()
    }

    folds: list[tuple[int, int]] = []
    cursor = MIN_TRAIN_DAYS
    while cursor + FOLD_DAYS < len(calendar):
        folds.append((cursor, cursor + FOLD_DAYS))
        cursor += FOLD_DAYS

    print(f"universo {len(closes)} pares · {len(folds)} folds anuales · "
          f"comisiones adversas {ADVERSE_FEE * 10000:.0f}bps")
    print("señal: VOLATILIDAD 30d ASCENDENTE (el factor hallado a t=-5.23)\n")

    oos: list[Period] = []
    for train_end, test_end in folds:
        best = None
        best_total = -1e9
        for basket in BASKETS:
            for weighting in WEIGHTINGS:
                train = periods_for(
                    closes, volumes, calendar, WARMUP, train_end, basket, weighting, ADVERSE_FEE
                )
                if len(train) < 6:
                    continue
                total, _dd = compound([p.strategy for p in train])
                if total > best_total:
                    best_total = total
                    best = (basket, weighting)
        if best is None:
            continue
        basket, weighting = best
        chunk = periods_for(
            closes, volumes, calendar, train_end, test_end, basket, weighting, ADVERSE_FEE
        )
        oos.extend(chunk)
        total, drawdown = compound([p.strategy for p in chunk])
        btc_total, btc_dd = compound([p.btc for p in chunk])
        print(
            f"  fold hasta {calendar[min(test_end, len(calendar) - 1)]}: "
            f"top{basket} {weighting:<11} OOS {total:>+8.1f}% (dd {drawdown:>5.1f}%)  "
            f"BTC {btc_total:>+8.1f}% (dd {btc_dd:>5.1f}%)"
        )

    strategy = [period.strategy for period in oos]
    btc = [period.btc for period in oos]
    spreads = [period.spread for period in oos]

    total, drawdown = compound(strategy)
    btc_total, btc_dd = compound(btc)
    print(f"\n  periodos OOS: {len(oos)}")
    print(f"  estrategia: {total:+.1f}%  caida {drawdown:.1f}%")
    print(f"  BTC:        {btc_total:+.1f}%  caida {btc_dd:.1f}%")

    matched_exposure = min(1.0, drawdown / btc_dd) if btc_dd > 0 else 1.0
    btc_matched, btc_matched_dd = compound(btc, matched_exposure)
    print(
        f"  BTC AL MISMO RIESGO (exposicion {matched_exposure:.2f}): "
        f"{btc_matched:+.1f}%  caida {btc_matched_dd:.1f}%"
    )

    error = standard_error(spreads)
    mean_spread = sum(spreads) / len(spreads)
    effect = abs(mean_spread) / error if error and error > 0 else None
    positives, count, p_value = sign_test(spreads)
    best_index = max(range(len(spreads)), key=lambda i: spreads[i])
    trimmed = [value for i, value in enumerate(spreads) if i != best_index]
    trimmed_error = standard_error(trimmed)
    trimmed_mean = sum(trimmed) / len(trimmed)
    trimmed_effect = (
        abs(trimmed_mean) / trimmed_error if trimmed_error and trimmed_error > 0 else None
    )

    print("\n  --- criterio pre-declarado sobre el spread mensual ---")
    print(f"  diferencia media (estrategia - BTC): {mean_spread:+.2%}")
    print(f"  mediana: {sorted(spreads)[len(spreads) // 2]:+.2%}")
    print(f"  efecto: {'n/a' if effect is None else f'{effect:.2f}'} (suelo {EFFECT_FLOOR:.1f})")
    print(f"  gana en {positives}/{count} periodos = {positives / count:.0%}, signo p={p_value:.4f}")
    print(
        f"  sin el mejor periodo: media {trimmed_mean:+.2%}, "
        f"efecto {'n/a' if trimmed_effect is None else f'{trimmed_effect:.2f}'}"
    )

    print(f"\n  --- con tu tope de caida del {DRAWDOWN_CAP:.0f}% aplicado a AMBOS ---")
    strategy_exposure = exposure_for_cap(strategy, DRAWDOWN_CAP)
    btc_exposure = exposure_for_cap(btc, DRAWDOWN_CAP)
    capped_strategy, capped_strategy_dd = compound(strategy, strategy_exposure)
    capped_btc, capped_btc_dd = compound(btc, btc_exposure)
    print(
        f"  estrategia a exposicion {strategy_exposure:.2f}: {capped_strategy:+.1f}%  "
        f"caida {capped_strategy_dd:.1f}%"
    )
    print(
        f"  BTC a exposicion {btc_exposure:.2f}:         {capped_btc:+.1f}%  "
        f"caida {capped_btc_dd:.1f}%"
    )

    passes = (
        mean_spread > 0
        and effect is not None
        and effect >= EFFECT_FLOOR
        and trimmed_effect is not None
        and trimmed_effect >= EFFECT_FLOOR
        and capped_strategy > capped_btc
    )
    verdict = (
        "EL FACTOR DE BAJA VOLATILIDAD SE CONVIERTE EN DINERO Y BATE A BTC AL MISMO RIESGO"
        if passes
        else "EL FACTOR NO PASA EL CRITERIO COMPLETO"
    )
    print(f"\n  VEREDICTO: {verdict}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "oos_periods": len(oos),
                "strategy_total_pct": round(total, 2),
                "strategy_drawdown_pct": round(drawdown, 2),
                "btc_total_pct": round(btc_total, 2),
                "btc_drawdown_pct": round(btc_dd, 2),
                "btc_risk_matched_pct": round(btc_matched, 2),
                "mean_spread": round(mean_spread, 6),
                "median_spread": round(sorted(spreads)[len(spreads) // 2], 6),
                "effect": None if effect is None else round(effect, 3),
                "effect_trimmed": None if trimmed_effect is None else round(trimmed_effect, 3),
                "wins": positives,
                "sign_test_p": round(p_value, 6),
                "capped": {
                    "cap_pct": DRAWDOWN_CAP,
                    "strategy_exposure": round(strategy_exposure, 3),
                    "strategy_pct": round(capped_strategy, 2),
                    "btc_exposure": round(btc_exposure, 3),
                    "btc_pct": round(capped_btc, 2),
                },
                "verdict": verdict,
                "survivorship_bias": "not eliminated; hand-picked universe biases results UP",
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
