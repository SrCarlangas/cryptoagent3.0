# legacy/ — retired designs

Nothing in this directory runs, is imported, or is deployed. It is kept so the
evidence trail survives: several of these designs were tested, measured and
rejected on the record, and deleting them would erase why the current agent looks
the way it does.

Verified retired, not merely unused: no module under `src/` imports anything here,
no test collects it, and the deployment excludes it.

## What is here and why it was retired

| Path | What it was | Why it went |
|---|---|---|
| `policies/core.py` | POL-101/102/103 deterministic SMA pullback, reversion and breakout policies | Hand-written thresholds; replaced by a learned policy |
| `policies/evidence_v3.py`, `evidence_v4.py` | Frozen identities of the confidence-threshold engines | V3 replayed at −75.61% vs buy & hold +67.66%; V4 lost over 10 round trips |
| `application/local_ml.py`, `ml_training.py` | 3-class BUY/HOLD/SELL softmax at a 4h horizon | Holdout accuracy 0.3990 against a 0.4026 majority baseline: a base-rate predictor. An argmax policy at 4h also flips ~1371 times a year, costing ~137% of capital in fees |
| `application/live_demo.py` | Clock-driven baseline runner | Decisions tied to fixed candle boundaries, not to events |
| `application/offline_pipeline.py`, `decision.py`, `services.py` | Offline decision pipeline for POL-101 | Served the retired policy machinery |
| `observability/dashboard.py`, `floor.py`, `static/` | Isometric pixel-office dashboard with six departments | Described a deterministic pipeline that no longer exists; replaced by `agent_dashboard.py` |
| `scripts/compare_agents.py` | Weekly Slack comparison of V4 vs the softmax shadow | Compared two retired agents; replaced by `scripts/daily_summary.py` |
| `scripts/run_realtime_demo.py` | V4 entry point | Replaced by `scripts/run_exposure_agent.py` |
| `adapters/`, `domain/features.py`, `risk.py`, `state_machine.py`, `replay_pkg/`, `simulation_pkg/`, `validation_pkg/` | Supporting machinery for the offline POL-101 design | Unreachable from the current entry points |
| `docs/` | Specs, roadmap and task lists for the deterministic design | Describe the retired architecture |

## Why the old ML model is not the current agent

They are different problems. The retired model predicted a **direction** over 4
hours and was scored on accuracy. The current agent chooses an **exposure**, is
scored on money, and prices its own transaction costs inside its reward — which is
what makes its reluctance to churn emergent rather than configured.
