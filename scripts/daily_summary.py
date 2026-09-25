"""Concise daily summary of what the LLM agent actually did.

Reports the agent that decides now. The previous version described the numeric
policy: its regime, its probability, its gradient steps. That policy is still in the
system as advisor and fallback, but it is no longer the decision maker, so a report
organised around it described a system that no longer exists. Worse, it counted
FALLBACK_QUANT entries as vetoes, which reads as "a protective layer blocked the
agent" when what actually happened is "the model did not answer and the fallback
decided". Those call for completely different reactions.

Reads only the activity journal and the agent's memory, both read-only, so it needs
no API credentials and can never disturb the running agent.

Summarises a rolling 24-hour window rather than a calendar day, so the output does
not depend on what time the timer happens to fire and never reports a half day.

Brevity is the stated requirement, so the message is capped at a handful of lines
and the test suite asserts it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from btc_decision_agent.observability.llm_agent_dashboard import (
    classify_origin,
    recent_deliberations,
    track_record_view,
)

D = Decimal
DEFAULT_JOURNAL = "data/live/llm-agent-activity.jsonl"
DEFAULT_MEMORY = "data/live/llm-agent-memory.sqlite3"
DEFAULT_MODEL = "qwen3:30b-a3b"
_REGIME = re.compile(r"_R(\d+)_")

REGIME_LABELS = {
    0: "recuperacion",
    1: "bajista",
    2: "consolidacion",
    3: "alcista",
}
"""Human labels for the regimes the advisor learned, from the regime audit report.

Descriptions of observed behaviour, not inputs: nothing reads them. If the advisor
is retrained they must be re-derived from research/inspect_agent_regimes.py rather
than assumed.
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
    entries: list[dict[str, Any]],
    *,
    memory_path: Path | None = None,
    model: str = DEFAULT_MODEL,
    hours: int,
    now: datetime,
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

    # Who decided, counted rather than assumed. A quiet day because the agent chose
    # to hold, a quiet day because the fallback was driving, and a quiet day because
    # a data gate was blocking are three different situations.
    origins: Counter[str] = Counter(
        classify_origin(str(entry.get("reason", "")).removeprefix("DRY_RUN:"))
        for entry in in_window
    )
    # Only genuine vetoes. Neither an agent decision nor a fallback decision is a
    # veto; conflating them is what made the old report misleading.
    vetoes = Counter(
        str(entry.get("reason", "")).removeprefix("DRY_RUN:")
        for entry in in_window
        if classify_origin(str(entry.get("reason", "")).removeprefix("DRY_RUN:")) == "VETADO"
    )
    regimes = Counter(
        int(match.group(1))
        for entry in in_window
        if (match := _REGIME.search(str(entry.get("reason", ""))))
    )

    equity_now = _equity(latest) if latest else None
    equity_then = _equity(first) if first else None
    price_now = D(latest["price"]) if latest and latest.get("price") else None
    price_then = D(first["price"]) if first and first.get("price") else None

    fees = sum((D(entry.get("fees_usdt") or "0") for entry in orders), D("0"))

    # Whether these decisions could actually place an order: read from the recorded
    # field, never inferred. The DRY_RUN prefix only appears on entries that wanted
    # to trade, so a shadow agent that spent the day holding looks live without this.
    authority: bool | None = None
    for entry in reversed(entries):
        if entry.get("order_authority") is not None:
            authority = bool(entry["order_authority"])
            break
    else:
        if latest is not None and str(latest.get("reason", "")).startswith("DRY_RUN:"):
            authority = False

    verdict: dict[str, Any] | None = None
    record: dict[str, Any] = {}
    if memory_path is not None:
        deliberations = recent_deliberations(memory_path, limit=1)
        verdict = deliberations[0] if deliberations else None
        record = track_record_view(memory_path)

    patterns = record.get("patterns") or []
    supported = sum(1 for item in patterns if item["supported"])

    return {
        "generated_at": now.isoformat(),
        "model": model,
        "window_hours": hours,
        "window_start": window_start.isoformat(),
        "order_authority": authority,
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
        "position": (latest.get("position_after") or latest.get("position_before"))
        if latest
        else None,
        "entry_price": latest.get("entry_price") if latest else None,
        "active_stop_price": latest.get("active_stop_price") if latest else None,
        "equity_usdt": format(equity_now, "f") if equity_now is not None else None,
        "equity_change_pct": (
            format(_pct(equity_now, equity_then), ".2f")
            if equity_now is not None
            and equity_then is not None
            and _pct(equity_now, equity_then) is not None
            else None
        ),
        "price_usdt": format(price_now, "f") if price_now is not None else None,
        "price_change_pct": (
            format(_pct(price_now, price_then), ".2f")
            if price_now is not None
            and price_then is not None
            and _pct(price_now, price_then) is not None
            else None
        ),
        # The agent's standing verdict, in its own terms.
        "target_exposure": (verdict or {}).get("target_exposure"),
        "conviction": (verdict or {}).get("conviction"),
        "expected_move_pct": (verdict or {}).get("expected_move_pct"),
        "advisor_says": (verdict or {}).get("quant_says"),
        "advisor_p_long": (verdict or {}).get("quant_p_long"),
        "overrode_advisor": (verdict or {}).get("overrode_quant"),
        "decided_by_llm": origins.get("LLM", 0) + origins.get("LLM_SOSTENIDO", 0),
        "decided_by_fallback": origins.get("FALLBACK", 0),
        "vetoed": origins.get("VETADO", 0),
        "dominant_regime": (max(regimes, key=lambda key: regimes[key]) if regimes else None),
        "vetoes": dict(vetoes),
        "memory_decisions": (record.get("stats") or {}).get("decisiones_totales"),
        "memory_resolved": (record.get("stats") or {}).get("resueltas"),
        "memory_mean_pct": (record.get("stats") or {}).get("resultado_medio_pct"),
        "patterns_supported": supported,
        "patterns_inconclusive": len(patterns) - supported,
        "last_seen": latest.get("at") if latest else None,
        "stale": (
            latest is not None
            and (now - datetime.fromisoformat(latest["at"])) > timedelta(minutes=15)
        ),
    }


