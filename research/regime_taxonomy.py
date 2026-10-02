"""Regime taxonomy for BTC/USDT spot: a causal detector, and an oracle that scores it.

Design is frozen in `research/REGIME-STUDY-PREREGISTRATION.md`. Two things in here are
easy to corrupt and are therefore separated by construction:

- `detect_regimes` is **causal**. Day t sees closed daily bars up to and including t and
  nothing else. This is what a playbook is allowed to read.
- `oracle_regimes` is **acausal on purpose**: it uses centered windows, so it sees the
  future. It exists only to answer "how late was the causal detector, and how often did
  it cry wolf". No entry, exit, stop or sizing rule may read it, and
  `tests/test_regime_taxonomy.py` asserts that the oracle is never reachable from the
  detector's output.

Regimes are described, not predicted. The project has already measured that direction is
not forecastable at affordable horizons (0 of 20 signal/horizon pairs reach one standard
error, `data/validation/exposure-diagnosis.md` section D2), so a label here is a statement
about the path that has already happened, never a claim about the next one.

Pure Python by project convention. The daily series is ~2450 points; speed is irrelevant
and clarity is not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from multislot_sim import Bar

Regime = Literal["ALCISTA", "BAJISTA", "LATERAL", "ALTA_VOL_SIN_DIRECCION"]

REGIMES: tuple[Regime, ...] = ("ALCISTA", "BAJISTA", "LATERAL", "ALTA_VOL_SIN_DIRECCION")

HOURS_PER_DAY = 24
MIN_WINDOW_COVERAGE = 0.95
"""Fraction of a lookback's calendar span that must be present as complete daily bars.

Matches `multislot_sim.MIN_LOOKBACK_COVERAGE`, and the agreement is the point. An earlier
revision demanded an UNBROKEN run of `span + 1` daily bars instead, and that silently
deleted 723 days -- all of 2020 and 2021, including the COVID crash and the entire 2021
bull market, 38% of the development region. The dataset's 15 documented gaps are 1-5
MISSING HOURS, mostly in 2020-2021; each one reset the streak, and with a gap every two or
three months the streak never reached 181, so the first labelled day landed in March 2022.

