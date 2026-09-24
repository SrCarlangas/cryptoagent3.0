"""Train the local BUY/HOLD/SELL softmax model from the frozen 1h dataset."""

from __future__ import annotations

import argparse
from decimal import Decimal

from btc_decision_agent.application.ml_training import train_from_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the dependency-free local softmax model.")
    parser.add_argument("--dataset", default="data/history/btcusdt-1h")
    parser.add_argument("--model-path", default="data/models/local-softmax-v1.json")
    parser.add_argument("--report-json", default="data/reports/local-softmax-v1-training.json")
    parser.add_argument("--report-md", default="data/reports/local-softmax-v1-training.md")
    parser.add_argument("--round-trip-cost-bps", default="20")
    parser.add_argument("--decision-threshold-bps", default="10")
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--learning-rate", type=float, default=0.0003)
    parser.add_argument("--l2", type=float, default=0.0001)
    args = parser.parse_args()
    report = train_from_dataset(
        args.dataset,
        args.model_path,
        args.report_json,
        args.report_md,
        round_trip_cost_bps=Decimal(args.round_trip_cost_bps),
        decision_threshold_bps=Decimal(args.decision_threshold_bps),
        holdout_fraction=args.holdout_fraction,
        learning_rate=args.learning_rate,
        l2=args.l2,
    )
    holdout = report["holdout"]
    print(
        f"model={report['model_version']} train={report['split']['train_examples']} "
        f"holdout={holdout['examples']} accuracy={holdout['accuracy']:.6f} "
        f"macro_f1={holdout['macro_f1']:.6f} log_loss={holdout['log_loss']:.6f}"
    )
    print(f"model_path={args.model_path} report_json={args.report_json} report_md={args.report_md}")


if __name__ == "__main__":
    main()
