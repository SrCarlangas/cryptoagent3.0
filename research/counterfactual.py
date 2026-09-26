"""Replay recorded agent decisions against different EXECUTION rules, in seconds.

The problem this solves
----------------------
Each backtest costs two to five hours because every decision is an LLM call. That made
every question about execution expensive, so execution went untested while three
iterations were spent on the agent's judgement.

But the agent's decisions are recorded. Replaying them against the real hourly price path
with different stop, sizing and re-entry rules needs no model at all, so a question that
cost five hours now costs a second. That is the difference between guessing and measuring.

What it has already refuted
---------------------------
The first hypothesis was that the protective stop was the largest destroyer of return.
Removing it made the bear window WORSE (-10.05% against -2.96%), and widening it while
holding position size constant barely moved anything. What moved the result was SIZE.
That inverted the premise of the three preceding iterations.

Two cautions were learned from that run and are enforced here:

1. The trace it ran on predated the playbook, so it carried no plan fields, and the
   reader silently substituted 95% allocation / 3% stop / 2% risk for every decision.
   The numbers were real but they described a uniform policy, not the playbook. Missing
   plan fields are now a hard error, because a default that silently replaces measured
   data produces a confident number about a system that does not exist.

2. Widening a stop DIVIDES the position, because sizing is `equity * risk / stop`. A
   variant labelled "wider stop" was really "wider stop and a third of the position".
   Isolating the stop requires raising the risk budget by the same factor.

The asymmetry this was built to measure
---------------------------------------
Exits are continuous and entries are discrete. The protective stop is evaluated against
every hourly bar, but nothing can re-enter until the next LLM decision, which in a
backtest is three to five days later. So a stop fired in hour one costs the agent the
rest of the interval in cash. Live the same stop costs it thirty minutes, because the
runner polls and decides again.

Buy-and-hold carries no stop, and the numeric policy's simulation carries no stop either.
The agent is the only participant paying that dead time, which makes the comparison
unfair by an amount nobody had measured. `hours_invested_pct` measures it directly, and
the re-entry variants price it.

Usage:
    python -m research.counterfactual [report.json] [--reconstruct-plans]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from dataclasses import replace as dc_replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from multislot_sim import load_bars

from btc_decision_agent.application.exposure_features import (
    MARKET_FEATURE_NAMES,
    market_features,
)
from btc_decision_agent.application.exposure_training import build_daily_perception
from btc_decision_agent.application.llm_tools import EXPOSURE_INVESTED
from btc_decision_agent.application.realtime_demo import (
    ProtectiveDecisionEngine,
    RealtimeParams,
)
from btc_decision_agent.application.regime_playbook import (
    PLAYBOOK_VERSION,
    ExecutionPlan,
    Posture,
    plan_adjustment,
    resolve_plan,
    strategy_for,
)

D = Decimal
START_CAPITAL = 10_000.0
FEE = 0.001

# Every field the playbook records per decision. Absent even one of them means the trace
# was produced before the playbook existed, and replaying it would measure a policy that
# was never run.
REQUIRED_PLAN_FIELDS = (
    "plan_allocation_pct",
    "plan_stop_pct",
    "plan_risk_pct",
    "plan_horizon_hours",
    "posture",
)

# Who decides the exposure, holding execution fixed. This separates the agent's judgement
# from the playbook's structure, which no run so far has done.
FROM_AGENT = "agente"
FROM_PLAYBOOK = "playbook"
VETO_ONLY = "solo veto"
ADD_ONLY = "solo sumar"
ALWAYS_IN = "siempre invertido"
RERESOLVED = "reresuelto"
RAW_AGENT = "agente sin tutela"
"""What the agent asked for, with the playbook unable to override it.

FROM_AGENT is not this: it replays the RESOLVED target, which already carries the
playbook's overrides. This uses `agent_asked_for` directly, so it answers what full
authority would have produced. The playbook still sets the size and the stop geometry
through resolve_plan; what it loses is the power to reverse the direction.
"""

TIE_BREAK_ONLY = "solo desempate"
"""The agent owns the direction; the default only breaks a declared tie."""

OLD_BURDEN = "override retirado"
"""The retired burden of proof, reimplemented here so it can still be measured.

