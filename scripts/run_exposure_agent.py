"""Run the local exposure AGENT as the single order authority on Binance DEMO.

The agent is the only source of direction. Deterministic layers around it may veto
or protect but never originate a BUY or a SELL, and there is no moving-average or
threshold rule anywhere in the decision path.

Orders stay DEMO-only and require explicit opt-in. Startup fails closed when the
policy is missing, schema-mismatched, or not promoted.
"""

from __future__ import annotations

import argparse
import signal
import threading
from decimal import Decimal
from pathlib import Path

from btc_decision_agent.adapters.binance_execution import build_demo_adapter
from btc_decision_agent.adapters.binance_stream import BinancePublicStreamAdapter
from btc_decision_agent.application.execution_intents import ExecutionIntentStore
from btc_decision_agent.application.exposure_runtime import (
    ExposureAgentEngine,
    ExposureAgentRuntime,
)
from btc_decision_agent.application.process_guard import load_env_file, single_instance
from btc_decision_agent.application.realtime_demo import (
    AdaptiveMarketObserver,
    EngineStateStore,
    RealtimeDemoRunner,
    RealtimeParams,
)
from btc_decision_agent.observability.journal import ActivityJournal

D = Decimal
DEFAULT_JOURNAL = "data/live/exposure-agent-activity.jsonl"
DEFAULT_LOCK = "data/live/exposure-agent.lock"
DEFAULT_STATE = "data/live/exposure-agent-state.json"
DEFAULT_INTENTS = "data/live/exposure-agent-intents.sqlite3"
DEFAULT_MODEL = "data/models/local-exposure-agent-v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Local exposure agent on Binance DEMO.")
    parser.add_argument(
        "--allocation-pct",
        type=str,
        default="95",
        help=(
            "percentage of free USDT deployed when the agent goes long. The agent "
            "decides WHETHER to be exposed; this bounds HOW MUCH (default: 95)"
        ),
    )
    parser.add_argument("--risk-per-trade-pct", type=str, default="2")
    parser.add_argument("--daily-loss-pct", type=str, default="5")
    parser.add_argument(
        "--max-drawdown-pct",
        type=str,
        default="25",
        help=(
            "portfolio disaster stop. Deliberately wider than the V4 default of 10 "
            "because the agent's own drawdowns out of sample reached 34%%; a 10%% "
            "breaker would fire on normal behaviour and permanently flatten it"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="observe and decide without orders")
    parser.add_argument(
        "--i-understand-this-is-demo",
        action="store_true",
        help="required to place DEMO orders",
    )
    parser.add_argument("--journal", default=DEFAULT_JOURNAL)
    parser.add_argument("--lock-file", default=DEFAULT_LOCK)
    parser.add_argument("--state-file", default=DEFAULT_STATE)
    parser.add_argument("--intent-db", default=DEFAULT_INTENTS)
    parser.add_argument("--model-path", default=DEFAULT_MODEL)
    parser.add_argument(
        "--online-learning",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="keep learning from realised outcomes in production (default: enabled)",
    )
    parser.add_argument(
        "--allow-unpromoted-model",
        action="store_true",
        help="dry-run research only; never permits orders",
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--max-events", type=int, default=0)
    args = parser.parse_args()
    load_env_file(args.env_file)

    allocation_pct = D(args.allocation_pct)
    if not D("0") < allocation_pct <= D("100"):
        raise SystemExit("--allocation-pct must be in (0, 100]")
    place_orders = args.i_understand_this_is_demo and not args.dry_run
    if place_orders and args.allow_unpromoted_model:
        raise SystemExit("--allow-unpromoted-model is restricted to dry-run research")

    params = RealtimeParams(
        allocation_fraction=allocation_pct / D("100"),
        risk_per_trade_fraction=D(args.risk_per_trade_pct) / D("100"),
        daily_loss_fraction=D(args.daily_loss_pct) / D("100"),
        max_drawdown_fraction=D(args.max_drawdown_pct) / D("100"),
    )

    model_path = Path(args.model_path)
    if not model_path.is_file():
        raise SystemExit(
            f"exposure policy not found: {model_path}; "
            "run PYTHONPATH=src:research python research/train_exposure_agent.py"
        )
    try:
        agent = ExposureAgentRuntime(
            model_path,
            online_learning=args.online_learning,
            round_trip_cost_bps=params.round_trip_cost_bps,
            allow_unpromoted=args.allow_unpromoted_model,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"exposure policy rejected: {error}") from error

    adapter = build_demo_adapter(enabled=True)
    if adapter.venue().value != "DEMO":
        raise SystemExit(f"refusing to run against {adapter.venue().value}; DEMO required")

    engine = ExposureAgentEngine(params, agent)
    runner = RealtimeDemoRunner(
        adapter,
        AdaptiveMarketObserver(),
        engine,
        ActivityJournal(args.journal),
        params,
        state_store=EngineStateStore(args.state_file),
        intent_store=ExecutionIntentStore(args.intent_db),
        dry_run=not place_orders,
    )
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    mode = "LIVE-DEMO" if place_orders else "SHADOW/DRY-RUN"
    print(
        f"mode={mode} policy={agent.policy_version} "
        f"regimes={agent.policy.regimes} trained_steps={agent.policy.trained_steps} "
        f"cadence={agent.cadence} online_learning={args.online_learning} "
        f"allocation={allocation_pct}% drawdown_breaker={args.max_drawdown_pct}% "
        f"journal={args.journal} state={args.state_file}",
        flush=True,
    )

    stream = BinancePublicStreamAdapter()
    with single_instance(args.lock_file):
        runner.bootstrap()
        print(
            f"bootstrap complete: daily_history={runner.observer.daily_history_days} days",
            flush=True,
        )
        for processed, event in enumerate(stream.events(stop), start=1):
            if stop.is_set():
                break
            decision = runner.process_event(event)
            if decision is not None:
                explanation = engine.last_explanation
                evidence = decision.evidence
                print(
                    f"[{evidence.at.isoformat(timespec='seconds')}] "
                    f"action={decision.action.value} reason={decision.reason} "
                    f"p_long={explanation.get('p_long')} "
                    f"regime={explanation.get('dominant_regime')} "
                    f"veto={explanation.get('veto', 'none')} "
                    f"price={evidence.price} "
                    f"daily_history={runner.observer.daily_history_days}",
                    flush=True,
                )
            if args.max_events > 0 and processed >= args.max_events:
                break


if __name__ == "__main__":
    main()
