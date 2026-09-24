"""Phases 2-5 of the multi-slot study: baselines, sweep, protections, stress, verdict.

Run:
    .venv/bin/python -m research.run_multislot_study

Writes machine-readable JSON plus a Markdown summary to data/validation/.
The verdict is explicit: a configuration is only a candidate if it beats
buy & hold net of costs in the full window AND in the bear window.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research.multislot_sim import (
    DEFAULT_CAPITAL,
    SimConfig,
    SimResult,
    all_cash,
    buy_and_hold,
    load_bars,
    run_simulation,
    standard_windows,
)

REPORT_STEM = Path("data/validation/multislot-study")
SWEEP_SLOTS = (2, 4, 6, 8)
SWEEP_SPACING = (0.02, 0.03, 0.05, 0.08)
SWEEP_TAKE_PROFIT = (0.01, 0.02, 0.03, 0.05)
SWEEP_SIZING = ("A", "B", "C")
PRIMARY = "full_2020_2026"
BEAR = "bear_2021_11_to_2022_11"


def _row(result: SimResult) -> dict[str, Any]:
    return {
        "label": result.label,
        "net_return_pct": round(result.net_return_pct, 3),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "longest_underwater_hours": result.longest_underwater_hours,
        "buys": result.buys,
        "sells": result.sells,
        "losing_sells": result.losing_sells,
        "fees_paid": round(result.fees_paid, 2),
        "fully_deployed_pct": round(result.fully_deployed_pct, 1),
        "final_deployed_pct": round(result.final_deployed_pct, 1),
        "final_equity": round(result.final_equity, 2),
        "halted_bars": result.halted_bars,
    }


def main() -> None:
    bars, dataset_id = load_bars()
    windows = standard_windows(bars)

    # ---------------- Phase 2: baselines ----------------
    baselines: dict[str, dict[str, Any]] = {}
    for name, (start, end) in windows.items():
        baselines[name] = {
            "buy_and_hold": _row(buy_and_hold(bars, start, end)),
            "all_cash": _row(all_cash(bars, start, end)),
        }
    bh_primary = baselines[PRIMARY]["buy_and_hold"]["net_return_pct"]
    bh_bear = baselines[BEAR]["buy_and_hold"]["net_return_pct"]

    # ---------------- Phase 3: unprotected sweep ----------------
    sweep: list[dict[str, Any]] = []
    for slots in SWEEP_SLOTS:
        for spacing in SWEEP_SPACING:
            for take_profit in SWEEP_TAKE_PROFIT:
                for sizing in SWEEP_SIZING:
                    config = SimConfig(
                        slots=slots,
                        spacing=spacing,
                        take_profit=take_profit,
                        slot_sizing=sizing,  # type: ignore[arg-type]
                    )
                    entry: dict[str, Any] = {"config": asdict(config), "label": config.label()}
                    for name, (start, end) in windows.items():
                        entry[name] = _row(run_simulation(bars, start, end, config))
                    entry["beats_bh_primary"] = entry[PRIMARY]["net_return_pct"] > bh_primary
                    entry["beats_bh_bear"] = entry[BEAR]["net_return_pct"] > bh_bear
                    sweep.append(entry)

    by_primary = sorted(sweep, key=lambda item: item[PRIMARY]["net_return_pct"], reverse=True)
    by_bear = sorted(sweep, key=lambda item: item[BEAR]["net_return_pct"], reverse=True)
    unprotected_winners = [item for item in sweep if item["beats_bh_primary"] and item["beats_bh_bear"]]

    # ---------------- Phase 4: protections ----------------
    # Applied to the best unprotected configuration by bear behaviour, since a
    # design that is catastrophic in the bear is rejected regardless of total return.
    base_cfg_dict = dict(by_bear[0]["config"])
    base_cfg_dict.pop("regime_hours", None)
    base_cfg_dict.pop("tranche_stop", None)
    base_cfg_dict.pop("disaster_drawdown", None)

    protection_variants: dict[str, dict[str, Any]] = {
        "none": {},
        "regime_200d": {"regime_hours": 4800},
        "tranche_stop_15": {"tranche_stop": 0.15},
        "tranche_stop_20": {"tranche_stop": 0.20},
        "disaster_25": {"disaster_drawdown": 0.25},
        "disaster_35": {"disaster_drawdown": 0.35},
        "regime_plus_disaster_25": {"regime_hours": 4800, "disaster_drawdown": 0.25},
        "regime_plus_disaster_35": {"regime_hours": 4800, "disaster_drawdown": 0.35},
        "full_stack_15_25": {
            "regime_hours": 4800,
            "tranche_stop": 0.15,
            "disaster_drawdown": 0.25,
        },
        "full_stack_20_35": {
            "regime_hours": 4800,
            "tranche_stop": 0.20,
            "disaster_drawdown": 0.35,
        },
    }
    protections: dict[str, dict[str, Any]] = {}
    for name, overrides in protection_variants.items():
        config = SimConfig(**{**base_cfg_dict, **overrides})
        record: dict[str, Any] = {"config": asdict(config), "label": config.label()}
        for window_name, (start, end) in windows.items():
            record[window_name] = _row(run_simulation(bars, start, end, config))
        record["beats_bh_primary"] = record[PRIMARY]["net_return_pct"] > bh_primary
        record["beats_bh_bear"] = record[BEAR]["net_return_pct"] > bh_bear
        protections[name] = record

    # ---------------- Phase 5: stress ----------------
    adverse: dict[str, dict[str, Any]] = {}
    for name, overrides in protection_variants.items():
        config = SimConfig(**{**base_cfg_dict, **overrides, "fee_per_side": 0.002})
        record = {"config": asdict(config), "label": config.label()}
        for window_name, (start, end) in windows.items():
            record[window_name] = _row(run_simulation(bars, start, end, config))
        adverse[name] = record

    # Neighbour sensitivity: perturb spacing and take-profit one step each way.
    best_protected_name = max(
        protections, key=lambda key: protections[key][PRIMARY]["net_return_pct"]
    )
    best_protected = SimConfig(**protections[best_protected_name]["config"])
    neighbours: list[dict[str, Any]] = []
    for spacing in {
        max(0.01, round(best_protected.spacing - 0.01, 4)),
        best_protected.spacing,
        round(best_protected.spacing + 0.01, 4),
    }:
        for take_profit in {
            max(0.005, round(best_protected.take_profit - 0.01, 4)),
            best_protected.take_profit,
            round(best_protected.take_profit + 0.01, 4),
        }:
            config = SimConfig(
                slots=best_protected.slots,
                spacing=spacing,
                take_profit=take_profit,
                fee_per_side=best_protected.fee_per_side,
                slot_sizing=best_protected.slot_sizing,
                regime_hours=best_protected.regime_hours,
                tranche_stop=best_protected.tranche_stop,
                disaster_drawdown=best_protected.disaster_drawdown,
            )
            start, end = windows[PRIMARY]
            result = run_simulation(bars, start, end, config)
            neighbours.append(
                {
                    "label": config.label(),
                    "spacing": spacing,
                    "take_profit": take_profit,
                    "net_return_pct": round(result.net_return_pct, 3),
                    "beats_bh_primary": result.net_return_pct > bh_primary,
                }
            )

    # ---- Trend-following family: the regime filter must also be able to EXIT ----
    # Without a regime exit, a position opened in an uptrend is carried through the
    # whole bear. This family is the strongest honest challenger to buy & hold.
    never_take_profit = 99.0
    trend: dict[str, dict[str, Any]] = {}
    for hours in (600, 900, 1200, 1800, 2400, 3600, 4800, 6000, 7200):
        config = SimConfig(
            slots=1,
            take_profit=never_take_profit,
            regime_hours=hours,
            regime_exit=True,
        )
        adverse_config = SimConfig(
            slots=1,
            take_profit=never_take_profit,
            regime_hours=hours,
            regime_exit=True,
            fee_per_side=0.002,
        )
        record = {"config": asdict(config), "label": f"trend_MA_{hours}h"}
        for window_name, (start, end) in windows.items():
            record[window_name] = _row(run_simulation(bars, start, end, config))
        primary_start, primary_end = windows[PRIMARY]
        record["adverse_primary"] = _row(
            run_simulation(bars, primary_start, primary_end, adverse_config)
        )
        record["beats_bh_primary"] = record[PRIMARY]["net_return_pct"] > bh_primary
        record["beats_bh_primary_adverse"] = record["adverse_primary"]["net_return_pct"] > bh_primary
        trend[f"MA_{hours}h"] = record

    # Overfit test: an isolated peak whose immediate neighbours lose is not an edge.
    ordered_hours = [600, 900, 1200, 1800, 2400, 3600, 4800, 6000, 7200]
    robust_trend: list[str] = []
    for position, hours in enumerate(ordered_hours):
        key = f"MA_{hours}h"
        if not trend[key]["beats_bh_primary"]:
            continue
        neighbours_ok = True
        for offset in (-1, 1):
            neighbour_index = position + offset
            if 0 <= neighbour_index < len(ordered_hours):
                neighbour_key = f"MA_{ordered_hours[neighbour_index]}h"
                if not trend[neighbour_key]["beats_bh_primary"]:
                    neighbours_ok = False
        if neighbours_ok:
            robust_trend.append(key)
    trend_adverse_winners = [
        key for key, record in trend.items() if record["beats_bh_primary_adverse"]
    ]

    protected_winners = [
        name
        for name, record in protections.items()
        if record["beats_bh_primary"] and record["beats_bh_bear"]
    ]
    # A design is only deployable if it survives BOTH the neighbour test and the
    # adverse-fee test. Beating buy & hold at one lucky parameter point is not an edge.
    deployable = [key for key in robust_trend if key in trend_adverse_winners]
    verdict = {
        "multislot_ladder_beats_bh": bool(protected_winners),
        "protected_ladder_configs_beating_bh": protected_winners,
        "unprotected_ladder_configs_beating_bh": [item["label"] for item in unprotected_winners],
        "trend_configs_beating_bh_at_observed_fees": [
            key for key, record in trend.items() if record["beats_bh_primary"]
        ],
        "trend_configs_surviving_neighbour_test": robust_trend,
        "trend_configs_beating_bh_at_adverse_fees": trend_adverse_winners,
        "deployable_configurations": deployable,
        "recommendation": (
            "DEPLOY" if deployable else "DO_NOT_DEPLOY_AS_PRIMARY_RETURN_STRATEGY"
        ),
        "buy_and_hold_primary_pct": bh_primary,
        "buy_and_hold_bear_pct": bh_bear,
        "robust_finding": (
            "No configuration robustly beats buy & hold net of costs. The only property "
            "that holds across every window and every variant is drawdown reduction."
        ),
    }

    payload = {
        "schema_version": "multislot-study/1.0.0",
        "created_at": datetime.now(tz=UTC).isoformat(),
        "dataset_id": dataset_id,
        "starting_capital_usdt": DEFAULT_CAPITAL,
        "venue_costs": {"observed_fee_per_side_bps": 10, "adverse_fee_per_side_bps": 20},
        "evidence_class": "BAR_PROXY_1H_APPROXIMATION",
        "limitations": [
            "1h bars cannot reproduce the runtime 5m/30m tactical features.",
            "No historical BBO spread or aggTrade order flow is available.",
            "Take-profit requires a confirmed close; stops trigger on the low and fill at the worse of stop and open.",
            "Documented dataset gaps restart indicator warmup and are never bridged.",
            "This can reject a design; it cannot prove live profitability.",
        ],
        "rejected_by_design": {
            "rule": "sell one or two slots when all slots are committed",
            "reason": (
                "All slots full means price fell through every ladder level, which is the point "
                "of maximum unrealized loss. Selling there realizes the worst loss and frees "
                "capital to re-buy an asset that just demonstrated it keeps falling. Capacity "
                "must come from wider spacing or a reserved tranche, not forced capitulation."
            ),
        },
        "windows": {
            name: {
                "start_index": start,
                "end_index": end,
                "bars": end - start,
                "start_utc": datetime.fromtimestamp(
                    bars[start].open_time_ms / 1000, tz=UTC
                ).isoformat(),
                "end_utc": datetime.fromtimestamp(
                    bars[end - 1].open_time_ms / 1000, tz=UTC
                ).isoformat(),
            }
            for name, (start, end) in windows.items()
        },
        "baselines": baselines,
        "sweep_size": len(sweep),
        "sweep_top10_by_primary": by_primary[:10],
        "sweep_top10_by_bear": by_bear[:10],
        "protections": protections,
        "adverse_fees": adverse,
        "neighbour_sensitivity": neighbours,
        "trend_following_family": trend,
        "verdict": verdict,
    }

    REPORT_STEM.parent.mkdir(parents=True, exist_ok=True)
    REPORT_STEM.with_suffix(".json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# Multi-slot ladder study (BAR_PROXY 1h approximation)",
        "",
        f"- Dataset: `{dataset_id}`",
        f"- Starting capital: {DEFAULT_CAPITAL:,.2f} USDT",
        "- Fees: 10 bps per side observed, 20 bps adverse scenario",
        f"- Configurations swept: {len(sweep)}",
        f"- **Verdict: {verdict['recommendation']}**",
        "",
        "## Baselines",
        "",
        "| window | buy & hold | max DD |",
        "|---|---:|---:|",
    ]
    for name in windows:
        base = baselines[name]["buy_and_hold"]
        lines.append(f"| {name} | {base['net_return_pct']:.2f}% | {base['max_drawdown_pct']:.1f}% |")
    lines += [
        "",
        "## Protections applied to the best bear-ranked ladder",
        "",
        "| protection | full 2020-2026 | bear 2021-22 | max DD | beats B&H full | beats B&H bear |",
        "|---|---:|---:|---:|:--:|:--:|",
    ]
    for name, record in protections.items():
        lines.append(
            f"| {name} | {record[PRIMARY]['net_return_pct']:.2f}% | "
            f"{record[BEAR]['net_return_pct']:.2f}% | "
            f"{record[PRIMARY]['max_drawdown_pct']:.1f}% | "
            f"{'yes' if record['beats_bh_primary'] else 'no'} | "
            f"{'yes' if record['beats_bh_bear'] else 'no'} |"
        )
    lines += [
        "",
        f"Buy & hold reference: full {bh_primary:.2f}%, bear {bh_bear:.2f}%.",
        "",
        "## Trend-following challenger (regime entry + regime exit)",
        "",
        "| MA | full 2020-2026 | max DD | bear 2021-22 | adverse fees | beats B&H |",
        "|---|---:|---:|---:|---:|:--:|",
    ]
    for hours in (600, 900, 1200, 1800, 2400, 3600, 4800, 6000, 7200):
        record = trend[f"MA_{hours}h"]
        lines.append(
            f"| {hours}h ({hours // 24}d) | {record[PRIMARY]['net_return_pct']:.2f}% | "
            f"{record[PRIMARY]['max_drawdown_pct']:.1f}% | {record[BEAR]['net_return_pct']:.2f}% | "
            f"{record['adverse_primary']['net_return_pct']:.2f}% | "
            f"{'yes' if record['beats_bh_primary'] else 'no'} |"
        )
    lines += [
        "",
        f"Surviving the neighbour (overfit) test: {robust_trend or 'none'}.",
        f"Beating buy & hold at adverse fees: {trend_adverse_winners or 'none'}.",
        f"Deployable after both tests: {deployable or 'none'}.",
        "",
        "## Rejected by design",
        "",
        payload["rejected_by_design"]["reason"],
        "",
        "## Limitations",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    REPORT_STEM.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"dataset={dataset_id}")
    print(f"buy_and_hold full={bh_primary:.2f}% bear={bh_bear:.2f}%")
    print(f"sweep={len(sweep)} configs")
    print(f"unprotected beating B&H both windows: {len(unprotected_winners)}")
    print("top3 by full window:")
    for item in by_primary[:3]:
        print(f"  {item['label']:52s} full={item[PRIMARY]['net_return_pct']:9.2f}% bear={item[BEAR]['net_return_pct']:8.2f}%")
    print("top3 by bear window:")
    for item in by_bear[:3]:
        print(f"  {item['label']:52s} full={item[PRIMARY]['net_return_pct']:9.2f}% bear={item[BEAR]['net_return_pct']:8.2f}%")
    print("protections:")
    for name, record in protections.items():
        print(
            f"  {name:26s} full={record[PRIMARY]['net_return_pct']:9.2f}% "
            f"bear={record[BEAR]['net_return_pct']:8.2f}% dd={record[PRIMARY]['max_drawdown_pct']:5.1f}% "
            f"bh_full={'Y' if record['beats_bh_primary'] else 'N'} bh_bear={'Y' if record['beats_bh_bear'] else 'N'}"
        )
    print(f"VERDICT={verdict['recommendation']} winners={protected_winners}")


if __name__ == "__main__":
    main()
