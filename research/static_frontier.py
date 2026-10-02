"""The no-forecast frontier: constant fractional BTC exposure, rebalanced with a band.

This exists because every forecasting arm measured in this project loses to the thing it is
trying to beat. On the development window: perfect foresight +207.8%, buy and hold +184.4%,
the trained quantitative policy +132.1%, a seeded coin flip +81.8 to +89.6%, and the LLM
+68.9%. Only the unobtainable oracle beat holding.

So the honest question stops being "which model decides best" and becomes "what is the best
structure that decides NOTHING". A constant fraction `f` of capital in BTC, rebalanced when it
drifts past a band, needs no signal, no model and no regime label. It is the null that the
rewritten gate scores the agent against, and nothing measured here has beaten it at equal
risk.

Honesty constraints, same as the rest of the research harness:

- equity marked to market on every HOURLY bar, so the drawdown is what the capital felt
- fees charged on the traded notional at each rebalance, both legs
- a rebalance BAND rather than a fixed schedule, because rebalancing every bar would pay the
  churn this project priced at 137% of capital per year
- documented dataset gaps are never bridged

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.static_frontier
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from multislot_sim import Bar, load_bars

DATASET = "data/history/btcusdt-1h-2017"
HONEST_FEE = 0.001
ADVERSE_FEE = 0.002
DRAWDOWN_CAP = 0.25
REPORT = Path("data/validation/static-frontier.json")


@dataclass
class FrontierPoint:
    """One constant-fraction policy, measured end to end."""

    fraction: float
    band: float
    fee_per_side: float
    net_return_pct: float
    max_drawdown_pct: float
    rebalances: int
    fees_paid_pct: float

    def respects_cap(self) -> bool:
        return self.max_drawdown_pct <= DRAWDOWN_CAP * 100.0


def simulate(
    bars: list[Bar], fraction: float, band: float, fee_per_side: float
) -> FrontierPoint:
    """Hold `fraction` of equity in BTC, rebalancing when drift exceeds `band`."""
    price = bars[0].close
    equity = 1.0
    units = equity * fraction / price
    cash = equity - units * price
    cash -= units * price * fee_per_side  # entry fee on the initial purchase
    peak = equity
    worst = 0.0
    rebalances = 0
    fees = 0.0

    for bar in bars:
        price = bar.close
        held = units * price
        equity = cash + held
        if equity <= 0.0:
            break
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)

        actual = held / equity
        if abs(actual - fraction) > band:
            target_value = equity * fraction
            traded = abs(target_value - held)
            fee = traded * fee_per_side
            fees += fee
            units = target_value / price
            cash = equity - target_value - fee
            rebalances += 1

    final = cash + units * bars[-1].close
    final -= units * bars[-1].close * fee_per_side  # exit fee, never silently dropped
    return FrontierPoint(
        fraction=fraction,
        band=band,
        fee_per_side=fee_per_side,
        net_return_pct=(final - 1.0) * 100.0,
        max_drawdown_pct=worst * 100.0,
        rebalances=rebalances,
        fees_paid_pct=fees * 100.0,
    )


def main() -> int:
    bars, dataset_id = load_bars(DATASET)
    print(f"dataset {dataset_id}")
    print(f"{len(bars)} barras horarias, {bars[0].close:.0f} -> {bars[-1].close:.0f}")
    hold = simulate(bars, 1.0, 1.0, ADVERSE_FEE)
    print(
        f"comprar y mantener (f=1.00): {hold.net_return_pct:+,.0f}%  "
        f"caida {hold.max_drawdown_pct:.1f}%"
    )
    print(f"\ntope de caida declarado: {DRAWDOWN_CAP:.0%}\n")

    points: list[FrontierPoint] = []
    for fee, label in ((ADVERSE_FEE, "ADVERSAS 20bps"), (HONEST_FEE, "honestas 10bps")):
        print(f"--- comisiones {label} ---")
        print(
            f"  {'f':>5} {'banda':>6} {'retorno':>12} {'caida':>8} "
            f"{'rebal':>6} {'comision':>9} {'tope':>6}"
        )
        for fraction in (0.20, 0.30, 0.35, 0.40, 0.50, 0.60, 0.80, 1.00):
            for band in (0.05,):
                point = simulate(bars, fraction, band, fee)
                points.append(point)
                print(
                    f"  {fraction:>5.2f} {band:>6.0%} {point.net_return_pct:>11,.0f}% "
                    f"{point.max_drawdown_pct:>7.1f}% {point.rebalances:>6} "
                    f"{point.fees_paid_pct:>8.1f}% "
                    f"{'si' if point.respects_cap() else 'NO':>6}"
                )
        print()

    print("--- sensibilidad a la banda de rebalanceo, f=0.35, comisiones adversas ---")
    print(f"  {'banda':>6} {'retorno':>12} {'caida':>8} {'rebal':>6} {'comision':>9}")
    for band in (0.02, 0.05, 0.10, 0.20, 1.00):
        point = simulate(bars, 0.35, band, ADVERSE_FEE)
        points.append(point)
        shown = "sin rebal." if band >= 1.0 else f"{band:.0%}"
        print(
            f"  {shown:>6} {point.net_return_pct:>11,.0f}% "
            f"{point.max_drawdown_pct:>7.1f}% {point.rebalances:>6} "
            f"{point.fees_paid_pct:>8.1f}%"
        )

    admissible = [
        point
        for point in points
        if point.fee_per_side == ADVERSE_FEE and point.band == 0.05 and point.respects_cap()
    ]
    if admissible:
        best = max(admissible, key=lambda point: point.net_return_pct)
        print(
            f"\nMEJOR f QUE RESPETA EL TOPE (adversas, banda 5%): f={best.fraction:.2f} -> "
            f"{best.net_return_pct:+,.0f}% con caida {best.max_drawdown_pct:.1f}%"
        )
    else:
        print("\nNinguna fraccion con banda 5% respeta el tope.")

    payload: dict[str, Any] = {
        "dataset_id": dataset_id,
        "drawdown_cap": DRAWDOWN_CAP,
        "buy_and_hold": asdict(hold),
        "points": [asdict(point) for point in points],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\ninforme: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
