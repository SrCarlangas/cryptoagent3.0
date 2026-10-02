"""Do VOLUME and FLOW inputs carry signal that closes alone do not?

Why this exists. `research/exposure-diagnosis.md` measured trend signals built from closes and
found nothing: of twenty signal/horizon pairs on non-overlapping samples, none reached one
standard error. Today's bounds measurement then showed that even a PERFECT brain on the current
inputs adds only +13% of return over holding (+207.8% vs +184.4%), because the ceiling is set by
the architecture, not the decider.

But `market_features` consumes **only daily closes and the current price**. The dataset has
carried `base_volume`, `quote_volume`, `trade_count`, `high`, `low` and `open` the whole time and
**not one of them has ever been measured**. That is the strongest form of the "wrong inputs"
hypothesis: not a missing exotic dataset, a missing column already on disk.

This is the gate that must pass BEFORE any model is built on these inputs. The project's central
lesson is that no model creates signal that is not there, so measuring the input first is the
cheap step and building the model first is the expensive mistake it already made.

Method, deliberately identical to `exposure-diagnosis.md` section D2 so the numbers are directly
comparable:

- Spearman rank correlation of each feature against the FORWARD return.
- Measured on NON-OVERLAPPING samples, averaged over every stride offset, because overlapping
  windows share outcomes and inflate significance.
- Horizons restricted to those where section C priced churn as affordable (>= 48h).
- Reported as rho / standard error, with sign stability across offsets. The bar to clear is the
  one the previous study failed: **one standard error**, and ideally two.

Every feature is causal and scale-free: computed from completed bars up to the decision bar, and
expressed as a z-score or a ratio so it does not depend on the price level or the epoch.

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.flow_diagnosis
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from btc_decision_agent.adapters.backfill import HistoricalDataset

DATASET = "data/history/btcusdt-1h-2017"
REPORT = Path("data/validation/flow-diagnosis.json")
HORIZONS_HOURS = (48, 96, 168, 336)
"""Only horizons where the original study priced churn as affordable."""
LOOKBACK = 30
"""Bars of history for each z-score, in units of the feature's own cadence (daily)."""


@dataclass(frozen=True)
class DailyBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    base_volume: float
    quote_volume: float
    trade_count: int


def load_daily(directory: str = DATASET) -> list[DailyBar]:
    """Aggregate hourly rows into UTC days, keeping the columns closes-only work discarded."""
    _, rows = HistoricalDataset(directory).load()
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = datetime.fromtimestamp(int(row["open_time"]) / 1000, tz=UTC).strftime("%Y-%m-%d")
        buckets.setdefault(key, []).append(row)

    daily: list[DailyBar] = []
    for date in sorted(buckets):
        hours = sorted(buckets[date], key=lambda item: int(item["open_time"]))
        if len(hours) < 23:
            continue  # Incomplete day: withheld rather than approximated.
        daily.append(
            DailyBar(
                date=date,
                open=float(hours[0]["open"]),
                high=max(float(item["high"]) for item in hours),
                low=min(float(item["low"]) for item in hours),
                close=float(hours[-1]["close"]),
                base_volume=sum(float(item["base_volume"]) for item in hours),
                quote_volume=sum(float(item["quote_volume"]) for item in hours),
                trade_count=sum(int(item["trade_count"]) for item in hours),
            )
        )
    return daily


def _zscore(series: list[float], index: int, lookback: int) -> float | None:
    """Standardise the latest value against its own trailing window. Causal."""
    if index < lookback:
        return None
    window = series[index - lookback : index + 1]
    mean = sum(window) / len(window)
    variance = sum((value - mean) ** 2 for value in window) / (len(window) - 1)
    deviation = math.sqrt(variance)
    if deviation <= 0.0:
        return None
    return (series[index] - mean) / deviation


def build_features(daily: list[DailyBar]) -> dict[str, list[float | None]]:
    """Scale-free, causal features derived from the columns closes-only work never used."""
    closes = [bar.close for bar in daily]
    volumes = [bar.quote_volume for bar in daily]
    counts = [float(bar.trade_count) for bar in daily]
    # Mean trade size: a crude but real proxy for who is trading. Large average tickets lean
    # institutional, small ones retail. Nothing in this project has ever looked at it.
    tickets = [
        bar.quote_volume / bar.trade_count if bar.trade_count else 0.0 for bar in daily
    ]
    # Intrabar range against close-to-close move: how much of the day's travel the close kept.
    ranges = [
        (bar.high - bar.low) / bar.close if bar.close > 0 else 0.0 for bar in daily
    ]
    # Amihud illiquidity: price impact per unit of money traded.
    impacts: list[float] = [0.0]
    for index in range(1, len(daily)):
        move = abs(math.log(closes[index] / closes[index - 1])) if closes[index - 1] > 0 else 0.0
        impacts.append(move / volumes[index] * 1e9 if volumes[index] > 0 else 0.0)
    # Signed-volume imbalance over 5 days: the closest thing to order flow that OHLCV allows.
    # Each bar's volume is signed by whether it closed above or below its open.
    imbalance: list[float | None] = []
    for index in range(len(daily)):
        if index < 5:
            imbalance.append(None)
            continue
        window = daily[index - 4 : index + 1]
        signed = sum(
            (1.0 if bar.close >= bar.open else -1.0) * bar.quote_volume for bar in window
        )
        total = sum(bar.quote_volume for bar in window)
        imbalance.append(signed / total if total > 0 else None)

    features: dict[str, list[float | None]] = {
        "volumen_z30": [_zscore(volumes, index, LOOKBACK) for index in range(len(daily))],
        "num_operaciones_z30": [_zscore(counts, index, LOOKBACK) for index in range(len(daily))],
        "ticket_medio_z30": [_zscore(tickets, index, LOOKBACK) for index in range(len(daily))],
        "rango_intradia_z30": [_zscore(ranges, index, LOOKBACK) for index in range(len(daily))],
        "iliquidez_amihud_z30": [_zscore(impacts, index, LOOKBACK) for index in range(len(daily))],
        "desequilibrio_volumen_5d": imbalance,
    }
    return features


