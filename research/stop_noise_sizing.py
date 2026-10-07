"""Dimension BTC protective-stop distances from MEASURED noise, not a fitted return.

The live agent uses a 3% hard stop, 2.5% trailing stop, 1% trailing activation,
0.5% break-even activation and 0.25% break-even lock. The hypothesis under test is
that ALL of those distances sit INSIDE the normal hourly noise of BTC, so the stop
fires on microstructure rather than on information.

Everything here is MEASUREMENT over the frozen 1h dataset (open LOW-triggered
maximum adverse excursion from the running peak, exactly what trips a real stop),
plus a thin layer of explicit ARITHMETIC inference (how far a stop must sit to push
the noise-touch probability below a target). The two are kept separate on purpose:
the empirical fractions are facts about the sample; the recommended distances are
read directly off those fractions, not re-fitted.

Documented dataset gaps are never bridged. A forward window is only counted when
the 24h / 72h / 168h / 720h horizon is fully covered by a single contiguous run of
bars (``contiguous_run`` strictly increasing by one each step), so no excursion is
measured across a hole in the data.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from itertools import pairwise

from multislot_sim import Bar, load_bars

DATASET = "data/history/btcusdt-1h-2017"
HOURS_PER_DAY = 24
HORIZONS_H = (24, 72, 168, 720)
# MAE thresholds (fraction) at which we count a noise touch.
TOUCH_LEVELS = (0.0025, 0.005, 0.01, 0.025, 0.03, 0.05, 0.08, 0.10, 0.15)
# Live break-even parameters.
BE_ACTIVATION = 0.005  # price must rise >= 0.5% above entry to arm the lock
BE_LOCK = 0.0025  # once armed, a fall back to entry + 0.25% is the trip level
BE_HORIZONS_H = (24, 72, 168)
FEE_PER_SIDE_BPS = 10.0  # 10 bps per side


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile over an already-sorted list."""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct / 100.0 * (len(sorted_values) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[low]
    frac = rank - low
    return sorted_values[low] * (1.0 - frac) + sorted_values[high] * frac


def _year(bar: Bar) -> int:
    return datetime.fromtimestamp(bar.open_time_ms / 1000.0, tz=UTC).year


# ---------------------------------------------------------------------------
# 1. Base volatility
# ---------------------------------------------------------------------------
def base_volatility(bars: list[Bar]) -> dict[str, object]:
    """Std dev of hourly log returns, its daily equivalent, and per-year daily vol."""
    log_returns: list[float] = []
    per_year: dict[int, list[float]] = {}
    for prev, cur in pairwise(bars):
        # Only use strictly contiguous consecutive bars (no gap bridging).
        if cur.contiguous_run <= prev.contiguous_run:
            continue
        if prev.close <= 0 or cur.close <= 0:
            continue
        r = math.log(cur.close / prev.close)
        log_returns.append(r)
        per_year.setdefault(_year(cur), []).append(r)

    def std(xs: list[float]) -> float:
        n = len(xs)
        if n < 2:
            return float("nan")
        mean = sum(xs) / n
        var = sum((x - mean) ** 2 for x in xs) / (n - 1)
        return math.sqrt(var)

    hourly = std(log_returns)
    daily = hourly * math.sqrt(HOURS_PER_DAY)
    yearly = {
        year: std(rs) * math.sqrt(HOURS_PER_DAY)
        for year, rs in sorted(per_year.items())
        if len(rs) >= 2
    }
    return {
        "n_hourly_returns": len(log_returns),
        "hourly_std": hourly,
        "daily_std_equiv": daily,
        "daily_std_by_year": yearly,
    }


# ---------------------------------------------------------------------------
# 2 & 3. Maximum adverse excursion and noise-touch probability
# ---------------------------------------------------------------------------
def _mae_for_horizon(bars: list[Bar], start: int, horizon_h: int) -> float | None:
    """Max retrace from the running peak over the next ``horizon_h`` bars.

    Simulates a LONG opened at ``bars[start].close``. The running peak tracks bar
    HIGHs (the best price seen); the adverse excursion at each step uses the bar LOW
    (what a stop actually tests). Returns the largest (peak - low) / peak observed,
    or ``None`` if the horizon is not fully covered by a contiguous run of bars.
    """
    end = start + horizon_h
    if end >= len(bars):
        return None
    # Require an unbroken contiguous run across the whole forward window.
    expected = bars[start].contiguous_run
    for i in range(start + 1, end + 1):
        expected += 1
        if bars[i].contiguous_run != expected:
            return None
    entry = bars[start].close
    peak = entry
    worst = 0.0
    for i in range(start + 1, end + 1):
        bar = bars[i]
        retrace = (peak - bar.low) / peak
        if retrace > worst:
            worst = retrace
        if bar.high > peak:
            peak = bar.high
    return worst


def adverse_excursion(bars: list[Bar]) -> dict[int, dict[str, object]]:
    """Per-horizon MAE distribution and noise-touch fractions."""
    out: dict[int, dict[str, object]] = {}
    for horizon in HORIZONS_H:
        maes: list[float] = []
        for start in range(len(bars)):
            mae = _mae_for_horizon(bars, start, horizon)
            if mae is not None:
                maes.append(mae)
        maes.sort()
        n = len(maes)
        touch = {
            level: (sum(1 for m in maes if m >= level) / n if n else float("nan"))
            for level in TOUCH_LEVELS
        }
        out[horizon] = {
            "n_windows": n,
            "median": _percentile(maes, 50),
            "p25": _percentile(maes, 25),
            "p75": _percentile(maes, 75),
            "p90": _percentile(maes, 90),
            "touch": touch,
        }
    return out


def stop_for_targets(
    excursion: dict[int, dict[str, object]], horizons_h: tuple[int, ...] = (168, 720)
) -> dict[int, dict[float, float | None]]:
    """Smallest TOUCH_LEVEL whose noise-touch probability is below each target.

    Pure arithmetic read off the empirical touch fractions: for a target touch
    probability (0.50 / 0.25 / 0.10) it returns the tightest tabulated stop distance
    that already keeps the probability under that target, or ``None`` if even the
    widest tabulated level still touches more often than the target.
    """
    targets = (0.50, 0.25, 0.10)
    out: dict[int, dict[float, float | None]] = {}
    for horizon in horizons_h:
        touch = excursion[horizon]["touch"]  # type: ignore[index]
        row: dict[float, float | None] = {}
        for target in targets:
            chosen: float | None = None
            for level in TOUCH_LEVELS:  # ascending
                if touch[level] < target:
                    chosen = level
                    break
            row[target] = chosen
        out[horizon] = row
    return out


# ---------------------------------------------------------------------------
# 4. Break-even lock survival
# ---------------------------------------------------------------------------
def breakeven_survival(bars: list[Bar]) -> dict[int, dict[str, object]]:
    """Given the +0.5% activation was hit, how often price falls back to +0.25%.

    For each start, within each horizon, we require the forward window to be
    contiguous. Among windows where the high ever reached entry*(1+0.5%) BEFORE the
    end (arming the lock), we measure the fraction where, AFTER arming, a bar low
    returned to entry*(1+0.25%) within the horizon -- i.e. the lock would trip.
    """
    out: dict[int, dict[str, object]] = {}
    for horizon in BE_HORIZONS_H:
        armed = 0
        tripped = 0
        for start in range(len(bars)):
            end = start + horizon
            if end >= len(bars):
                continue
            expected = bars[start].contiguous_run
            contiguous = True
            for i in range(start + 1, end + 1):
                expected += 1
                if bars[i].contiguous_run != expected:
                    contiguous = False
                    break
            if not contiguous:
                continue
            entry = bars[start].close
            arm_price = entry * (1.0 + BE_ACTIVATION)
            lock_price = entry * (1.0 + BE_LOCK)
            is_armed = False
            did_trip = False
            for i in range(start + 1, end + 1):
                bar = bars[i]
                if not is_armed:
                    if bar.high >= arm_price:
                        is_armed = True
                        # Same bar could also dip to the lock after arming.
                        if bar.low <= lock_price:
                            did_trip = True
                            break
                else:
                    if bar.low <= lock_price:
                        did_trip = True
                        break
            if is_armed:
                armed += 1
                if did_trip:
                    tripped += 1
        out[horizon] = {
            "n_armed": armed,
            "n_tripped": tripped,
            "trip_fraction": (tripped / armed) if armed else float("nan"),
        }
    return out


# ---------------------------------------------------------------------------
# 5. Spread crossing cost
# ---------------------------------------------------------------------------
def spread_cost() -> dict[str, float]:
    """Round-trip cost of crossing the spread vs the 0.25% break-even lock."""
    one_side = FEE_PER_SIDE_BPS / 10000.0
    round_trip = 2.0 * one_side
    return {
        "fee_per_side": one_side,
        "round_trip": round_trip,
        "be_lock": BE_LOCK,
        "be_lock_minus_round_trip": BE_LOCK - round_trip,
        "round_trip_as_mult_of_lock": round_trip / BE_LOCK,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _pct(x: float) -> str:
    return "nan" if (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.2f}%"


def main() -> None:
    bars, dataset_id = load_bars(DATASET)
    first = datetime.fromtimestamp(bars[0].open_time_ms / 1000.0, tz=UTC)
    last = datetime.fromtimestamp(bars[-1].open_time_ms / 1000.0, tz=UTC)
    print(f"dataset_id = {dataset_id}")
    print(f"bars       = {len(bars):,}  ({first:%Y-%m-%d} -> {last:%Y-%m-%d})")
    print()

    # 1. Base volatility
    vol = base_volatility(bars)
    print("=== 1. BASE VOLATILITY (measurement) ===")
    print(f"hourly log-return std      = {_pct(vol['hourly_std'])}")  # type: ignore[arg-type]
    print(
        f"daily equivalent (x sqrt24)= {_pct(vol['daily_std_equiv'])}"  # type: ignore[arg-type]
    )
    print(f"n hourly returns used      = {vol['n_hourly_returns']:,}")
    print("daily vol by year:")
    for year, dv in vol["daily_std_by_year"].items():  # type: ignore[union-attr]
        print(f"  {year}: {_pct(dv)}")
    print()

    # 2 & 3. Adverse excursion + touch
    exc = adverse_excursion(bars)
    print("=== 2. MAX ADVERSE EXCURSION from running peak (measurement) ===")
    print(f"{'horizon':>9} {'n':>8} {'median':>8} {'p25':>8} {'p75':>8} {'p90':>8}")
    for horizon in HORIZONS_H:
        row = exc[horizon]
        label = f"{horizon}h" if horizon < 168 else f"{horizon // 24}d"
        print(
            f"{label:>9} {row['n_windows']:>8,} "  # type: ignore[str-format]
            f"{_pct(row['median']):>8} {_pct(row['p25']):>8} "  # type: ignore[arg-type]
            f"{_pct(row['p75']):>8} {_pct(row['p90']):>8}"  # type: ignore[arg-type]
        )
    print()

    print("=== 3. NOISE-TOUCH PROBABILITY P(MAE >= level) (measurement) ===")
    header = "level".rjust(7) + "".join(
        (f"{h}h" if h < 168 else f"{h // 24}d").rjust(9) for h in HORIZONS_H
    )
    print(header)
    for level in TOUCH_LEVELS:
        cells = "".join(
            _pct(exc[h]["touch"][level]).rjust(9) for h in HORIZONS_H  # type: ignore[index]
        )
        print(f"{level * 100:>6.2f}%" + cells)
    print()

    stops = stop_for_targets(exc, horizons_h=(168, 720))
    print("=== 3b. STOP DISTANCE needed to hold noise-touch below target (arithmetic) ===")
    print("  smallest tabulated distance whose P(touch) < target")
    print(f"{'horizon':>9} {'<50%':>8} {'<25%':>8} {'<10%':>8}")
    for horizon in (168, 720):
        row = stops[horizon]
        label = f"{horizon // 24}d"

        def fmt(v: float | None) -> str:
            return ">15.00%+" if v is None else f"{v * 100:.2f}%"

        print(f"{label:>9} {fmt(row[0.50]):>8} {fmt(row[0.25]):>8} {fmt(row[0.10]):>8}")
    print()

    # 4. Break-even survival
    be = breakeven_survival(bars)
    print("=== 4. BREAK-EVEN LOCK SURVIVAL (measurement) ===")
    print("  given +0.5% was hit (lock armed), P(price falls back to entry+0.25%)")
    print(f"{'horizon':>9} {'n_armed':>10} {'n_tripped':>10} {'trip_frac':>10}")
    for horizon in BE_HORIZONS_H:
        row = be[horizon]
        label = f"{horizon}h" if horizon < 168 else f"{horizon // 24}d"
        print(
            f"{label:>9} {row['n_armed']:>10,} "  # type: ignore[str-format]
            f"{row['n_tripped']:>10,} {_pct(row['trip_fraction']):>10}"  # type: ignore[arg-type]
        )
    print()

    # 5. Spread cost
    sc = spread_cost()
    print("=== 5. SPREAD-CROSSING COST (arithmetic) ===")
    print(f"fee per side               = {_pct(sc['fee_per_side'])} (10 bps)")
    print(f"round-trip (in + out)      = {_pct(sc['round_trip'])}")
    print(f"break-even lock distance   = {_pct(sc['be_lock'])}")
    print(f"lock minus round-trip      = {_pct(sc['be_lock_minus_round_trip'])}")
    print(f"round-trip / lock          = {sc['round_trip_as_mult_of_lock']:.2f}x")
    print()


if __name__ == "__main__":
    main()