def render(summary: dict[str, Any]) -> str:
    """A short Slack message. Brevity is the requirement, so no tables."""
    when = datetime.fromisoformat(summary["generated_at"]).strftime("%d %b %Y %H:%M UTC")
    lines = [
        f"*Agente LLM · {summary['model']}* · ultimas {summary['window_hours']}h · {when}"
    ]

    if summary["stale"]:
        lines.append(
            f":warning: sin actividad desde {summary['last_seen']} — proceso posiblemente caido"
        )
    if summary["order_authority"] is False:
        lines.append(":warning: SOMBRA: razona y aprende pero no coloca ordenes")
    elif summary["order_authority"] is None:
        lines.append(":warning: no se pudo confirmar si tiene autoridad de ordenes")

    if summary["orders"] == 0:
        lines.append("• Operaciones: ninguna")
    else:
        parts = [f"COMPRA {o['base']} BTC @ {o['price']}" for o in summary["buys"]]
        parts += [f"VENTA {o['base']} BTC @ {o['price']}" for o in summary["sells"]]
        line = f"• Operaciones: {summary['orders']} — " + "; ".join(parts)
        if summary["fees_usdt"] and D(summary["fees_usdt"]) > 0:
            line += f" · comisiones {summary['fees_usdt']} USDT"
        lines.append(line)

    position_line = f"• Posicion: {summary['position'] or '?'}"
    if summary["position"] == "LONG":
        if summary["entry_price"]:
            position_line += f" · entrada {summary['entry_price']}"
        if summary["active_stop_price"]:
            position_line += f" · stop {summary['active_stop_price']}"
    lines.append(position_line)

    book: list[str] = []
    if summary["equity_usdt"]:
        change = summary["equity_change_pct"]
        book.append(
            f"Equity {_money(D(summary['equity_usdt']))} USDT"
            + (f" ({change}%)" if change is not None else "")
        )
    if summary["price_usdt"]:
        change = summary["price_change_pct"]
        book.append(
            f"BTC {_money(D(summary['price_usdt']))}" + (f" ({change}%)" if change is not None else "")
        )
    if book:
        lines.append("• " + " · ".join(book))

    # The agent's own conclusion, which is the thing a reader most wants.
    if summary["target_exposure"]:
        verdict = f"• Veredicto: {summary['target_exposure']}"
        if summary["conviction"] is not None:
            verdict += f" conv {float(summary['conviction']) * 100:.0f}%"
        if summary["expected_move_pct"] is not None:
            verdict += f" esperado {float(summary['expected_move_pct']):+.2f}%"
        if summary["advisor_says"]:
            verdict += f" · asesor {summary['advisor_says']}"
            if summary["advisor_p_long"] is not None:
                verdict += f" p={float(summary['advisor_p_long']):.2f}"
            if summary["overrode_advisor"]:
                verdict += " (contradicho)"
        regime = summary["dominant_regime"]
        if regime is not None:
            verdict += f" · regimen {regime} ({REGIME_LABELS.get(regime, '?')})"
        lines.append(verdict)

    lines.append(
        f"• Quien decidio: LLM {summary['decided_by_llm']} · "
        f"fallback {summary['decided_by_fallback']} · vetado {summary['vetoed']}"
    )

    if summary["memory_decisions"] is not None:
        mean = summary["memory_mean_pct"]
        # Deliberately not called "aprendizaje": the model's weights never change.
        # This is the measured record that gets shown to it in its prompt.
        line = (
            f"• Historial medido: {summary['memory_decisions']} decisiones, "
            f"{summary['memory_resolved']} resueltas"
        )
        if mean is not None:
            line += f", medio {float(mean):+.2f}%"
        line += (
            f" · {summary['patterns_supported']} patrones con respaldo, "
            f"{summary['patterns_inconclusive']} no concluyentes"
        )
        lines.append(line)

    vetoes = summary["vetoes"]
    if vetoes:
        top = sorted(vetoes.items(), key=lambda item: item[1], reverse=True)[:3]
        lines.append("• Vetos: " + ", ".join(f"{name} x{count}" for name, count in top))

    return "\n".join(lines)


