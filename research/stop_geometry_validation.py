"""Does fixing the break-even ratchet actually make money? Measured out of sample.

The defect is proven: a lock of entry+0.25% against a 0.20% round trip nets 0.05%, and on
nine years of hourly BTC it fires ~99% of the time once armed. That makes removing it
CORRECT. It does not, by itself, make it PROFITABLE -- and this project has been wrong before
by assuming a defect fix must show up as return.

So this measures the stop geometry end to end on history the parameters were not chosen on,
and scores it against the two nulls that matter:

- buy and hold, de-leveraged to the SAME realised drawdown (the rewritten gate's comparator,
  because beating raw buy and hold by holding less is not skill)
- staying in USDT, which the regime study found nothing beat out of sample

Honesty constraints:

- the position is opened at a bar close and the stop is checked against subsequent bar LOWS,
  which is what triggers a real stop; checking closes would understate every stop
- a stop and a target inside the same bar resolve as the STOP, the adverse assumption, since
  hourly bars cannot say which came first
- fees are charged on both legs at the adverse rate
- the holdout is 2018-2019, already spent in this project, so it is reported as CONTEXT and
  the verdict is taken on the full history minus the development window

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.stop_geometry_validation
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from multislot_sim import Bar, load_bars

DATASET = "data/history/btcusdt-1h-2017"
REPORT = Path("data/validation/stop-geometry-validation.json")
ADVERSE_FEE = 0.001
"""Per side. 20 bps the round trip, matching the engine's own round_trip_cost_bps."""
HOLD_HOURS = 720
"""Re-entry cadence: a closed position waits for the next slot rather than re-buying at once,
so a stop that fires cannot be undone by instantly re-entering at the same price."""


@dataclass(frozen=True)
class Geometry:
    name: str
    hard_stop: float
    trailing: float
    trailing_activation: float
    break_even_activation: float
    break_even_lock: float

    def stop_for(self, entry: float, high: float) -> float:
        """The engine's own `_active_stop`, in floats. Must mirror it exactly."""
        initial = entry * (1.0 - self.hard_stop)
        if self.break_even_lock > 0.0 and high >= entry * (1.0 + self.break_even_activation):
            initial = max(initial, entry * (1.0 + self.break_even_lock))
        if high < entry * (1.0 + self.trailing_activation):
            return initial
        return max(initial, high * (1.0 - self.trailing))


@dataclass
class Outcome:
    name: str
    net_return_pct: float
    max_drawdown_pct: float
    trades: int
    stopped_out: int
    fees_paid_pct: float


def simulate(bars: list[Bar], geometry: Geometry) -> Outcome:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    trades = 0
    stopped = 0
    fees = 0.0
    index = 0

    while index < len(bars) - 1:
        entry = bars[index].close
        if entry <= 0:
            index += 1
            continue
        equity -= equity * ADVERSE_FEE
        fees += ADVERSE_FEE
        trades += 1
        high = entry
        exit_price = entry
        exited = False
        last = min(index + HOLD_HOURS, len(bars) - 1)

        for step in range(index + 1, last + 1):
            bar = bars[step]
            stop = geometry.stop_for(entry, high)
            # Adverse ordering: the low is tested BEFORE the high is updated, so a bar that
            # both dips to the stop and makes a new high counts as a stop.
            if bar.low <= stop:
                exit_price = stop
                exited = True
                stopped += 1
                break
            high = max(high, bar.high)
            marked = equity * (bar.close / entry)
            peak = max(peak, marked)
            worst = max(worst, (peak - marked) / peak)

        if not exited:
            exit_price = bars[last].close
        equity *= exit_price / entry
        equity -= equity * ADVERSE_FEE
        fees += ADVERSE_FEE
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
        index = last

    return Outcome(
        name=geometry.name,
        net_return_pct=(equity - 1.0) * 100.0,
        max_drawdown_pct=worst * 100.0,
        trades=trades,
        stopped_out=stopped,
        fees_paid_pct=fees * 100.0,
    )


