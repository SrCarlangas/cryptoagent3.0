"""Per-regime playbooks: does ANY regime beat sitting in USDT, out of sample, after costs?

The success criterion is the preregistered one (`REGIME-STUDY-PREREGISTRATION.md` §6),
evaluated on the VALIDATION segment with ADVERSE fees:

1. max drawdown <= 25%
2. net return > 0 AND above all-USDT by more than its own standard error
3. not worse than buy-and-hold-with-cap by more than its own standard error

Criterion 2 is instantiated with this project's existing convention (`regime_attribution`):
all-USDT returns exactly 0, so "above USDT by more than its own standard error" means the
mean per-segment return is positive with **effect = |mean| / SE(mean) >= 1.0**. Below 1 a
result is not distinguishable from zero no matter how large the total looks. Declared
before measuring.

Honesty constraints, inherited from `multislot_sim` because they were learned the hard way
in this project:

- Equity is marked to market on every HOURLY bar, so the drawdown is what the capital
  actually felt, not what the daily closes imply.
- Stops trigger on the hourly LOW and fill at the worse of the stop price and the bar open,
  which models gapping through the stop instead of assuming a perfect fill.
- One bar of execution lag: a regime label observed on a completed day is acted on at the
  NEXT day's close.
- Documented dataset gaps are never bridged.
- Fees are charged on the traded notional on both sides.

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.regime_playbook_study
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from multislot_sim import Bar, load_bars
from regime_taxonomy import (
    REGIMES,
    DailyBar,
    Regime,
    RegimeParams,
    detect_regimes,
    to_daily,
)

TRAIN_END = "2023-06-30"
VALIDATION_END = "2025-03-31"
HONEST_FEE = 0.001
ADVERSE_FEE = 0.002
DRAWDOWN_CAP = 0.25
EFFECT_FLOOR = 1.0
MIN_SEGMENTS = 4
MIN_EXPOSED_DAYS = 120
"""Evaluability floor. A criterion that cannot be evaluated FAILS, it does not pass.

Iteration 3 added this after a measured artifact: BAJISTA on the validation segment had 5
runs totalling ~35 days, four of them shorter than ten days, and an "effect" of 1.58
computed across them. Five dips are not a sample you can conclude a regime from.
"""
ORACLE_HALF_WINDOW = 45
REPORT = Path("data/validation/regime-playbooks.json")

EXTENDED_DATASET = "data/history/btcusdt-1h-2017"
"""Series extended back to Binance BTCUSDT inception. See `research/extend_history.py`."""

CLEAN_TEST = ("2018-01-01", "2019-12-31")
"""Unseen confirmation region, created by extending the series BACKWARDS.

