"""Train the local exposure agent on five years of history and select by profit.

Selection rule, per the user's instruction: the objective is maximum net
profitability, and buy and hold is reported only as context, never as a pass/fail
gate.

What keeps that honest is WHERE profitability is measured. Task 1 established that
picking a configuration on the same years used to measure it produces large
positive numbers that turn negative later: in-sample excesses of +471pp and
+1081pp became -86pp and -23pp out of sample. So every configuration here is
trained on a segment and scored ONLY on the segment that follows, across several
walk-forward folds. The configuration chosen is the one with the best mean
out-of-sample profit, and the number reported as its expected performance is that
out-of-sample number, not the training one.

Writes data/validation/exposure-agent-selection.{json,md} and, for the winning
configuration, a trained policy to data/models/local-exposure-agent-v1.json.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from multislot_sim import Bar, load_bars, window_index

from btc_decision_agent.application.exposure_agent import RegimeMixturePolicy
from btc_decision_agent.application.exposure_training import (
    DailyPerception,
    RolloutResult,
    TrainingConfig,
    build_daily_perception,
    buy_and_hold_reference,
    evaluate_agent,
    train_agent,
)

REPORT_STEM = Path("data/validation/exposure-agent-selection")
MODEL_PATH = Path("data/models/local-exposure-agent-v1.json")
FIVE_YEAR_START = "2021-09-16"


def walk_forward_folds(bars: list[Bar]) -> list[tuple[str, int, int, int]]:
    """(name, train_start, train_end/test_start, test_end) over the five-year window.

    Folds are expanding-window: each one trains on everything up to a cut and is
    tested on the year or so after it. Every test segment is strictly later than
    the data that produced the weights.
    """
    definitions = [
        ("fold_1_test_2023H2", FIVE_YEAR_START, "2023-07-01", "2024-07-01"),
        ("fold_2_test_2024H2", FIVE_YEAR_START, "2024-07-01", "2025-07-01"),
        ("fold_3_test_2025H2", FIVE_YEAR_START, "2025-07-01", "2026-09-16"),
    ]
    folds: list[tuple[str, int, int, int]] = []
    for name, begin, cut, finish in definitions:
        start = window_index(bars, begin)
        boundary = window_index(bars, cut)
        end = min(window_index(bars, finish), len(bars))
        if start < boundary < end:
            folds.append((name, start, boundary, end))
    return folds


def candidate_configs() -> list[TrainingConfig]:
    """A deliberately small grid.

    Every extra configuration is another chance to get lucky on a fold, so the
    grid stays narrow and the winner still has to survive being averaged across
    folds and re-checked for seed stability afterwards.
    """
    configs: list[TrainingConfig] = []
    for cadence in (6, 12, 24, 48):
        for regimes in (2, 4):
            for learning_rate in (0.02, 0.08):
                configs.append(
                    TrainingConfig(
                        cadence_hours=cadence,
                        regimes=regimes,
                        learning_rate=learning_rate,
                        epochs=4,
                        fee_per_side=0.001,
                    )
                )
    return configs


def config_label(config: TrainingConfig) -> str:
    return (
        f"cadence={config.cadence_hours}h|regimes={config.regimes}"
        f"|lr={config.learning_rate}|epochs={config.epochs}"
    )


def score_config(
    bars: list[Bar],
    perception: DailyPerception,
    folds: list[tuple[str, int, int, int]],
    config: TrainingConfig,
) -> dict[str, Any]:
    per_fold: dict[str, Any] = {}
    out_of_sample_returns: list[float] = []
    out_of_sample_drawdowns: list[float] = []
    for name, train_start, boundary, end in folds:
        policy, history = train_agent(bars, perception, train_start, boundary, config)
        test = evaluate_agent(bars, perception, policy, boundary, end, config)
        reference = buy_and_hold_reference(bars, boundary, end, config.fee_per_side)
        in_sample = evaluate_agent(bars, perception, policy, train_start, boundary, config)
        per_fold[name] = {
            "out_of_sample": asdict(test),
            "in_sample": asdict(in_sample),
            "buy_and_hold_reference": reference,
            "training_mean_reward_last_epoch": history[-1].mean_reward,
        }
        out_of_sample_returns.append(test.net_return_pct)
        out_of_sample_drawdowns.append(test.max_drawdown_pct)
    return {
        "config": asdict(config),
        "label": config_label(config),
        "folds": per_fold,
        "mean_out_of_sample_return_pct": mean(out_of_sample_returns),
        "worst_out_of_sample_return_pct": min(out_of_sample_returns),
        "mean_out_of_sample_drawdown_pct": mean(out_of_sample_drawdowns),
        "folds_profitable": sum(1 for value in out_of_sample_returns if value > 0.0),
        "folds_total": len(out_of_sample_returns),
    }


def seed_stability(
    bars: list[Bar],
    perception: DailyPerception,
    folds: list[tuple[str, int, int, int]],
    config: TrainingConfig,
    seeds: tuple[int, ...] = (1, 7, 101, 20260924, 999983),
) -> dict[str, Any]:
    """Re-run the winner under different initialisations.

    The policy is randomly initialised and explores stochastically, so a single
    seed's result is one draw from a distribution. A configuration whose profit
    depends on the seed has not learned anything transferable.
    """
    per_seed: dict[str, float] = {}
    for seed in seeds:
        scored = score_config(bars, perception, folds, replace(config, seed=seed))
        per_seed[str(seed)] = scored["mean_out_of_sample_return_pct"]
    values = list(per_seed.values())
    average = mean(values)
    spread = max(values) - min(values)
    return {
        "per_seed_mean_out_of_sample_return_pct": per_seed,
        "mean": average,
        "worst": min(values),
        "best": max(values),
        "spread": spread,
        "seeds_profitable": sum(1 for value in values if value > 0.0),
        "seeds_total": len(values),
    }


def adverse_fee_check(
    bars: list[Bar],
    perception: DailyPerception,
    folds: list[tuple[str, int, int, int]],
    config: TrainingConfig,
) -> dict[str, Any]:
    """Retrain and rescore at double the real fee."""
    scored = score_config(bars, perception, folds, replace(config, fee_per_side=0.002))
    return {
        "mean_out_of_sample_return_pct": scored["mean_out_of_sample_return_pct"],
        "worst_out_of_sample_return_pct": scored["worst_out_of_sample_return_pct"],
        "folds_profitable": scored["folds_profitable"],
        "folds_total": scored["folds_total"],
    }


def train_final_policy(
    bars: list[Bar],
    perception: DailyPerception,
    config: TrainingConfig,
    start: int,
    end: int,
) -> tuple[RegimeMixturePolicy, RolloutResult]:
    policy, history = train_agent(bars, perception, start, end, config)
    return policy, history[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and select the local exposure agent.")
    parser.add_argument("--dataset", default="data/history/btcusdt-1h")
    parser.add_argument("--skip-robustness", action="store_true")
    args = parser.parse_args()

    bars, dataset_id = load_bars(args.dataset)
    perception = build_daily_perception(bars)
    folds = walk_forward_folds(bars)
    if not folds:
        raise SystemExit("no usable walk-forward folds")

    scored = [score_config(bars, perception, folds, config) for config in candidate_configs()]
    scored.sort(key=lambda item: item["mean_out_of_sample_return_pct"], reverse=True)
    best = scored[0]
    best_config = TrainingConfig(**best["config"])

    robustness: dict[str, Any] = {}
    if not args.skip_robustness:
        robustness = {
            "seed_stability": seed_stability(bars, perception, folds, best_config),
            "adverse_fees_20bps": adverse_fee_check(bars, perception, folds, best_config),
        }

    # Final policy: trained on the whole five-year window with the chosen config.
    five_year_start = window_index(bars, FIVE_YEAR_START)
    final_policy, final_training = train_final_policy(
        bars, perception, best_config, five_year_start, len(bars)
    )
    final_policy.metadata = {
        "dataset_id": dataset_id,
        "trained_at": datetime.now(UTC).isoformat(),
        "training_window": {
            "start": datetime.fromtimestamp(
                bars[five_year_start].open_time_ms / 1000, UTC
            ).isoformat(),
            "end": datetime.fromtimestamp(bars[-1].open_time_ms / 1000, UTC).isoformat(),
            "bars": len(bars) - five_year_start,
        },
        "selection": {
            "method": "expanding-window walk-forward, scored only on later segments",
            "objective": "maximum mean out-of-sample net return",
            "chosen_config": best["label"],
            "mean_out_of_sample_return_pct": best["mean_out_of_sample_return_pct"],
            "worst_out_of_sample_return_pct": best["worst_out_of_sample_return_pct"],
            "folds_profitable": f"{best['folds_profitable']}/{best['folds_total']}",
        },
        "robustness": robustness,
        "final_training_pass": asdict(final_training),
        "promotion_status": "PENDING_REVIEW",
    }

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_id": dataset_id,
        "perception": {
            "total_days": perception.total_days,
            "sparse_days_under_20_bars": perception.sparse_days,
        },
        "folds": [
            {
                "name": name,
                "train_start": datetime.fromtimestamp(bars[a].open_time_ms / 1000, UTC).isoformat(),
                "test_start": datetime.fromtimestamp(bars[b].open_time_ms / 1000, UTC).isoformat(),
                "test_end": datetime.fromtimestamp(bars[c - 1].open_time_ms / 1000, UTC).isoformat(),
            }
            for name, a, b, c in folds
        ],
        "configurations_ranked": scored,
        "chosen": best,
        "robustness": robustness,
        "final_policy": {
            "path": str(MODEL_PATH),
            "regime_usage_last_training_pass": final_training.regime_usage,
            "decision_counts_last_training_pass": final_training.decision_counts,
        },
    }

    REPORT_STEM.parent.mkdir(parents=True, exist_ok=True)
    REPORT_STEM.with_suffix(".json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_STEM.with_suffix(".md").write_text(render(report) + "\n", encoding="utf-8")
    final_policy.save(MODEL_PATH)
    print(render(report))


def render(report: dict[str, Any]) -> str:
    lines: list[str] = ["# Local exposure agent: training and selection", ""]
    lines.append(f"- dataset_id: `{report['dataset_id']}`")
    perception = report["perception"]
    lines.append(
        f"- daily perception: {perception['total_days']} days, "
        f"{perception['sparse_days_under_20_bars']} with fewer than 20 hourly bars"
    )
    lines.append("- objective: maximum net profitability. Buy and hold is context, not a gate.")
    lines.append("")
    lines.append("## Walk-forward folds")
    lines.append("")
    for fold in report["folds"]:
        lines.append(
            f"- `{fold['name']}`: train from {fold['train_start'][:10]}, "
            f"test {fold['test_start'][:10]} to {fold['test_end'][:10]}"
        )
    lines.append("")

    lines.append("## Configurations ranked by mean OUT-OF-SAMPLE return")
    lines.append("")
    lines.append("| config | mean OOS | worst OOS | mean OOS dd | folds profitable |")
    lines.append("|---|---|---|---|---|")
    for item in report["configurations_ranked"]:
        lines.append(
            f"| `{item['label']}` | {item['mean_out_of_sample_return_pct']:+.2f}% | "
            f"{item['worst_out_of_sample_return_pct']:+.2f}% | "
            f"{item['mean_out_of_sample_drawdown_pct']:.2f}% | "
            f"{item['folds_profitable']}/{item['folds_total']} |"
        )
    lines.append("")

    chosen = report["chosen"]
    lines.append(f"## Chosen: `{chosen['label']}`")
    lines.append("")
    lines.append("| fold | agent OOS | buy & hold (context) | agent dd | b&h dd | buys | sells | exposure |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name, values in chosen["folds"].items():
        out = values["out_of_sample"]
        reference = values["buy_and_hold_reference"]
        lines.append(
            f"| {name} | {out['net_return_pct']:+.2f}% | "
            f"{reference['net_return_pct']:+.2f}% | {out['max_drawdown_pct']:.2f}% | "
            f"{reference['max_drawdown_pct']:.2f}% | {out['buys']} | {out['sells']} | "
            f"{out['exposure_share']:.1%} |"
        )
    lines.append("")

    if report.get("robustness"):
        seeds = report["robustness"]["seed_stability"]
        adverse = report["robustness"]["adverse_fees_20bps"]
        lines.append("## Robustness")
        lines.append("")
        lines.append(
            f"- seed stability: mean {seeds['mean']:+.2f}%, worst {seeds['worst']:+.2f}%, "
            f"best {seeds['best']:+.2f}%, spread {seeds['spread']:.2f}pp, "
            f"{seeds['seeds_profitable']}/{seeds['seeds_total']} seeds profitable"
        )
        lines.append(
            f"- adverse 20bps fees: mean OOS {adverse['mean_out_of_sample_return_pct']:+.2f}%, "
            f"worst {adverse['worst_out_of_sample_return_pct']:+.2f}%, "
            f"{adverse['folds_profitable']}/{adverse['folds_total']} folds profitable"
        )
        lines.append("")

    final = report["final_policy"]
    lines.append("## Final policy trained on the full five years")
    lines.append("")
    lines.append(f"- saved to `{final['path']}`")
    usage = ", ".join(f"{value:.1%}" for value in final["regime_usage_last_training_pass"])
    lines.append(f"- regime usage: {usage}")
    lines.append(f"- decisions: {final['decision_counts_last_training_pass']}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
