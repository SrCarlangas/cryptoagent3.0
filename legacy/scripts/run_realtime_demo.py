"""Run the single-authority, event-driven Binance DEMO agent.

The process observes public Binance streams continuously. Orders remain DEMO-only
and require explicit opt-in. Confidence model V1 is experimental/unvalidated.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from btc_decision_agent.application.local_ml import LocalMLAgent
from btc_decision_agent.policies.evidence_v4 import STRATEGY_VERSION

from btc_decision_agent.adapters.binance_execution import build_demo_adapter
from btc_decision_agent.adapters.binance_stream import BinancePublicStreamAdapter
from btc_decision_agent.application.execution_intents import ExecutionIntentStore
from btc_decision_agent.application.realtime_demo import (
    AdaptiveMarketObserver,
    ConfidenceDecisionEngine,
    EngineStateStore,
    RealtimeDemoRunner,
    RealtimeParams,
)
from btc_decision_agent.observability.journal import ActivityJournal

D = Decimal
DEFAULT_JOURNAL = "data/live/realtime-demo-activity.jsonl"
DEFAULT_LOCK = "data/live/realtime-demo.lock"
DEFAULT_STATE = "data/live/realtime-engine-state.json"
DEFAULT_INTENTS = "data/live/realtime-execution-intents.sqlite3"
DEFAULT_MODEL = "data/models/local-softmax-v1.json"


def load_env_file(path: str = ".env") -> None:
    """Load a local KEY=VALUE file without logging or overwriting exported vars."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, value)


@contextmanager
def single_instance(path: str) -> Iterator[None]:
    """Fail closed when another order-authority process owns the lock."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SystemExit(f"another realtime demo runner owns {path}") from error
        stream.seek(0)
        stream.truncate()
        stream.write(str(os.getpid()))
        stream.flush()
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def main() -> None:
    parser = argparse.ArgumentParser(description="Event-driven Binance DEMO agent.")
    parser.add_argument(
        "--allocation-pct",
        type=str,
        default="80",
        help="percentage of currently free USDT allocated on each BUY (default: 80)",
    )
    parser.add_argument("--buy-confidence", type=str, default="0.72")
    parser.add_argument("--sell-confidence", type=str, default="0.42")
    parser.add_argument("--buy-persistence-seconds", type=int, default=120)
    parser.add_argument("--sell-persistence-seconds", type=int, default=180)
    parser.add_argument("--cooldown-seconds", type=int, default=3600)
    parser.add_argument("--risk-per-trade-pct", type=str, default="2")
    parser.add_argument("--daily-loss-pct", type=str, default="5")
    parser.add_argument("--max-drawdown-pct", type=str, default="10")
    parser.add_argument("--dry-run", action="store_true", help="observe and decide without orders")
    parser.add_argument(
        "--i-understand-this-is-demo",
        action="store_true",
        help="required to place experimental DEMO orders",
    )
    parser.add_argument("--journal", default=DEFAULT_JOURNAL)
    parser.add_argument("--lock-file", default=DEFAULT_LOCK)
    parser.add_argument("--state-file", default=DEFAULT_STATE)
    parser.add_argument("--intent-db", default=DEFAULT_INTENTS)
    parser.add_argument(
        "--model-path",
        default=DEFAULT_MODEL,
        help="trained local softmax JSON; startup fails closed when absent or invalid",
    )
    parser.add_argument(
        "--online-learning",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="persist causal delayed-label updates and experience (default: disabled)",
    )
    parser.add_argument(
        "--allow-unpromoted-model",
        action="store_true",
        help="allow a rejected model for dry-run research only; never permits orders",
    )
    parser.add_argument("--env-file", default=".env", help="local credentials file; exported env wins")
    parser.add_argument("--max-events", type=int, default=0, help="exit after N stream events; 0 is continuous")
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
        buy_confidence=D(args.buy_confidence),
        sell_confidence=D(args.sell_confidence),
        buy_persistence_seconds=args.buy_persistence_seconds,
        sell_persistence_seconds=args.sell_persistence_seconds,
        cooldown_seconds=args.cooldown_seconds,
        risk_per_trade_fraction=D(args.risk_per_trade_pct) / D("100"),
        daily_loss_fraction=D(args.daily_loss_pct) / D("100"),
        max_drawdown_fraction=D(args.max_drawdown_pct) / D("100"),
    )

    model_path = Path(args.model_path)
    if not model_path.is_file():
        raise SystemExit(
            f"local model not found: {model_path}; run python -m scripts.train_local_model"
        )
    try:
        directional_model = LocalMLAgent(
            model_path,
            online_learning=args.online_learning,
            round_trip_cost_bps=params.round_trip_cost_bps,
            decision_threshold_bps=params.min_expected_edge_bps,
            allow_unpromoted=args.allow_unpromoted_model,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"local model rejected: {error}") from error

    adapter = build_demo_adapter(enabled=True)
    if adapter.venue().value != "DEMO":
        raise SystemExit(f"refusing to run against {adapter.venue().value}; DEMO required")
    stream = BinancePublicStreamAdapter()
    observer = AdaptiveMarketObserver()
    runner = RealtimeDemoRunner(
        adapter,
        observer,
        ConfidenceDecisionEngine(params, directional_model),
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
        f"mode={mode} strategy={STRATEGY_VERSION} model={directional_model.model_version} "
        f"online_learning={args.online_learning} allocation={allocation_pct}% "
        f"risk={args.risk_per_trade_pct}% journal={args.journal} state={args.state_file} "
        f"intents={args.intent_db}",
        flush=True,
    )

    with single_instance(args.lock_file):
        runner.bootstrap()
        for processed, event in enumerate(stream.events(stop), start=1):
            if stop.is_set():
                break
            decision = runner.process_event(event)
            if decision is not None:
                evidence = decision.evidence
                prediction = decision.model_prediction
                print(
                    f"[{evidence.at.isoformat(timespec='seconds')}] "
                    f"action={decision.action.value} reason={decision.reason} "
                    f"model_direction={prediction.direction.value if prediction else 'VETOED'} "
                    f"model_confidence={prediction.confidence if prediction else 'n/a'} "
                    f"structural={evidence.structural_confidence} "
                    f"tactical={evidence.tactical_confidence} grade={evidence.grade} "
                    f"net_tactical_edge={evidence.expected_edge_bps}bps "
                    f"coverage={evidence.coverage}",
                    flush=True,
                )
            if args.max_events > 0 and processed >= args.max_events:
                break


if __name__ == "__main__":
    main()
