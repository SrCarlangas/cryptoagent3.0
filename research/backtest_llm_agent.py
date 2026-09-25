"""Replay the LLM agent over historical days and measure what it would have earned.

What this can and cannot establish
----------------------------------
The quantitative policy was validated with 3 walk-forward folds x 16 configurations
x 5 seeds plus an adverse-fee sweep, because each of those runs costs milliseconds.
One LLM decision costs 45 to 100 seconds. A single pass over five years of daily
decisions is roughly 17 hours of compute; the equivalent sweep would be months.

So this measures ONE window, ONE pass, at honest fees. That is a materially weaker
standard of evidence and the report says so in its own output. It is enough to catch
a broken or pathological agent. It is not enough to establish an edge.

Honesty mechanics baked in
--------------------------
- The history index is cut to days strictly before the day being decided, so the
  agent can never read its own future. Same for the base rate it is shown.
- The agent's memory starts empty and fills as the replay advances, so the learning
  loop is exercised in the same order it will be live.
- Decisions are taken on day D's close and FILLED at day D+1's close, so it never
  trades at a price it used to decide.
- Fees are charged on every switch. Equity is marked to market every day, not only
  on decision days.
- Buy and hold and the quantitative policy are run over the identical window for
  context.

Writes data/validation/llm-agent-backtest.{json,md}.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import replace as dc_replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from multislot_sim import load_bars

from btc_decision_agent.application.exposure_agent import (
    ExposureAction,
    PortfolioState,
    RegimeMixturePolicy,
    compose_features,
)
from btc_decision_agent.application.exposure_features import (
    MIN_DAILY_HISTORY,
    market_features,
)
from btc_decision_agent.application.exposure_training import build_daily_perception
from btc_decision_agent.application.llm_agent import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    LLMTradingAgent,
    LLMUnavailable,
    OllamaClient,
)
from btc_decision_agent.application.llm_memory import AgentMemory, render_memory_block
from btc_decision_agent.application.llm_tools import (
    EXPOSURE_CASH,
    EXPOSURE_INVESTED,
    HistoryIndex,
    cost_view,
    market_view,
    position_view,
    quant_view,
    render_state_block,
)
from btc_decision_agent.application.realtime_demo import (
    ProtectiveDecisionEngine,
    RealtimeParams,
    size_entry_percentage,
)
from btc_decision_agent.application.regime_playbook import (
    meets_burden_of_proof,
    resolve_plan,
)

D = Decimal
REPORT = Path("data/validation/llm-agent-backtest")


def simulate_quant(
    policy: RegimeMixturePolicy,
    closes: list[float],
    start_day: int,
    end_day: int,
    fee: float,
) -> dict[str, Any]:
    """The validated numeric policy over the identical window, for context."""
    cash, units, switches = 1.0, 0.0, 0
    peak, drawdown = 1.0, 0.0
    for day in range(start_day, end_day):
        price = closes[day]
        features = market_features(closes[:day], price)
        state = PortfolioState(position_long=units > 0.0, round_trip_cost_bps=fee * 2 * 10_000)
        outcome = policy.decide(compose_features(features, state), state)
        want_long = outcome.action == ExposureAction.TARGET_LONG
        fill = closes[min(day + 1, end_day - 1)]
        if want_long and units == 0.0:
            units, cash, switches = (cash * (1 - fee)) / fill, 0.0, switches + 1
        elif not want_long and units > 0.0:
            cash, units, switches = units * fill * (1 - fee), 0.0, switches + 1
        equity = cash + units * price
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    final = cash + (units * closes[end_day - 1] * (1 - fee) if units else 0.0)
    return {
        "net_return_pct": (final - 1.0) * 100.0,
        "max_drawdown_pct": drawdown * 100.0,
        "switches": switches,
    }


def simulate_buy_and_hold(closes: list[float], start_day: int, end_day: int, fee: float) -> dict[str, Any]:
    units = (1.0 * (1 - fee)) / closes[start_day]
    peak, drawdown = 1.0, 0.0
    for day in range(start_day, end_day):
        equity = units * closes[day]
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    final = units * closes[end_day - 1] * (1 - fee)
    return {
        "net_return_pct": (final - 1.0) * 100.0,
        "max_drawdown_pct": drawdown * 100.0,
        "switches": 2,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay the LLM agent over history.")
    parser.add_argument("--decisions", type=int, default=100, help="how many decisions to replay")
    parser.add_argument("--step-days", type=int, default=2, help="days between decisions")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--policy", default="data/models/local-exposure-agent-v1.json")
    parser.add_argument("--index", default="data/models/history-index.json")
    parser.add_argument("--fee-per-side", type=float, default=0.001)
    parser.add_argument("--think", action="store_true", help="enable reasoning (much slower)")
    parser.add_argument(
        "--end-day",
        type=int,
        default=0,
        help="last day index of the window; 0 means the most recent day. Exists so a "
        "change aimed at rising markets can be replayed on a window that actually "
        "contains one, instead of being judged on a window that barely tests it",
    )
    args = parser.parse_args()

    bars, dataset_id = load_bars()
    perception = build_daily_perception(bars)
    closes = perception.closes
    index = HistoryIndex(args.index)
    policy = RegimeMixturePolicy.load(args.policy)

    span = args.decisions * args.step_days
    end_day = args.end_day if args.end_day > 0 else len(closes) - 1
    if end_day > len(closes) - 1:
        raise SystemExit(f"--end-day beyond the dataset ({len(closes) - 1} days available)")
    start_day = end_day - span
    if start_day < MIN_DAILY_HISTORY + 1:
        raise SystemExit("not enough history for that many decisions")

    memory_path = Path(tempfile.mkdtemp()) / "backtest-memory.sqlite3"
    memory = AgentMemory(memory_path, horizon_hours=24 * args.step_days)
    # The client is driven directly rather than through LLMTradingAgent because the
    # backtest must control the day cutoff when building state, which live code has
    # no reason to do.
    client = OllamaClient(args.endpoint, args.model)
    params = RealtimeParams(
        allocation_fraction=D("0.95"),
        round_trip_cost_bps=D(str(args.fee_per_side * 2 * 10_000)),
    )

    fee = args.fee_per_side
    # A real starting capital rather than 1.0, because sizing goes through the
    # production formula and that formula has a minimum notional. Normalised capital
    # would round every order to zero.
    START_CAPITAL = 10_000.0
    cash, units, switches = START_CAPITAL, 0.0, 0
    entry_price: float | None = None
    high_since_entry: float | None = None
    active_plan: dict[str, Any] | None = None
    holding_days = 0
    peak, drawdown = START_CAPITAL, 0.0
    failures = 0
    stop_exits = 0
    burden_blocks = 0
    # The engine itself computes the stop, rather than the backtest reimplementing it.
    # Two copies of stop geometry would drift, and the drift would be invisible because
    # each side looks reasonable alone.
    stop_engine = ProtectiveDecisionEngine(params)

    def current_stop(price: float) -> float | None:
        if entry_price is None:
            return None
        stop_engine.import_state(
            dc_replace(
                stop_engine.state,
                entry_price=D(str(entry_price)),
                high_since_entry=D(str(high_since_entry or entry_price)),
                execution_plan=active_plan,
            )
        )
        raw = stop_engine.active_stop(D(str(price)))
        return float(raw) if raw is not None else None
    trace: list[dict[str, Any]] = []
    started = time.time()
    # A synthetic clock so memory horizons behave as they will live.
    clock = datetime(2020, 1, 1, tzinfo=UTC)

    decision_days = list(range(start_day, end_day, args.step_days))
    print(
        f"replaying {len(decision_days)} decisions, step {args.step_days}d, "
        f"model {args.model}, think={args.think}",
        flush=True,
    )

    for number, day in enumerate(decision_days, start=1):
        price = closes[day]
        vector = market_features(closes[:day], price)
        position_long = units > 0.0
        now = clock + timedelta(days=day - start_day)

        market = market_view([D(str(value)) for value in closes[:day]], D(str(price)))
        portfolio = PortfolioState(
            position_long=position_long,
            round_trip_cost_bps=float(params.round_trip_cost_bps),
            holding_hours=holding_days * 24,
        )
        quant = quant_view(policy, vector, portfolio)
        position = position_view(
            position_long=position_long,
            btc_qty=D(str(units)),
            usdt_free=D(str(cash)),
            price=D(str(price)),
            entry_price=D(str(entry_price)) if entry_price is not None else None,
            holding_hours=holding_days * 24,
            active_stop=None,
        )
        # The cutoff is what keeps this honest.
        analogues = index.analogues(vector, 8, before_day=day)
        block = render_state_block(
            market,
            position,
            cost_view(params.round_trip_cost_bps, params.allocation_fraction),
            quant,
            analogues,
            index.summarise(analogues),
            index.base_rates(before_day=day),
            render_memory_block(memory, vector),
        )

        try:
            verdict = client.verdict(block, think=args.think, num_predict=2500 if args.think else 900)
        except LLMUnavailable as error:
            failures += 1
            print(f"  [{number}/{len(decision_days)}] fallo del modelo: {error}", flush=True)
            continue

        wants_long = verdict.wants_long
        changing = wants_long != position_long
        # Same economics as live, including the asymmetry: the cost threshold gates
        # ENTRIES only, and the declared expected move is bounded by what the market's
        # own volatility could deliver. Replaying with different rules than production
        # would measure a system that does not exist.
        clears = LLMTradingAgent.clears_cost_static(
            wants_long=wants_long,
            position_long=position_long,
            expected_move_pct=verdict.expected_move_pct,
            round_trip_cost_bps=float(params.round_trip_cost_bps),
            daily_vol_pct=market.get("volatilidad_diaria_30d_pct"),
        )
        # The regime's strategy, resolved exactly as production resolves it.
        plan = resolve_plan(
            regime=int(quant.get("regimen", 0)),
            posture=verdict.posture,
            conviction=verdict.conviction,
            daily_vol_pct=market.get("volatilidad_diaria_30d_pct"),
        )
        burden_met = meets_burden_of_proof(
            regime=int(quant.get("regimen", 0)),
            wants_invested=wants_long,
            conviction=verdict.conviction,
        )
        if changing and clears and not burden_met:
            burden_blocks += 1
        acted = changing and clears and burden_met
        fill = closes[min(day + 1, end_day)]

        if acted and wants_long:
            sizing = plan.apply(params)
            equity_now = cash + units * price
            quote = float(
                size_entry_percentage(
                    D(str(cash)),
                    sizing.allocation_fraction,
                    min_notional=params.min_notional_usdt,
                    equity=D(str(equity_now)),
                    risk_per_trade_fraction=sizing.risk_per_trade_fraction,
                    stop_loss_fraction=sizing.stop_loss_fraction,
                )
            )
            if quote > 0.0:
                units += (quote * (1 - fee)) / fill
                cash -= quote
                entry_price = fill
                high_since_entry = fill
                active_plan = plan.to_dict()
                holding_days, switches = 0, switches + 1
            else:
                acted = False
        elif acted and not wants_long:
            cash += units * fill * (1 - fee)
            units = 0.0
            entry_price, high_since_entry, active_plan = None, None, None
            holding_days, switches = 0, switches + 1
        elif units > 0.0:
            holding_days += args.step_days

        memory.record(
            decided_at=now,
            event_id=f"bt-{day}",
            features=vector,
            regime=int(quant.get("regimen", 0)),
            quant_p_long=float(quant.get("p_largo", 0.0)),
            target_exposure=verdict.target_exposure,
            exposure_before=EXPOSURE_INVESTED if position_long else EXPOSURE_CASH,
            derived_order="BUY" if acted and wants_long else ("SELL" if acted else "HOLD"),
            conviction=verdict.conviction,
            expected_move_pct=verdict.expected_move_pct,
            reason=verdict.reason,
            thinking=verdict.thinking,
            price=D(str(price)),
            acted=acted,
            posture=verdict.posture,
        )
        memory.resolve_pending(now, D(str(price)))

        # Walk every day until the next decision, marking to market and letting the
        # protective stop fire. Only closes are available, so an intraday wick that
        # would have triggered the stop is invisible here: this UNDERSTATES stop-outs,
        # which flatters wide stops and is stated in the report.
        for mark in range(day, min(day + args.step_days, end_day)):
            close = closes[mark]
            if units > 0.0:
                high_since_entry = max(high_since_entry or close, close)
                stop = current_stop(close)
                if stop is not None and close <= stop:
                    # Filled at the stop, or at the close when the day gapped through
                    # it, whichever is worse for the position.
                    exit_price = min(stop, close)
                    cash += units * exit_price * (1 - fee)
                    units = 0.0
                    entry_price, high_since_entry, active_plan = None, None, None
                    holding_days = 0
                    stop_exits += 1
                    switches += 1
            equity = cash + units * close
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak - equity) / peak)

        trace.append(
            {
                "decision": number,
                "day_index": day,
                "price": round(price, 2),
                "target": verdict.target_exposure,
                "posture": verdict.posture,
                "strategy": plan.strategy_name,
                "plan_allocation_pct": float(plan.allocation_fraction * 100),
                "plan_stop_pct": float(plan.stop_loss_fraction * 100),
                "plan_risk_pct": float(plan.risk_per_trade_fraction * 100),
                "plan_horizon_hours": plan.horizon_hours,
                "burden_met": burden_met,
                "invested_share": round(
                    (units * price) / (cash + units * price) if (cash + units * price) else 0.0, 4
                ),
                "conviction": verdict.conviction,
                "expected_move_pct": verdict.expected_move_pct,
                "acted": acted,
                "changing": changing,
                "clears_cost": clears,
                "regime": quant.get("regimen"),
                "quant_recommends": quant.get("recomienda"),
                "seconds": round(verdict.seconds, 1),
                "equity": round((cash + units * price) / START_CAPITAL, 6),
            }
        )
        if number % 10 == 0 or number == 1:
            elapsed = time.time() - started
            print(
                f"  [{number}/{len(decision_days)}] dia {day} precio {price:.0f} -> "
                f"{verdict.target_exposure} conv {verdict.conviction:.2f} "
                f"{verdict.posture[:3]} conv {verdict.conviction:.2f} actuo={acted} "
                f"invertido {(units * price) / (cash + units * price) * 100 if (cash + units * price) else 0:.0f}% "
                f"equity {(cash + units * price) / START_CAPITAL:.4f} "
                f"({elapsed / number:.0f}s/decision)",
                flush=True,
            )

    final = cash + (units * closes[end_day - 1] * (1 - fee) if units else 0.0)
    agent_result = {
        "net_return_pct": (final / START_CAPITAL - 1.0) * 100.0,
        "max_drawdown_pct": drawdown * 100.0,
        "stop_exits": stop_exits,
        "burden_blocks": burden_blocks,
        "switches": switches,
        "decisions": len(trace),
        "model_failures": failures,
        "long_share": (
            sum(1 for item in trace if item["target"] == EXPOSURE_INVESTED) / len(trace)
            if trace
            else 0.0
        ),
        "acted_share": (
            sum(1 for item in trace if item["acted"]) / len(trace) if trace else 0.0
        ),
        # Only decisions that actually wanted to MOVE and were refused. The previous
        # version counted every decision whose target was cash and whose expected move
        # did not clear the fee, which includes the large majority that were already in
        # cash and needed no action at all. It reported 79 blocked exits when the real
        # number was zero, which would have read as the fix having failed.
        "blocked_changes_by_cost": sum(
            1 for item in trace if item.get("changing") and not item["clears_cost"]
        ),
        "blocked_exits_by_cost": sum(
            1
            for item in trace
            if item.get("changing")
            and not item["clears_cost"]
            and item["target"] != EXPOSURE_INVESTED
        ),
        "agreement_with_quant": (
            sum(1 for item in trace if item["target"] == item["quant_recommends"]) / len(trace)
            if trace
            else 0.0
        ),
    }
    quant_result = simulate_quant(policy, closes, start_day, end_day, fee)
    hold_result = simulate_buy_and_hold(closes, start_day, end_day, fee)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_id": dataset_id,
        "model": args.model,
        "think_enabled": args.think,
        "fee_per_side": fee,
        "window": {
            "start_day_index": start_day,
            "end_day_index": end_day,
            "days": end_day - start_day,
            "step_days": args.step_days,
        },
        "llm_agent": agent_result,
        "quant_policy": quant_result,
        "buy_and_hold": hold_result,
        "wall_clock_seconds": round(time.time() - started, 1),
        "evidence_caveat": (
            "Una sola ventana, una sola pasada, comisiones honestas. El modelo "
            "cuantitativo se valido con 3 cortes x 16 configuraciones x 5 semillas mas "
            "comisiones adversas porque cada corrida cuesta milisegundos; una decision "
            "del LLM cuesta 45-100 s. Esto sirve para detectar un agente roto o "
            "patologico. NO alcanza para establecer una ventaja."
        ),
        "trace": trace,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.with_suffix(".json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT.with_suffix(".md").write_text(render(payload) + "\n", encoding="utf-8")
    print()
    print(render(payload))


def render(payload: dict[str, Any]) -> str:
    agent = payload["llm_agent"]
    quant = payload["quant_policy"]
    hold = payload["buy_and_hold"]
    window = payload["window"]
    lines = [
        "# Backtest del agente LLM",
        "",
        f"- modelo: `{payload['model']}` (razonamiento {'activado' if payload['think_enabled'] else 'desactivado'})",
        f"- dataset: `{payload['dataset_id']}`",
        f"- ventana: {window['days']} dias, decision cada {window['step_days']} dias",
        f"- comision: {payload['fee_per_side'] * 10_000:.0f} bps por lado",
        f"- tiempo de computo: {payload['wall_clock_seconds'] / 60:.0f} minutos",
        "",
        "| | retorno neto | drawdown max | cambios |",
        "|---|---|---|---|",
        f"| **agente LLM** | {agent['net_return_pct']:+.2f}% | {agent['max_drawdown_pct']:.2f}% | {agent['switches']} |",
        f"| modelo cuantitativo | {quant['net_return_pct']:+.2f}% | {quant['max_drawdown_pct']:.2f}% | {quant['switches']} |",
        f"| buy and hold | {hold['net_return_pct']:+.2f}% | {hold['max_drawdown_pct']:.2f}% | {hold['switches']} |",
        "",
        "## Comportamiento del agente",
        "",
        f"- decisiones tomadas: {agent['decisions']} (fallos del modelo: {agent['model_failures']})",
        f"- eligio {EXPOSURE_INVESTED} en el {agent['long_share']:.0%} de las decisiones",
        f"- actuo en el {agent['acted_share']:.0%} (el resto no requeria cambio o no cubria costo)",
        f"- cambios de exposicion que el costo bloqueo: {agent['blocked_changes_by_cost']}"
        f" (de ellos salidas: {agent['blocked_exits_by_cost']}, debe ser 0)",
        f"- cambios que la carga de la prueba del regimen bloqueo: {agent['burden_blocks']}",
        f"- salidas por stop protector: {agent['stop_exits']}",
        "",
        "## Estrategia por regimen",
        "",
        "| regimen | decisiones | invertido | postura dominante | asignacion media | stop medio |",
        "|---|---|---|---|---|---|",
    ]
    by_regime: dict[Any, list[dict[str, Any]]] = {}
    for item in payload["trace"]:
        by_regime.setdefault(item.get("regime"), []).append(item)
    for regime in sorted(by_regime, key=lambda value: (value is None, value)):
        rows = by_regime[regime]
        invested = sum(1 for row in rows if row["target"] == EXPOSURE_INVESTED)
        postures: dict[str, int] = {}
        for row in rows:
            postures[row.get("posture", "?")] = postures.get(row.get("posture", "?"), 0) + 1
        dominant = max(postures, key=lambda key: postures[key]) if postures else "?"
        allocation = sum(row.get("plan_allocation_pct", 0.0) for row in rows) / len(rows)
        stop = sum(row.get("plan_stop_pct", 0.0) for row in rows) / len(rows)
        lines.append(
            f"| {regime} | {len(rows)} | {invested} ({invested / len(rows):.0%}) | "
            f"{dominant} | {allocation:.0f}% | {stop:.1f}% |"
        )
    lines += [
        "",
        "## Advertencia sobre la simulacion",
        "",
        "Los stops se evaluan contra CIERRES diarios porque es lo unico que hay en el "
        "dataset. Una mecha intradia que habria tocado el stop es invisible aqui, asi "
        "que esto SUBESTIMA las salidas por stop y por tanto favorece a los stops "
        "anchos. Leer la ventaja de la estrategia alcista con esa reserva.",
        f"- coincidio con el modelo cuantitativo en el {agent['agreement_with_quant']:.0%}",
        "",
        "",
        "## Advertencia sobre la evidencia",
        "",
        payload["evidence_caveat"],
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
