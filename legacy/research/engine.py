"""Reusable train/test backtest engine over the frozen 1h dataset.

Design choices that keep the study honest:
- Resampling to 4h/1d is causal (a higher bar closes only after its last 1h bar).
- Train/test split is chronological; parameters are chosen on train only.
- Every completed trade pays a conservative round-trip cost in bps.
- We report net edge, drawdown, tail loss and comparison vs buy&hold and cash.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

D = Decimal
_INTERVAL_HOURS = {"1h": 1, "4h": 4, "1d": 24}
_DEFAULT_TRAIN_FRACTION = D("0.6")


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class Trade:
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    gross_return: Decimal
    net_return: Decimal
    holding_bars: int
    exit_reason: str


@dataclass(frozen=True)
class BacktestResult:
    label: str
    horizon: str
    split: str
    bars: int
    trades: int
    coverage: Decimal
    gross_bps_avg: Decimal
    net_bps_avg: Decimal
    net_total_return: Decimal
    win_rate: Decimal
    max_drawdown: Decimal
    worst_trade: Decimal
    buy_hold_return: Decimal
    exposure_fraction: Decimal


def load_candles(interval: str = "1h") -> tuple[Candle, ...]:
    from btc_decision_agent.adapters.backfill import HistoricalDataset, as_decimal_bars

    _manifest, rows = HistoricalDataset("data/history/btcusdt-1h").load()
    base = as_decimal_bars(rows)
    candles = [
        Candle(row["open_time"], row["close_time"], row["open"], row["high"], row["low"], row["close"], row["base_volume"])
        for row in base
    ]
    if interval == "1h":
        return tuple(candles)
    return _resample(candles, interval)


def _resample(candles: Sequence[Candle], interval: str) -> tuple[Candle, ...]:
    """Aggregate contiguous 1h candles into higher timeframe candles, causally."""
    hours = _INTERVAL_HOURS[interval]
    step = timedelta(hours=1)
    out: list[Candle] = []
    bucket: list[Candle] = []
    anchor: datetime | None = None
    previous_close: datetime | None = None
    for candle in candles:
        if previous_close is not None and candle.open_time - previous_close > timedelta(seconds=1):
            bucket, anchor = [], None  # gap: drop the partial bucket
        if anchor is None:
            anchor = candle.open_time
        bucket.append(candle)
        previous_close = candle.close_time
        if len(bucket) == hours:
            out.append(
                Candle(
                    open_time=bucket[0].open_time,
                    close_time=bucket[0].open_time + hours * step,
                    open=bucket[0].open,
                    high=max(c.high for c in bucket),
                    low=min(c.low for c in bucket),
                    close=bucket[-1].close,
                    volume=sum((c.volume for c in bucket), D("0")),
                )
            )
            bucket, anchor = [], None
    return tuple(out)


def split_train_test(candles: Sequence[Candle], train_fraction: Decimal = _DEFAULT_TRAIN_FRACTION) -> tuple[tuple[Candle, ...], tuple[Candle, ...]]:
    cut = int(len(candles) * float(train_fraction))
    return tuple(candles[:cut]), tuple(candles[cut:])


# --- indicator helpers (causal: index i uses only candles[:i+1]) ---

def sma(values: Sequence[Decimal], n: int) -> Decimal | None:
    if len(values) < n:
        return None
    return sum(values[-n:], D("0")) / D(n)


def atr_fraction(candles: Sequence[Candle], n: int) -> Decimal | None:
    if len(candles) < n + 1:
        return None
    trs = []
    for i in range(len(candles) - n, len(candles)):
        high, low, prev_close = candles[i].high, candles[i].low, candles[i - 1].close
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    close = candles[-1].close
    return (sum(trs, D("0")) / D(n)) / close if close > 0 else None


# --- generic long-only backtest loop ---

Signal = Callable[[int, Sequence[Candle]], bool]


def backtest_long_only(
    candles: Sequence[Candle],
    *,
    label: str,
    horizon: str,
    split: str,
    entry_signal: Signal,
    exit_signal: Signal,
    round_trip_bps: Decimal,
    warmup: int,
    max_holding_bars: int,
    stop_loss_frac: Decimal | None,
) -> BacktestResult:
    """Long/flat backtest. entry_signal/exit_signal see only past+current closed bars."""
    net_cost = round_trip_bps / D("10000")
    trades: list[Trade] = []
    in_position = False
    entry_price = D("0")
    entry_index = 0
    exposed_bars = 0
    for i in range(warmup, len(candles)):
        window = candles[: i + 1]
        price = candles[i].close
        if in_position:
            exposed_bars += 1
            holding = i - entry_index
            reason: str | None = None
            drop = price / entry_price - D("1")
            if stop_loss_frac is not None and drop <= -stop_loss_frac:
                reason = "STOP"
            elif holding >= max_holding_bars:
                reason = "TIME"
            elif exit_signal(i, window):
                reason = "SIGNAL"
            if reason is not None:
                gross = price / entry_price - D("1")
                trades.append(
                    Trade(
                        entry_time=candles[entry_index].close_time,
                        exit_time=candles[i].close_time,
                        entry_price=entry_price,
                        exit_price=price,
                        gross_return=gross,
                        net_return=gross - net_cost,
                        holding_bars=holding,
                        exit_reason=reason,
                    )
                )
                in_position = False
            continue
        if entry_signal(i, window):
            in_position = True
            entry_price = price
            entry_index = i
    return _summarize(trades, candles, label=label, horizon=horizon, split=split, exposed_bars=exposed_bars)


def _summarize(trades: Sequence[Trade], candles: Sequence[Candle], *, label: str, horizon: str, split: str, exposed_bars: int) -> BacktestResult:
    nets = [t.net_return for t in trades]
    grosses = [t.gross_return for t in trades]
    equity = D("1")
    peak = D("1")
    worst_dd = D("0")
    for r in nets:
        equity *= (D("1") + r)
        peak = max(peak, equity)
        worst_dd = max(worst_dd, (peak - equity) / peak)
    wins = sum(1 for r in nets if r > 0)
    buy_hold = (candles[-1].close / candles[0].close - D("1")) if candles else D("0")
    count = len(trades)
    return BacktestResult(
        label=label,
        horizon=horizon,
        split=split,
        bars=len(candles),
        trades=count,
        coverage=(D(count) / D(len(candles))) if candles else D("0"),
        gross_bps_avg=(sum(grosses, D("0")) / D(count) * D("10000")) if count else D("0"),
        net_bps_avg=(sum(nets, D("0")) / D(count) * D("10000")) if count else D("0"),
        net_total_return=(equity - D("1")),
        win_rate=(D(wins) / D(count)) if count else D("0"),
        max_drawdown=worst_dd,
        worst_trade=min(nets) if nets else D("0"),
        buy_hold_return=buy_hold,
        exposure_fraction=(D(exposed_bars) / D(len(candles))) if candles else D("0"),
    )


def format_result(result: BacktestResult) -> str:
    return (
        f"{result.label:28s} {result.horizon:>3s} {result.split:>5s} "
        f"bars={result.bars:>6d} trades={result.trades:>5d} "
        f"cov={result.coverage:.4f} gross={result.gross_bps_avg:8.2f}bps net={result.net_bps_avg:8.2f}bps "
        f"total={result.net_total_return*100:8.2f}% win={result.win_rate:.2f} "
        f"maxDD={result.max_drawdown*100:6.2f}% worst={result.worst_trade*100:7.2f}% "
        f"b&h={result.buy_hold_return*100:8.2f}% expo={result.exposure_fraction:.2f}"
    )


def now_utc() -> datetime:
    return datetime.now(tz=UTC)
