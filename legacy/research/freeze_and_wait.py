"""Model the user's 'freeze and wait' tactic vs a stop-loss, and measure tail risk.

Tactic: enter long; if price falls, do NOT sell -- hold until it recovers to a
target profit (or forever). This usually produces many small wins and rare, huge
losses. We quantify that asymmetry on the frozen 1d series.

Usage: .venv/bin/python -m research.freeze_and_wait
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from research.engine import Candle, load_candles, split_train_test

D = Decimal
NET_COST = D("74.242622") / D("10000")


def simulate(candles: Sequence[Candle], *, take_profit: Decimal, use_stop: bool, stop: Decimal, max_hold: int) -> dict[str, object]:
    """Enter every N bars when flat; exit on take-profit, optional stop, or (freeze) never by drawdown."""
    nets: list[Decimal] = []
    holds: list[int] = []
    in_pos = False
    entry_price = D("0")
    entry_i = 0
    forced_open_at_end = D("0")
    entry_stride = 24  # attempt a new entry roughly monthly on 1d bars
    for i in range(len(candles)):
        price = candles[i].close
        if in_pos:
            change = price / entry_price - D("1")
            hold = i - entry_i
            reason = None
            if change >= take_profit:
                reason = "TAKE_PROFIT"
            elif use_stop and change <= -stop:
                reason = "STOP"
            elif use_stop and hold >= max_hold:
                # only the stop-managed variant honors a time stop; the pure
                # 'freeze' variant waits indefinitely, exposing its tail risk
                reason = "TIME"
            if reason is not None:
                nets.append(change - NET_COST)
                holds.append(hold)
                in_pos = False
            continue
        if i % entry_stride == 0:
            in_pos, entry_price, entry_i = True, price, i
    if in_pos:  # position never recovered: mark to last price (the tail risk)
        forced_open_at_end = candles[-1].close / entry_price - D("1") - NET_COST
    equity = peak = D("1")
    worst_dd = D("0")
    for r in nets:
        equity *= D("1") + r
        peak = max(peak, equity)
        worst_dd = max(worst_dd, (peak - equity) / peak)
    return {
        "closed_trades": len(nets),
        "win_rate": (sum(1 for r in nets if r > 0) / len(nets)) if nets else 0.0,
        "avg_net_pct": (float(sum(nets, D("0")) / D(len(nets))) * 100) if nets else 0.0,
        "worst_closed_pct": (float(min(nets)) * 100) if nets else 0.0,
        "closed_equity_pct": float((equity - D("1")) * 100),
        "max_dd_pct": float(worst_dd * 100),
        "open_position_left": in_pos,
        "open_unrealized_pct": float(forced_open_at_end * 100) if in_pos else None,
    }


def main() -> None:
    candles = load_candles("1d")
    _train, test = split_train_test(candles)
    print("=== 'Freeze and wait' vs stop-loss on 1d test split ===\n")
    scenarios = [
        ("freeze_wait_tp10", simulate(test, take_profit=D("0.10"), use_stop=False, stop=D("0"), max_hold=10_000)),
        ("stop15_tp10", simulate(test, take_profit=D("0.10"), use_stop=True, stop=D("0.15"), max_hold=60)),
        ("stop08_tp10", simulate(test, take_profit=D("0.10"), use_stop=True, stop=D("0.08"), max_hold=60)),
    ]
    for label, stats in scenarios:
        print(label)
        for key, value in stats.items():
            print(f"  {key}: {value}")
        print()


if __name__ == "__main__":
    main()