It was deleted from production because it cost 39 points on one replay. The real run that
followed came in WORSE, so the replay's prediction did not hold and the rule has to be
re-measured against the decisions the new configuration actually produced. Keeping a
research-only copy is how a retired rule stays falsifiable instead of becoming folklore.
"""

_RETIRED_THRESHOLDS: dict[int, float] = {0: 0.60, 1: 0.80, 2: 0.55, 3: 0.70}
"""The per-regime minimums as they stood when the override was removed."""


def _apply_retired_burden(regime: int, asked_invested: bool, conviction: float) -> bool:
    """The retired rule, reimplemented here rather than imported.

    Production no longer has it, and that is the point: a rule that has been withdrawn
    should not keep living in the code that trades. But it still has to be MEASURABLE,
    because the replay that justified withdrawing it was contradicted by the run that
    followed. A local copy keeps it falsifiable instead of turning it into folklore.
    """
    default_invested = strategy_for(regime).default_exposure == EXPOSURE_INVESTED
    if asked_invested == default_invested:
        return asked_invested
    if conviction >= _RETIRED_THRESHOLDS.get(regime, 0.80):
        return asked_invested
    return default_invested

STABILISED = "regimen estabilizado"
"""Re-run the burden of proof against a regime label that has to persist first.

Measured on the best run so far: the label changes on 37% of 5-day transitions and 31% of
transitions invert the default exposure, because regime 0 defaults to cash and regime 3
defaults to invested and the sequence alternates between them. Of 15 direction changes, 9
were imposed by the playbook AGAINST what the agent asked for: it wanted invested in regime
0 on 12 of 17 decisions and was forced to cash on 8 of them.

So the burden of proof is anchored to a label that moves faster than the strategies it
selects intend to hold. Regime 3 declares a 168 hour horizon and the label flips every
120 hour step. Abandoning a strategy faster than its own declared horizon is incoherent,
which is the argument for requiring persistence, and the requirement is derived from the
horizon of the strategy being LEFT rather than picked: leaving the deep bear needs one step,
leaving a trend needs the trend's horizon.
"""


@dataclass(frozen=True)
class Rules:
    """One execution policy to try."""

    name: str
    use_stop: bool = True
    stop_multiplier: float = 1.0
    """Widen or tighten every stop by this factor. 3.0 turns a 10% stop into 30%."""

    allocation_override: float | None = None
    """Force a fixed share of equity instead of the plan's allocation."""

    risk_multiplier: float = 1.0
    """Scale the risk budget. Needed to isolate the stop's effect from sizing, because
    sizing is `equity * risk / stop` and widening the stop alone shrinks the position."""

    trail_multiplier: float = 1.0
    """Widen or tighten the trailing leash behind the high, independently of the stop."""

    trail_activation_multiplier: float = 1.0
    """Move the profit level at which the trailing stop engages."""

    size_multiplier: float = 1.0
    """Scale the achieved position by this factor whichever term binds.

    The target is `min(allocation, risk / stop)`, so scaling allocation AND risk by k
    scales the result by k regardless of which of the two is the binding constraint.
    That makes this the clean knob for the one question the earlier run left open: does
    MORE size win, or less?
    """

    dead_band: float = 0.15
    scale: bool = True
    """False reproduces the old all-or-nothing behaviour."""

    reentry_cooldown_hours: int | None = None
    """Hours to wait after a protective stop before the standing stance may be re-entered.

    None reproduces today's backtest: once stopped, stay in cash until the next LLM
    decision, up to five days later. 0 means re-enter on the next hourly bar, which is
    close to what production does at a 30 minute cadence and is deliberately extreme:
    if it wins big, the measured underperformance was substantially an artefact of the
    decision cadence rather than of the agent's judgement. If it LOSES, then the stop is
    doing real work and production has a whipsaw problem nobody has seen yet, because
    live the agent re-enters within half an hour of being stopped out with its view
    unchanged, paying both fees and keeping its original stance.
    """

    exposure_from: str = FROM_AGENT
    """Whose exposure call to obey. See FROM_AGENT and friends."""

    break_even_activation: float | None = None
    """Profit, as a fraction of entry, before the stop ratchets up to break even.

    None leaves the engine default of 0.005, which is the point of testing this.

    `ExecutionPlan.apply` substitutes the allocation, the stop, the trailing stop, the
    trailing activation and the risk budget. It does NOT substitute the two break-even
    fields, so every regime and every posture inherits the engine defaults: the floor
    moves to entry + 0.25% as soon as the trade is 0.5% in profit.

    BTC covers 0.5% in an hour routinely, so this converts every position that ever goes
    green into a trade that exits on the first quarter-percent pullback, for +0.25% gross
    and +0.05% after the 0.2% round trip. The regime 3 doctrine shown to the agent
    promises a wide stop so noise cannot shake it out of a trend over 168 hours. The
    engine had it on a 0.25% leash. That is why widening the initial stop and the
    trailing stop changed almost nothing: neither was the binding constraint.
    """

    break_even_lock: float | None = None
    """Where the floor sits above entry once the break-even ratchet engages."""

    mark_from_fill: bool = False
    """Start checking the stop AFTER the entry exists instead of two days before it.

    A decision taken on day d uses data up to d and fills at the close of d+1, which is
    a deliberate one day execution lag. But the stop loop walks the hourly bars from day
    d, so the first ~48 hours it examines happened BEFORE the position was opened. Any
    dip in those two days kills a position that did not exist yet, at a stop derived from
    an entry price that had not been paid yet.

    In a market with 2.5% daily volatility, two days of bars almost always contain a move
    larger than the 1.6 to 3.5 daily sigma stop the playbook sets, so nearly every entry
    is liquidated on arrival. That is consistent with what the bear window shows: twelve
    stops against twelve entries, and a position open in 4.2% of hours while the agent
    asked to be invested in roughly a quarter of its decisions.

    True marks from d+2 to d+step+1, which is the span the position is actually held.
    """


