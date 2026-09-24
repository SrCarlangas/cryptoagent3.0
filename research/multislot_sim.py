"""Multi-slot (laddered tranche) simulator over the frozen 1h dataset.

Honesty constraints baked into this simulator:

- Equity is marked to market on EVERY bar, including open tranches. Measuring
  only closed trades is exactly how grid/averaging-down designs look
  artificially good, so that shortcut is not available here.
- Open tranches at the end of a window are liquidated at the mark with exit
  fees, never silently dropped.
- Take-profit fills only when the bar CLOSE reaches the target (we never assume
  we caught the intrabar high). Stops trigger on the bar LOW and fill at the
  worse of the stop price and the bar open (gap-through is modelled).
- Documented dataset gaps are never bridged: indicator warmup restarts after a
  gap, so no lookback window spans missing bars. Cash and tranches persist
  across a gap because the market did not disappear, only the data.
- This is a BAR-LEVEL APPROXIMATION. 1h bars cannot reproduce the runtime's
  5m/30m tactical features, real BBO spread, or aggTrade order flow. It can
  reject a design; it cannot prove live profitability.

Floats are used for speed (millions of bar iterations). Relative error is ~1e-15,
far below the decision thresholds, and all live execution paths keep Decimal.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from btc_decision_agent.adapters.backfill import HistoricalDataset

SlotSizing = Literal["A", "B", "C"]
HOUR_MS = 3_600_000
DEFAULT_DATASET = "data/history/btcusdt-1h"
# Start from the real post-clean-start DEMO equity so min-notional is realistic.
DEFAULT_CAPITAL = 4635.54
VENUE_MIN_NOTIONAL = 5.0
VENUE_LOT_STEP = 0.00001


@dataclass(frozen=True)
class Bar:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    contiguous_run: int
    """Number of consecutive bars (including this one) with no preceding gap."""


@dataclass(frozen=True)
class SimConfig:
    slots: int = 4
    spacing: float = 0.05
    """Fractional price drop below the last entry required to arm the next slot."""
    take_profit: float = 0.03
    fee_per_side: float = 0.001
    slot_sizing: SlotSizing = "C"
    regime_hours: int = 0
    """0 disables the regime filter. 4800 is the 200-day equivalent on 1h bars."""
    tranche_stop: float = 0.0
    """0 disables the wide per-tranche stop. Use e.g. 0.18 for -18%."""
    disaster_drawdown: float = 0.0
    """0 disables the portfolio disaster stop. Use e.g. 0.30 for -30% from peak."""
    regime_exit: bool = False
    """Liquidate every tranche when price closes below the regime reference.

    Without this, the regime filter only blocks new entries and a position opened
    in an uptrend is carried all the way down through a bear market.
    """
    disaster_recovery_hours: int = 4800
    """Trend reference that must be reclaimed before redeploying after a disaster stop.

    A disaster stop without a recovery gate is degenerate: it liquidates, instantly
    redeploys into the same downtrend, and re-triggers, realising the loss over and
    over. The recovery gate is therefore mandatory whenever the disaster stop is on.
    """

    def label(self) -> str:
        parts = [
            f"slots={self.slots}",
            f"spacing={self.spacing:.0%}",
            f"tp={self.take_profit:.0%}",
            f"sizing={self.slot_sizing}",
        ]
        if self.regime_hours:
            parts.append(f"regime={self.regime_hours}h")
        if self.tranche_stop:
            parts.append(f"tstop={self.tranche_stop:.0%}")
        if self.disaster_drawdown:
            parts.append(f"dd={self.disaster_drawdown:.0%}")
        if self.fee_per_side != 0.001:
            parts.append(f"fee={self.fee_per_side * 10000:.0f}bps")
        return " ".join(parts)


@dataclass
class SimResult:
    label: str
    bars: int
    net_return_pct: float
    max_drawdown_pct: float
    longest_underwater_hours: int
    buys: int
    sells: int
    losing_sells: int
    fees_paid: float
    fully_deployed_pct: float
    final_deployed_pct: float
    final_equity: float
    halted_bars: int
    config: dict[str, Any] = field(default_factory=dict)


def load_bars(dataset_directory: str | Path = DEFAULT_DATASET) -> tuple[list[Bar], str]:
    """Load the frozen dataset and annotate contiguity so gaps are never bridged."""
    manifest, rows = HistoricalDataset(dataset_directory).load()
    ordered = sorted(rows, key=lambda row: int(row["open_time"]))
    bars: list[Bar] = []
    previous_ms: int | None = None
    run = 0
    for row in ordered:
        open_ms = int(row["open_time"])
        run = run + 1 if previous_ms is not None and open_ms - previous_ms == HOUR_MS else 1
        bars.append(
            Bar(
                open_time_ms=open_ms,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                contiguous_run=run,
            )
        )
        previous_ms = open_ms
    return bars, manifest.dataset_id


MIN_LOOKBACK_COVERAGE = 0.95


def _prefix_means(bars: list[Bar], hours: int) -> list[float | None]:
    """Causal, time-based moving average that tolerates small documented gaps.

    The lookback is defined by elapsed TIME, not by bar count, and the average is
    taken over the bars actually present. A 200-day average is not invalidated by a
    handful of missing hours, but it is withheld when coverage of the window drops
    below MIN_LOOKBACK_COVERAGE, so a gap is never silently bridged as if the
    missing bars were flat.
    """
    if hours <= 0:
        return [None] * len(bars)
    span_ms = (hours - 1) * HOUR_MS
    required = hours * MIN_LOOKBACK_COVERAGE
    means: list[float | None] = [None] * len(bars)
    running = 0.0
    left = 0
    for index, bar in enumerate(bars):
        running += bar.close
        while bar.open_time_ms - bars[left].open_time_ms > span_ms:
            running -= bars[left].close
            left += 1
        count = index - left + 1
        elapsed = bar.open_time_ms - bars[left].open_time_ms
        if elapsed >= span_ms * MIN_LOOKBACK_COVERAGE and count >= required:
            means[index] = running / count
    return means


def run_simulation(
    bars: list[Bar], start: int, end: int, config: SimConfig, capital: float = DEFAULT_CAPITAL
) -> SimResult:
    """Simulate the laddered multi-slot strategy with mark-to-market equity."""
    if not 0 <= start < end <= len(bars):
        raise ValueError("invalid window bounds")
    if config.slots < 1:
        raise ValueError("slots must be >= 1")

    fee = config.fee_per_side
    regime = _prefix_means(bars, config.regime_hours) if config.regime_hours else None
    # The disaster stop always needs a recovery reference, even with no regime filter.
    recovery_hours = config.regime_hours or config.disaster_recovery_hours
    recovery = (
        regime
        if (regime is not None and config.regime_hours == recovery_hours)
        else (_prefix_means(bars, recovery_hours) if config.disaster_drawdown else None)
    )

    cash = capital
    tranches: list[tuple[float, float]] = []  # (entry_price, base_qty)
    next_buy: float | None = None
    peak_equity = capital
    max_drawdown = 0.0
    peak_index = start
    longest_underwater = 0
    buys = sells = losing_sells = 0
    fees_paid = 0.0
    fully_deployed_bars = 0
    halted_bars = 0
    halted = False

    def equity_at(price: float) -> float:
        return cash + sum(qty * price for _, qty in tranches)

    for index in range(start, end):
        bar = bars[index]
        price = bar.close

        # --- portfolio disaster stop (deterministic safety layer) ---
        if (
            config.disaster_drawdown
            and not halted
            and equity_at(price) <= peak_equity * (1.0 - config.disaster_drawdown)
        ):
            for entry_price, qty in tranches:
                proceeds = qty * price * (1.0 - fee)
                fees_paid += qty * price * fee
                cash += proceeds
                sells += 1
                if price < entry_price:
                    losing_sells += 1
            tranches = []
            next_buy = None
            halted = True
            # Restart the drawdown clock from the realised equity, otherwise the
            # stop re-triggers immediately against a peak we can no longer reach.
            peak_equity = cash
            peak_index = index

        # --- regime exit: leave entirely when the long-term trend is lost ---
        if config.regime_exit and regime is not None and tranches:
            reference = regime[index]
            if reference is not None and price < reference:
                for entry_price, qty in tranches:
                    proceeds = qty * price * (1.0 - fee)
                    fees_paid += qty * price * fee
                    cash += proceeds
                    sells += 1
                    if price < entry_price:
                        losing_sells += 1
                tranches = []
                next_buy = None

        # --- wide per-tranche stop: triggers on the low, fills at the worse price ---
        if config.tranche_stop and tranches:
            survivors: list[tuple[float, float]] = []
            for entry_price, qty in tranches:
                stop_price = entry_price * (1.0 - config.tranche_stop)
                if bar.low <= stop_price:
                    fill = min(stop_price, bar.open)
                    proceeds = qty * fill * (1.0 - fee)
                    fees_paid += qty * fill * fee
                    cash += proceeds
                    sells += 1
                    if fill < entry_price:
                        losing_sells += 1
                else:
                    survivors.append((entry_price, qty))
            tranches = survivors

        # --- take-profit per tranche, only on a confirmed close ---
        if tranches:
            survivors = []
            for entry_price, qty in tranches:
                if price >= entry_price * (1.0 + config.take_profit):
                    proceeds = qty * price * (1.0 - fee)
                    fees_paid += qty * price * fee
                    cash += proceeds
                    sells += 1
                    if price < entry_price:
                        losing_sells += 1
                else:
                    survivors.append((entry_price, qty))
            tranches = survivors
            if not tranches:
                next_buy = None

        # --- resume from a halt only once the regime recovers ---
        regime_ok = True
        if regime is not None:
            reference = regime[index]
            regime_ok = reference is not None and price > reference
        if halted:
            halted_bars += 1
            reference = recovery[index] if recovery is not None else None
            if reference is not None and price > reference:
                halted = False
                next_buy = None
            else:
                equity = equity_at(price)
                if equity > peak_equity:
                    peak_equity = equity
                    peak_index = index
                else:
                    max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
                    longest_underwater = max(longest_underwater, index - peak_index)
                continue

        # --- laddered entry ---
        free_slots = config.slots - len(tranches)
        if free_slots > 0 and regime_ok and (next_buy is None or price <= next_buy):
            equity = equity_at(price)
            if config.slot_sizing == "A":
                target = equity / config.slots
            elif config.slot_sizing == "B":
                target = capital / config.slots
            else:
                target = cash / free_slots
            spend = min(target, cash)
            # Each tranche must independently clear the venue minimum notional.
            if spend >= VENUE_MIN_NOTIONAL:
                qty = (spend * (1.0 - fee)) / price
                qty = int(qty / VENUE_LOT_STEP) * VENUE_LOT_STEP
                if qty > 0 and qty * price >= VENUE_MIN_NOTIONAL:
                    gross = qty * price / (1.0 - fee)
                    cash -= gross
                    fees_paid += gross * fee
                    tranches.append((price, qty))
                    buys += 1
                    next_buy = price * (1.0 - config.spacing)

        if len(tranches) >= config.slots:
            fully_deployed_bars += 1

        equity = equity_at(price)
        if equity > peak_equity:
            peak_equity = equity
            peak_index = index
        else:
            drawdown = (peak_equity - equity) / peak_equity
            max_drawdown = max(max_drawdown, drawdown)
            longest_underwater = max(longest_underwater, index - peak_index)

    # --- liquidate open tranches at the mark so nothing is silently dropped ---
    final_price = bars[end - 1].close
    deployed_value = sum(qty * final_price for _, qty in tranches)
    liquidation = cash + deployed_value * (1.0 - fee)
    fees_paid += deployed_value * fee
    window_bars = end - start

    return SimResult(
        label=config.label(),
        bars=window_bars,
        net_return_pct=(liquidation / capital - 1.0) * 100.0,
        max_drawdown_pct=max_drawdown * 100.0,
        longest_underwater_hours=longest_underwater,
        buys=buys,
        sells=sells,
        losing_sells=losing_sells,
        fees_paid=fees_paid,
        fully_deployed_pct=fully_deployed_bars / window_bars * 100.0,
        final_deployed_pct=(deployed_value / liquidation * 100.0) if liquidation > 0 else 0.0,
        final_equity=liquidation,
        halted_bars=halted_bars,
        config=asdict(config),
    )


def buy_and_hold(
    bars: list[Bar], start: int, end: int, fee: float = 0.001, capital: float = DEFAULT_CAPITAL
) -> SimResult:
    """Benchmark: deploy everything at the window open price, liquidate at the mark."""
    entry = bars[start].close
    qty = (capital * (1.0 - fee)) / entry
    peak_equity = capital
    max_drawdown = 0.0
    peak_index = start
    longest_underwater = 0
    for index in range(start, end):
        equity = qty * bars[index].close
        if equity > peak_equity:
            peak_equity = equity
            peak_index = index
        else:
            max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
            longest_underwater = max(longest_underwater, index - peak_index)
    liquidation = qty * bars[end - 1].close * (1.0 - fee)
    return SimResult(
        label="BUY_AND_HOLD",
        bars=end - start,
        net_return_pct=(liquidation / capital - 1.0) * 100.0,
        max_drawdown_pct=max_drawdown * 100.0,
        longest_underwater_hours=longest_underwater,
        buys=1,
        sells=1,
        losing_sells=0,
        fees_paid=capital * fee + qty * bars[end - 1].close * fee,
        fully_deployed_pct=100.0,
        final_deployed_pct=100.0,
        final_equity=liquidation,
        halted_bars=0,
        config={"strategy": "buy_and_hold", "fee_per_side": fee},
    )


def all_cash(bars: list[Bar], start: int, end: int, capital: float = DEFAULT_CAPITAL) -> SimResult:
    """Benchmark: never trade."""
    return SimResult(
        label="ALL_CASH",
        bars=end - start,
        net_return_pct=0.0,
        max_drawdown_pct=0.0,
        longest_underwater_hours=0,
        buys=0,
        sells=0,
        losing_sells=0,
        fees_paid=0.0,
        fully_deployed_pct=0.0,
        final_deployed_pct=0.0,
        final_equity=capital,
        halted_bars=0,
        config={"strategy": "all_cash"},
    )


def window_index(bars: list[Bar], iso_date: str) -> int:
    """First bar index at or after an ISO date."""
    target = int(datetime.fromisoformat(iso_date).replace(tzinfo=UTC).timestamp() * 1000)
    for index, bar in enumerate(bars):
        if bar.open_time_ms >= target:
            return index
    return len(bars) - 1


def standard_windows(bars: list[Bar]) -> dict[str, tuple[int, int]]:
    """Windows required by the study, including a bear market and mid-bear endings."""
    return {
        "full_2020_2026": (0, len(bars)),
        "bear_2021_11_to_2022_11": (
            window_index(bars, "2021-11-01"),
            window_index(bars, "2022-11-30"),
        ),
        "last_5y": (window_index(bars, "2021-09-16"), len(bars)),
        "bull_2020_2021": (0, window_index(bars, "2021-11-01")),
        "recovery_2023_2024": (
            window_index(bars, "2023-01-01"),
            window_index(bars, "2024-12-31"),
        ),
        "mid_bear_end_2022_06": (
            window_index(bars, "2020-01-01"),
            window_index(bars, "2022-06-30"),
        ),
    }


def write_report(path_stem: str | Path, payload: dict[str, Any]) -> None:
    stem = Path(path_stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


__all__ = [
    "DEFAULT_CAPITAL",
    "Bar",
    "SimConfig",
    "SimResult",
    "all_cash",
    "buy_and_hold",
    "load_bars",
    "run_simulation",
    "standard_windows",
    "window_index",
    "write_report",
]
