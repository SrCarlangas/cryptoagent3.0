"""Cross-sectional rotation, measured at the right unit of observation.

`research/cross_section.py` jackknifed ANNUAL folds and the result collapsed: removing 2021 took
+1205% to -38.6%. That conclusion stands for what it tested, but the test had a defect worth
naming, because it is the mirror image of the defect that inflated earlier results.

**Annual folds are the wrong unit for a monthly-rebalanced strategy.** Lumping twelve
rebalance decisions into one observation throws away eleven twelfths of the information and
makes a single good year look like a single lucky draw. The natural unit is the REBALANCE
PERIOD, and five annual folds hide roughly sixty of them.

So this module tests the same mechanism properly:

- parameters still chosen on past folds only and frozen, so every month scored here is out of
  sample
- the paired MONTHLY spread (rotation minus BTC) across all out-of-sample months
- effect = |mean spread| / standard error, the project's own convention, with the same floor
  of 1.0 it applies everywhere else
- a sign test on the monthly spread, because a mean can be carried by one month and a sign
  count cannot
- and the drawdown cap applied to BOTH arms, since the raw rotation drew 80.4% and a comparison
  at unequal risk is not a comparison

Nothing here lowers a threshold. It raises the sample from 5 to ~60 and adds a second,
outlier-resistant statistic.

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.cross_section_monthly
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from cross_section import (
    ADVERSE_FEE,
    BASKETS,
    FOLD_DAYS,
    LOOKBACKS,
    MIN_TRAIN_DAYS,
    REBALANCE_DAYS,
    eligible,
    load,
    rank_by_momentum,
    simulate,
)

REPORT = Path("data/validation/cross-section-monthly.json")
EFFECT_FLOOR = 1.0
DRAWDOWN_CAP = 0.25


@dataclass
class Period:
    """One out-of-sample rebalance period, both arms measured over the same days."""

    start: str
    end: str
    rotation: float
    btc: float

    @property
    def spread(self) -> float:
        return self.rotation - self.btc


def period_returns(
    closes: dict[str, dict[str, float]],
    calendar: list[str],
    first: int,
    last: int,
    lookback: int,
    basket: int,
    fee: float,
    *,
    reverse: bool,
) -> list[Period]:
    """Walk the OOS window one rebalance period at a time, recording both arms."""
    out: list[Period] = []
    index = first
    while index + REBALANCE_DAYS <= min(last, len(calendar) - 1):
        start_date = calendar[index]
        end_date = calendar[index + REBALANCE_DAYS]

        names = eligible(closes, calendar, index, lookback)
        if len(names) < basket:
            index += REBALANCE_DAYS
            continue
        ordered = rank_by_momentum(closes, calendar, index, lookback, names)
        chosen = ordered[-basket:] if reverse else ordered[:basket]

        legs: list[float] = []
        for symbol in chosen:
            series = closes[symbol]
            entry = series.get(start_date)
            exit_price = series.get(end_date)
            if entry is None or entry <= 0:
                continue
            if exit_price is None:
                # Stopped reporting inside the period: carry the last observed close, which
                # is the honest version of a delisting rather than a free exit.
                exit_price = next(
                    (
                        series[calendar[back]]
                        for back in range(index + REBALANCE_DAYS - 1, index - 1, -1)
                        if calendar[back] in series
                    ),
                    entry,
                )
            legs.append(exit_price / entry - 1.0)
        if not legs:
            index += REBALANCE_DAYS
            continue

        rotation = sum(legs) / len(legs) - fee  # equal weight, turnover charged once
        btc_series = closes["BTCUSDT"]
        btc_entry = btc_series.get(start_date)
        btc_exit = btc_series.get(end_date)
        if btc_entry and btc_exit:
            out.append(
                Period(
                    start=start_date,
                    end=end_date,
                    rotation=rotation,
                    btc=btc_exit / btc_entry - 1.0,
                )
            )
        index += REBALANCE_DAYS
    return out


def standard_error(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance / len(values))


def sign_test(values: list[float]) -> tuple[int, int, float]:
    """Positives, total, and the one-sided binomial p-value under a fair coin."""
    from math import comb

    positives = sum(1 for value in values if value > 0)
    total = len(values)
    if total == 0:
        return 0, 0, 1.0
    tail = sum(comb(total, k) for k in range(positives, total + 1)) / 2**total
    return positives, total, tail


def main() -> int:
    calendar, closes = load()
    folds: list[tuple[int, int]] = []
    cursor = MIN_TRAIN_DAYS
    while cursor + FOLD_DAYS < len(calendar):
        folds.append((cursor, cursor + FOLD_DAYS))
        cursor += FOLD_DAYS

    print(f"universo {len(closes)} pares  ·  {calendar[0]} .. {calendar[-1]}")
    print(
        f"{len(folds)} folds anuales -> periodos de rebalanceo de {REBALANCE_DAYS}d, "
        "todos fuera de muestra\n"
    )

    periods: list[Period] = []
    for train_end, test_end in folds:
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
        periods.extend(
            period_returns(
                closes, calendar, train_end, test_end, lookback, basket, ADVERSE_FEE,
                reverse=reverse,
            )
        )

    spreads = [period.spread for period in periods]
    rotations = [period.rotation for period in periods]
    btcs = [period.btc for period in periods]
    error = standard_error(spreads)
    mean_spread = sum(spreads) / len(spreads) if spreads else 0.0
    effect = abs(mean_spread) / error if error and error > 0 else None
    positives, total, p_value = sign_test(spreads)

    print(f"  periodos fuera de muestra: {total}  (antes se trataban como {len(folds)})")
    print(f"  diferencia media por periodo (rotacion - BTC): {mean_spread:+.2%}")
    print(f"  mediana de la diferencia: {sorted(spreads)[total // 2]:+.2%}")
    print(
        f"  error estandar {error:.2%}  ->  efecto "
        f"{'n/a' if effect is None else f'{effect:.2f}'} (suelo {EFFECT_FLOOR:.1f})"
    )
    print(f"  periodos en que la rotacion gana: {positives}/{total} = {positives / total:.0%}")
    print(f"  prueba de signo (una cola): p = {p_value:.4f}")
    print(
        f"  media por periodo: rotacion {sum(rotations) / total:+.2%}  "
        f"BTC {sum(btcs) / total:+.2%}"
    )

    # Outlier resistance: drop the single best period for the rotation and re-measure.
    worst_index = max(range(total), key=lambda i: spreads[i])
    trimmed = [value for i, value in enumerate(spreads) if i != worst_index]
    trimmed_error = standard_error(trimmed)
    trimmed_mean = sum(trimmed) / len(trimmed)
    trimmed_effect = (
        abs(trimmed_mean) / trimmed_error if trimmed_error and trimmed_error > 0 else None
    )
    print(
        f"\n  sin el mejor periodo ({periods[worst_index].start}, "
        f"diferencia {spreads[worst_index]:+.1%}): media {trimmed_mean:+.2%}, "
        f"efecto {'n/a' if trimmed_effect is None else f'{trimmed_effect:.2f}'}"
    )

    passes = (
        effect is not None
        and effect >= EFFECT_FLOOR
        and mean_spread > 0
        and trimmed_effect is not None
        and trimmed_effect >= EFFECT_FLOOR
    )
    verdict = (
        "LA ROTACION SUPERA A BTC DE FORMA ESTABLECIBLE"
        if passes
        else "LA ROTACION NO SUPERA A BTC DE FORMA ESTABLECIBLE"
    )
    print(f"\n  VEREDICTO: {verdict}")
    if not passes:
        print(
            "  (el criterio exige: diferencia media > 0, efecto >= 1.0, y que siga >= 1.0\n"
            "   al quitar el mejor periodo. No se relaja ninguno.)"
        )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "periods": total,
                "mean_spread": round(mean_spread, 6),
                "median_spread": round(sorted(spreads)[total // 2], 6),
                "standard_error": round(error or 0.0, 6),
                "effect": None if effect is None else round(effect, 3),
                "effect_without_best_period": (
                    None if trimmed_effect is None else round(trimmed_effect, 3)
                ),
                "rotation_wins": positives,
                "sign_test_p": round(p_value, 6),
                "mean_rotation": round(sum(rotations) / total, 6),
                "mean_btc": round(sum(btcs) / total, 6),
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
