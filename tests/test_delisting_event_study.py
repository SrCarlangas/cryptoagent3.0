"""Guards for the event study that closed the project's last open hypothesis.

Two of these encode mistakes made while building it.

`forward` must start its window the day AFTER the announcement. The corpus is the one dataset
in this project whose timestamps are genuinely point-in-time, and reading the announcement day
itself would quietly hand the study the move it is supposed to be predicting.

`sign_test` and the mean/median pair exist because the raw reading of this study was nearly
"+110.9% mean excess, the hypothesis holds". It did not hold: the mean was one event of
+1089.5% and the median was +0.65%. A mean without its median is not a result.
"""

from __future__ import annotations

import math

import pytest
from delisting_event_study import HORIZON, forward, sign_test, standard_error


def series(days: int = 80, start: float = 100.0, step: float = 1.0) -> tuple[
    dict[str, dict[str, float]], list[str]
]:
    calendar = [f"2024-{1 + day // 28:02d}-{1 + day % 28:02d}" for day in range(days)]
    closes = {"AAA": {day: start + step * index for index, day in enumerate(calendar)}}
    return closes, calendar


def test_the_window_starts_strictly_after_the_announcement_day() -> None:
    """A spike ON the announcement day must not enter the measured return.

    This is the causality guard. The announcement is public at some point during its own day;
    a window that includes that day is measuring the reaction it claims to forecast.
    """
    closes, calendar = series()
    day = calendar[10]
    clean = forward(closes, calendar, "AAA", day)
    assert clean is not None

    closes["AAA"][day] *= 100.0
    assert forward(closes, calendar, "AAA", day) == pytest.approx(clean)


def test_the_window_is_exactly_the_declared_horizon() -> None:
    """Hand-computed on a geometric series: the log return spans HORIZON-1 steps."""
    rate = 1.01
    calendar = [f"2024-{1 + day // 28:02d}-{1 + day % 28:02d}" for day in range(80)]
    closes = {"AAA": {day: 100.0 * rate**index for index, day in enumerate(calendar)}}
    measured = forward(closes, calendar, "AAA", calendar[10])
    assert measured is not None
    assert measured == pytest.approx(math.log(rate) * (HORIZON - 1), rel=1e-9)


def test_insufficient_future_abstains_rather_than_shortening_the_window() -> None:
    """Near the end of the data the honest answer is None. A silently shorter window would
    make late events incomparable to early ones and bias the average."""
    closes, calendar = series(days=40)
    assert forward(closes, calendar, "AAA", calendar[35]) is None


def test_a_missing_bar_at_either_end_abstains() -> None:
    closes, calendar = series()
    del closes["AAA"][calendar[11]]
    assert forward(closes, calendar, "AAA", calendar[10]) is None


def test_sign_test_matches_the_binomial_by_hand() -> None:
    """Three observations: all negative is 1/8, none negative is certainty."""
    all_negative = sign_test([-1.0, -2.0, -3.0])
    assert all_negative[0] == 3
    assert all_negative[2] == pytest.approx(1.0 / 8.0)

    none_negative = sign_test([1.0, 2.0, 3.0])
    assert none_negative[0] == 0
    assert none_negative[2] == pytest.approx(1.0)


def test_sign_test_on_a_coin_is_not_significant() -> None:
    """The measured study landed at 14/31 negative, p = 0.76. An even split must never read
    as evidence."""
    _negatives, _total, p_value = sign_test([1.0] * 15 + [-1.0] * 15)
    assert p_value > 0.4


def test_standard_error_matches_the_textbook_formula() -> None:
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    expected = math.sqrt(32.0 / 7.0) / math.sqrt(8)
    assert standard_error(values) == pytest.approx(expected, rel=1e-12)


def test_standard_error_abstains_on_a_sample_too_small_to_have_one() -> None:
    assert standard_error([1.0]) is None
    assert standard_error([1.0, 2.0]) is None


def test_one_outlier_moves_the_mean_and_not_the_median() -> None:
    """The convexity signature, asserted. This is why the study reports both.

    Without the median, a single +1089.5% event reads as a +110.9% edge.
    """
    flat = [0.0] * 30
    mean_flat = sum(flat) / len(flat)
    with_outlier = [*flat[:-1], 100.0]
    mean_outlier = sum(with_outlier) / len(with_outlier)

    assert mean_outlier > mean_flat + 3.0, "the mean must be dragged by the tail"
    assert sorted(with_outlier)[len(with_outlier) // 2] == pytest.approx(0.0), (
        "the median must be untouched by a single extreme"
    )
