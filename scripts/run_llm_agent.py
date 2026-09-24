"""Run the local LLM agent as the single order authority on Binance DEMO.

The agent is a local Qwen3-30B-A3B model reached over loopback. It reads a state
block computed from real Binance data plus five years of indexed history plus its
own outcome record, and chooses what the exposure should be.

Deterministic layers around it may veto or protect but never originate a direction.
If the model is unreachable or incoherent, the agent falls back to the quantitative
policy that was walk-forward validated on five years, so an LLM outage never leaves
the position unmanaged.

Orders stay DEMO-only and require explicit opt-in.
"""

from __future__ import annotations

import argparse
import signal
import threading
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from btc_decision_agent.adapters.binance_execution import build_demo_adapter
from btc_decision_agent.adapters.binance_stream import BinancePublicStreamAdapter
from btc_decision_agent.application.execution_intents import ExecutionIntentStore
from btc_decision_agent.application.llm_agent import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    LLMAgentEngine,
    build_agent,
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
DEFAULT_JOURNAL = "data/live/llm-agent-activity.jsonl"
DEFAULT_LOCK = "data/live/llm-agent.lock"
DEFAULT_STATE = "data/live/llm-agent-state.json"
DEFAULT_INTENTS = "data/live/llm-agent-intents.sqlite3"
DEFAULT_MEMORY = "data/live/llm-agent-memory.sqlite3"
DEFAULT_POLICY = "data/models/local-exposure-agent-v1.json"
DEFAULT_HISTORY = "data/models/history-index.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Local LLM agent on Binance DEMO.")
    parser.add_argument("--allocation-pct", default="95")
    parser.add_argument("--risk-per-trade-pct", default="2")
    parser.add_argument("--daily-loss-pct", default="5")
    parser.add_argument(
        "--max-drawdown-pct",
        default="25",
        help="portfolio disaster stop; wider than V4's 10%% because the agent's own "
        "out-of-sample drawdowns reached 34%%",
    )
    parser.add_argument(
        "--cadence-minutes",
        type=int,
        default=30,
        help="how often the agent re-deliberates. Protective layers stay live on "
        "every market event regardless of this",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--history-index", default=DEFAULT_HISTORY)
    parser.add_argument("--memory", default=DEFAULT_MEMORY)
    parser.add_argument(
        "--outcome-horizon-hours",
        type=int,
        default=24,
        help="how long before a decision's outcome is measured for learning",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--i-understand-this-is-demo", action="store_true")
    parser.add_argument("--journal", default=DEFAULT_JOURNAL)
    parser.add_argument("--lock-file", default=DEFAULT_LOCK)
    parser.add_argument("--state-file", default=DEFAULT_STATE)
    parser.add_argument("--intent-db", default=DEFAULT_INTENTS)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--max-events", type=int, default=0)
    args = parser.parse_args()
    load_env_file(args.env_file)

    allocation = D(args.allocation_pct)
    if not D("0") < allocation <= D("100"):
        raise SystemExit("--allocation-pct must be in (0, 100]")
    place_orders = args.i_understand_this_is_demo and not args.dry_run

    for label, path in (("policy", args.policy), ("history index", args.history_index)):
        if not Path(path).is_file():
            raise SystemExit(f"{label} not found: {path}")

    params = RealtimeParams(
        allocation_fraction=allocation / D("100"),
        risk_per_trade_fraction=D(args.risk_per_trade_pct) / D("100"),
        daily_loss_fraction=D(args.daily_loss_pct) / D("100"),
        max_drawdown_fraction=D(args.max_drawdown_pct) / D("100"),
    )

    try:
        agent = build_agent(
            policy_path=args.policy,
            index_path=args.history_index,
            memory_path=args.memory,
            model=args.model,
            endpoint=args.endpoint,
            horizon_hours=args.outcome_horizon_hours,
        )
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise SystemExit(f"could not build the agent: {error}") from error

    adapter = build_demo_adapter(enabled=True)
    if adapter.venue().value != "DEMO":
        raise SystemExit(f"refusing to run against {adapter.venue().value}; DEMO required")

    engine = LLMAgentEngine(
        params, agent, cadence=timedelta(minutes=args.cadence_minutes)
    )
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

    stats = agent.memory.stats()
    mode = "LIVE-DEMO" if place_orders else "SHADOW/DRY-RUN"
    print(
        f"mode={mode} model={args.model} cadence={args.cadence_minutes}min "
        f"history_days={agent.history.days} quant_steps={agent.policy.trained_steps} "
        f"memory_decisions={stats['decisiones_totales']} "
        f"allocation={allocation}% drawdown_breaker={args.max_drawdown_pct}%",
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
            if decision is not None and decision.reason not in {"AGENT_VERDICT_UNCHANGED"}:
                info = engine.last_explanation
                print(
                    f"[{decision.evidence.at.isoformat(timespec='seconds')}] "
                    f"action={decision.action.value} reason={decision.reason} "
                    f"target={info.get('target_exposure')} "
                    f"conv={info.get('conviction')} "
                    f"esperado={info.get('expected_move_pct')}% "
                    f"cubre_costo={info.get('clears_cost')} "
                    f"delib={info.get('deliberated')} "
                    f"{info.get('seconds')}s "
                    f"quant={info.get('quant_recommends')}/{info.get('quant_p_long')} "
                    f"veto={info.get('veto', 'none')}",
                    flush=True,
                )
                if info.get("reason"):
                    print(f"    razon: {str(info['reason'])[:300]}", flush=True)
            if args.max_events > 0 and processed >= args.max_events:
                break


if __name__ == "__main__":
    main()
