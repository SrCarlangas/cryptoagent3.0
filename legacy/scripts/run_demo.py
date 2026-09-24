"""CLI to run the demo trading loop against the Binance DEMO account.

Safety:
- Uses the demo venue only (https://demo-api.binance.com). Real capital is blocked.
- Requires --i-understand-this-is-demo to place orders; otherwise dry-run.
- Loads credentials from the environment (source your .env first).

Examples:
    set -a; source .env; set +a
    # one dry-run evaluation (no orders):
    .venv/bin/python -m scripts.run_demo --once --dry-run
    # one real demo evaluation (may place a demo order):
    .venv/bin/python -m scripts.run_demo --once --i-understand-this-is-demo
    # continuous loop, evaluating every 3600s:
    .venv/bin/python -m scripts.run_demo --loop --interval 4h --period-seconds 3600 --i-understand-this-is-demo
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from btc_decision_agent.application.live_demo import BaselineParams, DemoLiveRunner, LiveDecision

from btc_decision_agent.adapters.binance_execution import build_demo_adapter
from btc_decision_agent.domain.contracts import RiskMandate
from btc_decision_agent.observability.journal import ActivityJournal, entry_from_live

D = Decimal
DEFAULT_JOURNAL = "data/live/demo-activity.jsonl"


def _record(journal: ActivityJournal, decision: LiveDecision, *, venue: str, interval: str) -> None:
    order = decision.order
    journal.append(
        entry_from_live(
            venue=venue,
            interval=interval,
            action=decision.action.value,
            reason=decision.reason,
            position_before=decision.position_before.value,
            fast_sma=decision.fast_sma,
            slow_sma=decision.slow_sma,
            price=decision.price,
            usdt_free=decision.usdt_free,
            btc_qty=decision.btc_qty,
            order_side=order.side.value if order else None,
            order_quote_usdt=order.executed_quote_usdt if order else None,
            order_base_qty=order.executed_base_qty if order else None,
            order_avg_price=order.average_price if order else None,
            order_id=order.exchange_order_id if order else None,
            at=decision.at,
        )
    )


def _demo_mandate(max_exposure: Decimal) -> RiskMandate:
    now = datetime.now(tz=UTC)
    return RiskMandate(
        version="demo/1",
        authored_by="operator-demo",
        authored_at=now - timedelta(days=1),
        capital=max_exposure * D("10"),
        risk_per_decision=D("0.0025"),
        max_exposure=max_exposure,
        daily_loss_max=max_exposure * D("0.5"),
        drawdown_max=max_exposure * D("2"),
        min_notional=D("10"),
        step_size=D("0.00001"),
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=365),
    )


def _print(decision: LiveDecision) -> None:
    order = decision.order
    fills = (
        f" | fill {order.side.value} {order.executed_quote_usdt} USDT @ {order.average_price} (id={order.exchange_order_id})"
        if order is not None
        else ""
    )
    fast = f"{decision.fast_sma:.2f}" if decision.fast_sma is not None else "-"
    slow = f"{decision.slow_sma:.2f}" if decision.slow_sma is not None else "-"
    print(f"[{decision.at.isoformat(timespec='seconds')}] pos={decision.position_before.value} action={decision.action.value} reason={decision.reason} sma_fast={fast} sma_slow={slow}{fills}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Binance DEMO trading loop (no real funds).")
    parser.add_argument("--once", action="store_true", help="run a single evaluation and exit")
    parser.add_argument("--loop", action="store_true", help="run continuously")
    parser.add_argument("--interval", default="4h", choices=["1h", "4h", "1d"], help="strategy bar interval")
    parser.add_argument("--fast", type=int, default=12, help="fast SMA window (bars)")
    parser.add_argument("--slow", type=int, default=48, help="slow SMA window (bars)")
    parser.add_argument("--max-exposure-usdt", type=str, default="1000", help="max notional per position")
    parser.add_argument("--period-seconds", type=int, default=3600, help="seconds between evaluations in --loop")
    parser.add_argument("--dry-run", action="store_true", help="decide but never place orders")
    parser.add_argument("--i-understand-this-is-demo", action="store_true", help="required to place demo orders")
    parser.add_argument("--journal", default=DEFAULT_JOURNAL, help="activity journal path for the dashboard")
    args = parser.parse_args()

    place_orders = args.i_understand_this_is_demo and not args.dry_run
    if place_orders:
        raise SystemExit(
            "legacy clock-driven execution is disabled; use "
            "python -m scripts.run_realtime_demo --i-understand-this-is-demo"
        )
    adapter = build_demo_adapter(enabled=True)
    if adapter.venue().value != "DEMO":
        raise SystemExit(f"refusing to run: venue is {adapter.venue().value}, expected DEMO")
    mandate = _demo_mandate(D(args.max_exposure_usdt))
    runner = DemoLiveRunner(adapter, mandate, BaselineParams(fast=args.fast, slow=args.slow, interval=args.interval))
    journal = ActivityJournal(args.journal)

    mode = "LIVE-DEMO (orders enabled)" if place_orders else "DRY-RUN (no orders)"
    print(f"venue=DEMO mode={mode} interval={args.interval} sma={args.fast}/{args.slow} max_exposure={args.max_exposure_usdt} USDT journal={args.journal}", flush=True)

    def cycle() -> None:
        decision = runner.evaluate_once(dry_run=not place_orders)
        _record(journal, decision, venue="DEMO", interval=args.interval)
        _print(decision)

    if args.loop:
        while True:
            cycle()
            time.sleep(max(args.period_seconds, 1))
    else:
        cycle()


if __name__ == "__main__":
    main()