def spearman(pairs: list[tuple[float, float]]) -> float | None:
    """Rank correlation, ties averaged. Pure Python by project convention."""
    if len(pairs) < 10:
        return None

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda index: values[index])
        out = [0.0] * len(values)
        position = 0
        while position < len(order):
            end = position
            while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
                end += 1
            average = (position + end) / 2.0 + 1.0
            for index in range(position, end + 1):
                out[order[index]] = average
            position = end + 1
        return out

    left = ranks([pair[0] for pair in pairs])
    right = ranks([pair[1] for pair in pairs])
    n = len(pairs)
    mean_left = sum(left) / n
    mean_right = sum(right) / n
    covariance = sum(
        (left[i] - mean_left) * (right[i] - mean_right) for i in range(n)
    )
    var_left = sum((value - mean_left) ** 2 for value in left)
    var_right = sum((value - mean_right) ** 2 for value in right)
    if var_left <= 0 or var_right <= 0:
        return None
    return covariance / math.sqrt(var_left * var_right)


@dataclass
class Measurement:
    feature: str
    horizon_hours: int
    independent_n: int
    mean_rho: float
    min_rho: float
    max_rho: float
    rho_over_se: float
    sign_stable: bool

    def reaches_one_se(self) -> bool:
        return abs(self.rho_over_se) >= 1.0


def measure(
    daily: list[DailyBar], features: dict[str, list[float | None]]
) -> list[Measurement]:
    """Non-overlapping Spearman per feature and horizon, averaged over stride offsets."""
    closes = [bar.close for bar in daily]
    out: list[Measurement] = []

    for name, series in features.items():
        for hours in HORIZONS_HOURS:
            stride = max(1, hours // 24)
            per_offset: list[float] = []
            counts: list[int] = []
            for offset in range(stride):
                pairs: list[tuple[float, float]] = []
                index = offset
                while index + stride < len(daily):
                    value = series[index]
                    if value is not None and closes[index] > 0:
                        forward = math.log(closes[index + stride] / closes[index])
                        pairs.append((value, forward))
                    index += stride
                rho = spearman(pairs)
                if rho is not None:
                    per_offset.append(rho)
                    counts.append(len(pairs))
            if not per_offset:
                continue
            mean_rho = sum(per_offset) / len(per_offset)
            independent = max(counts)
            # Standard error of a Spearman correlation at this independent sample size.
            se = 1.0 / math.sqrt(max(independent - 1, 1))
            out.append(
                Measurement(
                    feature=name,
                    horizon_hours=hours,
                    independent_n=independent,
                    mean_rho=mean_rho,
                    min_rho=min(per_offset),
                    max_rho=max(per_offset),
                    rho_over_se=mean_rho / se,
                    sign_stable=all(value > 0 for value in per_offset)
                    or all(value < 0 for value in per_offset),
                )
            )
    return out


def main() -> int:
    daily = load_daily()
    print(f"dias completos {len(daily)}  {daily[0].date} .. {daily[-1].date}")
    print(
        "metodo identico a exposure-diagnosis seccion D2: Spearman sobre muestras NO solapadas,\n"
        "promediado sobre todos los desplazamientos, horizontes de churn asequible.\n"
        "La barra que el estudio anterior NO superó: un error estandar.\n"
    )
    features = build_features(daily)
    results = measure(daily, features)
    results.sort(key=lambda item: -abs(item.rho_over_se))

    print(
        f"{'feature':<26} {'horizonte':>9} {'n indep':>8} {'rho medio':>10} "
        f"{'rango rho':>18} {'rho/ee':>8} {'signo':>6}"
    )
    for item in results:
        print(
            f"{item.feature:<26} {item.horizon_hours:>8}h {item.independent_n:>8} "
            f"{item.mean_rho:>+10.4f} "
            f"{item.min_rho:>+8.3f}..{item.max_rho:>+8.3f} "
            f"{item.rho_over_se:>+8.2f} {'si' if item.sign_stable else 'no':>6}"
        )

    reached = [item for item in results if item.reaches_one_se()]
    two_se = [item for item in results if abs(item.rho_over_se) >= 2.0]
    print(f"\n  pares medidos: {len(results)}")
    print(f"  alcanzan 1 error estandar: {len(reached)}")
    print(f"  alcanzan 2 errores estandar: {len(two_se)}")
    if two_se:
        print("  candidatos con señal real (>= 2 ee, signo estable):")
        for item in two_se:
            if item.sign_stable:
                print(
                    f"    {item.feature} a {item.horizon_hours}h: "
                    f"rho {item.mean_rho:+.4f} = {item.rho_over_se:+.2f} ee"
                )
    else:
        print(
            "  VEREDICTO: ningun input de volumen/flujo alcanza 2 errores estandar.\n"
            "  Construir un LLM sobre estos inputs repetiria el error central del proyecto."
        )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "dataset": DATASET,
                "days": len(daily),
                "span": [daily[0].date, daily[-1].date],
                "method": "non-overlapping Spearman, all stride offsets, as diagnosis D2",
                "measurements": [asdict(item) for item in results],
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
