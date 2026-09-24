"""Does the agent actually distinguish regimes, or just split time into four bins?

Balanced regime usage (roughly 25% each) is not evidence of anything on its own.
A gate could partition time evenly and still be meaningless. This script tests the
claim properly by asking two questions of the trained policy:

1. Do the regimes activate under DIFFERENT market conditions? Reported as the mean
   of interpretable features conditional on each regime being dominant.

2. Do the regimes WANT different things? A regime that fires in distinct
   conditions but recommends the same action everywhere adds nothing. This is
   measured as each expert's own preference for being long, evaluated on the
   states where that regime actually dominates.

If both hold, "distinguishes regimes and adjusts strategy" is a description of the
model rather than a hope. Read-only; writes data/validation/exposure-agent-regimes.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from multislot_sim import load_bars, window_index

from btc_decision_agent.application.exposure_agent import (
    ACTIONS,
    ExposureAction,
    PortfolioState,
    RegimeMixturePolicy,
    compose_features,
)
from btc_decision_agent.application.exposure_features import (
    MARKET_FEATURE_NAMES,
    MIN_DAILY_HISTORY,
    market_features,
)
from btc_decision_agent.application.exposure_training import build_daily_perception

MODEL_PATH = Path("data/models/local-exposure-agent-v1.json")
REPORT_PATH = Path("data/validation/exposure-agent-regimes.md")
INTERESTING = (
    "log_price_over_ma200",
    "log_price_over_ma30",
    "return_30d",
    "return_90d",
    "volatility_30d",
    "volatility_ratio_30_90",
    "log_price_over_high_200d",
)


def expert_long_preference(policy: RegimeMixturePolicy, regime: int, features: list[float]) -> float:
    """P(long) if this regime alone decided, isolating one expert from the mixture."""
    normalized = policy.normalizer.transform(features)
    augmented = [1.0, *normalized]
    logits = [
        sum(w * x for w, x in zip(row, augmented, strict=True))
        for row in policy.experts[regime]
    ]
    largest = max(logits)
    exps = [pow(2.718281828459045, value - largest) for value in logits]
    total = sum(exps)
    index = ACTIONS.index(ExposureAction.TARGET_LONG)
    return exps[index] / total


def main() -> None:
    bars, dataset_id = load_bars()
    perception = build_daily_perception(bars)
    policy = RegimeMixturePolicy.load(MODEL_PATH)
    start = window_index(bars, "2021-09-16")

    buckets: dict[int, dict[str, list[float]]] = {
        k: {name: [] for name in INTERESTING} for k in range(policy.regimes)
    }
    own_preference: dict[int, list[float]] = {k: [] for k in range(policy.regimes)}
    mixture_preference: dict[int, list[float]] = {k: [] for k in range(policy.regimes)}
    counts = dict.fromkeys(range(policy.regimes), 0)

    # Evaluate flat-book states on a daily grid so the picture is about the market,
    # not about whatever position a particular rollout happened to be holding.
    state = PortfolioState(position_long=False, round_trip_cost_bps=20.0)
    for index in range(start, len(bars), 24):
        available = perception.available_at_bar[index]
        if available < MIN_DAILY_HISTORY:
            continue
        market = market_features(perception.closes[:available], float(bars[index].close))
        features = compose_features(market, state)
        outcome = policy.decide(features, state)
        regime = outcome.dominant_regime
        counts[regime] += 1
        for name in INTERESTING:
            buckets[regime][name].append(market[MARKET_FEATURE_NAMES.index(name)])
        own_preference[regime].append(expert_long_preference(policy, regime, features))
        mixture_preference[regime].append(
            outcome.action_probabilities[ExposureAction.TARGET_LONG.value]
        )

    total = sum(counts.values()) or 1
    lines: list[str] = ["# Do the agent's regimes mean anything?", ""]
    lines.append(f"- dataset_id: `{dataset_id}`")
    lines.append(f"- policy: `{policy.policy_version}`, {policy.regimes} regimes, {policy.trained_steps} training steps")
    lines.append(f"- evaluated on {total} daily states from a flat book")
    lines.append("")
    lines.append("## Conditions under which each regime dominates")
    lines.append("")
    header = "| regime | share | " + " | ".join(INTERESTING) + " | own P(long) | mixture P(long) |"
    lines.append(header)
    lines.append("|---" * (len(INTERESTING) + 4) + "|")
    summary: dict[str, Any] = {}
    for regime in range(policy.regimes):
        if counts[regime] == 0:
            lines.append(f"| {regime} | 0.0% | " + " | ".join("-" for _ in INTERESTING) + " | - | - |")
            continue
        cells = [f"{mean(buckets[regime][name]):+.4f}" for name in INTERESTING]
        own = mean(own_preference[regime])
        mixed = mean(mixture_preference[regime])
        lines.append(
            f"| {regime} | {counts[regime] / total:.1%} | " + " | ".join(cells) +
            f" | {own:.3f} | {mixed:.3f} |"
        )
        summary[str(regime)] = {
            "share": counts[regime] / total,
            "own_long_preference": own,
            "features": {name: mean(buckets[regime][name]) for name in INTERESTING},
        }
    lines.append("")

    active = [regime for regime in range(policy.regimes) if counts[regime] > 0]
    if len(active) < 2:
        lines.append("**Verdict: the gate collapsed to a single regime. Not regime-aware.**")
    else:
        trend_by_regime = {
            regime: mean(buckets[regime]["log_price_over_ma200"]) for regime in active
        }
        preference_by_regime = {regime: mean(own_preference[regime]) for regime in active}
        trend_spread = max(trend_by_regime.values()) - min(trend_by_regime.values())
        preference_spread = max(preference_by_regime.values()) - min(preference_by_regime.values())
        lines.append("## Verdict")
        lines.append("")
        lines.append(f"- active regimes: {len(active)} of {policy.regimes}")
        lines.append(
            f"- spread in trend context (log price over 200d average) across regimes: "
            f"{trend_spread:.4f}"
        )
        lines.append(
            f"- spread in each regime's own preference for being long: {preference_spread:.3f}"
        )
        conditions_differ = trend_spread > 0.05
        intentions_differ = preference_spread > 0.10
        lines.append("")
        if conditions_differ and intentions_differ:
            lines.append(
                "**Regimes are real.** They activate in measurably different trend "
                "contexts AND hold different views on whether to be exposed, so the "
                "agent is adjusting strategy by regime rather than averaging one rule."
            )
        elif conditions_differ:
            lines.append(
                "**Partial.** Regimes separate market conditions but want similar "
                "things, so regime detection is not yet changing behaviour much."
            )
        else:
            lines.append(
                "**Weak.** Regimes do not separate market conditions; the mixture is "
                "behaving close to a single averaged expert."
            )
        summary["verdict"] = {
            "active_regimes": len(active),
            "trend_spread": trend_spread,
            "preference_spread": preference_spread,
            "conditions_differ": conditions_differ,
            "intentions_differ": intentions_differ,
        }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    REPORT_PATH.with_suffix(".json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
