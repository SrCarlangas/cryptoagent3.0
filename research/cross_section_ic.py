"""Cross-sectional information coefficient: the right statistic, and ~30x the sample.

Every test in this project so far has thrown away most of its own data.

`cross_section_monthly.py` measured the PORTFOLIO spread: 60 out-of-sample observations, one
per rebalance. But the portfolio is one particular way of expressing a signal, and its payoff
is dominated by position sizing and by which few assets happened to be in the basket. The
signal's actual information content lives one level down, in the **cross-sectional ranking**:
on each date, does the signal order the assets in the order their next-period returns will
turn out to be?

That is the information coefficient, and it is computed WITHIN each period across assets and
then averaged across periods. With 30 assets and 60 periods it uses roughly **1,800
asset-period observations** instead of 60, and its standard error comes from the
period-to-period variation of the IC, which is the honest source of uncertainty.

This also lets the "wrong inputs" hypothesis be tested in a way it has not been. The volume and
flow features failed as TIME-SERIES signals on BTC (`flow_diagnosis.py`: 5 of 24 pairs reached
one standard error, 0 of 24 reached two, and 0 of 7 folds beat holding). Cross-sectionally they
are a different question: a feature can be useless for timing one asset and still rank thirty
of them. Nothing in this project has ever asked that.

Honesty, in the same terms as the rest of the harness:

- every signal is causal, computed from closes and volumes strictly before the decision date
- point-in-time eligibility: an asset is ranked only if it really had the history
- the forward return is the next rebalance period, non-overlapping, so periods are independent
- the t-statistic is mean_IC / (sd_IC / sqrt(periods)), the standard construction
- the universe is the same hand-picked one, so **survivorship bias still biases results UP**

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.cross_section_ic
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from cross_section import REBALANCE_DAYS
from flow_diagnosis import spearman

REPORT = Path("data/validation/cross-section-ic.json")
WARMUP = 180
"""Longest lookback any signal needs, so eligibility is uniform across signals."""

UNIVERSES = {
    # The corrected, full-alphabet universe. DEFAULT, because this is the universe the
    # project's headline result is stated on, and a script whose default reproduces a
    # DIFFERENT number than the report is a reproducibility trap. The earlier narrow file
    # was hand-picked (survivorship up) and an intermediate build of this one was truncated
    # alphabetically at GLMUSDT, silently dropping every pair from H to Z.
    "wide": Path("data/history/cross-section-wide-1d.json"),
    # Kept selectable so the weaker, hand-picked result stays auditable rather than deleted.
    "narrow": Path("data/history/cross-section-1d.json"),
}
DEFAULT_UNIVERSE = "wide"


def load_universe(name: str) -> tuple[list[str], dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Calendar, closes and volumes from ONE file, so the two can never disagree.

    The previous version loaded closes from one path and volumes from another hard-coded path.
    That is how a run silently mixes universes: the closes came from the file the loader was
    pointed at, while the volumes always came from the narrow file, so any symbol outside the
    narrow set was dropped for lack of volume -- which would quietly shrink a 254-pair
    universe back toward 30 without a single error message.
    """
    path = UNIVERSES[name]
    raw = json.loads(path.read_text(encoding="utf-8"))
    closes: dict[str, dict[str, float]] = {}
    volumes: dict[str, dict[str, float]] = {}
    dates: set[str] = set()
    for symbol, rows in raw.items():
        close_series: dict[str, float] = {}
        volume_series: dict[str, float] = {}
        for open_ms, close, quote in rows:
            date = datetime.fromtimestamp(open_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
            close_series[date] = float(close)
            volume_series[date] = float(quote)
            dates.add(date)
        closes[symbol] = close_series
        volumes[symbol] = volume_series
    return sorted(dates), closes, volumes


_FIRST_LISTED: dict[str, str] = {}


def listing_age_days(
    calendar: list[str], symbol: str, series: dict[str, float], date: str
) -> float:
    """Days between the pair's first observed close and `date`.

    A proxy for listing age, and the honest caveat belongs next to it: the first close in THIS
    dataset is not necessarily the pair's true listing date, only the earliest the data shows.
    For pairs listed before the dataset begins the age is therefore understated, which biases
    the signal toward zero rather than inventing one.
    """
    first = _FIRST_LISTED.get(symbol)
    if first is None:
        first = min(series)
        _FIRST_LISTED[symbol] = first
    start = datetime.strptime(first, "%Y-%m-%d").replace(tzinfo=UTC)
    today = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
    return max(0.0, (today - start).days)


def signals_for(
    closes: dict[str, dict[str, float]],
    volumes: dict[str, dict[str, float]],
    calendar: list[str],
    index: int,
    symbol: str,
) -> dict[str, float] | None:
    """Every candidate signal for one asset on one date, or None if history is missing."""
    date = calendar[index]
    series = closes[symbol]
    volume = volumes[symbol]
    if date not in series or series[date] <= 0:
        return None

    def close_at(offset: int) -> float | None:
        if index - offset < 0:
            return None
        key = calendar[index - offset]
        value = series.get(key)
        return value if value and value > 0 else None

    now = series[date]
    past30, past90, past180 = close_at(30), close_at(90), close_at(180)
    if past30 is None or past90 is None or past180 is None:
        return None

    recent_volume = [
        volume[calendar[index - back]]
        for back in range(30)
        if calendar[index - back] in volume
    ]
    older_volume = [
        volume[calendar[index - back]]
        for back in range(30, 90)
        if index - back >= 0 and calendar[index - back] in volume
    ]
    if len(recent_volume) < 20 or len(older_volume) < 40:
        return None
    recent_mean = sum(recent_volume) / len(recent_volume)
    older_mean = sum(older_volume) / len(older_volume)
    if recent_mean <= 0 or older_mean <= 0:
        return None

    daily = [
        math.log(series[calendar[index - back]] / series[calendar[index - back - 1]])
        for back in range(30)
        if calendar[index - back] in series
        and calendar[index - back - 1] in series
        and series[calendar[index - back - 1]] > 0
    ]
    if len(daily) < 20:
        return None
    mean_daily = sum(daily) / len(daily)
    volatility = math.sqrt(
        sum((value - mean_daily) ** 2 for value in daily) / (len(daily) - 1)
    )

    momentum30 = math.log(now / past30)
    # A constant-priced asset has no meaningful risk-adjusted momentum: the ratio is undefined,
    # not enormous. Guarding on `> 0` is not enough, because floating-point noise leaves a
    # genuinely flat series with a volatility around 1e-16, which turned a degenerate asset into
    # a score of ~1e15 and a permanent rank of #1 on this signal. Spearman ranks absorbed the
    # magnitude, so the published ICs are unaffected -- but the RANKING was still wrong, and a
    # future Pearson-based reader of this feature would have been destroyed by it.
    VOLATILITY_FLOOR = 1e-9
    return {        "momento_30d": momentum30,
        "momento_90d": math.log(now / past90),
        "momento_180d": math.log(now / past180),
        # Momentum normalised by its own volatility: the standard risk-adjusted version.
        "momento_30d_ajustado_vol": (
            momentum30 / volatility if volatility > VOLATILITY_FLOOR else 0.0
        ),
        # Volume GROWTH, cross-sectionally: which assets are attracting money right now.
        "crecimiento_volumen": math.log(recent_mean / older_mean),
        # Pure volatility rank, to see whether the cross-section simply pays for risk.
        "volatilidad_30d": volatility,
        # Money traded, as a size/liquidity control rather than a signal.
        "volumen_medio_30d": math.log(recent_mean),
        # How long the pair has been listed, in log days. This was measured as the second
        # strongest signal (t = +4.6) but lived only in an ad-hoc script, so the committed
        # module reproduced five signals while the report claimed six. Implemented here so
        # the documented result is the one this code produces.
        # Causal: the first observed close is in the past of any date that clears the warmup.
        "antiguedad_listado_log": math.log(1.0 + listing_age_days(calendar, symbol, series, date)),
    }


@dataclass
class ICResult:
    signal: str
    periods: int
    mean_ic: float
    median_ic: float
    sd_ic: float
    t_stat: float
    positive_periods: int
    asset_periods: int

    def reaches_two(self) -> bool:
        return abs(self.t_stat) >= 2.0


def main(argv: list[str] | None = None) -> int:
    name = (argv or [DEFAULT_UNIVERSE])[0]
    if name not in UNIVERSES:
        print(f"universo desconocido: {name}. Opciones: {', '.join(UNIVERSES)}")
        return 2
    calendar, closes, volumes = load_universe(name)
    print(f"fichero: {UNIVERSES[name]}")

    names = sorted(closes)
    per_signal: dict[str, list[float]] = {}
    per_signal_counts: dict[str, int] = {}

    index = WARMUP
    periods = 0
    while index + REBALANCE_DAYS < len(calendar):
        date = calendar[index]
        ahead = calendar[index + REBALANCE_DAYS]
        rows: list[tuple[dict[str, float], float]] = []
        for symbol in names:
            values = signals_for(closes, volumes, calendar, index, symbol)
            if values is None:
                continue
            series = closes[symbol]
            entry, exit_price = series.get(date), series.get(ahead)
            if entry is None or entry <= 0:
                continue
            if exit_price is None:
                # Stopped reporting: carry the last observed close inside the period.
                exit_price = next(
                    (
                        series[calendar[back]]
                        for back in range(index + REBALANCE_DAYS - 1, index - 1, -1)
                        if calendar[back] in series
                    ),
                    entry,
                )
            rows.append((values, math.log(exit_price / entry)))

        if len(rows) >= 8:
            periods += 1
            for signal in rows[0][0]:
                pairs = [(values[signal], forward) for values, forward in rows]
                ic = spearman(pairs)
                if ic is not None:
                    per_signal.setdefault(signal, []).append(ic)
                    per_signal_counts[signal] = per_signal_counts.get(signal, 0) + len(pairs)
        index += REBALANCE_DAYS

    results: list[ICResult] = []
    for signal, ics in per_signal.items():
        mean = sum(ics) / len(ics)
        sd = math.sqrt(sum((value - mean) ** 2 for value in ics) / (len(ics) - 1))
        t_stat = mean / (sd / math.sqrt(len(ics))) if sd > 0 else 0.0
        results.append(
            ICResult(
                signal=signal,
                periods=len(ics),
                mean_ic=mean,
                median_ic=sorted(ics)[len(ics) // 2],
                sd_ic=sd,
                t_stat=t_stat,
                positive_periods=sum(1 for value in ics if value > 0),
                asset_periods=per_signal_counts[signal],
            )
        )
    results.sort(key=lambda item: -abs(item.t_stat))

    print(f"universo {len(names)} pares  ·  periodos de {REBALANCE_DAYS}d no solapados")
    print(f"periodos utilizables: {periods}  ·  observaciones activo-periodo por senal: "
          f"~{results[0].asset_periods if results else 0}")
    # The caveat must describe the universe actually loaded. "Hand-picked" was true of the
    # narrow 30-pair file and false of the full-alphabet one, where the real residual bias is
    # that pairs Binance has since delisted are absent from the listing the file was built
    # from. Stating the wrong reservation is worse than stating none: it points the reader's
    # scepticism at the wrong thing.
    if name == "wide":
        print(
            "SESGO DE SUPERVIVENCIA no eliminado: faltan los pares ya deslistados por Binance\n"
            "(el fichero se construyo desde el listado vigente), sesga AL ALZA. El universo NO\n"
            "esta elegido a mano: es el alfabeto completo.\n"
        )
    else:
        print("SESGO DE SUPERVIVENCIA no eliminado: universo elegido a mano, sesga AL ALZA.\n")
    print(
        f"{'senal':<28} {'IC medio':>9} {'IC mediana':>11} {'sd':>7} "
        f"{'t':>7} {'periodos+':>10} {'obs':>6}"
    )
    for item in results:
        print(
            f"{item.signal:<28} {item.mean_ic:>+9.4f} {item.median_ic:>+11.4f} "
            f"{item.sd_ic:>7.3f} {item.t_stat:>+7.2f} "
            f"{item.positive_periods:>4}/{item.periods:<5} {item.asset_periods:>6}"
        )

    strong = [item for item in results if item.reaches_two()]
    print(f"\n  senales con |t| >= 2.0: {len(strong)} de {len(results)}")
    for item in strong:
        direction = "mayor es mejor" if item.mean_ic > 0 else "menor es mejor"
        print(
            f"    {item.signal}: IC {item.mean_ic:+.4f}, t={item.t_stat:+.2f}, "
            f"{item.positive_periods}/{item.periods} periodos positivos ({direction})"
        )
    if not strong:
        print(
            "    ninguna. Con ~1.800 observaciones activo-periodo tampoco aparece señal\n"
            "    transversal, lo que cierra la hipotesis de los inputs con los datos a mano."
        )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "universe": names,
                "rebalance_days": REBALANCE_DAYS,
                "periods": periods,
                "survivorship_bias": "not eliminated; hand-picked universe biases results UP",
                "results": [asdict(item) for item in results],
                "signals_reaching_two_sigma": [item.signal for item in strong],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\ninforme: {REPORT}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
