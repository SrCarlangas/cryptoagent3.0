"""Generate and optionally send an auditable hard-rules vs ML-shadow report."""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from collections import OrderedDict
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

from btc_decision_agent.observability.dashboard import build_state

from btc_decision_agent.observability.journal import ActivityJournal


def shadow(rows: list[dict[str, object]]) -> dict[str, str | int]:
    hourly: OrderedDict[str, dict[str, object]] = OrderedDict()
    for row in rows:
        if row.get("model_direction") and row.get("price"):
            hourly[str(row["at"])[:13]] = row
    points = list(hourly.values())
    equity, entry, trades, fee = D(1), None, [], D(".001")
    for row in points:
        price, direction = D(str(row["price"])), row["model_direction"]
        if entry is None and direction == "BUY":
            entry = price * (1 + fee)
        elif entry is not None and direction == "SELL":
            result = price * (1 - fee) / entry - 1
            equity *= 1 + result
            trades.append(result)
            entry = None
    if entry is not None and points:
        equity *= D(str(points[-1]["price"])) * (1 - fee) / entry
    return {
        "sample_hours": len(points),
        "closed_trades": len(trades),
        "return_pct": str((equity - 1) * 100),
        "win_rate": str(D(sum(item > 0 for item in trades)) / D(len(trades)) if trades else 0),
    }


def send_slack(text: str) -> bool:
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        return False
    body = json.dumps({"text": text}).encode()
    request = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return 200 <= response.status < 300


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hard", required=True)
    parser.add_argument("--shadow", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--slack", action="store_true")
    args = parser.parse_args()
    hard = build_state(ActivityJournal(args.hard))
    ml = shadow(ActivityJournal(args.shadow).read())
    hard_result = {
        "version": hard.get("active_strategy_version"),
        "return_pct": (hard.get("strategy_vs_hold") or {}).get("strategy_return_pct"),
        "excess_vs_buy_hold_pct": (hard.get("strategy_vs_hold") or {}).get("excess_pct"),
        "orders": hard.get("order_count"),
        "position": hard.get("position"),
    }
    report = {"generated_at": datetime.now(UTC).isoformat(), "hard_rules": hard_result, "ml_shadow": ml}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    message = (
        "*CryptoAgent comparison*\n"
        f"Hard rules ({hard_result['version']}): return {hard_result['return_pct']}%, "
        f"excess vs hold {hard_result['excess_vs_buy_hold_pct']}%, orders {hard_result['orders']}.\n"
        f"ML shadow: return {ml['return_pct']}%, trades {ml['closed_trades']}, "
        f"win rate {ml['win_rate']}, sample {ml['sample_hours']}h.\n"
        "ML remains shadow; figures use an hourly virtual portfolio with 10 bps fee per side."
    )
    out.with_suffix(".md").write_text(f"# Agent comparison\n\n{message}\n")
    if args.slack and not send_slack(message):
        raise SystemExit("Slack webhook not configured or send failed")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