The visible symptom was a conclusion about the market ("LATERAL never occurs in 2020-2022")
that was really a statement about the instrument. Withholding a feature across a real gap
is correct; withholding half the history because one hour was missing six months earlier is
not.
"""
# A calendar day missing more than one hour is not a trustworthy daily bar. The dataset's
# 15 documented gaps are all 1-5 hours, so this keeps the handful of affected days out of
# the feature windows instead of silently bridging them.
MIN_HOURS_FOR_DAILY_BAR = 23


@dataclass(frozen=True)
class DailyBar:
    """A completed UTC calendar day, aggregated from hourly bars."""

    date: str
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    hours: int
    contiguous_run: int
    """Consecutive complete daily bars ending here. 1 means the streak restarted."""


@dataclass(frozen=True)
class RegimeParams:
    """Thresholds. Chosen on the training segment only, then frozen (preregistration §3)."""

    efficiency_window: int = 30
    """Days over which path straightness is measured. Reported, no longer the direction gate."""
    volatility_window: int = 30
    """Days of daily log returns in the realised-volatility estimate."""
    volatility_reference_days: int = 365
    """Trailing window the volatility is ranked against, so the scale is epoch-free."""
    efficiency_threshold: float = 0.35
    """Kept for the retired ER-gated taxonomy, so iteration 1 stays reproducible."""
    volatility_percentile: float = 0.70
    """At or above, with no direction: the high-volatility-no-trend regime."""
    persistence_days: int = 5
    """Consecutive days a new label must hold before it replaces the standing one.

    Means exactly what it says: with 5, adoption happens on the fifth consecutive day. An
    earlier revision adopted on the FOURTH, a one-day gap between a declared parameter and
    its behaviour -- the same shape as the eight structural defects already catalogued here.

    Not a cosmetic filter. The zero-band column failed 7 of 7 gates in
    `exposure-diagnosis.md` section F, and the project's existing classifier changes label
    on 37% of 5-day transitions.
    """
    trend_ma_days: int = 100
    """Reference the price must be above for a market to count as advancing."""
    peak_window_days: int = 180
    """Trailing window the running peak is taken over, for drawdown."""
    drawdown_threshold: float = 0.20
    """Decline from the trailing peak at which the market is called bearish."""
    near_peak_threshold: float = 0.10
    """Maximum decline from the trailing peak still compatible with ALCISTA."""
    min_regime_days: int = 30
    """Minimum duration for a run to count as a regime at all.

    Added in iteration 3 after a measured artifact. Without it the detector emitted
    BAJISTA runs of 1, 4, 7, 9 and 14 days during a bull market -- brief dips, not bears --
    while the one real bear in the data was a single 275-day run. A playbook scored on the
    short runs showed +28.7% for being LONG in a regime called bearish, because it was
    buying dips. Same label, two different phenomena, and the criterion was satisfied by
    the wrong one. A regime a spot allocation can act on does not last four days.
    """
    direction_axis: Literal["drawdown", "efficiency"] = "drawdown"
    """Which direction axis to use.

    `efficiency` is iteration 1, retained so its negative result stays reproducible: a
    30-day efficiency ratio left the BAJISTA regime at 3% of days (0% in the oracle),
    because a staircase decline with violent counter-rallies is not a straight path. The
    2021-2022 bear, where buy and hold lost 73.3%, landed in LATERAL.

    `drawdown` is iteration 2: a bear is defined the way it is defined economically, by a
    sustained decline from the running peak while trading below trend.
    """


def to_daily(bars: list[Bar]) -> list[DailyBar]:
    """Aggregate hourly bars into completed UTC days, refusing to bridge gaps.

    A day is emitted only when it carries at least MIN_HOURS_FOR_DAILY_BAR hours. An
    incomplete or absent day breaks `contiguous_run`, so every feature window below can
    insist on an unbroken streak rather than quietly averaging across a hole.
    """
    buckets: dict[str, list[Bar]] = {}
    for bar in bars:
        moment = datetime.fromtimestamp(bar.open_time_ms / 1000, tz=UTC)
        buckets.setdefault(moment.strftime("%Y-%m-%d"), []).append(bar)

    daily: list[DailyBar] = []
    previous_date: datetime | None = None
    run = 0
    for date in sorted(buckets):
        hourly = sorted(buckets[date], key=lambda item: item.open_time_ms)
        if len(hourly) < MIN_HOURS_FOR_DAILY_BAR:
            run = 0  # Incomplete day: the streak dies, and this day is not emitted.
            continue
        moment = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
        adjacent = previous_date is not None and (moment - previous_date).days == 1
        run = run + 1 if adjacent else 1
        daily.append(
            DailyBar(
                date=date,
                open_time_ms=hourly[0].open_time_ms,
                open=hourly[0].open,
                high=max(item.high for item in hourly),
                low=min(item.low for item in hourly),
                close=hourly[-1].close,
                hours=len(hourly),
                contiguous_run=run,
            )
        )
        previous_date = moment
    return daily


def efficiency_ratio(closes: list[float]) -> float | None:
    """Kaufman efficiency ratio: net displacement over distance actually travelled.

    1.0 is a straight line, near 0 is a round trip. Returns None when the path did not
    move at all, because the ratio is undefined rather than zero.
    """
    if len(closes) < 2:
        return None
    travelled = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    if travelled <= 0.0:
        return None
    return abs(closes[-1] - closes[0]) / travelled


def realised_volatility(closes: list[float]) -> float | None:
    """Standard deviation of daily log returns. None when there are too few returns."""
    if len(closes) < 3:
        return None
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return math.sqrt(variance)


def percentile_rank(value: float, reference: list[float]) -> float | None:
    """Fraction of the reference at or below `value`. None when there is no reference."""
    if not reference:
        return None
    return sum(1 for item in reference if item <= value) / len(reference)


def drawdown_from_peak(closes: list[float]) -> float | None:
    """Fractional decline of the last close below the highest close in the window.

    0.0 means the window ends at its own peak. 0.25 means a quarter below it. This is the
    axis that replaced the efficiency ratio: a bear market is a sustained decline from the
    peak, which is what the money experiences, not a straight line, which is what the
    efficiency ratio measures.
    """
    if not closes:
        return None
    peak = max(closes)
    if peak <= 0.0:
        return None
    return (peak - closes[-1]) / peak


def moving_average(closes: list[float]) -> float | None:
    """Plain mean of the window. None when empty."""
    if not closes:
        return None
    return sum(closes) / len(closes)


@dataclass(frozen=True)
class RegimeFeatures:
    """Everything a label is derived from, kept so a decision can be audited."""

    date: str
    close: float
    efficiency: float | None
    window_return: float | None
    volatility: float | None
    volatility_rank: float | None
    drawdown: float | None = None
    price_over_ma: float | None = None

    def is_complete(self) -> bool:
        return (
            self.efficiency is not None
            and self.window_return is not None
            and self.volatility_rank is not None
        )

    def is_complete_for_drawdown_axis(self) -> bool:
        return (
            self.drawdown is not None
            and self.price_over_ma is not None
            and self.volatility_rank is not None
        )


def _window_coverage(daily: list[DailyBar], index: int, span: int) -> float:
    """How densely the last `span + 1` bars cover the calendar days they stretch across.

    1.0 means no day is missing. A value below MIN_WINDOW_COVERAGE means the lookback is
    reaching across enough absent days that the feature should be withheld rather than
    computed over a hole.
    """
    first = datetime.strptime(daily[index - span].date, "%Y-%m-%d").replace(tzinfo=UTC)
    last = datetime.strptime(daily[index].date, "%Y-%m-%d").replace(tzinfo=UTC)
    calendar_days = (last - first).days + 1
    if calendar_days <= 0:
        return 0.0
    return (span + 1) / calendar_days


def causal_features(daily: list[DailyBar], params: RegimeParams) -> list[RegimeFeatures]:
    """Features for every day, using only that day and the completed days before it.

    A feature is withheld (None) rather than approximated when its window would span a
    break in `contiguous_run`. Withholding is the behaviour that makes an abstention
    visible; approximating is how a gap becomes a silent wrong number.
    """
    span = max(
        params.efficiency_window,
        params.volatility_window,
        params.trend_ma_days,
        params.peak_window_days,
    )
    volatilities: list[float | None] = []
    out: list[RegimeFeatures] = []

    for index, bar in enumerate(daily):
        volatility: float | None = None
        efficiency: float | None = None
        window_return: float | None = None
        drawdown: float | None = None
        over_ma: float | None = None

        covered = _window_coverage(daily, index, span) if index >= span else 0.0
        if covered >= MIN_WINDOW_COVERAGE:
            window = [item.close for item in daily[index - span : index + 1]]
            efficiency = efficiency_ratio(window[-(params.efficiency_window + 1) :])
            volatility = realised_volatility(window[-(params.volatility_window + 1) :])
            first = window[-(params.efficiency_window + 1)]
            window_return = math.log(window[-1] / first) if first > 0 else None
            drawdown = drawdown_from_peak(window[-(params.peak_window_days + 1) :])
            average = moving_average(window[-(params.trend_ma_days + 1) :])
            if average is not None and average > 0.0 and window[-1] > 0.0:
                over_ma = math.log(window[-1] / average)

        volatilities.append(volatility)

        rank: float | None = None
        if volatility is not None:
            lookback = volatilities[max(0, index - params.volatility_reference_days + 1) :]
            reference = [item for item in lookback if item is not None]
            rank = percentile_rank(volatility, reference)

        out.append(
            RegimeFeatures(
                date=bar.date,
                close=bar.close,
                efficiency=efficiency,
                window_return=window_return,
                volatility=volatility,
                volatility_rank=rank,
                drawdown=drawdown,
                price_over_ma=over_ma,
            )
        )
    return out


def classify(features: RegimeFeatures, params: RegimeParams) -> Regime | None:
    """Map one day's features onto the frozen taxonomy. None means 'not enough evidence'.

    None is a first-class answer: without it, the warmup period would be labelled by
    whatever the thresholds happen to do to missing data.
    """
    if params.direction_axis == "drawdown":
        return _classify_by_drawdown(features, params)
    return _classify_by_efficiency(features, params)


def _classify_by_drawdown(features: RegimeFeatures, params: RegimeParams) -> Regime | None:
    """Iteration 2. Direction is decline from the running peak plus side of the trend.

    Order matters and is deliberate: BAJISTA is tested FIRST, because the entire point of
    this axis is that the regime carrying the losses must not be able to hide inside a
    residual bucket. Under the retired efficiency axis it hid in LATERAL.
    """
    if not features.is_complete_for_drawdown_axis():
        return None
    drawdown = features.drawdown
    over_ma = features.price_over_ma
    rank = features.volatility_rank
    assert drawdown is not None and over_ma is not None and rank is not None

    if drawdown >= params.drawdown_threshold and over_ma < 0.0:
        return "BAJISTA"
    if over_ma > 0.0 and drawdown <= params.near_peak_threshold:
        return "ALCISTA"
    if rank >= params.volatility_percentile:
        return "ALTA_VOL_SIN_DIRECCION"
    return "LATERAL"


def _classify_by_efficiency(features: RegimeFeatures, params: RegimeParams) -> Regime | None:
    """Iteration 1, retained so its measured failure stays reproducible.

    Left BAJISTA at 3% of days (0% in the oracle): a 30-day efficiency ratio cannot see a
    staircase decline, so the 2021-2022 bear was labelled LATERAL.
    """
    if not features.is_complete():
        return None
    assert features.efficiency is not None
    assert features.window_return is not None
    assert features.volatility_rank is not None

    if features.efficiency >= params.efficiency_threshold:
        return "ALCISTA" if features.window_return > 0 else "BAJISTA"
    if features.volatility_rank >= params.volatility_percentile:
        return "ALTA_VOL_SIN_DIRECCION"
    return "LATERAL"


def apply_persistence(raw: list[Regime | None], days: int) -> list[Regime | None]:
    """Hold the standing label until a challenger repeats `days` times in a row.

    This is the churn control the diagnosis demanded. It necessarily ADDS detection lag,
    which is the trade the study then measures rather than assumes.
    """
    if days <= 1:
        return list(raw)
    settled: list[Regime | None] = []
    standing: Regime | None = None
    candidate: Regime | None = None
    streak = 0
    for label in raw:
        if label is None:
            settled.append(standing)
            continue
        if standing is None:
            standing = label
            candidate, streak = label, 0
            settled.append(standing)
            continue
        if label == standing:
            candidate, streak = label, 0
        elif label == candidate:
            streak += 1
            if streak >= days:
                standing = label
                candidate, streak = label, 0
        else:
            candidate, streak = label, 1
        settled.append(standing)
    return settled


def enforce_min_segment(labels: list[Regime | None], min_days: int) -> list[Regime | None]:
    """Absorb runs shorter than `min_days` into the label that preceded them.

    Without this the oracle emits two-day "regimes", and then any detector that twitches
    often scores a low false-alarm rate by coincidence -- it matches noise to noise. A
    regime that does not last three weeks is not a regime a spot allocation can act on,
    so the reference has to say so.

    Applied repeatedly until stable, because absorbing one short run can leave its
    neighbours adjacent and equal.
    """
    if min_days <= 1:
        return list(labels)

    current = list(labels)
    for _ in range(len(current)):
        runs: list[tuple[int, int, Regime | None]] = []
        start = 0
        for index in range(1, len(current) + 1):
            if index == len(current) or current[index] != current[start]:
                runs.append((start, index, current[start]))
                start = index

        changed = False
        for position, (begin, end, label) in enumerate(runs):
            if label is None or end - begin >= min_days:
                continue
            replacement: Regime | None = None
            if position > 0:
                replacement = runs[position - 1][2]
            elif position + 1 < len(runs):
                replacement = runs[position + 1][2]
            if replacement is None or replacement == label:
                continue
            for index in range(begin, end):
                current[index] = replacement
            changed = True
            break
        if not changed:
            break
    return current


def apply_min_dwell(labels: list[Regime | None], min_days: int) -> list[Regime | None]:
    """Once adopted, a label cannot be replaced for `min_days` days. CAUSAL.

    This is the causal counterpart of `enforce_min_segment`, and the distinction is not
    pedantic. `enforce_min_segment` inspects the whole series to decide whether a run was
    long enough, which on day t requires knowing how long the current run will END UP
    being -- look-ahead, and of the kind that silently flatters a backtest. A minimum DWELL
    time asks the opposite question, which is answerable on day t: how long has the
    standing label already held? Only the past is consulted.

    It is the fix for the measured artifact in iteration 3: BAJISTA runs of 1, 4, 7, 9 and
    14 days during a bull market made "long the bear regime" look profitable, because those
    runs were dips rather than bears.
    """
    if min_days <= 1:
        return list(labels)
    out: list[Regime | None] = []
    standing: Regime | None = None
    held = 0
    for label in labels:
        if standing is None:
            standing = label
            held = 1 if label is not None else 0
            out.append(standing)
            continue
        if label is not None and label != standing and held >= min_days:
            standing = label
            held = 1
        else:
            held += 1
        out.append(standing)
    return out


def detect_regimes(
    daily: list[DailyBar], params: RegimeParams | None = None
) -> list[Regime | None]:
    """The causal detector. Day t is decided from completed days up to t and nothing more.

    This is the ONLY regime signal a playbook may consume.
    """
    chosen = params or RegimeParams()
    raw = [classify(item, chosen) for item in causal_features(daily, chosen)]
    settled = apply_persistence(raw, chosen.persistence_days)
    return apply_min_dwell(settled, chosen.min_regime_days)


# --------------------------------------------------------------------------------------
# The oracle. Uses the future BY DESIGN, exists only to score the detector above.
# --------------------------------------------------------------------------------------


def oracle_regimes(
    daily: list[DailyBar],
    params: RegimeParams | None = None,
    half_window: int = 15,
    min_segment_days: int = 21,
) -> list[Regime | None]:
    """Label each day with HINDSIGHT, so segments are clean. Acausal on purpose.

    It answers "what regime was this day really in", which is the only honest reference
    for measuring how late a causal detector was. Feeding this to a trading rule would be
    look-ahead of the most direct kind, so nothing in the playbook path takes it.

    Direction uses the future to CONFIRM, which is the oracle's whole privilege:

    - drawdown is taken from the peak of the PAST half-window only. Measuring it against a
      future peak would brand the dip before a rally as bearish, which is the opposite of
      the truth.
    - the forward return over the next half-window then confirms the direction.

    `min_segment_days` matters more than it looks. Without it the reference emits runs of
    two or three days, and a twitchy detector then scores a flattering false-alarm rate by
    matching its own noise against the reference's noise.
    """
    chosen = params or RegimeParams()
    closes = [bar.close for bar in daily]
    volatilities: list[float | None] = []

    for index in range(len(daily)):
        start_at, end_at = index - half_window, index + half_window
        usable = (
            start_at >= 0
            and end_at < len(daily)
            and daily[end_at].contiguous_run >= 2 * half_window + 1
        )
        volatilities.append(
            realised_volatility(closes[start_at : end_at + 1]) if usable else None
        )

    present = [item for item in volatilities if item is not None]
    labels: list[Regime | None] = []
    for index in range(len(daily)):
        volatility = volatilities[index]
        if volatility is None:
            labels.append(None)
            continue
        start_at, end_at = index - half_window, index + half_window
        past = closes[start_at : index + 1]
        drawdown = drawdown_from_peak(past)
        rank = percentile_rank(volatility, present)
        if drawdown is None or rank is None or closes[index] <= 0.0:
            labels.append(None)
            continue
        forward = math.log(closes[end_at] / closes[index])

        if chosen.direction_axis == "efficiency":
            efficiency = efficiency_ratio(closes[start_at : end_at + 1])
            if efficiency is None or closes[start_at] <= 0.0:
                labels.append(None)
                continue
            if efficiency >= chosen.efficiency_threshold:
                labels.append(
                    "ALCISTA"
                    if math.log(closes[end_at] / closes[start_at]) > 0
                    else "BAJISTA"
                )
            elif rank >= chosen.volatility_percentile:
                labels.append("ALTA_VOL_SIN_DIRECCION")
            else:
                labels.append("LATERAL")
            continue

        if drawdown >= chosen.drawdown_threshold and forward < 0.0:
            labels.append("BAJISTA")
        elif drawdown <= chosen.near_peak_threshold and forward > 0.0:
            labels.append("ALCISTA")
        elif rank >= chosen.volatility_percentile:
            labels.append("ALTA_VOL_SIN_DIRECCION")
        else:
            labels.append("LATERAL")
    return enforce_min_segment(labels, min_segment_days)


def transitions(labels: list[Regime | None]) -> list[tuple[int, Regime]]:
    """Indices where the label becomes a new non-None value, with that new value."""
    found: list[tuple[int, Regime]] = []
    standing: Regime | None = None
    for index, label in enumerate(labels):
        if label is not None and label != standing:
            if standing is not None:
                found.append((index, label))
            standing = label
    return found


@dataclass(frozen=True)
class DetectionQuality:
    """How fast, and how trustworthy, the causal detector is against the oracle."""

    oracle_transitions: int
    detector_transitions: int
    matched: int
    missed: int
    false_alarms: int
    median_lag_days: float | None
    mean_lag_days: float | None
    worst_lag_days: int | None
    false_alarm_rate: float | None
    coverage: float | None

    def summary(self) -> str:
        lag = "n/a" if self.median_lag_days is None else f"{self.median_lag_days:.1f}d"
        rate = "n/a" if self.false_alarm_rate is None else f"{self.false_alarm_rate:.0%}"
        cover = "n/a" if self.coverage is None else f"{self.coverage:.0%}"
        return (
            f"retardo mediano {lag} · falsas alarmas {rate} "
            f"({self.false_alarms}/{self.detector_transitions}) · cobertura {cover}"
        )


def score_detection(
    detector: list[Regime | None],
    oracle: list[Regime | None],
    tolerance_days: int = 30,
) -> DetectionQuality:
    """Match detector transitions to oracle transitions and report lag and false alarms.

    A detector transition counts as a true positive when the oracle changed to the SAME
    label within `tolerance_days`. Matching on label matters: switching at the right
    moment to the wrong regime is not a detection, and scoring it as one is how a useless
    detector looks responsive.
    """
    oracle_points = transitions(oracle)
    detector_points = transitions(detector)

    lags: list[int] = []
    used: set[int] = set()
    for position, (index, label) in enumerate(oracle_points):
        best: tuple[int, int] | None = None
        for other, (found_at, found) in enumerate(detector_points):
            if other in used or found != label:
                continue
            lag = found_at - index
            if -tolerance_days <= lag <= tolerance_days and (best is None or lag < best[1]):
                best = (other, lag)
        if best is not None:
            used.add(best[0])
            lags.append(best[1])
        del position

    matched = len(lags)
    ordered = sorted(lags)
    median = (
        None
        if not ordered
        else float(ordered[len(ordered) // 2])
        if len(ordered) % 2
        else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
    )
    return DetectionQuality(
        oracle_transitions=len(oracle_points),
        detector_transitions=len(detector_points),
        matched=matched,
        missed=len(oracle_points) - matched,
        false_alarms=len(detector_points) - matched,
        median_lag_days=median,
        mean_lag_days=sum(lags) / len(lags) if lags else None,
        worst_lag_days=max(lags) if lags else None,
        false_alarm_rate=(
            (len(detector_points) - matched) / len(detector_points) if detector_points else None
        ),
        coverage=matched / len(oracle_points) if oracle_points else None,
    )


def regime_shares(labels: list[Regime | None]) -> dict[str, float]:
    """Fraction of labelled days in each regime. Reported so a degenerate split is visible."""
    labelled = [item for item in labels if item is not None]
    if not labelled:
        return {name: 0.0 for name in REGIMES}
    return {
        name: sum(1 for item in labelled if item == name) / len(labelled) for name in REGIMES
    }