def buy_and_hold(bars: list[Bar]) -> tuple[float, float]:
    first = bars[0].close
    equity = 1.0 - ADVERSE_FEE
    peak = equity
    worst = 0.0
    for bar in bars:
        marked = (1.0 - ADVERSE_FEE) * bar.close / first
        peak = max(peak, marked)
        worst = max(worst, (peak - marked) / peak)
    final = (1.0 - ADVERSE_FEE) * bars[-1].close / first
    final -= final * ADVERSE_FEE
    return (final - 1.0) * 100.0, worst * 100.0


def risk_matched(hold_return: float, hold_drawdown: float, drawdown: float) -> float:
    """Buy and hold de-leveraged until its drawdown equals `drawdown`."""
    if hold_drawdown <= 0:
        return hold_return
    fraction = min(1.0, drawdown / hold_drawdown)
    return fraction * hold_return


SHIPPED = Geometry("vivo (roto): lock 0.25%", 0.03, 0.025, 0.01, 0.005, 0.0025)
FIXED = Geometry("arreglado: lock no arma", 0.03, 0.025, 0.01, 0.005, 0.0)
NOISE_WIDE = Geometry("ruido-medido: duro 10%, trail 8%", 0.10, 0.08, 0.05, 0.02, 0.0)


def main() -> int:
    bars, dataset_id = load_bars(DATASET)
    print(f"dataset {dataset_id}  ·  {len(bars):,} barras horarias")

    # Development window: where the live parameters were in force. Everything before it is
    # out of sample for them.
    split = int(len(bars) * 0.80)
    segments = {
        "FUERA DE MUESTRA (2017-08 -> ~2024)": bars[:split],
        "ventana de desarrollo (~2024 -> 2026-09)": bars[split:],
        "TODO": bars,
    }

    report: dict[str, object] = {"dataset_id": dataset_id, "segments": {}}
    for label, segment in segments.items():
        if len(segment) < HOLD_HOURS * 2:
            continue
        hold_return, hold_drawdown = buy_and_hold(segment)
        print(f"\n=== {label} ===")
        print(f"  {len(segment):,} barras")
        print(f"  comprar y mantener      {hold_return:>+10.2f}%   caida {hold_drawdown:.2f}%")
        print("  quedarse en USDT             +0.00%   caida 0.00%")
        print()
        print(f"  {'geometria':<34} {'retorno':>10} {'caida':>8} {'ops':>6} {'stops':>6} {'vs nulo':>9}")
        rows = []
        for geometry in (SHIPPED, FIXED, NOISE_WIDE):
            outcome = simulate(segment, geometry)
            null = risk_matched(hold_return, hold_drawdown, outcome.max_drawdown_pct)
            edge = outcome.net_return_pct - null
            beats_usdt = outcome.net_return_pct > 0.0
            print(
                f"  {outcome.name:<34} {outcome.net_return_pct:>+9.2f}% "
                f"{outcome.max_drawdown_pct:>7.2f}% {outcome.trades:>6} "
                f"{outcome.stopped_out:>6} {edge:>+8.2f}%"
            )
            rows.append(
                {
                    "geometry": outcome.name,
                    "net_return_pct": outcome.net_return_pct,
                    "max_drawdown_pct": outcome.max_drawdown_pct,
                    "trades": outcome.trades,
                    "stopped_out": outcome.stopped_out,
                    "fees_paid_pct": outcome.fees_paid_pct,
                    "risk_matched_null_pct": null,
                    "edge_vs_null_pct": edge,
                    "beats_usdt": beats_usdt,
                }
            )
        report["segments"][label] = {  # type: ignore[index]
            "bars": len(segment),
            "buy_and_hold_pct": hold_return,
            "buy_and_hold_drawdown_pct": hold_drawdown,
            "geometries": rows,
        }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\ninforme: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