SLACK_API = "https://slack.com/api/chat.postMessage"


def _post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return int(response.status), response.read()


def send_slack(text: str) -> tuple[bool, str]:
    """Post to Slack, returning whether it worked and why not if it did not.

    Two transports, because this workspace uses a bot rather than a webhook. If
    SLACK_BOT_TOKEN is set the message goes through chat.postMessage to
    SLACK_CHANNEL; otherwise SLACK_WEBHOOK_URL is used if present.

    The reason is returned rather than collapsed into a bool because "nothing is
    configured" and "Slack rejected the post" need different fixes, and because this
    reported success for weeks while delivering nothing.
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

    if token:
        channel = os.environ.get("SLACK_CHANNEL", "").strip()
        if not channel:
            return False, "SLACK_BOT_TOKEN esta puesta pero falta SLACK_CHANNEL"
        if not token.startswith("xoxb-"):
            return False, "SLACK_BOT_TOKEN no parece un token de bot (xoxb-)"
        body = json.dumps({"channel": channel, "text": text}).encode()
        try:
            _status, raw = _post(
                SLACK_API,
                body,
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": f"Bearer {token}",
                },
            )
        except urllib.error.HTTPError as error:
            return False, f"Slack respondio http {error.code}"
        except (urllib.error.URLError, TimeoutError) as error:
            return False, f"no se pudo contactar con Slack: {error}"
        # The Web API answers 200 even when it refuses the message, so the status
        # code proves nothing and the body has to be read. Trusting the 200 here is
        # exactly how a broken channel looks healthy.
        try:
            answer = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, "Slack devolvio una respuesta ilegible"
        if answer.get("ok"):
            return True, f"chat.postMessage -> {channel}"
        return False, f"Slack rechazo el mensaje: {answer.get('error', 'desconocido')}"

    if not webhook:
        return False, "no hay SLACK_BOT_TOKEN ni SLACK_WEBHOOK_URL configurados"
    # The message carries the live position and the book, so it must only ever go to
    # Slack. A typo in the variable would otherwise publish the account state to an
    # arbitrary host.
    if not webhook.startswith("https://hooks.slack.com/"):
        return False, "SLACK_WEBHOOK_URL no apunta a https://hooks.slack.com/"
    try:
        status, _raw = _post(
            webhook, json.dumps({"text": text}).encode(), {"Content-Type": "application/json"}
        )
    except urllib.error.HTTPError as error:
        return False, f"Slack respondio http {error.code}"
    except (urllib.error.URLError, TimeoutError) as error:
        return False, f"no se pudo contactar con Slack: {error}"
    if 200 <= status < 300:
        return True, f"webhook http {status}"
    return False, f"Slack respondio http {status}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Concise daily summary of the LLM agent's operations."
    )
    parser.add_argument("--journal", default=DEFAULT_JOURNAL)
    parser.add_argument("--memory", default=DEFAULT_MEMORY)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--slack", action="store_true", help="post to Slack (SLACK_BOT_TOKEN + SLACK_CHANNEL, o SLACK_WEBHOOK_URL)")
    parser.add_argument("--out", default="", help="also write the JSON summary here")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    from btc_decision_agent.application.process_guard import load_env_file

    load_env_file(args.env_file)

    summary = build_summary(
        read_entries(Path(args.journal)),
        memory_path=Path(args.memory),
        model=args.model,
        hours=args.hours,
        now=datetime.now(tz=UTC),
    )
    message = render(summary)
    print(message)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.slack:
        sent, detail = send_slack(message)
        print(f"slack: {'enviado' if sent else 'NO ENVIADO'} — {detail}")
        if not sent:
            # Exit non-zero so systemd marks the unit failed. Printing the problem and
            # returning success meant the timer reported "Succeeded" every day while
            # nothing was ever delivered, which is how a broken notification channel
            # stays broken for weeks.
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
