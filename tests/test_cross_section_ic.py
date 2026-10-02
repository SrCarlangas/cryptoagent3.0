"""Guards for the module that produced this project's one real finding.

`research/cross_section_ic.py` is the source of the six signals at |t| >= 2 (low volatility
-4.76, listing age +4.57, volume growth -4.09, mean volume -3.19, 30d reversal -2.54). It had
**zero tests** -- and it is the only positive result the project is willing to defend, which
makes it the code most worth attacking.

The first test is the one that matters. During the regime study this project came within one
commit of shipping `enforce_min_segment`, a function that read the future to decide the past.
A feature computed at time t that moves when t+1 changes is not a signal, it is a leak, and it
produces exactly the kind of beautiful t-statistic that fails out of sample.
"""

from __future__ import annotations

import copy
import math

import pytest
from cross_section_ic import signals_for


def synthetic(days: int = 260, drift: float = 0.004) -> tuple[
    dict[str, dict[str, float]], dict[str, dict[str, float]], list[str]
]:
    """One asset on a smooth upward path, with history long enough to clear the warmup."""
    calendar = [f"2024-{1 + day // 28:02d}-{1 + day % 28:02d}" for day in range(days)]
    closes = {"AAA": {day: 100.0 * math.exp(drift * index) for index, day in enumerate(calendar)}}
    volumes = {"AAA": {day: 1_000_000.0 for day in calendar}}
    return closes, volumes, calendar


def test_signals_do_not_move_when_only_the_future_changes() -> None:
    """THE look-ahead guard: perturb every bar AFTER the evaluation date, expect no change.

    If this test ever fails, every IC in `data/validation/cross-section-ic.json` is void and
    must be re-measured -- not re-explained.
    """
    closes, volumes, calendar = synthetic()
    index = 200

    before = signals_for(closes, volumes, calendar, index, "AAA")
    assert before is not None, "the fixture must clear the 180-day warmup"

    poisoned_closes = copy.deepcopy(closes)
    poisoned_volumes = copy.deepcopy(volumes)
    for future in calendar[index + 1 :]:
        poisoned_closes["AAA"][future] *= 7.5
        poisoned_volumes["AAA"][future] *= 0.01

    after = signals_for(poisoned_closes, poisoned_volumes, calendar, index, "AAA")
    assert after == before


def test_insufficient_history_abstains_instead_of_guessing() -> None:
    """Below the warmup the honest answer is None, not a signal built from a short window."""
    closes, volumes, calendar = synthetic()
    assert signals_for(closes, volumes, calendar, 10, "AAA") is None
    assert signals_for(closes, volumes, calendar, 179, "AAA") is None


def test_a_missing_asset_on_the_date_abstains() -> None:
    closes, volumes, calendar = synthetic()
    del closes["AAA"][calendar[200]]
    assert signals_for(closes, volumes, calendar, 200, "AAA") is None


def test_a_non_positive_price_abstains_rather_than_taking_a_log_of_zero() -> None:
    closes, volumes, calendar = synthetic()
    closes["AAA"][calendar[200]] = 0.0
    assert signals_for(closes, volumes, calendar, 200, "AAA") is None


def test_constant_growth_has_zero_volatility_and_a_guarded_ratio() -> None:
    """Equal daily log returns means zero dispersion, and the vol-adjusted momentum must not
    divide by it. This is the guard that keeps a degenerate asset from scoring infinitely."""
    closes, volumes, calendar = synthetic(drift=0.004)
    signals = signals_for(closes, volumes, calendar, 200, "AAA")
    assert signals is not None
    assert signals["volatilidad_30d"] == pytest.approx(0.0, abs=1e-12)
    assert signals["momento_30d_ajustado_vol"] == 0.0


def test_momentum_is_the_log_ratio_over_the_stated_lookback() -> None:
    """Hand-computed: 30 days of constant drift is exactly 30 * drift in log space."""
    drift = 0.004
    closes, volumes, calendar = synthetic(drift=drift)
    signals = signals_for(closes, volumes, calendar, 200, "AAA")
    assert signals is not None
    assert signals["momento_30d"] == pytest.approx(30 * drift, rel=1e-9)
    assert signals["momento_90d"] == pytest.approx(90 * drift, rel=1e-9)
    assert signals["momento_180d"] == pytest.approx(180 * drift, rel=1e-9)


def test_a_falling_asset_reports_negative_momentum() -> None:
    closes, volumes, calendar = synthetic(drift=-0.003)
    signals = signals_for(closes, volumes, calendar, 200, "AAA")
    assert signals is not None
    assert signals["momento_30d"] < 0.0


def test_flat_volume_reports_zero_growth_and_rising_volume_reports_positive() -> None:
    closes, volumes, calendar = synthetic()
    flat = signals_for(closes, volumes, calendar, 200, "AAA")
    assert flat is not None
    assert flat["crecimiento_volumen"] == pytest.approx(0.0, abs=1e-12)

    for recent in calendar[171:201]:
        volumes["AAA"][recent] *= 4.0
    rising = signals_for(closes, volumes, calendar, 200, "AAA")
    assert rising is not None
    assert rising["crecimiento_volumen"] > 0.0


def test_thin_volume_history_abstains() -> None:
    """The density defect in miniature: a cell with almost no data must not produce a feature.

    The narrative corpus failed for this reason at scale -- 93% of asset-period cells were
    empty, so a mention count was mechanically zero and had no cross-sectional variance.
    """
    closes, volumes, calendar = synthetic()
    for day in calendar[100:201]:
        del volumes["AAA"][day]
    assert signals_for(closes, volumes, calendar, 200, "AAA") is None
