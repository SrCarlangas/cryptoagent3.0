"""Post a finished backtest, its gate verdict and its per-regime attribution to Slack.

Exists so a five-hour run does not depend on somebody watching a terminal. It composes
the three things needed to judge a run and sends them in one message.

Deliberately reports the verdict whatever it is. A notifier that only fires on success
trains everyone to assume silence means failure, and this project has already had one
channel that reported success while delivering nothing.

Usage:
    python -m scripts.notify_backtest [--report path] [--slack] [--wait-for-pid N]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_REPORT = "data/validation/llm-agent-backtest.json"


def wait_for(pid: int, poll_seconds: int = 60) -> None:
    """Block until a process is gone. Used to fire exactly when a run finishes."""
    while True:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(poll_seconds)


def gate_verdict(report: Path) -> tuple[bool, list[str]]:
    """Run the pre-registered gate and capture which criteria failed."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.gate_llm_agent", "--report", str(report)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
        check=False,
    )
    failures = [
        line.strip().removeprefix("[FALLA] ").strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("[FALLA]")
    ]
    return result.returncode == 0, failures


def compose(report: Path, model: str) -> str:
    payload: dict[str, Any] = json.loads(report.read_text(encoding="utf-8"))
    agent = payload["llm_agent"]
    quant = payload["quant_policy"]
    hold = payload["buy_and_hold"]
    window = payload["window"]
    approved, failures = gate_verdict(report)

    lines = [
        f"*Backtest terminado* · {model} · {'APROBADO' if approved else 'RECHAZADO'}",
        f"• Ventana: dias {window['start_day_index']}-{window['end_day_index']} "
        f"({window['days']}d, paso {window['step_days']}d) · "
        f"{payload['wall_clock_seconds'] / 3600:.1f} h de computo",
        f"• Agente {agent['net_return_pct']:+.2f}% (dd {agent['max_drawdown_pct']:.1f}%) · "
        f"cuantitativo {quant['net_return_pct']:+.2f}% · "
        f"comprar y mantener {hold['net_return_pct']:+.2f}%",
    ]

    moves = (
        f"• {agent.get('entries', 0)} aperturas, {agent.get('exits', 0)} cierres, "
        f"{agent.get('scale_ups', 0)} ampliaciones, {agent.get('scale_downs', 0)} reducciones, "
        f"{agent.get('stop_exits', 0)} salidas por stop"
    )
    lines.append(moves)
    lines.append(
        f"• {agent['decisions']} decisiones · INVERTIDO {agent['long_share']:.0%} · "
        f"rotacion {agent['switches'] / max(agent['decisions'], 1):.0%} · "
        f"fallos del modelo {agent['model_failures']}"
    )

    if failures:
        lines.append("• Criterios fallados: " + "; ".join(failures[:4]))
    else:
        lines.append("• Los siete criterios pasan")

    # Per-regime attribution, which is the question the owner actually asked.
    trace = payload.get("trace") or []
    if len(trace) > 2:
        sys.path.insert(0, "research")
        from regime_attribution import attribute

        results = attribute(trace)
        parts = []
        for regime in sorted(results, key=lambda value: (value is None, value)):
            data = results[regime]
            parts.append(
                f"r{regime} {data['total_return_pct']:+.1f}% (ef {data['effect_in_standard_errors']:.1f})"
            )
        lines.append("• Por regimen: " + " · ".join(parts))

    lines.append(
        "• Recordatorio: una ventana, una pasada. Detecta un agente roto, no establece "
        "una ventaja."
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Notify a finished backtest to Slack.")
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--slack", action="store_true")
    parser.add_argument("--wait-for-pid", type=int, default=0)
    parser.add_argument("--model", default="qwen3:30b-a3b")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    if args.wait_for_pid:
        wait_for(args.wait_for_pid)
        # The report is written at the very end of the run; give the filesystem a moment.
        time.sleep(20)

    report = Path(args.report)
    if not report.is_file():
        message = (
            f"*Backtest terminado sin informe* · no existe {report}. "
            "Probablemente murio antes de escribirlo; revisar /tmp/backtest.log."
        )
    else:
        message = compose(report, args.model)

    print(message)
    if args.slack:
        from scripts.daily_summary import send_slack

        from btc_decision_agent.application.process_guard import load_env_file

        load_env_file(args.env_file)
        sent, detail = send_slack(message)
        print(f"slack: {'enviado' if sent else 'NO ENVIADO'} — {detail}")
        return 0 if sent else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