def _plan_dict(item: dict[str, Any], rules: Rules, allocation: Decimal) -> dict[str, Any]:
    """The recorded plan, with this variant's multipliers applied and bounds enforced.

    Prefers the full plan the run recorded under "plan". Older traces carry only the four
    scalar percentages, which say nothing about the trailing geometry, so those have to be
    inferred from the stop. That inference was wrong in the first version of this tool: it
    hardcoded a 1% trailing activation where the playbook derives 2 to 3% from volatility,
    which made the trailing stop look tighter than it is. Same failure mode as the stop
    defaults, so the full plan is now what the backtest records.
    """

    def bounded(value: Decimal) -> str:
        return format(min(D("0.95"), max(D("0.0001"), value)), "f")

    recorded = item.get("plan")
    if isinstance(recorded, dict):
        stop = D(str(recorded["stop_loss_fraction"]))
        trail = D(str(recorded["trailing_stop_fraction"]))
        activation = D(str(recorded["trailing_activation_fraction"]))
        risk = D(str(recorded["risk_per_trade_fraction"]))
        # Absent means the run predates the playbook owning these, so what ACTUALLY
        # governed its exits was the engine default, not the regime's geometry.
        be_activation = D(str(recorded.get("break_even_activation_fraction", "0.005")))
        be_lock = D(str(recorded.get("break_even_lock_fraction", "0.0025")))
    else:
        stop = D(str(item["plan_stop_pct"])) / 100
        # 0.8 is the trail-to-stop ratio the playbook uses in three of its four regimes
        # and 0.75 in the fourth, so it is close but it is an inference, not the plan.
        trail = stop * D("0.8")
        activation = D("0.02")
        risk = D(str(item["plan_risk_pct"])) / 100
        be_activation, be_lock = D("0.005"), D("0.0025")
    if rules.break_even_activation is not None:
        be_activation = D(str(rules.break_even_activation))
    if rules.break_even_lock is not None:
        be_lock = D(str(rules.break_even_lock))
    return {
        "version": "counterfactual/3",
        "regime": item.get("regime") or 0,
        "posture": item["posture"],
        "strategy_name": item.get("strategy", ""),
        "allocation_fraction": bounded(allocation * D(str(rules.size_multiplier))),
        "stop_loss_fraction": bounded(stop * D(str(rules.stop_multiplier))),
        "trailing_stop_fraction": bounded(trail * D(str(rules.trail_multiplier))),
        "trailing_activation_fraction": bounded(
            activation * D(str(rules.trail_activation_multiplier))
        ),
        "break_even_activation_fraction": bounded(be_activation),
        "break_even_lock_fraction": bounded(be_lock),
        "risk_per_trade_fraction": bounded(
            risk * D(str(rules.risk_multiplier)) * D(str(rules.size_multiplier))
        ),
        "horizon_hours": int(item["plan_horizon_hours"]),
        "daily_vol_pct": None,
    }


