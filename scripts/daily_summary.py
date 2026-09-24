"""Concise daily summary of what the exposure agent actually did.

Replaces the old weekly strategy-comparison report, which compared two retired
agents and no longer describes the system.

Reads only the activity journal and the policy document, so it needs no API
credentials: the journal already carries balances, price and the agent's own
reasoning for every evaluation. Keeping this read-only means the report can never
disturb the running agent.

Summarises a rolling 24-hour window rather than a calendar day, so the output does
not depend on what time the timer happens to fire and never reports a half day.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

D = Decimal
DEFAULT_JOURNAL = "data/live/exposure-agent-activity.jsonl"
DEFAULT_POLICY = "data/models/local-exposure-agent-v1.json"
_REGIME = re.compile(r"_R(\d+)_")

REGIME_LABELS = {
    0: "recuperacion",
    1: "bajista",
    2: "consolidacion",
    3: "alcista",
}
"""Human labels for the regimes the gate learned, from the regime audit report.

These are descriptions of observed behaviour, not inputs: the agent never reads
them. If the policy is retrained the labels must be re-derived from
research/inspect_agent_regimes.py rather than assumed.
"""


def read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def _equity(entry: dict[str, Any]) -> Decimal | None:
    if entry.get("price") is None:
        return None
    usdt = D(entry.get("usdt_free") or "0") + D(entry.get("usdt_locked") or "0")
    btc = D(entry.get("btc_qty") or "0")
    return usdt + btc * D(entry["price"])


def _pct(new: Decimal, old: Decimal) -> Decimal | None:
    if old <= 0:
        return None
    return (new / old - D("1")) * D("100")


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def build_summary(
    entries: list[dict[str, Any]], policy: dict[str, Any], *, hours: int, now: datetime
) -> dict[str, Any]:
    window_start = now - timedelta(hours=hours)
    in_window = [
        entry
        for entry in entries
        if entry.get("at") and datetime.fromisoformat(entry["at"]) >= window_start
    ]
    latest = entries[-1] if entries else None
    first = in_window[0] if in_window else None

    orders = [entry for entry in in_window if entry.get("order_side")]
    buys = [entry for entry in orders if entry["order_side"] == "BUY"]
    sells = [entry for entry in orders if entry["order_side"] == "SELL"]

    # Anything whose reason does not come from the agent was a deterministic layer
    # refusing to act. Distinguishing these is the point of the report: a quiet day
    # because the agent chose to hold is very different from a quiet day because a
    # data gate was blocking it.
    vetoes = Counter(
        entry.get("reason", "")
        for entry in in_window
        if not str(entry.get("reason", "")).removeprefix("DRY_RUN:").startswith("AGENT_")
    )
    regimes = Counter(
        int(match.group(1))
        for entry in in_window
        if (match := _REGIME.search(str(entry.get("reason", ""))))
    )
    decisions = Counter(
        entry.get("model_direction")
        for entry in in_window
        if entry.get("model_direction")
    )

    equity_now = _equity(latest) if latest else None
    equity_then = _equity(first) if first else None
    price_now = D(latest["price"]) if latest and latest.get("price") else None
    price_then = D(first["price"]) if first and first.get("price") else None

    fees = sum(
        (D(entry.get("fees_usdt") or "0") for entry in orders), D("0")
    )
    metadata = policy.get("metadata", {}) if isinstance(policy.get("metadata"), dict) else {}

    return {
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "window_start": window_start.isoformat(),
        "evaluations": len(in_window),
        "orders": len(orders),
        "buys": [
            {
                "at": entry["at"],
                "base": entry.get("order_base_qty"),
                "price": entry.get("order_avg_price"),
                "quote": entry.get("order_quote_usdt"),
            }
            for entry in buys
        ],
        "sells": [
            {
                "at": entry["at"],
                "base": entry.get("order_base_qty"),
                "price": entry.get("order_avg_price"),
                "quote": entry.get("order_quote_usdt"),
            }
            for entry in sells
        ],
        "fees_usdt": format(fees, "f"),
        "position": (latest.get("position_after") or latest.get("position_before")) if latest else None,
        "entry_price": latest.get("entry_price") if latest else None,
        "active_stop_price": latest.get("active_stop_price") if latest else None,
        "equity_usdt": format(equity_now, "f") if equity_now is not None else None,
        "equity_change_pct": (
            format(_pct(equity_now, equity_then), ".2f")
            if equity_now is not None and equity_then is not None and _pct(equity_now, equity_then) is not None
            else None
        ),
        "price_usdt": format(price_now, "f") if price_now is not None else None,
        "price_change_pct": (
            format(_pct(price_now, price_then), ".2f")
            if price_now is not None and price_then is not None and _pct(price_now, price_then) is not None
            else None
        ),
        "p_long": (
            (latest.get("model_probabilities") or {}).get("TARGET_LONG") if latest else None
        ),
        "dominant_regime": (
            max(regimes, key=lambda key: regimes[key]) if regimes else None
        ),
        "regime_share": {str(key): value / len(in_window) for key, value in regimes.items()}
        if in_window
        else {},
        "decision_counts": dict(decisions),
        "vetoes": dict(vetoes),
        "policy_version": metadata.get("promotion_status") and policy.get("policy_version"),
        "trained_steps": policy.get("trained_steps"),
        "online_learning": bool(latest.get("online_learning")) if latest else False,
        "last_seen": latest.get("at") if latest else None,
        "stale": (
            latest is not None
            and (now - datetime.fromisoformat(latest["at"])) > timedelta(minutes=15)
        ),
    }


def render(summary: dict[str, Any]) -> str:
    """A short Slack message. Brevity is the requirement, so no tables."""
    when = datetime.fromisoformat(summary["generated_at"]).strftime("%d %b %Y %H:%M UTC")
    lines = [f"*Agente de exposicion* · ultimas {summary['window_hours']}h · {when}"]

    if summary["stale"]:
        lines.append(f":warning: sin actividad desde {summary['last_seen']} — proceso posiblemente caido")

    if summary["orders"] == 0:
        lines.append("• Operaciones: ninguna")
    else:
        parts = []
        for order in summary["buys"]:
            parts.append(f"COMPRA {order['base']} BTC @ {order['price']}")
        for order in summary["sells"]:
            parts.append(f"VENTA {order['base']} BTC @ {order['price']}")
        lines.append(f"• Operaciones: {summary['orders']} — " + "; ".join(parts))
        if summary["fees_usdt"] and D(summary["fees_usdt"]) > 0:
            lines.append(f"• Comisiones: {summary['fees_usdt']} USDT")

    position = summary["position"] or "?"
    stop = summary["active_stop_price"]
    position_line = f"• Posicion: {position}"
    if position == "LONG" and stop:
        position_line += f" · stop {stop}"
    lines.append(position_line)

    if summary["equity_usdt"]:
        change = summary["equity_change_pct"]
        suffix = f" ({change}% en la ventana)" if change is not None else ""
        lines.append(f"• Equity: {_money(D(summary['equity_usdt']))} USDT{suffix}")
    if summary["price_usdt"]:
        change = summary["price_change_pct"]
        suffix = f" ({change}%)" if change is not None else ""
        lines.append(f"• BTC: {_money(D(summary['price_usdt']))}{suffix}")

    regime = summary["dominant_regime"]
    if regime is not None:
        label = REGIME_LABELS.get(regime, "?")
        p_long = summary["p_long"]
        view = f"regimen {regime} ({label})"
        if p_long is not None:
            view += f" · P(largo) {float(p_long) * 100:.0f}%"
        lines.append(f"• Criterio del agente: {view}")

    vetoes = summary["vetoes"]
    if vetoes:
        top = sorted(vetoes.items(), key=lambda item: item[1], reverse=True)[:3]
        lines.append("• Vetos: " + ", ".join(f"{name} x{count}" for name, count in top))
    else:
        lines.append("• Vetos: ninguno")

    lines.append(
        f"• Aprendizaje: {summary['trained_steps']} pasos"
        + (" (online activo)" if summary["online_learning"] else " (online apagado)")
    )
    return "\n".join(lines)


def send_slack(text: str) -> bool:
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        return False
    body = json.dumps({"text": text}).encode()
    request = urllib.request.Request(
        webhook, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = int(response.status)
    except (urllib.error.URLError, TimeoutError):
        return False
    return 200 <= status < 300


def main() -> None:
    parser = argparse.ArgumentParser(description="Concise daily summary of the agent's operations.")
    parser.add_argument("--journal", default=DEFAULT_JOURNAL)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--slack", action="store_true", help="post to SLACK_WEBHOOK_URL")
    parser.add_argument("--out", default="", help="also write the JSON summary here")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    from btc_decision_agent.application.process_guard import load_env_file

    load_env_file(args.env_file)

    entries = read_entries(Path(args.journal))
    policy_path = Path(args.policy)
    policy: dict[str, Any] = {}
    if policy_path.is_file():
        raw: object = json.loads(policy_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            policy = raw

    summary = build_summary(
        entries, policy, hours=args.hours, now=datetime.now(tz=UTC)
    )
    message = render(summary)
    print(message)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.slack:
        print("slack:", "sent" if send_slack(message) else "NOT sent (missing webhook or error)")


if __name__ == "__main__":
    main()
