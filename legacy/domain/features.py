"""Pure Decimal implementations of F-001..F-012 and conservative costs."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from itertools import pairwise

from .contracts import CostEstimate, CostScenario, FeatureValue, QualityStatus

D = Decimal
BPS = D("10000")


@dataclass(frozen=True)
class Bar:
    """Closed-bar input with explicit causal and quality provenance."""

    event_id: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    base_volume: Decimal
    final: bool = True
    event_time_max: datetime | None = None
    quality: QualityStatus = QualityStatus.QUALIFIED
    continuity: bool = True
    gaps: tuple[str, ...] = ()
    source_contract_ids: tuple[str, ...] = ("S-02", "S-03")
    source_watermarks: dict[str, datetime] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None or self.close_time.tzinfo is None:
            raise ValueError("bar timestamps must be UTC-aware")
        if self.open_time.utcoffset() != UTC.utcoffset(self.open_time) or self.close_time.utcoffset() != UTC.utcoffset(self.close_time):
            raise ValueError("bar timestamps must be UTC")
        if self.open_time >= self.close_time:
            raise ValueError("bar close must follow open")
        if self.low > min(self.open, self.close) or max(self.open, self.close) > self.high or self.base_volume < 0:
            raise ValueError("bar OHLCV is invalid")
        event_time = self.close_time if self.event_time_max is None else self.event_time_max
        if event_time.tzinfo is None or event_time.utcoffset() != UTC.utcoffset(event_time):
            raise ValueError("bar event_time_max must be UTC")
        if event_time < self.close_time:
            raise ValueError("bar event_time_max cannot precede close")
        if any(stamp.tzinfo is None or stamp.utcoffset() != UTC.utcoffset(stamp) for stamp in self.source_watermarks.values()):
            raise ValueError("bar watermarks must be UTC")
        object.__setattr__(self, "event_time_max", event_time)


def _bar_reason(bars: Sequence[Bar], as_of: datetime, *, require_contiguous: bool = True) -> str | None:
    if any(not bar.final for bar in bars):
        return "BAR_NOT_FINAL"
    if any(bar.quality != QualityStatus.QUALIFIED for bar in bars):
        return "BAR_NOT_QUALIFIED"
    if any(not bar.continuity or bar.gaps for bar in bars):
        return "BAR_GAP_OR_DISCONTINUITY"
    if any(bar.close_time > as_of or bar.event_time_max is None or bar.event_time_max > as_of for bar in bars):
        return "FUTURE_BAR_INPUT"
    if require_contiguous and any(left.close_time != right.open_time for left, right in pairwise(bars)):
        return "BAR_GAP_OR_DISCONTINUITY"
    return None


def _feature(
    feature_id: str,
    value: Decimal | None,
    unit: str,
    as_of: datetime,
    inputs: Sequence[str],
    reason: str | None = None,
    horizon: str = "1h",
    window: str = "",
    *,
    max_input_event_time: datetime | None = None,
    source_contract_ids: Sequence[str] = (),
    source_watermarks: dict[str, datetime] | None = None,
) -> FeatureValue:
    return FeatureValue(
        feature_id=feature_id,
        value=value,
        unit=unit,
        as_of_time=as_of,
        max_input_event_time=max_input_event_time or as_of,
        horizon=horizon,
        window_definition=window,
        input_event_ids=tuple(dict.fromkeys(inputs)),
        source_contract_ids=tuple(sorted(set(source_contract_ids))),
        source_watermarks=source_watermarks or {},
        quality=QualityStatus.QUALIFIED if value is not None else QualityStatus.BLOCKED,
        null_reason=reason,
    )


def _bar_feature(feature_id: str, value: Decimal | None, unit: str, as_of: datetime, bars: Sequence[Bar], reason: str | None = None, *, window: str = "") -> FeatureValue:
    maximum = max((bar.event_time_max for bar in bars if bar.event_time_max is not None), default=as_of)
    sources = tuple(source for bar in bars for source in bar.source_contract_ids)
    watermarks: dict[str, datetime] = {}
    for bar in bars:
        for source, stamp in bar.source_watermarks.items():
            watermarks[source] = max(stamp, watermarks.get(source, stamp))
    return _feature(feature_id, value, unit, as_of, [bar.event_id for bar in bars], reason, window=window, max_input_event_time=maximum, source_contract_ids=sources, source_watermarks=watermarks)


def sma(bars: Sequence[Bar], n: int, as_of: datetime) -> FeatureValue:
    """F-001: simple average of N consecutive FINAL qualified closes."""
    if n < 2 or len(bars) < n:
        return _feature("F-001", None, "USDT/BTC", as_of, (), "INSUFFICIENT_FINAL_BARS", window=f"N={n}")
    selected = bars[-n:]
    reason = _bar_reason(selected, as_of)
    if reason:
        return _bar_feature("F-001", None, "USDT/BTC", as_of, selected, reason, window=f"N={n}")
    return _bar_feature("F-001", sum((bar.close for bar in selected), D("0")) / D(n), "USDT/BTC", as_of, selected, window=f"N={n}")


def distance_to_sma(close: Decimal | None, average: Decimal | None, as_of: datetime, *, input_features: Sequence[FeatureValue] = ()) -> FeatureValue:
    """F-002: close / SMA - 1, preserving upstream causal provenance."""
    maximum = max((item.max_input_event_time for item in input_features), default=as_of)
    ids = tuple(ref for item in input_features for ref in item.input_event_ids)
    sources = tuple(source for item in input_features for source in item.source_contract_ids)
    if close is None or average is None or average <= 0:
        return _feature("F-002", None, "ratio", as_of, ids, "NON_POSITIVE_SMA", max_input_event_time=maximum, source_contract_ids=sources)
    return _feature("F-002", close / average - D("1"), "ratio", as_of, ids, max_input_event_time=maximum, source_contract_ids=sources)


def sma_slope(current: Decimal | None, prior: Decimal | None, k: int, as_of: datetime, *, input_features: Sequence[FeatureValue] = ()) -> FeatureValue:
    """F-003: normalized SMA change per bar."""
    maximum = max((item.max_input_event_time for item in input_features), default=as_of)
    ids = tuple(ref for item in input_features for ref in item.input_event_ids)
    sources = tuple(source for item in input_features for source in item.source_contract_ids)
    if k < 1 or current is None or prior is None or prior <= 0:
        return _feature("F-003", None, "ratio/bar", as_of, ids, "INSUFFICIENT_SMA_HISTORY", max_input_event_time=maximum, source_contract_ids=sources)
    return _feature("F-003", (current / prior - D("1")) / D(k), "ratio/bar", as_of, ids, max_input_event_time=maximum, source_contract_ids=sources)


def volume_ratio(bars: Sequence[Bar], n: int, as_of: datetime) -> FeatureValue:
    """F-004: target volume divided by prior-N mean, excluding target."""
    if n < 1 or len(bars) < n + 1:
        return _feature("F-004", None, "ratio", as_of, (), "INSUFFICIENT_FINAL_BARS")
    selected = bars[-n - 1 :]
    reason = _bar_reason(selected, as_of)
    if reason:
        return _bar_feature("F-004", None, "ratio", as_of, selected, reason)
    current, prior = selected[-1], selected[:-1]
    baseline = sum((bar.base_volume for bar in prior), D("0")) / D(n)
    if baseline == 0:
        return _bar_feature("F-004", None, "ratio", as_of, selected, "ZERO_VOLUME_BASELINE")
    return _bar_feature("F-004", current.base_volume / baseline, "ratio", as_of, selected)


def true_range(current: Bar, previous: Bar, as_of: datetime) -> FeatureValue:
    """F-005: max intrabar and previous-close ranges."""
    selected = (previous, current)
    reason = _bar_reason(selected, as_of)
    if reason:
        return _bar_feature("F-005", None, "USDT/BTC", as_of, selected, reason)
    value = max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close))
    return _bar_feature("F-005", value, "USDT/BTC", as_of, selected)


def atr(bars: Sequence[Bar], n: int, as_of: datetime) -> tuple[FeatureValue, FeatureValue]:
    """F-006: simple ATR and ATR/close."""
    if n < 1 or len(bars) < n + 1:
        null = _feature("F-006", None, "USDT/BTC", as_of, (), "INSUFFICIENT_TRUE_RANGES")
        return null, _feature("F-006F", None, "ratio", as_of, (), "INSUFFICIENT_TRUE_RANGES")
    selected = bars[-n - 1 :]
    reason = _bar_reason(selected, as_of)
    if reason:
        return _bar_feature("F-006", None, "USDT/BTC", as_of, selected, reason), _bar_feature("F-006F", None, "ratio", as_of, selected, reason)
    ranges = [max(selected[i].high - selected[i].low, abs(selected[i].high - selected[i - 1].close), abs(selected[i].low - selected[i - 1].close)) for i in range(1, len(selected))]
    value = sum(ranges, D("0")) / D(n)
    fraction = value / selected[-1].close if selected[-1].close > 0 else None
    return _bar_feature("F-006", value, "USDT/BTC", as_of, selected), _bar_feature("F-006F", fraction, "ratio", as_of, selected, None if fraction is not None else "NON_POSITIVE_CLOSE")


def realized_volatility(bars: Sequence[Bar], n: int, as_of: datetime) -> FeatureValue:
    """F-007: sample standard deviation of N Decimal log returns."""
    if n < 2 or len(bars) < n + 1:
        return _feature("F-007", None, "ratio/bar", as_of, (), "INSUFFICIENT_LOG_RETURNS")
    selected = bars[-n - 1 :]
    reason = _bar_reason(selected, as_of)
    if reason or any(bar.close <= 0 for bar in selected):
        return _bar_feature("F-007", None, "ratio/bar", as_of, selected, reason or "INSUFFICIENT_LOG_RETURNS")
    with localcontext() as ctx:
        ctx.prec = 34
        returns = [(selected[i].close / selected[i - 1].close).ln() for i in range(1, len(selected))]
        mean = sum(returns, D("0")) / D(n)
        variance = sum(((item - mean) ** 2 for item in returns), D("0")) / D(n - 1)
        value = variance.sqrt()
    return _bar_feature("F-007", value, "ratio/bar", as_of, selected)


def spread_features(bid: Decimal, ask: Decimal, as_of: datetime, *, event_id: str | None = None, source_contract_id: str = "S-04", event_time: datetime | None = None) -> dict[str, FeatureValue]:
    """F-008: mid, absolute spread, spread and side crossing in bps."""
    inputs = (event_id,) if event_id else ()
    stamp = event_time or as_of
    if bid <= 0 or ask < bid:
        null = _feature("F-008", None, "bps", as_of, inputs, "INVALID_BBO", max_input_event_time=stamp, source_contract_ids=(source_contract_id,))
        return {key: null for key in ("mid", "spread_abs", "spread_bps", "buy_cross_bps", "sell_cross_bps")}
    mid = (bid + ask) / D("2")
    spread_abs = ask - bid
    return {
        "mid": _feature("F-008-MID", mid, "USDT/BTC", as_of, inputs, max_input_event_time=stamp, source_contract_ids=(source_contract_id,)),
        "spread_abs": _feature("F-008-ABS", spread_abs, "USDT/BTC", as_of, inputs, max_input_event_time=stamp, source_contract_ids=(source_contract_id,)),
        "spread_bps": _feature("F-008", BPS * spread_abs / mid, "bps", as_of, inputs, max_input_event_time=stamp, source_contract_ids=(source_contract_id,)),
        "buy_cross_bps": _feature("F-008-BUY", BPS * (ask - mid) / mid, "bps", as_of, inputs, max_input_event_time=stamp, source_contract_ids=(source_contract_id,)),
        "sell_cross_bps": _feature("F-008-SELL", BPS * (mid - bid) / mid, "bps", as_of, inputs, max_input_event_time=stamp, source_contract_ids=(source_contract_id,)),
    }


def depth_vwap(levels: Sequence[tuple[Decimal, Decimal]], quantity: Decimal, side: str) -> tuple[Decimal | None, Decimal | None]:
    """F-009: walk visible levels and measure slippage beyond best quote."""
    if quantity <= 0 or not levels or side not in {"buy", "sell"}:
        return None, None
    remaining, notional = quantity, D("0")
    for price, available in levels:
        fill = min(remaining, available)
        notional += fill * price
        remaining -= fill
        if remaining == 0:
            break
    if remaining > 0:
        return None, None
    vwap = notional / quantity
    best = levels[0][0]
    slip = BPS * (vwap - best) / best if side == "buy" else BPS * (best - vwap) / best
    return vwap, slip


def round_trip_cost(components: Iterable[Decimal | None]) -> Decimal | None:
    """F-010: exact sum; one unknown component makes the total unknown."""
    values = tuple(components)
    if any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), D("0"))


def build_cost_estimate(
    version: str,
    quantity: Decimal,
    scenario: CostScenario,
    fee_bps: Decimal | None,
    cross_bps: Decimal | None,
    depth_bps: Decimal | None,
    impact_bps: Decimal | None,
    other_bps: Decimal | None,
    as_of: datetime,
    *,
    frame_ref: str,
    input_event_ids: Sequence[str],
    max_input_event_time: datetime,
) -> CostEstimate:
    total = round_trip_cost((fee_bps, cross_bps, depth_bps, impact_bps, other_bps))
    return CostEstimate(
        version=version,
        frame_ref=frame_ref,
        action="ENTER_LONG",
        base_quantity=quantity,
        scenario=scenario,
        fee_bps=fee_bps,
        cross_bps=cross_bps,
        depth_slippage_bps=depth_bps,
        impact_bps=impact_bps,
        other_bps=other_bps,
        total_bps=total,
        conservative_lower_bps=total,
        conservative_upper_bps=total,
        quality=QualityStatus.QUALIFIED if total is not None else QualityStatus.BLOCKED,
        as_of_time=as_of,
        max_input_event_time=max_input_event_time,
        input_event_ids=tuple(input_event_ids),
    )


def depth_imbalance(bids: Sequence[tuple[Decimal, Decimal]], asks: Sequence[tuple[Decimal, Decimal]], mid: Decimal, band_bps: Decimal, as_of: datetime) -> FeatureValue:
    """F-011: symmetric notional imbalance within a fixed bps band."""
    lower, upper = mid * (D("1") - band_bps / BPS), mid * (D("1") + band_bps / BPS)
    bid_notional = sum((price * qty for price, qty in bids if price >= lower), D("0"))
    ask_notional = sum((price * qty for price, qty in asks if price <= upper), D("0"))
    denominator = bid_notional + ask_notional
    if denominator == 0:
        return _feature("F-011", None, "ratio", as_of, (), "ZERO_DEPTH_NOTIONAL", source_contract_ids=("S-05", "S-06"))
    return _feature("F-011", (bid_notional - ask_notional) / denominator, "ratio", as_of, (), source_contract_ids=("S-05", "S-06"))


def persistent_imbalance(samples: Sequence[tuple[Decimal, Decimal]], window_seconds: Decimal, min_coverage: Decimal, as_of: datetime) -> FeatureValue:
    """F-012: time-weighted imbalance with explicit coverage."""
    coverage = sum((duration for _, duration in samples), D("0"))
    if window_seconds <= 0 or coverage <= 0 or coverage / window_seconds < min_coverage:
        return _feature("F-012", None, "ratio", as_of, (), "INSUFFICIENT_COVERAGE", source_contract_ids=("S-05", "S-06"))
    value = sum((imbalance * duration for imbalance, duration in samples), D("0")) / coverage
    return _feature("F-012", value, "ratio", as_of, (), source_contract_ids=("S-05", "S-06"))