def stabilise_regimes(trace: list[dict[str, Any]], step_days: int) -> list[int | None]:
    """The regime each decision would see if a label had to persist to take effect.

    A new label is provisional until it has held for at least the HORIZON OF THE STRATEGY
    IT WOULD REPLACE. Leaving the deep bear, whose horizon is 24 hours, takes one step.
    Leaving an established trend, whose horizon is 168 hours, takes as many steps as that
    horizon covers. Nothing here is fitted: the horizons are the ones the playbook already
    declares, and the rule is that a strategy is not abandoned faster than it said it meant
    to hold.
    """
    effective: list[int | None] = []
    current = trace[0].get("regime")
    pending: int | None = None
    pending_steps = 0
    for item in trace:
        observed = item.get("regime")
        if observed == current:
            pending, pending_steps = None, 0
        else:
            if observed == pending:
                pending_steps += 1
            else:
                pending, pending_steps = observed, 1
            needed = max(
                1, -(-strategy_for(current).horizon_hours // (step_days * 24))
            )  # ceil division
            if pending_steps >= needed:
                current, pending, pending_steps = observed, None, 0
        effective.append(current)
    return effective


def _wants_invested(item: dict[str, Any], rules: Rules) -> bool:
    """Resolve the exposure for this decision under the variant's authority rule."""
    agent_in = bool(item["target"] == EXPOSURE_INVESTED)
    playbook_in = strategy_for(item.get("regime")).default_exposure == EXPOSURE_INVESTED
    if rules.exposure_from == FROM_PLAYBOOK:
        return playbook_in
    if rules.exposure_from == VETO_ONLY:
        return agent_in and playbook_in
    if rules.exposure_from == ADD_ONLY:
        return agent_in or playbook_in
    if rules.exposure_from == ALWAYS_IN:
        return True
    if rules.exposure_from in {OLD_BURDEN, TIE_BREAK_ONLY, RERESOLVED, STABILISED, RAW_AGENT}:
        # Re-run the burden of proof from what the agent ACTUALLY asked for, which the
        # trace records separately from the resolved target. RERESOLVED uses the observed
        # regime and must reproduce the recorded target, which is the control that proves
        # the re-resolution is faithful before the stabilised version is believed.
        #
        # A trace recorded before the burden of proof existed has no such field, and the
        # first version of this read it with .get() and silently treated absence as "asked
        # for cash". That made the control diverge from the run by 18 points on the bear
        # window, which is the same silent-default failure the plan-field guard above was
        # written for. Guarding it here rather than trusting the reader to notice.
        if item.get("agent_asked_for") is None:
            raise SystemExit(
                f"la decision {item.get('decision')} no trae 'agent_asked_for'.\n"
                "Esa traza es anterior a la carga de la prueba, asi que no se puede "
                "reresolver la exposicion sin inventar lo que el agente pidio."
            )
        asked = bool(item.get("agent_asked_for") == EXPOSURE_INVESTED)
        if rules.exposure_from == RAW_AGENT:
            return asked
        conviction = float(item.get("conviction") or 0.5)
        if rules.exposure_from == TIE_BREAK_ONLY:
            # The default only breaks a declared tie: a model stating less conviction than a
            # coin flip has not really stated an exposure.
            if conviction >= 0.5:
                return asked
            return strategy_for(item["_effective_regime"]).default_exposure == EXPOSURE_INVESTED
        regime = int(
            item["_effective_regime"]
            if rules.exposure_from in {STABILISED, OLD_BURDEN}
            else (item.get("regime") or 1)
        )
        return _apply_retired_burden(regime, asked, conviction)
    return agent_in


def simulate(
    trace: list[dict[str, Any]], closes: list[float], hourly: list[list[Any]], rules: Rules
) -> dict[str, Any]:
    params = RealtimeParams(allocation_fraction=D("0.95"), round_trip_cost_bps=D("20"))
    engine = ProtectiveDecisionEngine(params)
    cash, units = START_CAPITAL, 0.0
    entry_price: float | None = None
    high: float | None = None
    active_plan: dict[str, Any] | None = None
    peak, drawdown = START_CAPITAL, 0.0
    switches = stop_exits = scale_ups = reentries = phantom_stops = 0
    hours_total = hours_invested = 0

    def stop_now(price: float) -> float | None:
        if entry_price is None or not rules.use_stop or active_plan is None:
            return None
        engine.import_state(
            dc_replace(
                engine.state,
                entry_price=D(str(entry_price)),
                high_since_entry=D(str(high or entry_price)),
                execution_plan=active_plan,
            )
        )
        raw = engine.active_stop(D(str(price)))
        return float(raw) if raw is not None else None

    def buy(price: float, sizing: RealtimeParams, target: Decimal, plan: dict[str, Any]) -> bool:
        """Move toward `target` at `price`. Returns True if an order was placed."""
        nonlocal cash, units, entry_price, high, active_plan, scale_ups
        adjustment = plan_adjustment(
            target_allocation=target,
            btc_qty=D(str(units)),
            price=D(str(price)),
            usdt_free=D(str(cash)),
            risk_per_trade_fraction=sizing.risk_per_trade_fraction,
            stop_loss_fraction=sizing.stop_loss_fraction,
            min_notional=params.min_notional_usdt,
            base_step=params.base_step_size,
            dead_band=D(str(rules.dead_band)),
        )
        if adjustment.action != "COMPRAR":
            return False
        bought = float(adjustment.quote_usdt) * (1 - FEE) / price
        if units > 0.0 and entry_price is not None:
            entry_price = (entry_price * units + price * bought) / (units + bought)
            high = max(high or price, price)
            scale_ups += 1
        else:
            entry_price, high = price, price
        units += bought
        cash -= float(adjustment.quote_usdt)
        active_plan = plan
        return True

    for index, item in enumerate(trace):
        for field in REQUIRED_PLAN_FIELDS:
            if item.get(field) is None:
                raise SystemExit(
                    f"la decision {item.get('decision')} no trae '{field}'.\n"
                    "Esa traza es anterior al playbook. Rellenar los huecos con valores "
                    "por defecto daria numeros reales sobre una politica que nunca corrio, "
                    "asi que se rechaza en vez de inventarla."
                )
        day = int(item["day_index"])
        step = int(trace[index + 1]["day_index"]) - day if index + 1 < len(trace) else 1
        fill = closes[min(day + 1, len(closes) - 1)]
        wants_long = _wants_invested(item, rules)

        allocation = D(str(item["plan_allocation_pct"])) / 100
        if rules.allocation_override is not None:
            allocation = D(str(rules.allocation_override))
        plan_dict = _plan_dict(item, rules, allocation)
        sizing = ExecutionPlan.from_dict(plan_dict).apply(params)

        target = sizing.allocation_fraction if wants_long else D("0")
        if not rules.scale and units > 0.0 and target > 0:
            target = D(str((units * fill) / (cash + units * fill)))  # freeze the size

        if target > 0:
            if buy(fill, sizing, target, plan_dict):
                switches += 1
        else:
            adjustment = plan_adjustment(
                target_allocation=target,
                btc_qty=D(str(units)),
                price=D(str(fill)),
                usdt_free=D(str(cash)),
                risk_per_trade_fraction=sizing.risk_per_trade_fraction,
                stop_loss_fraction=sizing.stop_loss_fraction,
                min_notional=params.min_notional_usdt,
                base_step=params.base_step_size,
                dead_band=D(str(rules.dead_band)),
            )
            if adjustment.action == "VENDER":
                sold = float(adjustment.base_qty)
                cash += sold * fill * (1 - FEE)
                units -= sold
                switches += 1
                if units <= 1e-12:
                    units, entry_price, high, active_plan = 0.0, None, None, None

        hours_since_stop: int | None = None
        first_mark = day + 2 if rules.mark_from_fill else day
        last_mark = day + step + 2 if rules.mark_from_fill else day + step
        for mark in range(first_mark, min(last_mark, len(closes))):
            for bar in hourly[mark] or ():
                hours_total += 1
                if hours_since_stop is not None:
                    hours_since_stop += 1
                if units > 0.0:
                    high = max(high or float(bar.high), float(bar.high))
                    level = stop_now(float(bar.close))
                    if level is not None and float(bar.low) <= level:
                        cash += units * min(level, float(bar.open)) * (1 - FEE)
                        units = 0.0
                        entry_price, high, active_plan = None, None, None
                        stop_exits += 1
                        switches += 1
                        hours_since_stop = 0
                        if mark < day + 2:
                            # Fired on a bar that precedes the fill: impossible in reality.
                            phantom_stops += 1
                elif (
                    rules.reentry_cooldown_hours is not None
                    and wants_long
                    and hours_since_stop is not None
                    and hours_since_stop >= rules.reentry_cooldown_hours
                    and buy(float(bar.close), sizing, target, plan_dict)
                ):
                    # The standing decision has not changed, so production would be back
                    # in within one poll. Reproducing that is the point of this variant.
                    reentries += 1
                    switches += 1
                    hours_since_stop = None
                if units > 0.0:
                    hours_invested += 1
                equity = cash + units * float(bar.close)
                peak = max(peak, equity)
                drawdown = max(drawdown, (peak - equity) / peak)
            equity = cash + units * closes[mark]
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak - equity) / peak)

    final = cash + (units * closes[int(trace[-1]["day_index"])] * (1 - FEE) if units else 0.0)
    return {
        "name": rules.name,
        "net_return_pct": (final / START_CAPITAL - 1.0) * 100.0,
        "max_drawdown_pct": drawdown * 100.0,
        "switches": switches,
        "stop_exits": stop_exits,
        "phantom_stops": phantom_stops,
        "scale_ups": scale_ups,
        "reentries": reentries,
        "hours_invested_pct": (hours_invested / hours_total * 100.0) if hours_total else 0.0,
    }