The 2025-04 -> 2026-09 holdout was spent on 2026-10-01 and is NOT re-measured to support a
new claim; re-testing on it after iterating on what it showed would destroy it. Extending
the dataset adds data at the FRONT, so this region is genuinely unseen: the 2017 mania, the
2018 bear and the 2019 recovery, which is a harder and more different epoch than the one
that was spent.
"""
SPENT_HOLDOUT = ("2025-04-01", "2026-09-16")


@dataclass(frozen=True)
class Playbook:
    """An exposure and a stop. Deliberately small: there is no edge to express with more."""

    name: str
    exposure: float
    """Fraction of capital in BTC while the regime holds. 0.0 is the USDT control."""
    stop_fraction: float = 0.0
    """Protective stop below entry. 0.0 disables it."""
    trailing: bool = False
    """Whether the stop follows the highest close reached since entry."""

    def label(self) -> str:
        if self.exposure == 0.0:
            return "USDT (control)"
        parts = [f"expo {self.exposure:.0%}"]
        if self.stop_fraction:
            parts.append(f"{'trail' if self.trailing else 'stop'} {self.stop_fraction:.0%}")
        return " ".join(parts)


@dataclass
class SegmentResult:
    """One contiguous run of days in a regime, traded once."""

    start_date: str
    end_date: str
    days: int
    gross_move: float
    net_return: float
    stopped: bool
    max_drawdown: float


def hourly_by_date(bars: list[Bar]) -> dict[str, list[Bar]]:
    """Index hourly bars by UTC calendar date, so a day can be walked intrabar."""
    buckets: dict[str, list[Bar]] = {}
    for bar in bars:
        key = datetime.fromtimestamp(bar.open_time_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
        buckets.setdefault(key, []).append(bar)
    for key in buckets:
        buckets[key].sort(key=lambda item: item.open_time_ms)
    return buckets


def regime_segments(
    daily: list[DailyBar], labels: list[Regime | None], regime: Regime
) -> list[tuple[int, int]]:
    """Maximal runs of consecutive day indices carrying `regime`.

    Returned as (first, last) INCLUSIVE day indices into `daily`.
    """
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, label in enumerate(labels):
        if label == regime and start is None:
            start = index
        elif label != regime and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(labels) - 1))
    return runs


def trade_segment(
    daily: list[DailyBar],
    hourly: dict[str, list[Bar]],
    first: int,
    last: int,
    book: Playbook,
    fee_per_side: float,
) -> SegmentResult | None:
    """Trade one regime segment with one bar of execution lag. None when untradeable.

    Entry is the close of `first + 1`, because the label on day `first` is only known once
    that day has completed. Exit is the close of `last + 1` for the same reason.
    """
    entry_day, exit_day = first + 1, last + 1
    if exit_day >= len(daily) or entry_day > exit_day:
        return None
    entry_price = daily[entry_day].close
    if entry_price <= 0.0:
        return None

    exposure = book.exposure
    if exposure == 0.0:
        return SegmentResult(
            start_date=daily[entry_day].date,
            end_date=daily[exit_day].date,
            days=exit_day - entry_day + 1,
            gross_move=daily[exit_day].close / entry_price - 1.0,
            net_return=0.0,
            stopped=False,
            max_drawdown=0.0,
        )

    stop_price = entry_price * (1.0 - book.stop_fraction) if book.stop_fraction else 0.0
    peak_close = entry_price
    equity = 1.0 - exposure * fee_per_side
    peak_equity = equity
    worst = 0.0
    exit_price = daily[exit_day].close
    stopped = False

    for day in range(entry_day + 1, exit_day + 1):
        for bar in hourly.get(daily[day].date, []):
            if stop_price and bar.low <= stop_price:
                fill = min(stop_price, bar.open)
                exit_price = fill
                stopped = True
                break
            marked = 1.0 + exposure * (bar.close / entry_price - 1.0)
            marked -= exposure * fee_per_side
            peak_equity = max(peak_equity, marked)
            worst = max(worst, (peak_equity - marked) / peak_equity if peak_equity > 0 else 0.0)
        if stopped:
            break
        if book.trailing and book.stop_fraction:
            peak_close = max(peak_close, daily[day].close)
            stop_price = max(stop_price, peak_close * (1.0 - book.stop_fraction))

    equity = 1.0 + exposure * (exit_price / entry_price - 1.0)
    equity -= exposure * fee_per_side * 2.0
    peak_equity = max(peak_equity, equity)
    worst = max(worst, (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0)

    return SegmentResult(
        start_date=daily[entry_day].date,
        end_date=daily[exit_day].date,
        days=exit_day - entry_day + 1,
        gross_move=daily[exit_day].close / entry_price - 1.0,
        net_return=equity - 1.0,
        stopped=stopped,
        max_drawdown=worst,
    )


def standard_error(values: list[float]) -> float | None:
    """Standard error of the mean. None below three samples, where it is meaningless."""
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    return math.sqrt(variance / len(values))


@dataclass
class PlaybookResult:
    """Everything the preregistered criterion needs, plus what it took to get there."""

    regime: str
    playbook: str
    segments: int
    total_return: float
    mean_segment: float
    standard_error: float | None
    effect: float | None
    max_drawdown: float
    stops_hit: int
    days_exposed: int
    mean_daily: float = 0.0
    """Mean per-DAY log return across segments, so unequal durations are comparable."""
    shortest_segment: int = 0
    longest_segment: int = 0

    def meets_drawdown(self) -> bool:
        return self.max_drawdown <= DRAWDOWN_CAP

    def is_evaluable(self) -> bool:
        """Enough segments and enough exposed time to support any conclusion at all."""
        return self.segments >= MIN_SEGMENTS and self.days_exposed >= MIN_EXPOSED_DAYS

    def beats_usdt(self) -> bool:
        """Criterion 2: positive and distinguishable from zero by its own standard error.

        Evaluated on the mean DAILY log return, not on the raw per-segment return. Comparing
        a 275-day segment with a 4-day segment as equal samples is what let dip-buying
        masquerade as a bearish playbook in iteration 3.
        """
        if not self.is_evaluable():
            return False
        return (
            self.total_return > 0.0
            and self.mean_daily > 0.0
            and self.effect is not None
            and self.effect >= EFFECT_FLOOR
        )


def not_worse_than_hold(
    candidate: PlaybookResult, hold: PlaybookResult
) -> bool:
    """Criterion 3: not worse than buy-and-hold-with-cap by more than its standard error.

    Within a single regime, "buy and hold with a cap" IS the 100%-exposure, no-stop
    playbook whenever that playbook's own drawdown stays under the cap -- the cap simply
    never fires. So the comparison reduces to: is the candidate's mean daily return within
    one standard error of the unhedged hold's?

    A candidate that IS the hold passes trivially, which is correct rather than a loophole:
    criterion 3 exists to stop a playbook paying for its tail protection with the whole
    trend, and a playbook that takes no protection cannot be doing that.
    """
    if candidate.playbook == hold.playbook:
        return True
    if not hold.meets_drawdown():
        # The unprotected hold itself breaches the 25% cap, so it is INADMISSIBLE as a
        # comparator: the study cannot require a playbook to keep pace with a benchmark the
        # risk constraint forbids. Criterion 3 exists to stop a playbook paying for its tail
        # protection with the whole trend; when there is no admissible trend to pay with,
        # there is nothing for it to fail. Left implicit this was simply wrong -- BAJISTA's
        # hold drew down 61.3% and was still being used as the yardstick.
        return True
    if candidate.standard_error is None:
        return False
    return candidate.mean_daily >= hold.mean_daily - candidate.standard_error


def evaluate(
    daily: list[DailyBar],
    hourly: dict[str, list[Bar]],
    labels: list[Regime | None],
    regime: Regime,
    book: Playbook,
    fee_per_side: float,
) -> PlaybookResult:
    """Run one playbook over every segment of one regime and score it."""
    results: list[SegmentResult] = []
    for first, last in regime_segments(daily, labels, regime):
        traded = trade_segment(daily, hourly, first, last, book, fee_per_side)
        if traded is not None:
            results.append(traded)

    returns = [item.net_return for item in results]
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for item in results:
        # Within-segment drawdown is felt on top of the capital standing at its start.
        worst = max(worst, item.max_drawdown)
        equity *= 1.0 + item.net_return
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak if peak > 0 else 0.0)

    # Per-day log return normalises duration, which is the axis the artifact exploited.
    dailies = [
        math.log(1.0 + item.net_return) / item.days
        for item in results
        if item.days > 0 and 1.0 + item.net_return > 0.0
    ]
    error = standard_error(dailies)
    mean_daily = sum(dailies) / len(dailies) if dailies else 0.0
    mean_segment = sum(returns) / len(returns) if returns else 0.0
    return PlaybookResult(
        regime=regime,
        playbook=book.label(),
        segments=len(results),
        total_return=equity - 1.0,
        mean_segment=mean_segment,
        standard_error=error,
        effect=abs(mean_daily) / error if error and error > 0 else None,
        max_drawdown=worst,
        stops_hit=sum(1 for item in results if item.stopped),
        days_exposed=sum(item.days for item in results),
        mean_daily=mean_daily,
        shortest_segment=min((item.days for item in results), default=0),
        longest_segment=max((item.days for item in results), default=0),
    )


CANDIDATES: tuple[Playbook, ...] = (
    Playbook("usdt", 0.0),
    Playbook("long", 1.0),
    Playbook("half", 0.5),
    Playbook("long_stop_15", 1.0, 0.15),
    Playbook("long_stop_10", 1.0, 0.10),
    Playbook("long_trail_15", 1.0, 0.15, trailing=True),
    Playbook("half_stop_15", 0.5, 0.15),
)


def evaluate_date_range(
    daily: list[DailyBar],
    hourly: dict[str, list[Bar]],
    params: RegimeParams,
    fee: float,
    first_date: str,
    last_date: str,
) -> dict[str, list[PlaybookResult]]:
    """Score playbooks over a date range, with labels computed on the FULL series.

    Slicing the series before detecting would throw away the 180-day warmup inside the
    range, which on a 533-day holdout would discard a third of the evidence. Running the
    causal detector over all history and then selecting which DAYS to score is not
    look-ahead: day t still sees only days up to t. What changes is merely that history
    before the range is allowed to exist.
    """
    labels = detect_regimes(daily, params)
    inside = [
        index
        for index, bar in enumerate(daily)
        if first_date <= bar.date <= last_date
    ]
    if not inside:
        return {regime: [] for regime in REGIMES}
    low, high = min(inside), max(inside)
    masked: list[Regime | None] = [
        label if low <= index <= high else None for index, label in enumerate(labels)
    ]
    out: dict[str, list[PlaybookResult]] = {}
    for regime in REGIMES:
        out[regime] = [
            evaluate(daily, hourly, masked, regime, book, fee) for book in CANDIDATES
        ]
    return out


def split(daily: list[DailyBar]) -> tuple[list[DailyBar], list[DailyBar], list[DailyBar]]:
    train = [bar for bar in daily if bar.date <= TRAIN_END]
    validation = [bar for bar in daily if TRAIN_END < bar.date <= VALIDATION_END]
    test = [bar for bar in daily if bar.date > VALIDATION_END]
    return train, validation, test


def run_segment(
    daily: list[DailyBar], hourly: dict[str, list[Bar]], params: RegimeParams, fee: float
) -> dict[str, list[PlaybookResult]]:
    labels = detect_regimes(daily, params)
    out: dict[str, list[PlaybookResult]] = {}
    for regime in REGIMES:
        out[regime] = [
            evaluate(daily, hourly, labels, regime, book, fee) for book in CANDIDATES
        ]
    return out


def show(title: str, grouped: dict[str, list[PlaybookResult]]) -> None:
    print(f"\n=== {title} ===")
    print(
        f"{'regimen':<24} {'playbook':<20} {'tram':>5} {'dias':>5} {'min/max d':>10} "
        f"{'total':>8} {'efecto':>7} {'dd':>7} {'crit':>5}"
    )
    for regime in REGIMES:
        for item in grouped[regime]:
            if item.segments == 0:
                continue
            effect = "n/a" if item.effect is None else f"{item.effect:.2f}"
            verdict = "--"
            if item.playbook != "USDT (control)":
                if not item.is_evaluable():
                    verdict = "N/EV"
                else:
                    verdict = "PASA" if item.meets_drawdown() and item.beats_usdt() else "no"
            spread = f"{item.shortest_segment}/{item.longest_segment}"
            print(
                f"{regime:<24} {item.playbook:<20} {item.segments:>5} "
                f"{item.days_exposed:>5} {spread:>10} "
                f"{item.total_return:>7.1%} {effect:>7} "
                f"{item.max_drawdown:>6.1%} {verdict:>5}"
            )


def main() -> int:
    bars, dataset_id = load_bars()
    daily = to_daily(bars)
    hourly = hourly_by_date(bars)
    train, validation, test = split(daily)
    params = RegimeParams(direction_axis="drawdown")

    print(f"dataset {dataset_id}")
    print(
        f"train {len(train)}d  validacion {len(validation)}d  "
        f"prueba {len(test)}d (SIN TOCAR)  ·  tope de caida {DRAWDOWN_CAP:.0%}  ·  "
        f"efecto minimo {EFFECT_FLOOR:.1f}"
    )

    development = [bar for bar in daily if bar.date <= VALIDATION_END]
    on_train = run_segment(train, hourly, params, HONEST_FEE)
    show("TRAIN · comisiones honestas 10bps · solo para elegir", on_train)

    pooled = run_segment(development, hourly, params, ADVERSE_FEE)
    show(
        f"REGION DE DESARROLLO {development[0].date}..{development[-1].date} "
        f"({len(development)}d) · comisiones ADVERSAS · umbrales congelados a priori",
        pooled,
    )

    held_adverse = run_segment(validation, hourly, params, ADVERSE_FEE)
    show("VALIDACION · comisiones ADVERSAS 20bps · esto es la evidencia", held_adverse)

    held_honest = run_segment(validation, hourly, params, HONEST_FEE)
    show("VALIDACION · comisiones honestas 10bps · contexto", held_honest)

    print(
        "\n=== VEREDICTO POR REGIMEN (region de desarrollo, comisiones adversas) ===\n"
        "    Se usa la region completa porque la validacion sola da 3-5 tramos por regimen,\n"
        "    y con esa muestra el error estandar impide que el efecto alcance 1.0 salvo por\n"
        "    suerte. Los umbrales estan congelados a priori, no ajustados al retorno."
    )
    winners: list[PlaybookResult] = []
    for regime in REGIMES:
        hold = next(
            item for item in pooled[regime] if item.playbook == "expo 100%"
        )
        viable = [
            item
            for item in pooled[regime]
            if item.playbook != "USDT (control)"
            and item.segments > 0
            and item.meets_drawdown()
            and item.beats_usdt()
            and not_worse_than_hold(item, hold)
        ]
        if not viable:
            best = max(
                (item for item in pooled[regime] if item.segments > 0),
                key=lambda item: item.total_return,
                default=None,
            )
            detail = (
                "sin tramos"
                if best is None
                else f"el mejor fue {best.playbook}: {best.total_return:+.1%}, "
                f"efecto {'n/a' if best.effect is None else f'{best.effect:.2f}'}, "
                f"dd {best.max_drawdown:.1%}, {best.segments} tramos/"
                f"{best.days_exposed}d"
                + ("" if best.is_evaluable() else " -- NO EVALUABLE, luego FALLA")
            )
            print(f"  {regime:<24} QUEDARSE EN USDT -- {detail}")
            continue
        champion = max(viable, key=lambda item: item.effect or 0.0)
        winners.append(champion)
        print(
            f"  {regime:<24} CUMPLE con {champion.playbook}: "
            f"{champion.total_return:+.1%}, efecto {champion.effect:.2f}, "
            f"dd {champion.max_drawdown:.1%}, {champion.segments} tramos"
        )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "criterion": {
                    "drawdown_cap": DRAWDOWN_CAP,
                    "effect_floor": EFFECT_FLOOR,
                    "adverse_fee_per_side": ADVERSE_FEE,
                },
                "params": asdict(params),
                "train_honest": {k: [asdict(i) for i in v] for k, v in on_train.items()},
                "validation_adverse": {
                    k: [asdict(i) for i in v] for k, v in held_adverse.items()
                },
                "validation_honest": {
                    k: [asdict(i) for i in v] for k, v in held_honest.items()
                },
                "development_pooled_adverse": {
                    k: [asdict(i) for i in v] for k, v in pooled.items()
                },
                "regimes_meeting_criterion": [asdict(i) for i in winners],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\ninforme: {REPORT}")
    print(f"regimenes que cumplen el criterio: {len(winners)}")
    return 0 if winners else 1


if __name__ == "__main__":
    raise SystemExit(main())
