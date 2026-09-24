"""Print an honest performance report of the demo agent vs buy & hold.

Reads the activity journal (no network, no orders) and prints returns, order
counts, exposure and the excess over simply holding BTC. This is the objective,
auditable answer to "is the strategy adding value?".

Example:
    .venv/bin/python -m scripts.demo_report --journal data/live/demo-activity.jsonl
"""

from __future__ import annotations

import argparse
from decimal import Decimal

from btc_decision_agent.observability.dashboard import build_state

from btc_decision_agent.observability.journal import ActivityJournal

D = Decimal


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo agent performance report vs buy & hold.")
    parser.add_argument("--journal", default="data/live/demo-activity.jsonl", help="activity journal path")
    args = parser.parse_args()

    state = build_state(ActivityJournal(args.journal), history=10)
    svh = state["strategy_vs_hold"]
    print("=== BTC Decision Agent — DEMO performance report ===")
    print(f"venue:          {state['venue']}")
    print(f"interval:       {state['interval']}")
    print(f"evaluations:    {state['eval_count']}")
    print(f"orders:         {state['order_count']} ({state['buy_count']} buy / {state['sell_count']} sell)")
    print(f"position now:   {state['position']}")
    print(f"equity (USDT):  {state['equity_usdt']}")
    if svh is None:
        print("\nNot enough data yet for a strategy-vs-hold comparison (need 2+ priced evaluations).")
        return
    strat = D(svh["strategy_return_pct"])
    hold = D(svh["buy_hold_return_pct"])
    excess = D(svh["excess_pct"])
    verdict = "STRATEGY AHEAD of buy&hold" if excess > 0 else "STRATEGY BEHIND buy&hold" if excess < 0 else "TIED with buy&hold"
    print("\n--- strategy vs buy & hold (same starting capital) ---")
    print(f"strategy return:   {strat:+.4f}%")
    print(f"buy & hold return: {hold:+.4f}%")
    print(f"excess vs hold:    {excess:+.4f}%   -> {verdict}")
    print("\nNote: demo funds only. A positive excess over a meaningful sample is the")
    print("bar to clear before real capital is even discussed.")


if __name__ == "__main__":
    main()