# The two defects found, expressed as switches so every later group can be read against a
# simulation that no longer contains them.
LEGACY_BE: dict[str, float] = {"break_even_activation": 0.005, "break_even_lock": 0.0025}
"""The engine's hard-coded ratchet, which is what actually governed every recorded exit."""

VARIANTS: tuple[tuple[str, tuple[Rules, ...]], ...] = (
    (
        "DEFECTO 1: el stop se evaluaba desde 48h ANTES de existir la posicion",
        (
            Rules("como corrio de verdad", mark_from_fill=False, **LEGACY_BE),  # type: ignore[arg-type]
            Rules("marcando desde el llenado", mark_from_fill=True, **LEGACY_BE),  # type: ignore[arg-type]
            Rules("sin stop, marca desde d", mark_from_fill=False, use_stop=False, **LEGACY_BE),  # type: ignore[arg-type]
            Rules("sin stop, desde el llenado", mark_from_fill=True, use_stop=False, **LEGACY_BE),  # type: ignore[arg-type]
        ),
    ),
    (
        "DEFECTO 2: el piso de break-even que el playbook no sustituia",
        (
            Rules("legado 0.5% activa, piso 0.25%", mark_from_fill=True, **LEGACY_BE),  # type: ignore[arg-type]
            Rules("playbook 1.1, piso por regimen", mark_from_fill=True),
            Rules(
                "sin piso (inalcanzable)",
                mark_from_fill=True,
                break_even_activation=0.90,
                break_even_lock=0.0025,
            ),
            Rules(
                "sin piso NI arrastre",
                mark_from_fill=True,
                break_even_activation=0.90,
                trail_activation_multiplier=45.0,
            ),
            Rules(
                "legado pero sin arrastre",
                mark_from_fill=True,
                trail_activation_multiplier=45.0,
                **LEGACY_BE,  # type: ignore[arg-type]
            ),
        ),
    ),
    (
        "EJECUCION: el stop y el tamano, ya sin los dos defectos",
        (
            Rules("base corregida", mark_from_fill=True),
            Rules("SIN stop protector", mark_from_fill=True, use_stop=False),
            Rules("stop x2, posicion menor", mark_from_fill=True, stop_multiplier=2.0),
            Rules(
                "stop x2, MISMO tamano",
                mark_from_fill=True,
                stop_multiplier=2.0,
                risk_multiplier=2.0,
            ),
            Rules("mitad de tamano", mark_from_fill=True, size_multiplier=0.5),
            Rules("doble de tamano", mark_from_fill=True, size_multiplier=2.0),
            Rules("arrastre x1.5", mark_from_fill=True, trail_multiplier=1.5),
        ),
    ),
    (
        "CADENCIA: cuanto cuesta no poder reentrar hasta la proxima decision",
        (
            Rules("sin reentrada (hoy)", mark_from_fill=True, reentry_cooldown_hours=None),
            Rules("reentra tras 1h", mark_from_fill=True, reentry_cooldown_hours=1),
            Rules("reentra tras 24h", mark_from_fill=True, reentry_cooldown_hours=24),
            Rules("reentra tras 72h", mark_from_fill=True, reentry_cooldown_hours=72),
        ),
    ),
    (
        "AUTORIDAD: de quien es el criterio que gana dinero",
        (
            Rules("agente decide (hoy)", mark_from_fill=True, exposure_from=FROM_AGENT),
            Rules("solo playbook, sin agente", mark_from_fill=True, exposure_from=FROM_PLAYBOOK),
            Rules("agente solo puede vetar", mark_from_fill=True, exposure_from=VETO_ONLY),
            Rules("agente solo puede sumar", mark_from_fill=True, exposure_from=ADD_ONLY),
            Rules("siempre invertido", mark_from_fill=True, exposure_from=ALWAYS_IN),
        ),
    ),
    (
        "ESTABILIDAD: la carga de la prueba cuelga de una etiqueta que oscila",
        (
            Rules("como corrio", mark_from_fill=True, exposure_from=FROM_AGENT),
            Rules("reresuelto (control)", mark_from_fill=True, exposure_from=RERESOLVED),
            Rules("regimen con persistencia", mark_from_fill=True, exposure_from=STABILISED),
            Rules("agente SIN tutela", mark_from_fill=True, exposure_from=RAW_AGENT),
            Rules("agente + desempate 0.50", mark_from_fill=True, exposure_from=TIE_BREAK_ONLY),
            Rules("con el override retirado", mark_from_fill=True, exposure_from=OLD_BURDEN),
        ),
    ),
    (
        "ESCALADO: la banda muerta y el todo-o-nada",
        (
            Rules("sin escalar (como antes)", mark_from_fill=True, scale=False),
            Rules("banda muerta 5pp", mark_from_fill=True, dead_band=0.05),
            Rules("banda muerta 30pp", mark_from_fill=True, dead_band=0.30),
        ),
    ),
)


