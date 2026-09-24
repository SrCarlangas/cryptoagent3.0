# CryptoAgent 3.0 — local exposure agent

A local, learned trading agent that operates a **Binance DEMO** account (no real
funds). One agent decides; deterministic safety layers may only veto it.

There is no moving-average rule, no threshold ladder and no hand-written trend test
anywhere in the decision path. What is coded is an objective and a learning rule.
The behaviour is whatever maximises that objective on five years of data.

## What the agent is

| | |
|---|---|
| Policy | Mixture of experts over 4 learned regimes, pure Python, no numpy |
| Action | Target exposure: `TARGET_LONG` or `TARGET_FLAT` |
| Decision | Combined with the position held, becomes BUY / HOLD / SELL |
| Reward | Realised log return of the chosen exposure, minus the fee that choice actually pays |
| Learning | Exact full-information policy gradient, offline on 5 years plus online in production |
| Perception | 19 scale-free features from **completed** daily closes plus the current price |

Because log returns sum to terminal wealth, maximising expected reward *is*
maximising profitability rather than a proxy such as direction accuracy. Because
transaction costs sit inside the reward, reluctance to churn is **learned, not
configured** — no dead band exists in the code.

### The regimes it found

The gate discovered these from data; no bar was ever labelled by hand.

| Regime | Share | vs 200d avg | 30d return | Volatility | P(long) | Behaviour |
|---|---|---|---|---|---|---|
| 1 | 19.9% | −26.2% | −18.4% | highest | **0.416** | deep bear, step aside |
| 0 | 33.6% | −6.3% | +5.2% | mid | 0.508 | recovery chop |
| 2 | 22.9% | +19.5% | −0.9% | low | 0.525 | consolidation above trend |
| 3 | 23.5% | +17.3% | +12.1% | lowest | **0.560** | strong bull, stay long |

## Evidence

Parameters were selected on expanding walk-forward folds and scored **only** on
segments later than the data that produced the weights.

| Fold | Agent | Buy & hold (context) | Agent drawdown | B&H drawdown |
|---|---|---|---|---|
| Jul 2023 – Jun 2024 | +107.18% | +105.60% | 21.43% | 22.69% |
| Jul 2024 – Jun 2025 | +49.14% | +69.92% | 23.97% | 30.94% |
| Jul 2025 – Sep 2026 | −9.83% | −29.69% | 34.42% | 53.74% |

It tracks the market when it rises and loses much less when it falls, always with
lower drawdown. Across 5 random seeds all 5 were profitable (mean **+42.42%**), and
at double the real fees the mean was +44.67%.

**Stated honestly:** the configuration was chosen using these same folds, so the
single best figure is optimistically biased. The defensible expectation is the
multi-seed mean, and the whole 16-configuration grid ranged roughly +21% to +49%.
Buy & hold is reported as context only — it is not an approval criterion.

An earlier study (`data/validation/exposure-diagnosis.md`) found no exploitable
point-in-time trend signal in this data at all: of 20 signal/horizon pairs at
affordable churn horizons, none reached 1 standard error. That is why the agent
tilts rather than making confident calls, and why a confident model here would be
overfitting.

## Decision path

Strictest first. Only the agent can originate a direction.

```
1 circuit breakers        -> may force EXIT, never an entry
2 exchange protective stop -> may force EXIT
3 data quality gate        -> abstain on untrustworthy evidence
4 perception sufficiency   -> abstain without 200 completed daily closes
5 THE AGENT                -> the only source of direction
6 commit cadence           -> hold to the frequency it was validated at
```

## Layout

```
src/btc_decision_agent/
  application/
    exposure_agent.py      the policy: regimes, gradient, reward specification
    exposure_features.py   perception, identical in training and live
    exposure_training.py   on-policy rollout, no look-ahead
    exposure_runtime.py    live wiring + the engine that vetoes but never decides
    realtime_demo.py       observer, runner, protections, durable state
    execution_intents.py   PREPARED-before-POST idempotency ledger
  observability/
    agent_dashboard.py     pixel dashboard (read-only)
scripts/
  run_exposure_agent.py    the process that holds order authority
  run_agent_dashboard.py   dashboard
  daily_summary.py         concise daily Slack summary
  promote_exposure_agent.py the only thing that grants order authority
research/                  training, walk-forward selection, diagnostics
legacy/                    retired designs, kept for audit; NOT deployed, NOT imported
```

## Running it

```bash
# validate
.venv/bin/ruff check . && .venv/bin/mypy -p btc_decision_agent && .venv/bin/pytest -q

# train and select (writes the policy + reports)
PYTHONPATH=src:research .venv/bin/python research/train_exposure_agent.py

# grant order authority (records the evidence into the policy file)
PYTHONPATH=src .venv/bin/python scripts/promote_exposure_agent.py

# observe without trading
PYTHONPATH=src:. .venv/bin/python scripts/run_exposure_agent.py --dry-run

# place DEMO orders (explicit opt-in required)
PYTHONPATH=src:. .venv/bin/python scripts/run_exposure_agent.py --i-understand-this-is-demo
```

The runtime refuses to start unless the policy document is `PROMOTED`, and refuses
to run against anything other than the DEMO venue.

## Safety

- DEMO only. `--i-understand-this-is-demo` is required before any order is placed.
- Exactly one order-authority service is ever installed and enabled.
- Exchange-side `STOP_LOSS` is placed and tracked; it is not a soft in-process stop.
- Orders are idempotent via a PREPARED-before-POST SQLite intent ledger.
- Credentials come from `.env`, which is gitignored. Never commit real keys.
