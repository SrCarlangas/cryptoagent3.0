"""Walk-forward search for a per-regime playbook: does anything beat sitting in USDT?

Takes the regime as an argument so BAJISTA and ALCISTA are answered by the SAME code. Running
two separate scripts would let the two answers drift apart on a detail nobody re-reads, which
is how this project previously compared runs that did not share an execution geometry.

Why walk-forward rather than one more holdout: there is no unspent region left. 2017-08 to
2019-12 was spent as the regime study's clean test, 2020-01 to 2025-03 is the selection
region, and 2025-04 to 2026-09 was spent as the first holdout. A fourth "clean" measurement
on any of them would be a measurement on data already seen.

Expanding walk-forward answers the question that is still answerable: **does CHOOSING a
playbook from past data generalise to the year that follows?** Every measurement here is out
of sample relative to the data that produced the choice, fold by fold, which is the property
a single holdout buys and which this project's own `exposure_diagnosis.temporal_out_of_sample`
already uses.

Reservation that must travel with every number below: the author has already seen most of
this history across earlier iterations, so these folds are weaker evidence than a genuinely
untouched region would have been. They are not a substitute for one; they are what remains.

Purge: a regime segment straddling a fold boundary is DROPPED rather than split. Splitting it
would let the selection fold see part of the outcome the test fold is scored on, which is the
same leakage the history index already had to fix once.

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.bajista_walkforward
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from multislot_sim import Bar, load_bars
from regime_playbook_study import (
    ADVERSE_FEE,
    CANDIDATES,
    DRAWDOWN_CAP,
    EFFECT_FLOOR,
    EXTENDED_DATASET,
    MIN_SEGMENTS,
    Playbook,
    SegmentResult,
    hourly_by_date,
    regime_segments,
    standard_error,
    trade_segment,
)
from regime_taxonomy import REGIMES, DailyBar, Regime, RegimeParams, detect_regimes, to_daily

FOLD_YEARS = 1
MIN_TRAIN_DAYS = 540
"""Enough history to hold at least one full bear episode before the first choice."""
EMBARGO_DAYS = 30
"""Matches the detector's minimum dwell, so no chosen segment can straddle a boundary."""
REPORT_TEMPLATE = "data/validation/{regime}-walkforward.json"


@dataclass
class FoldOutcome:
    """One selection-then-measurement pair. Only `test_*` fields are evidence."""

    fold: int
    train_end: str
    test_end: str
    chosen: str
    train_segments: int
    train_return: float
    test_segments: int
    test_return: float
    test_drawdown: float
    usdt_return: float = 0.0

    def beat_usdt(self) -> bool:
        return self.test_return > 0.0

    def respected_cap(self) -> bool:
        return self.test_drawdown <= DRAWDOWN_CAP


def _score(results: list[SegmentResult]) -> tuple[float, float, float | None]:
    """Total return, max drawdown and the per-day effect, over a list of traded segments."""
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for item in results:
        worst = max(worst, item.max_drawdown)
        equity *= 1.0 + item.net_return
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak if peak > 0 else 0.0)
    dailies = [
        math.log(1.0 + item.net_return) / item.days
        for item in results
        if item.days > 0 and 1.0 + item.net_return > 0.0
    ]
    error = standard_error(dailies)
    mean = sum(dailies) / len(dailies) if dailies else 0.0
    effect = abs(mean) / error if error and error > 0 else None
    return equity - 1.0, worst, effect


def _run(
    regime: Regime,
    daily: list[DailyBar],
    hourly: dict[str, list[Bar]],
    labels: list[Regime | None],
    book: Playbook,
    first: str,
    last: str,
) -> list[SegmentResult]:
    """Trade every regime segment that lies ENTIRELY inside [first, last]."""
    out: list[SegmentResult] = []
    for start, end in regime_segments(daily, labels, regime):
        # Purge: the segment must be wholly inside the window, including its exit bar.
        if daily[start].date < first or end + 1 >= len(daily) or daily[end + 1].date > last:
            continue
        traded = trade_segment(daily, hourly, start, end, book, ADVERSE_FEE)
        if traded is not None:
            out.append(traded)
    return out


def _select(
    regime: Regime,
    daily: list[DailyBar],
    hourly: dict[str, list[Bar]],
    labels: list[Regime | None],
    first: str,
    last: str,
) -> tuple[Playbook, int, float]:
    """Pick the playbook with the best per-day effect on the TRAIN window.

    USDT is the default and it wins by default: a long playbook has to clear the drawdown
    cap, be positive, and reach the pre-declared effect floor to displace it. That ordering
    is the point -- doing nothing does not have to earn its place.
    """
    usdt = next(book for book in CANDIDATES if book.exposure == 0.0)
    best: tuple[Playbook, int, float] = (usdt, 0, 0.0)
    best_effect = 0.0
    for book in CANDIDATES:
        if book.exposure == 0.0:
            continue
        results = _run(regime, daily, hourly, labels, book, first, last)
        if len(results) < MIN_SEGMENTS:
            continue
        total, drawdown, effect = _score(results)
        if effect is None or drawdown > DRAWDOWN_CAP or total <= 0.0:
            continue
        if effect >= EFFECT_FLOOR and effect > best_effect:
            best_effect = effect
            best = (book, len(results), total)
    return best


