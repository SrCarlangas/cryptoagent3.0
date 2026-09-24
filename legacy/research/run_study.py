"""Multi-horizon, multi-mechanism BTC study with an honest train/test scorecard.

Precomputes causal indicators once per horizon (O(n)) so the 1h series is tractable.
Parameters are chosen only by construction/train; the test split is read once for
reporting. Every completed trade pays a conservative round-trip cost in bps.

Usage: .venv/bin/python -m research.run_study
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from research.engine import Candle, load_candles, split_train_test

D = Decimal
COST_BPS = D("64.242622")
BUFFER = D("10")
NET_COST = (COST_BPS + BUFFER) / D("10000")


@dataclass(frozen=True)
class Result:
    label: str
    horizon: str
    split: str
    bars: int
    trades: int
    net_bps_avg: Decimal
    gross_bps_avg: Decimal
    net_total_pct: Decimal
    win_rate: Decimal
    max_dd_pct: Decimal
    worst_pct: Decimal
    buy_hold_pct: Decimal
    exposure: Decimal


def _sma_series(closes: Sequence[Decimal], n: int) -> list[Decimal | None]:
    out: list[Decimal | None] = [None] * len(closes)
    if n <= 0 or len(closes) < n:
        return out
    running = sum(closes[:n], D("0"))
    out[n - 1] = running / D(n)
    for i in range(n, len(closes)):
        running += closes[i] - closes[i - n]
        out[i] = running / D(n)
    return out


def _atr_fraction_series(candles: Sequence[Candle], n: int) -> list[Decimal | None]:
    out: list[Decimal | None] = [None] * len(candles)
    trs = [D("0")] * len(candles)
    for i in range(1, len(candles)):
        high, low, prev_close = candles[i].high, candles[i].low, candles[i - 1].close
        trs[i] = max(high - low, abs(high - prev_close), abs(low - prev_close))
    running = sum(trs[1 : n + 1], D("0"))
    if len(candles) > n:
        close = candles[n].close
        out[n] = (running / D(n)) / close if close > 0 else None
    for i in range(n + 1, len(candles)):
        running += trs[i] - trs[i - n]
        close = candles[i].close
        out[i] = (running / D(n)) / close if close > 0 else None
    return out


def _rolling_high(candles: Sequence[Candle], lookback: int) -> list[Decimal | None]:
    out: list[Decimal | None] = [None] * len(candles)
    for i in range(lookback, len(candles)):
        out[i] = max(c.high for c in candles[i - lookback : i])
    return out


def _rolling_low(candles: Sequence[Candle], lookback: int) -> list[Decimal | None]:
    out: list[Decimal | None] = [None] * len(candles)
    for i in range(lookback, len(candles)):
        out[i] = min(c.low for c in candles[i - lookback : i])
    return out


def _run(
    candles: Sequence[Candle],
    *,
    label: str,
    horizon: str,
    split: str,
    enter: list[bool],
    leave: list[bool],
    warmup: int,
    max_holding: int,
    stop: Decimal | None,
) -> Result:
    nets: list[Decimal] = []
    grosses: list[Decimal] = []
    in_pos = False
    entry_price = D("0")
    entry_i = 0
    exposed = 0
    for i in range(warmup, len(candles)):
        price = candles[i].close
        if in_pos:
            exposed += 1
            drop = price / entry_price - D("1")
            hit = (stop is not None and drop <= -stop) or (i - entry_i >= max_holding) or leave[i]
            if hit:
                gross = price / entry_price - D("1")
                grosses.append(gross)
                nets.append(gross - NET_COST)
                in_pos = False
            continue
        if enter[i]:
            in_pos, entry_price, entry_i = True, price, i
    return _summ(nets, grosses, candles, label=label, horizon=horizon, split=split, exposed=exposed)


def _summ(nets: list[Decimal], grosses: list[Decimal], candles: Sequence[Candle], *, label: str, horizon: str, split: str, exposed: int) -> Result:
    equity = peak = D("1")
    worst_dd = D("0")
    for r in nets:
        equity *= D("1") + r
        peak = max(peak, equity)
        worst_dd = max(worst_dd, (peak - equity) / peak)
    count = len(nets)
    wins = sum(1 for r in nets if r > 0)
    bh = (candles[-1].close / candles[0].close - D("1")) if candles else D("0")
    return Result(
        label=label,
        horizon=horizon,
        split=split,
        bars=len(candles),
        trades=count,
        net_bps_avg=(sum(nets, D("0")) / D(count) * D("10000")) if count else D("0"),
        gross_bps_avg=(sum(grosses, D("0")) / D(count) * D("10000")) if count else D("0"),
        net_total_pct=(equity - D("1")) * D("100"),
        win_rate=(D(wins) / D(count)) if count else D("0"),
        max_dd_pct=worst_dd * D("100"),
        worst_pct=(min(nets) * D("100")) if nets else D("0"),
        buy_hold_pct=bh * D("100"),
        exposure=(D(exposed) / D(len(candles))) if candles else D("0"),
    )


def _fmt(r: Result) -> str:
    return (
        f"{r.label:26s} {r.horizon:>3s} {r.split:>5s} "
        f"trades={r.trades:>5d} net={r.net_bps_avg:8.2f}bps gross={r.gross_bps_avg:8.2f}bps "
        f"total={r.net_total_pct:9.2f}% win={r.win_rate:.2f} maxDD={r.max_dd_pct:6.2f}% "
        f"worst={r.worst_pct:7.2f}% b&h={r.buy_hold_pct:9.2f}% expo={r.exposure:.2f}"
    )


def trend(candles: Sequence[Candle], fast: int, slow: int) -> tuple[list[bool], list[bool], int]:
    closes = [c.close for c in candles]
    f = _sma_series(closes, fast)
    s = _sma_series(closes, slow)
    enter = [f[i] is not None and s[i] is not None and f[i] > s[i] and closes[i] > s[i] for i in range(len(candles))]  # type: ignore[operator]
    leave = [f[i] is None or s[i] is None or f[i] < s[i] for i in range(len(candles))]  # type: ignore[operator]
    return enter, leave, slow + 1


def breakout(candles: Sequence[Candle], lookback: int, atr_n: int, atr_min: Decimal) -> tuple[list[bool], list[bool], int]:
    highs = _rolling_high(candles, lookback)
    lows = _rolling_low(candles, lookback)
    af = _atr_fraction_series(candles, atr_n)
    enter = [highs[i] is not None and af[i] is not None and af[i] >= atr_min and candles[i].close > highs[i] for i in range(len(candles))]  # type: ignore[operator]
    leave = [lows[i] is not None and candles[i].close < lows[i] for i in range(len(candles))]  # type: ignore[operator]
    return enter, leave, lookback + atr_n + 1


def reversion(candles: Sequence[Candle], n: int, drop_frac: Decimal) -> tuple[list[bool], list[bool], int]:
    closes = [c.close for c in candles]
    mean = _sma_series(closes, n)
    enter = [
        i > 0 and mean[i] is not None and mean[i] > 0 and (closes[i] / mean[i] - D("1")) <= -drop_frac and closes[i] > closes[i - 1]  # type: ignore[operator]
        for i in range(len(candles))
    ]
    leave = [mean[i] is None or closes[i] >= mean[i] for i in range(len(candles))]  # type: ignore[operator]
    return enter, leave, n + 1


def evaluate(label: str, horizon: str, builder, *, max_holding: int, stop: Decimal | None) -> tuple[Result, Result]:
    candles = load_candles(horizon)
    train, test = split_train_test(candles)
    enter_tr, leave_tr, warmup = builder(train)
    enter_te, leave_te, _ = builder(test)
    r_tr = _run(train, label=label, horizon=horizon, split="train", enter=enter_tr, leave=leave_tr, warmup=warmup, max_holding=max_holding, stop=stop)
    r_te = _run(test, label=label, horizon=horizon, split="test", enter=enter_te, leave=leave_te, warmup=warmup, max_holding=max_holding, stop=stop)
    return r_tr, r_te


def main() -> None:
    print("=== BTC/USDT long-only | cost 74.24 bps round-trip (with buffer) | train 60% / test 40% ===\n")
    configs = [
        ("trend_24_168", "1h", lambda c: trend(c, 24, 168), 336, None),
        ("trend_24_168_stop15", "1h", lambda c: trend(c, 24, 168), 336, D("0.15")),
        ("trend_12_42", "4h", lambda c: trend(c, 12, 42), 90, None),
        ("trend_12_42_stop15", "4h", lambda c: trend(c, 12, 42), 90, D("0.15")),
        ("trend_10_50", "1d", lambda c: trend(c, 10, 50), 90, None),
        ("trend_10_50_stop20", "1d", lambda c: trend(c, 10, 50), 90, D("0.20")),
        ("trend_20_100", "1d", lambda c: trend(c, 20, 100), 120, None),
        ("breakout_30", "4h", lambda c: breakout(c, 30, 14, D("0.005")), 60, D("0.12")),
        ("breakout_20", "1d", lambda c: breakout(c, 20, 14, D("0.004")), 40, D("0.15")),
        ("reversion_42", "4h", lambda c: reversion(c, 42, D("0.08")), 30, D("0.20")),
        ("reversion_20", "1d", lambda c: reversion(c, 20, D("0.12")), 20, D("0.25")),
    ]
    for label, horizon, builder, hold, stop in configs:
        r_tr, r_te = evaluate(label, horizon, builder, max_holding=hold, stop=stop)
        print(_fmt(r_tr))
        print(_fmt(r_te))
        print()
    for horizon in ("1h", "4h", "1d"):
        candles = load_candles(horizon)
        _t, test = split_train_test(candles)
        bh = (test[-1].close / test[0].close - D("1")) * D("100") if test else D("0")
        print(f"buy_and_hold               {horizon:>3s}  test  total={bh:9.2f}%")


if __name__ == "__main__":
    main()
