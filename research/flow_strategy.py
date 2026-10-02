"""Does the flow signal survive contact with costs? Walk-forward, vs holding at equal risk.

`research/flow_diagnosis.py` found the first thing this project has ever measured above one
standard error at an affordable churn horizon: volume and flow features reach 1 SE in **5 of 24**
pairs, all positive and all sign-stable, against **0 of 20** for the closes-only features the
agent actually consumes. The strongest is mean trade size (`ticket_medio_z30`), positive at 48h,
96h and 168h.

That is a lead, not an edge. A rank correlation of +0.03 says the ordering is slightly better than
chance; it says nothing about whether the ordering survives a 20 bps round trip. This module
asks the economic question instead of the statistical one, and it asks it the way the rest of the
project has learned to:

- **Walk-forward with 1-year out-of-sample folds.** The threshold and the feature are chosen on
  past data only and then frozen for the year that follows. Selecting the feature after seeing
  the diagnosis is exactly the bias that made 20 of 42 cells look like winners before, so the
  selection happens inside each fold.
- **Compared against buy and hold AT EQUAL RISK**, which is the comparator the rewritten gate
  uses: a static fraction of BTC sized to the strategy's own realised drawdown earns that
  fraction of holding's return for free, so beating raw holding is not the test -- beating the
  de-leveraged version of it is.
- **One bar of execution lag** and fees on both legs.

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.flow_strategy
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from flow_diagnosis import DailyBar, build_features, load_daily

ADVERSE_FEE = 0.002
HONEST_FEE = 0.001
FOLD_DAYS = 365
MIN_TRAIN_DAYS = 730
CANDIDATES = (
    "ticket_medio_z30",
    "num_operaciones_z30",
    "volumen_z30",
    "rango_intradia_z30",
    "compuesto",
)
REPORT = Path("data/validation/flow-strategy.json")


@dataclass
class Run:
    """One exposure path, measured end to end."""

    label: str
    net_return_pct: float
    max_drawdown_pct: float
    switches: int
    long_share: float
    fees_paid_pct: float


def composite(features: dict[str, list[float | None]], index: int) -> float | None:
    """Equal-weight mean of the four features that reached one standard error.

    Equal weights on purpose. Fitting weights on four signals this weak would fit noise, and
    the project has a measured example of exactly that failing out of sample.
    """
    values = [
        features[name][index]
        for name in ("ticket_medio_z30", "num_operaciones_z30", "volumen_z30", "rango_intradia_z30")
    ]
    present = [value for value in values if value is not None]
    if len(present) < 4:
        return None
    return sum(present) / len(present)


def signal_at(
    features: dict[str, list[float | None]], name: str, index: int
) -> float | None:
    return composite(features, index) if name == "compuesto" else features[name][index]


def simulate(
    daily: list[DailyBar],
    features: dict[str, list[float | None]],
    name: str,
    threshold: float,
    fee: float,
    first: int,
    last: int,
    *,
    exposure: float = 1.0,
) -> Run:
    """Long `exposure` when the signal clears `threshold`, flat otherwise. One day of lag."""
    equity = 1.0
    peak = 1.0
    worst = 0.0
    invested = False
    switches = 0
    fees = 0.0
    long_days = 0
    days = 0

    for index in range(first, min(last, len(daily) - 1)):
        value = signal_at(features, name, index)
        want = value is not None and value > threshold
        # Act on the NEXT bar: the signal is only known once the day has completed.
        move = math.log(daily[index + 1].close / daily[index].close)
        if want != invested:
            fee_paid = exposure * fee
            equity *= 1.0 - fee_paid
            fees += fee_paid
            switches += 1
            invested = want
        if invested:
            equity *= math.exp(move * exposure)
            long_days += 1
        days += 1
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak if peak > 0 else 0.0)

    return Run(
        label=f"{name} > {threshold:+.2f}",
        net_return_pct=(equity - 1.0) * 100.0,
        max_drawdown_pct=worst * 100.0,
        switches=switches,
        long_share=long_days / days if days else 0.0,
        fees_paid_pct=fees * 100.0,
    )


def buy_and_hold(daily: list[DailyBar], fee: float, first: int, last: int) -> Run:
    equity = 1.0 - fee
    peak = 1.0
    worst = 0.0
    for index in range(first, min(last, len(daily) - 1)):
        equity *= daily[index + 1].close / daily[index].close
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak if peak > 0 else 0.0)
    equity *= 1.0 - fee
    return Run(
        label="comprar y mantener",
        net_return_pct=(equity - 1.0) * 100.0,
        max_drawdown_pct=worst * 100.0,
        switches=1,
        long_share=1.0,
        fees_paid_pct=fee * 200.0,
    )


def risk_matched(hold: Run, strategy_drawdown: float) -> float:
    """Return of a static fraction of holding sized to the strategy's own drawdown.

    This is the gate's comparator: the free alternative. A strategy that does not beat it is
    a more expensive way to hold less BTC.
    """
    if hold.max_drawdown_pct <= 0.0:
        return 0.0
    fraction = min(1.0, strategy_drawdown / hold.max_drawdown_pct)
    return fraction * hold.net_return_pct


def main() -> int:
    daily = load_daily()
    features = build_features(daily)
    print(f"dias {len(daily)}  {daily[0].date} .. {daily[-1].date}")
    print(
        f"walk-forward: train >= {MIN_TRAIN_DAYS}d, OOS {FOLD_DAYS}d, "
        f"comisiones adversas {ADVERSE_FEE * 10000:.0f}bps, 1 dia de retardo\n"
    )

    folds: list[tuple[int, int]] = []
    cursor = MIN_TRAIN_DAYS
    while cursor + FOLD_DAYS < len(daily) - 1:
        folds.append((cursor, cursor + FOLD_DAYS))
        cursor += FOLD_DAYS

    thresholds = (-0.5, 0.0, 0.5)
    pooled_equity = 1.0
    pooled_worst = 0.0
    pooled_peak = 1.0
    rows: list[dict[str, object]] = []

    print(
        f"{'fold':>4} {'train hasta':<12} {'OOS hasta':<12} {'elegido':<28} "
        f"{'OOS':>8} {'b&h':>8} {'b&h@riesgo':>11} {'dd':>7}"
    )
    for number, (train_end, test_end) in enumerate(folds, start=1):
        best_label = None
        best_return = -1e9
        for name in CANDIDATES:
            for threshold in thresholds:
                run = simulate(
                    daily, features, name, threshold, ADVERSE_FEE, 0, train_end
                )
                if run.net_return_pct > best_return:
                    best_return = run.net_return_pct
                    best_label = (name, threshold)
        assert best_label is not None
        name, threshold = best_label

        tested = simulate(
            daily, features, name, threshold, ADVERSE_FEE, train_end, test_end
        )
        hold = buy_and_hold(daily, ADVERSE_FEE, train_end, test_end)
        matched = risk_matched(hold, tested.max_drawdown_pct)

        pooled_equity *= 1.0 + tested.net_return_pct / 100.0
        pooled_peak = max(pooled_peak, pooled_equity)
        pooled_worst = max(
            pooled_worst, (pooled_peak - pooled_equity) / pooled_peak if pooled_peak > 0 else 0.0
        )
        rows.append(
            {
                "fold": number,
                "train_end": daily[train_end].date,
                "test_end": daily[min(test_end, len(daily) - 1)].date,
                "chosen": f"{name} > {threshold:+.2f}",
                "oos_return_pct": round(tested.net_return_pct, 2),
                "hold_return_pct": round(hold.net_return_pct, 2),
                "risk_matched_pct": round(matched, 2),
                "oos_drawdown_pct": round(tested.max_drawdown_pct, 2),
                "beat_risk_matched": tested.net_return_pct > matched,
            }
        )
        print(
            f"{number:>4} {daily[train_end].date:<12} "
            f"{daily[min(test_end, len(daily) - 1)].date:<12} "
            f"{name + ' > ' + format(threshold, '+.2f'):<28} "
            f"{tested.net_return_pct:>7.1f}% {hold.net_return_pct:>7.1f}% "
            f"{matched:>10.1f}% {tested.max_drawdown_pct:>6.1f}%"
        )

    beats = sum(1 for row in rows if row["beat_risk_matched"])
    print(f"\n  folds: {len(rows)}")
    print(f"  folds que baten a comprar-y-mantener AL MISMO RIESGO: {beats} de {len(rows)}")
    print(f"  retorno compuesto de la estrategia OOS: {(pooled_equity - 1.0) * 100:+.1f}%")
    print(f"  caida compuesta: {pooled_worst * 100:.1f}%")

    full_hold = buy_and_hold(daily, ADVERSE_FEE, MIN_TRAIN_DAYS, len(daily) - 1)
    print(
        f"  comprar y mantener sobre el mismo tramo: {full_hold.net_return_pct:+.1f}% "
        f"con caida {full_hold.max_drawdown_pct:.1f}%"
    )
    matched_full = risk_matched(full_hold, pooled_worst * 100)
    print(f"  comprar y mantener AL MISMO RIESGO: {matched_full:+.1f}%")
    verdict = (
        "LA SEÑAL DE FLUJO NO SE CONVIERTE EN DINERO"
        if (pooled_equity - 1.0) * 100 <= matched_full
        else "LA SEÑAL DE FLUJO SUPERA AL ESTATICO AL MISMO RIESGO"
    )
    print(f"\n  VEREDICTO: {verdict}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "folds": rows,
                "pooled_return_pct": round((pooled_equity - 1.0) * 100, 2),
                "pooled_drawdown_pct": round(pooled_worst * 100, 2),
                "hold": asdict(full_hold),
                "hold_risk_matched_pct": round(matched_full, 2),
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
