"""Promote or demote the exposure agent's policy, recording the evidence.

Granting order authority is a decision, not a side effect of training, so it is a
separate explicit step. The runtime refuses any policy that is not PROMOTED, and
this script is the only thing that sets that flag. It writes the evidence it was
promoted on into the policy file itself, so an auditor reading the model can see
what justified it without going hunting for a report.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from btc_decision_agent.application.exposure_agent import RegimeMixturePolicy

DEFAULT_MODEL = "data/models/local-exposure-agent-v1.json"
DEFAULT_SELECTION = "data/validation/exposure-agent-selection.json"
DEFAULT_REGIMES = "data/validation/exposure-agent-regimes.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Set the exposure policy's promotion status.")
    parser.add_argument("--model-path", default=DEFAULT_MODEL)
    parser.add_argument("--selection-report", default=DEFAULT_SELECTION)
    parser.add_argument("--regime-report", default=DEFAULT_REGIMES)
    parser.add_argument("--demote", action="store_true", help="revoke authority instead")
    parser.add_argument(
        "--note",
        default="",
        help="free-text justification stored alongside the evidence",
    )
    args = parser.parse_args()

    model_path = Path(args.model_path)
    policy = RegimeMixturePolicy.load(model_path)

    if args.demote:
        policy.metadata = {
            **policy.metadata,
            "promotion_status": "DEMOTED",
            "demoted_at": datetime.now(UTC).isoformat(),
            "demotion_note": args.note,
        }
        policy.save(model_path)
        print(f"DEMOTED {policy.policy_version} at {model_path}")
        return

    selection = _load(Path(args.selection_report))
    regimes = _load(Path(args.regime_report))
    chosen = selection.get("chosen", {}) if isinstance(selection.get("chosen"), dict) else {}
    robustness = selection.get("robustness", {})
    seed_stability = robustness.get("seed_stability", {}) if isinstance(robustness, dict) else {}
    adverse = robustness.get("adverse_fees_20bps", {}) if isinstance(robustness, dict) else {}
    verdict = regimes.get("verdict", {}) if isinstance(regimes.get("verdict"), dict) else {}

    evidence = {
        "objective": "maximum net profitability, measured out of sample",
        "selection_method": (
            "expanding-window walk-forward; every score comes from a segment later "
            "than the data that produced the weights"
        ),
        "chosen_config": chosen.get("label"),
        "mean_out_of_sample_return_pct": chosen.get("mean_out_of_sample_return_pct"),
        "worst_out_of_sample_return_pct": chosen.get("worst_out_of_sample_return_pct"),
        "folds_profitable": (
            f"{chosen.get('folds_profitable')}/{chosen.get('folds_total')}"
            if chosen
            else None
        ),
        "seed_stability_mean_pct": seed_stability.get("mean"),
        "seed_stability_worst_pct": seed_stability.get("worst"),
        "seeds_profitable": (
            f"{seed_stability.get('seeds_profitable')}/{seed_stability.get('seeds_total')}"
            if seed_stability
            else None
        ),
        "adverse_20bps_mean_pct": adverse.get("mean_out_of_sample_return_pct"),
        "regimes_active": verdict.get("active_regimes"),
        "regime_conditions_differ": verdict.get("conditions_differ"),
        "regime_intentions_differ": verdict.get("intentions_differ"),
        "known_limitation": (
            "The configuration was chosen using these same walk-forward folds, so the "
            "single-config figure is optimistically biased. The defensible expectation "
            "is the multi-seed mean, and the whole 16-config grid ranged roughly +21% "
            "to +49% mean out-of-sample."
        ),
        "buy_and_hold_role": "reported as context only; it is not an approval criterion",
    }

    policy.metadata = {
        **policy.metadata,
        "promotion_status": "PROMOTED",
        "promoted_at": datetime.now(UTC).isoformat(),
        "promotion_note": args.note,
        "promotion_evidence": evidence,
    }
    policy.save(model_path)
    print(f"PROMOTED {policy.policy_version} at {model_path}")
    for key, value in evidence.items():
        if value is not None and key not in {"known_limitation", "buy_and_hold_role"}:
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