def reconstruct_plans(
    trace: list[dict[str, Any]], closes: list[float], *, keep_posture: bool = False
) -> list[dict[str, Any]]:
    """Fill missing plan fields by resolving the playbook at NEUTRAL posture.

    Traces recorded before the playbook carry the agent's exposure and conviction but no
    plan. Those decisions are still real, and the windows they cover are the only ones
    available outside the one run that has plan fields, so throwing them away costs
    evidence. This derives what the playbook WOULD have produced for each of them from
    the regime, the declared conviction and the volatility measured on that day.

    Posture is pinned to NEUTRAL because posture is the one input only the model can
    supply. That makes this a control rather than a recreation: it answers execution
    questions about stop, size, re-entry and authority on a fixed posture, and says
    nothing about the posture choice itself. Every result from a reconstructed trace is
    labelled, because a derived number that looks like a measured one is how a plausible
    story gets mistaken for evidence.

    With keep_posture it does something different and more useful: it re-resolves the plan
    from the CURRENT playbook using the posture the model actually chose. That answers what
    a playbook change would have done to decisions already taken, without spending three
    hours of GPU to find out. It is still an approximation for the usual reason, that a
    different position path would have changed what the model saw.
    """
    vol_index = MARKET_FEATURE_NAMES.index("volatility_30d")
    filled: list[dict[str, Any]] = []
    for item in trace:
        day = int(item["day_index"])
        vector = market_features(closes[:day], closes[day])
        plan = resolve_plan(
            regime=item.get("regime"),
            posture=(
                str(item.get("posture") or Posture.NEUTRAL.value)
                if keep_posture
                else Posture.NEUTRAL.value
            ),
            conviction=float(item.get("conviction") or 0.5),
            daily_vol_pct=vector[vol_index] * 100.0,
        )
        filled.append(
            item
            | {
                "posture": plan.posture,
                "strategy": plan.strategy_name,
                "plan_allocation_pct": float(plan.allocation_fraction * 100),
                "plan_stop_pct": float(plan.stop_loss_fraction * 100),
                "plan_risk_pct": float(plan.risk_per_trade_fraction * 100),
                "plan_horizon_hours": plan.horizon_hours,
                # The whole plan, so the replay uses the real trailing and break-even
                # geometry instead of inferring it from the stop.
                "plan": plan.to_dict(),
            }
        )
    return filled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="?", default="data/validation/llm-agent-backtest.json")
    parser.add_argument(
        "--reconstruct-plans",
        action="store_true",
        help=(
            "derive missing plan fields from the playbook at NEUTRAL posture, so a trace "
            "recorded before the playbook can still answer execution questions"
        ),
    )
    parser.add_argument(
        "--replan",
        action="store_true",
        help=(
            "re-resolve every plan through the CURRENT playbook, keeping the posture the "
            "model chose. Answers what a playbook change would have done to decisions "
            "already recorded, in seconds instead of three GPU hours"
        ),
    )
    args = parser.parse_args()
    path = Path(args.report)
    if not path.is_file():
        print(f"informe no encontrado: {path}")
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    trace = payload.get("trace") or []
    if len(trace) < 5:
        print("traza demasiado corta")
        return 1

    bars, _ = load_bars()
    perception = build_daily_perception(bars)
    closes = perception.closes
    hourly: list[list[Any]] = [[] for _ in closes]
    for bar, day_of_bar in zip(bars, perception.available_at_bar, strict=False):
        if 0 <= day_of_bar < len(hourly):
            hourly[day_of_bar].append(bar)

    reconstructed = args.reconstruct_plans and any(
        item.get(field) is None for item in trace for field in REQUIRED_PLAN_FIELDS
    )
    if reconstructed:
        trace = reconstruct_plans(trace, closes)
    elif args.replan:
        trace = reconstruct_plans(trace, closes, keep_posture=True)

    window = payload["window"]
    effective = stabilise_regimes(trace, int(window["step_days"]))
    trace = [item | {"_effective_regime": regime} for item, regime in zip(trace, effective, strict=True)]
    print("=" * 100)
    print(f"CONTRAFACTUALES SOBRE LAS MISMAS DECISIONES  ·  {path.name}")
    print(
        f"  ventana dias {window['start_day_index']}-{window['end_day_index']}, "
        f"{len(trace)} decisiones, paso {window['step_days']}d"
    )
    print(
        f"  referencia: comprar y mantener {payload['buy_and_hold']['net_return_pct']:+.2f}%, "
        f"cuantitativo {payload['quant_policy']['net_return_pct']:+.2f}%"
    )
    if reconstructed:
        print(
            "  PLANES RECONSTRUIDOS: esta traza es anterior al playbook. La exposicion y la\n"
            "  conviccion son las que el modelo dijo; el plan se deriva del playbook a postura\n"
            "  NEUTRAL con la volatilidad medida de cada dia. Sirve para preguntas de\n"
            "  ejecucion a postura fija, no para juzgar la eleccion de postura."
        )
    elif args.replan:
        print(
            f"  REPLANIFICADO con el playbook actual ({PLAYBOOK_VERSION}), conservando la\n"
            "  postura que el modelo eligio en cada decision. Las decisiones son reales; los\n"
            "  parametros de ejecucion son los de hoy, no los de la corrida."
        )
    print("=" * 100)
    header = (
        f"  {'variante':<28} {'retorno':>10} {'drawdown':>9} "
        f"{'h invert':>9} {'cambios':>8} {'stops':>6} {'fantasma':>9} "
        f"{'reentr':>7} {'ampl':>5}"
    )
    for title, group in VARIANTS:
        print()
        print(f"  {title}")
        print(header)
        print("  " + "-" * 98)
        for rules in group:
            result = simulate(trace, closes, hourly, rules)
            print(
                f"  {result['name']:<28} {result['net_return_pct']:>+9.2f}% "
                f"{result['max_drawdown_pct']:>8.2f}% {result['hours_invested_pct']:>8.1f}% "
                f"{result['switches']:>8} {result['stop_exits']:>6} "
                f"{result['phantom_stops']:>9} "
                f"{result['reentries']:>7} {result['scale_ups']:>5}"
            )
    print()
    print("  'h invert' es el porcentaje de HORAS con posicion abierta, no de decisiones.")
    print("  'fantasma' son stops disparados por barras ANTERIORES al llenado de la orden:")
    print("  precios que ya habian pasado cuando la posicion se abrio. Son imposibles.")
    print()
    print("  APROXIMACION: las decisiones del agente estan CONGELADAS y solo cambia como se")
    print("  ejecutan. Un camino de posicion distinto habria cambiado lo que el agente veia y")
    print("  por tanto lo que decidia. Esto acota el tamano de un efecto y ordena las opciones;")
    print("  no predice lo que daria una corrida nueva. Lo que prometa aqui hay que confirmarlo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