def folds(daily: list[DailyBar]) -> list[tuple[str, str]]:
    """Expanding (train_end, test_end) pairs with a one-year out-of-sample step."""
    first = datetime.strptime(daily[0].date, "%Y-%m-%d").replace(tzinfo=UTC)
    final = datetime.strptime(daily[-1].date, "%Y-%m-%d").replace(tzinfo=UTC)
    out: list[tuple[str, str]] = []
    train_end = first + timedelta(days=MIN_TRAIN_DAYS)
    while True:
        test_end = train_end + timedelta(days=365 * FOLD_YEARS)
        if test_end > final:
            break
        out.append((train_end.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d")))
        train_end = test_end
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward playbook search per regime.")
    parser.add_argument("--regime", default="BAJISTA", choices=list(REGIMES))
    args = parser.parse_args()
    regime: Regime = args.regime

    bars, dataset_id = load_bars(EXTENDED_DATASET)
    daily = to_daily(bars)
    hourly = hourly_by_date(bars)
    params = RegimeParams(direction_axis="drawdown")
    labels = detect_regimes(daily, params)

    print(f"dataset {dataset_id}")
    print(f"dias {len(daily)}  {daily[0].date} .. {daily[-1].date}")
    print(
        f"regimen {regime}  ·  comisiones adversas {ADVERSE_FEE * 10000:.0f}bps  ·  "
        f"techo de caida {DRAWDOWN_CAP:.0%}  ·  efecto minimo {EFFECT_FLOOR:.1f}  ·  "
        f"embargo {EMBARGO_DAYS}d"
    )

    outcomes: list[FoldOutcome] = []
    for index, (train_end, test_end) in enumerate(folds(daily), start=1):
        embargo = (
            datetime.strptime(train_end, "%Y-%m-%d").replace(tzinfo=UTC)
            + timedelta(days=EMBARGO_DAYS)
        ).strftime("%Y-%m-%d")
        book, train_segments, train_return = _select(
            regime, daily, hourly, labels, daily[0].date, train_end
        )
        tested = _run(regime, daily, hourly, labels, book, embargo, test_end)
        total, drawdown, _ = _score(tested)
        outcomes.append(
            FoldOutcome(
                fold=index,
                train_end=train_end,
                test_end=test_end,
                chosen=book.label(),
                train_segments=train_segments,
                train_return=train_return,
                test_segments=len(tested),
                test_return=total,
                test_drawdown=drawdown,
            )
        )

    print(f"\n{'fold':>4} {'train hasta':<12} {'test hasta':<12} {'elegido':<22} "
          f"{'tram':>5} {'test':>8} {'dd':>7} {'vs USDT':>8}")
    for item in outcomes:
        verdict = "gana" if item.beat_usdt() else ("empata" if item.test_segments == 0 else "pierde")
        print(
            f"{item.fold:>4} {item.train_end:<12} {item.test_end:<12} {item.chosen:<22} "
            f"{item.test_segments:>5} {item.test_return:>7.1%} {item.test_drawdown:>6.1%} "
            f"{verdict:>8}"
        )

    traded = [item for item in outcomes if item.test_segments > 0 and item.chosen != "USDT (control)"]
    chose_usdt = [item for item in outcomes if item.chosen == "USDT (control)"]
    wins = [item for item in traded if item.beat_usdt()]

    print(f"\n  folds totales: {len(outcomes)}")
    print(f"  folds donde la seleccion eligio USDT (nada paso el suelo en train): {len(chose_usdt)}")
    print(f"  folds donde eligio operar: {len(traded)}")
    if traded:
        print(f"  de esos, batieron a USDT fuera de muestra: {len(wins)} de {len(traded)}")
        compounded = 1.0
        for item in traded:
            compounded *= 1.0 + item.test_return
        print(f"  retorno compuesto de las elecciones operadas: {compounded - 1.0:+.1%}")
        print(f"  peor caida fuera de muestra: {max(item.test_drawdown for item in traded):.1%}")

    # The simple alternative, applied blindly to every fold, for contrast.
    print("\n  contraste: cada playbook aplicado a TODOS los folds sin seleccionar")
    print(f"    {'playbook':<22} {'tram':>5} {'total':>9} {'dd':>7} {'efecto':>12}")
    for book in CANDIDATES:
        pooled: list[SegmentResult] = []
        for train_end, test_end in folds(daily):
            embargo = (
                datetime.strptime(train_end, "%Y-%m-%d").replace(tzinfo=UTC)
                + timedelta(days=EMBARGO_DAYS)
            ).strftime("%Y-%m-%d")
            pooled.extend(_run(regime, daily, hourly, labels, book, embargo, test_end))
        total, drawdown, effect = _score(pooled)
        shown = "n/a" if effect is None else f"{effect:.2f}"
        marker = "  <- control" if book.exposure == 0.0 else ""
        print(
            f"    {book.label():<22} {len(pooled):>5} {total:>8.1%} {drawdown:>6.1%} "
            f"efecto {shown:>5}{marker}"
        )

    report = Path(REPORT_TEMPLATE.format(regime=regime.lower()))
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "regime": regime,
                "criterion": {
                    "drawdown_cap": DRAWDOWN_CAP,
                    "effect_floor": EFFECT_FLOOR,
                    "min_segments": MIN_SEGMENTS,
                    "adverse_fee_per_side": ADVERSE_FEE,
                    "embargo_days": EMBARGO_DAYS,
                },
                "params": asdict(params),
                "folds": [asdict(item) for item in outcomes],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\ninforme: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
