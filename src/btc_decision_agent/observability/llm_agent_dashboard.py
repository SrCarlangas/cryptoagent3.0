"""Pixel-styled live dashboard for the LLM exposure agent (stdlib only).

Why this replaces the previous dashboard
----------------------------------------
The previous one described a numeric policy: four learned regimes, a probability,
a veto chain. That policy is still here, but it is no longer the decision maker. It
is an advisor the agent may overrule and the fallback that keeps the position
managed when the model is unreachable.

The subject of this dashboard is therefore the thing that actually decides: a local
LLM that reads a rendered view of the market, its own position, the commission it
would pay, the numeric advisor's opinion, the closest situations in five years of
history with what followed them, and its own measured track record. The panels are
chosen so the three questions a reader actually has can be answered without reading
a log:

  Who decided this, the LLM or the fallback?
  Why, in its own words?
  Has it earned the confidence it is declaring?

That last one is why the calibration and measured-pattern panels exist. Conviction
is cheap to print and expensive to believe, so it is shown next to the realised hit
rate for the same conviction bucket, and a pattern is described as supported only
when it clears the same statistical gate the agent itself is held to.

The panel is NOT called "lessons learned". The model's weights never change; these
are statistics over the agent's own past decisions that get placed in its prompt.
Calling them lessons would claim the model improved, which is not what happens.

Data sources: the activity journal for live position and book, the agent's memory
database for reasoning, calibration and measured patterns. Both read-only.

Serves:
  GET /            self-refreshing HTML
  GET /api/state   the same data as JSON
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from btc_decision_agent.application.llm_memory import (
    MIN_EFFECT_IN_STANDARD_ERRORS,
    MIN_SAMPLES_FOR_SUPPORT,
    AgentMemory,
)
from btc_decision_agent.application.llm_tools import EXPOSURE_CASH, EXPOSURE_INVESTED
from btc_decision_agent.observability.journal import ActivityJournal

D = Decimal

_REGIME = re.compile(r"_R(\d+)_")
_CONVICTION = re.compile(r"_C(\d+)_")
_MODE = re.compile(r"_C\d+_([DF])")

DEFAULT_COST_BPS = 20.0
"""Round-trip commission in basis points, mirrored from the agent's own default.

Shown beside the expected move because an expected move that does not clear the
commission is not a trade, and that distinction is the single most common reason the
agent declines to act.
"""

REGIME_NAMES: dict[int, str] = {
    0: "RECUPERACION LATERAL",
    1: "BAJISTA PROFUNDO",
    2: "CONSOLIDACION",
    3: "ALCISTA FUERTE",
}
REGIME_HINTS: dict[int, str] = {
    0: "bajo la media de 200d, corto plazo al alza",
    1: "muy bajo tendencia, volatilidad alta",
    2: "sobre tendencia, momento plano",
    3: "sobre tendencia, momento al alza",
}

DECISION_CHAIN: tuple[tuple[str, str], ...] = (
    ("INTERRUPTORES", "desastre de cartera / perdida diaria"),
    ("STOP EXCHANGE", "stop del lado del exchange"),
    ("DATOS", "calidad de la evidencia"),
    ("PERCEPCION", "200 cierres diarios completos"),
    ("AGENTE LLM", "unica fuente de direccion"),
    ("COSTE Y CADENCIA", "el movimiento debe cubrir la comision"),
)

_DATA_VETOES = {
    "DATA_STALE",
    "HISTORY_INSUFFICIENT",
    "BBO_MISSING",
    "SPREAD_TOO_WIDE",
    "PRICE_MISSING",
}


def _clean_reason(entry: dict[str, Any]) -> str:
    return str(entry.get("reason", "")).removeprefix("DRY_RUN:")


def _equity(entry: dict[str, Any]) -> Decimal | None:
    if entry.get("price") is None:
        return None
    usdt = D(entry.get("usdt_free") or "0") + D(entry.get("usdt_locked") or "0")
    return usdt + D(entry.get("btc_qty") or "0") * D(entry["price"])


def classify_origin(reason: str) -> str:
    """Who originated this decision.

    The distinction matters more than anything else on the page. An operator
    looking at a dashboard titled "LLM agent" is entitled to know when the LLM did
    not actually decide, and the reason code is the only honest record of that.
    """
    if reason.startswith("FALLBACK_QUANT"):
        return "FALLBACK"
    if reason == "AGENT_VERDICT_UNCHANGED":
        return "LLM_SOSTENIDO"
    if reason.startswith("AGENT_"):
        return "LLM"
    return "VETADO"


def parse_reason(reason: str) -> dict[str, Any]:
    """Pull the structured fields back out of the reason code.

    The code is the agent's own compact record, so reading it is preferred over
    inferring state from anything else.
    """
    out: dict[str, Any] = {
        "origin": classify_origin(reason),
        "regime": None,
        "conviction": None,
        "deliberated": None,
        "below_cost": reason.endswith("_BELOW_COST"),
    }
    if match := _REGIME.search(reason):
        out["regime"] = int(match.group(1))
    if match := _CONVICTION.search(reason):
        out["conviction"] = int(match.group(1)) / 100.0
    if match := _MODE.search(reason):
        out["deliberated"] = match.group(1) == "D"
    return out


def stage_states(entry: dict[str, Any] | None) -> list[dict[str, str]]:
    """Which layer stopped the last decision, and which ones it passed.

    Derived from the reason code rather than guessed, so a green chain genuinely
    means the agent's decision reached execution. A dashboard that decorates rather
    than reports is worse than no dashboard.
    """
    if entry is None:
        return [{"id": name, "hint": hint, "state": "idle"} for name, hint in DECISION_CHAIN]

    reason = _clean_reason(entry)
    blocked_at: str | None = None
    if reason.startswith("BREAKER") or "DRAWDOWN" in reason or "DAILY_LOSS" in reason:
        blocked_at = "INTERRUPTORES"
    elif reason == "PROTECTIVE_STOP":
        blocked_at = "STOP EXCHANGE"
    elif reason in _DATA_VETOES:
        blocked_at = "DATOS"
    elif reason == "PERCEPTION_INSUFFICIENT":
        blocked_at = "PERCEPCION"
    elif reason.endswith("_BELOW_COST") or reason.endswith("AWAITING_CADENCE"):
        # The agent did decide; the economics or the commit frequency held it back.
        blocked_at = "COSTE Y CADENCIA"

    order = [name for name, _ in DECISION_CHAIN]
    stop_index = order.index(blocked_at) if blocked_at else len(order)
    states: list[dict[str, str]] = []
    for index, (name, hint) in enumerate(DECISION_CHAIN):
        if index < stop_index:
            state = "pass"
        elif index == stop_index:
            state = "block"
        else:
            state = "idle"
        states.append({"id": name, "hint": hint, "state": state})
    return states


def recent_deliberations(memory_path: Path, limit: int = 12) -> list[dict[str, Any]]:
    """The agent's own words, most recent first.

    Read with a separate read-only connection rather than through AgentMemory so the
    dashboard cannot create or migrate the database it is only supposed to observe.
    """
    if not memory_path.is_file():
        return []
    uri = f"file:{memory_path}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=5.0)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT decided_at, regime, quant_p_long, target_exposure, exposure_before, "
                "derived_order, conviction, expected_move_pct, reason, thinking, "
                "price_at_decision, acted, resolved, realized_pct "
                "FROM decisions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except sqlite3.Error:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        quant_p = row["quant_p_long"]
        quant_says = (
            None
            if quant_p is None
            else (EXPOSURE_INVESTED if float(quant_p) >= 0.5 else EXPOSURE_CASH)
        )
        target = str(row["target_exposure"])
        out.append(
            {
                "decided_at": row["decided_at"],
                "regime": row["regime"],
                "quant_p_long": None if quant_p is None else round(float(quant_p), 4),
                "quant_says": quant_says,
                "target_exposure": target,
                "exposure_before": row["exposure_before"],
                "derived_order": row["derived_order"],
                # An override is the clearest evidence the LLM is not a rubber stamp
                # on the numeric policy, so it is computed rather than left implicit.
                "overrode_quant": quant_says is not None and quant_says != target,
                "conviction": row["conviction"],
                "expected_move_pct": row["expected_move_pct"],
                "reason": row["reason"],
                "deliberated": bool(row["thinking"]),
                "price": row["price_at_decision"],
                "acted": bool(row["acted"]),
                "resolved": bool(row["resolved"]),
                "realized_pct": row["realized_pct"],
            }
        )
    return out


def track_record_view(memory_path: Path) -> dict[str, Any]:
    """Track record, calibration and the statistically gated measured patterns.

    Reuses AgentMemory so the gate shown here is the same code the agent is held to.
    A dashboard applying its own looser threshold would quietly report findings the
    agent was never told about.
    """
    empty: dict[str, Any] = {
        "available": False,
        "error": None,
        "stats": {},
        "calibration": {},
        "patterns": [],
        "min_samples": MIN_SAMPLES_FOR_SUPPORT,
        "min_effect": MIN_EFFECT_IN_STANDARD_ERRORS,
    }
    if not memory_path.is_file():
        return {**empty, "error": f"memoria no encontrada: {memory_path}"}
    try:
        memory = AgentMemory(memory_path, read_only=True)
        patterns = [
            {
                "scope": item.scope,
                "samples": item.samples,
                "mean_realized_pct": round(item.mean_realized_pct, 3),
                "effect_in_standard_errors": round(item.effect_in_standard_errors, 2),
                "supported": item.supported,
            }
            for item in memory.measured_patterns()
        ]
        return {
            "available": True,
            "error": None,
            "stats": memory.stats(),
            "calibration": memory.calibration(),
            "patterns": patterns,
            "min_samples": MIN_SAMPLES_FOR_SUPPORT,
            "min_effect": MIN_EFFECT_IN_STANDARD_ERRORS,
        }
    except (sqlite3.Error, OSError, ValueError) as error:
        # Reported rather than swallowed: an empty learning panel that silently
        # means "could not read" is indistinguishable from "nothing learned yet",
        # and those call for very different reactions.
        return {**empty, "error": f"{type(error).__name__}: {error}"}


def equity_series(
    entries: list[dict[str, Any]], *, points: int = 240, fee_per_side: float = 0.001
) -> dict[str, Any]:
    """The agent's equity against buy and hold, both rebased to 100 at the first record.

    Illustrative only, and the honest caveats are returned with the data so the page
    can show them rather than imply more than this measures:

    The window starts at the first journal entry, not at the start of the strategy.
    This journal begins when the LLM agent was deployed, so the chart shows days, not
    years, and a day of BTC noise dwarfs any decision made in it.

    Buy and hold is charged the entry commission, because comparing a net result
    against a gross one flatters the agent for free.

    The agent inherited an open position, so at the first record it was already fully
    invested. The two lines therefore start out nearly identical by construction, and
    they only separate once the agent actually changes exposure.
    """
    priced = [entry for entry in entries if entry.get("price") and _equity(entry) is not None]
    if len(priced) < 2:
        return {"available": False, "points": [], "reason": "hacen falta al menos dos registros"}

    first = priced[0]
    base_equity = _equity(first)
    base_price = D(first["price"])
    if base_equity is None or base_equity <= 0 or base_price <= 0:
        return {"available": False, "points": [], "reason": "primer registro sin valor utilizable"}

    # Buy and hold buys once at the first price, paying the entry commission.
    units = (base_equity * (D("1") - D(str(fee_per_side)))) / base_price

    step = max(len(priced) // points, 1)
    sampled = priced[::step]
    if sampled[-1] is not priced[-1]:
        sampled.append(priced[-1])

    out: list[dict[str, Any]] = []
    for entry in sampled:
        equity = _equity(entry)
        if equity is None:
            continue
        hold = units * D(entry["price"])
        out.append(
            {
                "at": entry.get("at"),
                "agent": round(float(equity / base_equity) * 100.0, 4),
                "hold": round(float(hold / base_equity) * 100.0, 4),
                "price": float(entry["price"]),
            }
        )
    if len(out) < 2:
        return {"available": False, "points": [], "reason": "serie demasiado corta"}

    last = out[-1]
    return {
        "available": True,
        "points": out,
        "from": out[0]["at"],
        "to": last["at"],
        "samples": len(priced),
        "agent_pct": round(last["agent"] - 100.0, 2),
        "hold_pct": round(last["hold"] - 100.0, 2),
        "difference_pp": round(last["agent"] - last["hold"], 2),
        "fee_per_side": fee_per_side,
    }


def build_state(
    journal: ActivityJournal,
    memory_path: Path | None = None,
    *,
    model: str = "qwen3:30b-a3b",
    cost_bps: float = DEFAULT_COST_BPS,
    history: int = 40,
) -> dict[str, Any]:
    entries = journal.read()
    latest = entries[-1] if entries else None
    orders = [entry for entry in entries if entry.get("order_side")]

    parsed = parse_reason(_clean_reason(latest)) if latest else parse_reason("")

    # The freshest entry the LLM actually originated. A long gap between this and
    # last_seen means the agent is alive but the model is not answering.
    last_llm: dict[str, Any] | None = None
    for entry in reversed(entries):
        if classify_origin(_clean_reason(entry)).startswith("LLM"):
            last_llm = entry
            break

    # The standing verdict. Most entries are AGENT_VERDICT_UNCHANGED, which carries
    # no regime or conviction because no new inference ran. Blanking the panels on
    # those would hide the agent's actual position for the 29 minutes between
    # deliberations, so the last real verdict is carried forward and dated.
    standing = parsed
    standing_at = (latest or {}).get("at")
    if parsed["regime"] is None and parsed["conviction"] is None:
        for entry in reversed(entries):
            candidate = parse_reason(_clean_reason(entry))
            if candidate["regime"] is not None or candidate["conviction"] is not None:
                standing = candidate
                standing_at = entry.get("at")
                break

    origins: dict[str, int] = {}
    for entry in entries:
        key = classify_origin(_clean_reason(entry))
        origins[key] = origins.get(key, 0) + 1

    conviction = standing["conviction"]
    probabilities = (latest or {}).get("model_probabilities") or {}
    if isinstance(probabilities, dict) and probabilities.get("TARGET_LONG"):
        conviction = float(probabilities["TARGET_LONG"])

    # Whether these decisions could actually place an order. Read from the recorded
    # field, never inferred: the DRY_RUN reason prefix only appears on entries that
    # wanted to trade, so inferring it would report a holding shadow agent as live.
    authority: bool | None = None
    for entry in reversed(entries):
        if entry.get("order_authority") is not None:
            authority = bool(entry["order_authority"])
            break
    else:
        if latest is not None and str(latest.get("reason", "")).startswith("DRY_RUN:"):
            authority = False

    version: str | None = None
    for entry in reversed(entries):
        if entry.get("directional_model_version"):
            version = str(entry["directional_model_version"])
            break

    equity = _equity(latest) if latest else None
    first_equity = next((_equity(entry) for entry in entries if _equity(entry)), None)

    recent = []
    for entry in reversed(entries[-history:]):
        reason = _clean_reason(entry)
        recent.append(
            {
                "at": entry.get("at"),
                "action": entry.get("action"),
                "reason": reason,
                "origin": classify_origin(reason),
                "price": entry.get("price"),
                "order": (
                    f"{entry.get('order_side')} {entry.get('order_base_qty')} "
                    f"@ {entry.get('order_avg_price')}"
                    if entry.get("order_side")
                    else None
                ),
            }
        )

    memory = memory_path if memory_path is not None else Path("data/live/llm-agent-memory.sqlite3")
    deliberations = recent_deliberations(memory)
    latest_deliberation = deliberations[0] if deliberations else None

    return {
        "model": model,
        "agent_version": version,
        "advisor_version": (latest or {}).get("confidence_model"),
        "cost_bps": cost_bps,
        # None means the journal predates the field: reported as unknown rather than
        # guessed, because guessing wrong in the permissive direction is the one
        # error that matters here.
        "order_authority": authority,
        # who decided
        "origin": parsed["origin"],
        "origin_counts": origins,
        "deliberated": standing["deliberated"],
        "below_cost": parsed["below_cost"],
        "last_llm_at": (last_llm or {}).get("at"),
        "standing_verdict_at": standing_at,
        # what it decided
        "target_exposure": (
            latest_deliberation["target_exposure"] if latest_deliberation else None
        ),
        "action": (latest or {}).get("action"),
        "reason": _clean_reason(latest) if latest else None,
        "conviction": conviction,
        "active_regime": standing["regime"],
        "regime_names": {str(key): value for key, value in REGIME_NAMES.items()},
        "regime_hints": {str(key): value for key, value in REGIME_HINTS.items()},
        # its own words
        "latest_deliberation": latest_deliberation,
        "deliberations": deliberations,
        # the book
        "position": (latest or {}).get("position_after") or (latest or {}).get("position_before"),
        "price": (latest or {}).get("price"),
        "entry_price": (latest or {}).get("entry_price"),
        "active_stop_price": (latest or {}).get("active_stop_price"),
        "equity": format(equity, "f") if equity is not None else None,
        "equity_change_pct": (
            format((equity / first_equity - D("1")) * D("100"), ".2f")
            if equity is not None and first_equity is not None and first_equity > 0
            else None
        ),
        "usdt_free": (latest or {}).get("usdt_free"),
        "btc_qty": (latest or {}).get("btc_qty"),
        # activity
        "order_count": len(orders),
        "buys": sum(1 for entry in orders if entry.get("order_side") == "BUY"),
        "sells": sum(1 for entry in orders if entry.get("order_side") == "SELL"),
        "evaluations": len(entries),
        "last_seen": (latest or {}).get("at"),
        "stages": stage_states(latest),
        "recent": recent,
        "series": equity_series(entries),
        # has it earned its confidence
        "track_record": track_record_view(memory),
    }


LLM_AGENT_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>AGENTE LLM · BTC</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
@font-face{font-family:pixel;src:local('Monaco')}
:root{color-scheme:dark;--ink:#e8edf8;--muted:#9da9bd;--line:#263751;--cyan:#5eead4;
--amber:#ffcc66;--red:#ff6b6b;--violet:#b39ddb;--dim:#1b2740}
*{box-sizing:border-box}
html,body{margin:0;background:#060913;color:var(--ink);
font-family:pixel,'SFMono-Regular',Consolas,monospace;font-size:13px}
body{padding:16px;max-width:1180px;margin:0 auto}
.px{background:rgba(8,13,26,.93);border:2px solid var(--line);box-shadow:3px 3px 0 #02040a}
header{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:14px}
.brand{padding:9px 13px;font-weight:800;letter-spacing:.08em}
.brand b{color:var(--cyan)}
.chip{padding:7px 10px;font-size:11px;color:var(--muted)}
.chip b{color:var(--ink)}
.spacer{flex:1}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));gap:12px;margin-bottom:12px}
.card{padding:13px}
.wide{margin-bottom:12px;padding:13px}
h2{font-size:11px;margin:0 0 10px;color:var(--cyan);letter-spacing:.14em;font-weight:700}
.big{font-size:26px;letter-spacing:.02em}
.sub{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.5}
.row{display:flex;justify-content:space-between;gap:10px;padding:4px 0;font-size:12px;
border-bottom:1px dashed #1b2740}
.row:last-child{border-bottom:0}
.row span:first-child{color:var(--muted)}
.tag{display:inline-block;padding:2px 7px;font-size:10px;border:2px solid var(--dim);letter-spacing:.08em}
.tag.llm{border-color:var(--cyan);color:var(--cyan)}
.tag.fb{border-color:var(--amber);color:var(--amber)}
.tag.veto{border-color:var(--red);color:var(--red)}
.tag.deep{border-color:var(--violet);color:var(--violet)}
.meter{display:flex;gap:3px;margin-top:8px}
.meter i{flex:1;height:14px;background:var(--dim);display:block}
.meter i.f{background:var(--cyan)}
.meter i.h{background:#0f766e}
.regimes{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
.reg{border:2px solid var(--dim);padding:8px;background:#070b16}
.reg.on{border-color:var(--cyan);background:#07231f;box-shadow:inset 0 0 0 2px #0b3a33}
.reg .n{font-size:10px;color:var(--muted);letter-spacing:.1em}
.reg.on .n{color:var(--cyan)}
.reg .t{font-size:11px;margin-top:4px;font-weight:700}
.reg .h{font-size:10px;color:#6b7a91;margin-top:3px;line-height:1.35}
.chain{display:flex;flex-direction:column;gap:6px}
.stage{display:flex;align-items:center;gap:9px;font-size:11px}
.dot{width:12px;height:12px;border:2px solid var(--dim);flex:0 0 auto}
.dot.pass{background:var(--cyan);border-color:var(--cyan)}
.dot.block{background:var(--red);border-color:var(--red)}
.stage .nm{min-width:150px;letter-spacing:.06em}
.stage .hint{color:#6b7a91;font-size:10px}
.stage.blocked .nm{color:var(--red)}
.stage.idle .nm{color:#4a5872}
/* the agent's own words: the centrepiece, so it gets room to breathe */
.prose{background:#050810;border:2px solid var(--dim);padding:12px;font-size:12px;
line-height:1.65;max-height:230px;overflow:auto;white-space:pre-wrap;color:#cfd8e8}
.verdictbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:9px}
table{width:100%;border-collapse:collapse;font-size:11px}
th,td{text-align:left;padding:5px 7px;border-bottom:1px solid #16203a;vertical-align:top}
th{color:var(--muted);font-weight:400;letter-spacing:.08em;font-size:10px}
td.act{color:var(--cyan)}
td.ord{color:var(--amber)}
td.ov{color:var(--violet)}
td.pos{color:var(--cyan)}
td.neg{color:var(--red)}
.warn{border-color:var(--red)!important;color:var(--red)}
.stale{border-color:var(--amber)!important;color:var(--amber)}
.ok{border-color:var(--cyan)!important;color:var(--cyan)}
/* a pulse, so a working page is visibly distinguishable from a frozen one even
   when every number on it is legitimately unchanged */
#live b{display:inline-block;width:7px;height:7px;background:var(--cyan);margin-right:6px}
#live.beat b{background:#0b3a33}
.pat{display:flex;gap:9px;align-items:baseline;font-size:11px;padding:4px 0;
border-bottom:1px dashed #1b2740}
.pat:last-child{border-bottom:0}
.pat .v{min-width:118px;font-size:10px;letter-spacing:.06em}
.pat.ok .v{color:var(--cyan)}
.pat.no .v{color:#6b7a91}
/* equity chart: plain SVG, no libraries, so it works offline behind the tunnel */
#chart{width:100%;height:220px;display:block;background:#050810;border:2px solid var(--dim)}
.chartbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:9px;font-size:11px}
.key{display:inline-flex;align-items:center;gap:6px;color:var(--muted)}
.key i{width:14px;height:3px;display:inline-block}
.key.agent i{background:var(--cyan)}
.key.hold i{background:var(--amber)}
.delta{padding:2px 7px;border:2px solid var(--dim);font-size:10px;letter-spacing:.06em}
.delta.up{border-color:var(--cyan);color:var(--cyan)}
.delta.down{border-color:var(--red);color:var(--red)}
footer{margin-top:14px;font-size:10px;color:#4a5872;line-height:1.6}
</style></head>
<body>
<header>
  <div class="px brand">AGENTE <b>LLM</b> · BTC</div>
  <div class="px chip">modelo <b id="model">—</b></div>
  <div class="px chip">version <b id="ver">—</b></div>
  <div class="px chip">asesor <b id="adv">—</b></div>
  <div class="spacer"></div>
  <div class="px chip" id="live">conectando…</div>
  <div class="px chip" id="mode">—</div>
  <div class="px chip" id="seen">—</div>
</header>

<div class="grid">
  <div class="px card">
    <h2>EXPOSICION OBJETIVO</h2>
    <div class="big" id="target">—</div>
    <div class="sub" id="targetSub">—</div>
  </div>
  <div class="px card">
    <h2>CONVICCION DECLARADA</h2>
    <div class="big" id="conv">—</div>
    <div class="meter" id="meter"></div>
    <div class="sub" id="convSub">—</div>
  </div>
  <div class="px card">
    <h2>LIBRO</h2>
    <div class="big" id="eq">—</div>
    <div class="sub" id="eqSub">—</div>
  </div>
</div>

<div class="grid">
  <div class="px card">
    <h2>QUIEN DECIDIO</h2>
    <div class="big" id="origin">—</div>
    <div class="sub" id="originSub">—</div>
    <div class="row" style="margin-top:9px"><span>decidio el LLM</span><span id="oLlm">—</span></div>
    <div class="row"><span>sostuvo su veredicto</span><span id="oHold">—</span></div>
    <div class="row"><span>fallback cuantitativo</span><span id="oFb">—</span></div>
    <div class="row"><span>vetado antes del agente</span><span id="oVeto">—</span></div>
  </div>
  <div class="px card">
    <h2>CADENA DE DECISION</h2>
    <div class="chain" id="chain"></div>
    <div class="sub">Las capas deterministas solo pueden vetar. Unicamente el
      AGENTE LLM puede originar una compra o una venta.</div>
  </div>
  <div class="px card">
    <h2>REGIMEN DEL ASESOR</h2>
    <div class="regimes" id="regs"></div>
    <div class="sub">El modelo cuantitativo clasifica el mercado y opina. El agente
      puede contradecirlo, y cuando lo hace queda registrado.</div>
  </div>
</div>

<div class="px wide">
  <h2>AGENTE FRENTE A COMPRAR Y MANTENER</h2>
  <div class="chartbar" id="chartBar"></div>
  <svg id="chart" viewBox="0 0 960 220" preserveAspectRatio="none" role="img"
       aria-label="Equity del agente comparada con comprar y mantener"></svg>
  <div class="sub" id="chartNote">—</div>
</div>

<div class="px wide">
  <h2>RAZONAMIENTO DEL AGENTE</h2>
  <div class="verdictbar" id="vbar"></div>
  <div class="prose" id="prose">sin deliberaciones registradas todavia</div>
</div>

<div class="grid">
  <div class="px card">
    <h2>REGISTRO DE DECISIONES</h2>
    <div class="row"><span>decisiones registradas</span><span id="mTot">—</span></div>
    <div class="row"><span>resueltas</span><span id="mRes">—</span></div>
    <div class="row"><span>ordenes ejecutadas</span><span id="mAct">—</span></div>
    <div class="row"><span>resultado medio</span><span id="mAvg">—</span></div>
    <div class="row"><span>evaluaciones (journal)</span><span id="ev">—</span></div>
    <div class="row"><span>compras / ventas</span><span id="bs">—</span></div>
  </div>
  <div class="px card">
    <h2>CALIBRACION</h2>
    <table><thead><tr><th>conviccion</th><th>casos</th><th>acierto</th><th>medio</th></tr></thead>
    <tbody id="calRows"></tbody></table>
    <div class="sub">Convicci&oacute;n declarada frente a acierto real. Si el acierto queda
      por debajo del rango, el agente es sobreconfiado y se le dice.</div>
  </div>
  <div class="px card">
    <h2>PATRONES MEDIDOS EN SU HISTORIAL</h2>
    <div id="patterns"></div>
    <div class="sub" id="patternGate">—</div>
  </div>
</div>

<div class="px wide">
  <h2>DELIBERACIONES RECIENTES</h2>
  <table><thead><tr><th>momento</th><th>objetivo</th><th>conv</th><th>esperado</th>
  <th>asesor</th><th>orden</th><th>resultado</th></tr></thead>
  <tbody id="delibRows"></tbody></table>
</div>

<div class="px wide">
  <h2>ACTIVIDAD EN VIVO</h2>
  <table><thead><tr><th>momento</th><th>origen</th><th>accion</th><th>motivo</th>
  <th>precio</th><th>orden</th></tr></thead>
  <tbody id="rows"></tbody></table>
</div>

<footer>
  Vista de solo lectura del journal de actividad y de la memoria del agente. El
  agente opera en una cuenta DEMO de Binance. El modelo cuantitativo sigue cargado
  como asesor y como fallback: si el LLM no responde, la posicion sigue gestionada.
  Una conviccion alta no es una promesa; el panel de calibracion existe para eso.
</footer>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s==null?'':s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const num = (v,d=2) => v==null ? '—' : Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
const when = s => (s||'').replace('T',' ').slice(0,19);

function meter(p){
  const cells = 20, on = Math.round((p||0)*cells);
  let out = '';
  for(let i=0;i<cells;i++){ out += '<i class="'+(i<on ? (p>=0.5?'f':'h') : '')+'"></i>'; }
  return out;
}
function originTag(o){
  if(o==='LLM') return '<span class="tag llm">LLM</span>';
  if(o==='LLM_SOSTENIDO') return '<span class="tag llm">LLM ·</span>';
  if(o==='FALLBACK') return '<span class="tag fb">FALLBACK</span>';
  return '<span class="tag veto">VETADO</span>';
}

function drawChart(series){
  const svg = $('chart'), bar = $('chartBar'), note = $('chartNote');
  if(!series || !series.available || !series.points || series.points.length < 2){
    svg.innerHTML = '';
    bar.innerHTML = '';
    note.textContent = (series && series.reason) ? series.reason : 'sin datos suficientes todavia';
    return;
  }
  const pts = series.points;
  const W = 960, H = 220, L = 46, R = 8, T = 12, B = 22;
  let lo = Infinity, hi = -Infinity;
  for(const p of pts){
    lo = Math.min(lo, p.agent, p.hold);
    hi = Math.max(hi, p.agent, p.hold);
  }
  // Always keep the 100 baseline in view; a chart that crops it hides whether the
  // book is up or down at a glance.
  lo = Math.min(lo, 100); hi = Math.max(hi, 100);
  const pad = Math.max((hi - lo) * 0.08, 0.05);
  lo -= pad; hi += pad;
  const x = i => L + (i / (pts.length - 1)) * (W - L - R);
  const y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

  const line = key => pts.map((p, i) => x(i).toFixed(1) + ',' + y(p[key]).toFixed(1)).join(' ');
  const gridVals = [lo + (hi - lo) * 0.5, 100, hi - pad, lo + pad];
  const seen = {};
  let grid = '';
  for(const v of gridVals){
    const k = v.toFixed(2);
    if(seen[k]) continue;
    seen[k] = 1;
    const isBase = Math.abs(v - 100) < 1e-9;
    grid += '<line x1="' + L + '" y1="' + y(v).toFixed(1) + '" x2="' + (W - R)
      + '" y2="' + y(v).toFixed(1) + '" stroke="' + (isBase ? '#3a4a66' : '#16203a')
      + '" stroke-width="1"' + (isBase ? ' stroke-dasharray="4 4"' : '') + '/>';
    grid += '<text x="4" y="' + (y(v) + 3.5).toFixed(1) + '" fill="'
      + (isBase ? '#9da9bd' : '#4a5872') + '" font-size="9">' + v.toFixed(2) + '</text>';
  }
  const t0 = (pts[0].at || '').replace('T', ' ').slice(5, 16);
  const t1 = (pts[pts.length - 1].at || '').replace('T', ' ').slice(5, 16);
  svg.innerHTML = grid
    + '<polyline fill="none" stroke="#ffcc66" stroke-width="2" points="' + line('hold') + '"/>'
    + '<polyline fill="none" stroke="#5eead4" stroke-width="2" points="' + line('agent') + '"/>'
    + '<text x="' + L + '" y="' + (H - 6) + '" fill="#4a5872" font-size="9">' + esc(t0) + '</text>'
    + '<text x="' + (W - R) + '" y="' + (H - 6) + '" fill="#4a5872" font-size="9" '
    + 'text-anchor="end">' + esc(t1) + '</text>';

  const d = series.difference_pp;
  bar.innerHTML = '<span class="key agent"><i></i>agente ' + (series.agent_pct >= 0 ? '+' : '')
      + series.agent_pct.toFixed(2) + '%</span>'
    + '<span class="key hold"><i></i>comprar y mantener ' + (series.hold_pct >= 0 ? '+' : '')
      + series.hold_pct.toFixed(2) + '%</span>'
    + '<span class="delta ' + (d >= 0 ? 'up' : 'down') + '">diferencia '
      + (d >= 0 ? '+' : '') + d.toFixed(2) + 'pp</span>';

  note.textContent = 'Base 100 en el primer registro del journal (' + series.samples
    + ' evaluaciones). Comprar y mantener paga la comision de entrada de '
    + (series.fee_per_side * 10000).toFixed(0) + ' bps. '
    + 'Solo ilustrativo: la ventana empieza cuando se despliego este agente, no cuando '
    + 'empezo la estrategia, y el agente heredo una posicion abierta, asi que las dos '
    + 'lineas arrancan casi iguales por construccion y solo se separan cuando cambia '
    + 'de exposicion.';
}

// Connection state is tracked and shown. A silent catch made a dead tunnel, a
// restarting service and a healthy-but-quiet agent all look identical, which is
// the whole reason this page appeared frozen.
let lastOk = 0, lastEval = null, lastEvalChange = 0, lastError = '', beat = false;

function heartbeat(){
  const el = $('live');
  beat = !beat;
  let state = 'ok', text;
  if(!lastOk){
    state = 'warn';
    text = 'sin conexion con el panel' + (lastError ? ' ('+esc(lastError)+')' : '');
  } else {
    const age = Math.round((Date.now()-lastOk)/1000);
    const still = Math.round((Date.now()-lastEvalChange)/1000);
    if(age > 15){
      state = 'warn';
      text = 'SIN CONEXION · ultimo dato hace '+age+'s';
    } else if(still > 120){
      // The page is fine and the agent is not advancing. A different problem, and
      // it must not be reported as a connection failure.
      state = 'stale';
      text = 'conectado · el agente no avanza desde hace '+still+'s';
    } else {
      text = 'en vivo · hace '+age+'s';
    }
  }
  // className is rebuilt in one go so the pulse class is not wiped by it.
  el.className = 'px chip ' + state + (beat ? ' beat' : '');
  el.innerHTML = '<b></b>' + text;
}

async function tick(){
  let s;
  try {
    const r = await fetch('/api/state',{cache:'no-store'});
    if(!r.ok) throw new Error('http '+r.status);
    s = await r.json();
    lastOk = Date.now();
    lastError = '';
    if(s.evaluations !== lastEval){ lastEval = s.evaluations; lastEvalChange = Date.now(); }
  } catch(e){
    lastError = (e && e.message) ? e.message : 'fallo de red';
    heartbeat();
    return;
  }

  $('model').textContent = s.model || '—';
  $('ver').textContent = s.agent_version || '—';
  $('adv').textContent = s.advisor_version || '—';
  const mode = $('mode');
  if(s.order_authority === true){ mode.textContent = 'AUTORIDAD DE ORDENES'; }
  else if(s.order_authority === false){ mode.textContent = 'SOMBRA (sin ordenes)'; }
  else { mode.textContent = 'MODO DESCONOCIDO'; }
  mode.classList.toggle('warn', s.order_authority !== true);

  const seen = $('seen');
  seen.textContent = s.last_seen ? ('visto ' + when(s.last_seen)) : 'sin actividad';
  seen.classList.toggle('warn', !!(s.last_seen && (Date.now()-Date.parse(s.last_seen)) > 900000));

  $('target').textContent = s.target_exposure || (s.position || '—');
  let tsub = s.action ? ('ultima accion <b>'+esc(s.action)+'</b>') : '—';
  if(s.reason) tsub += '<br>'+esc(s.reason);
  if(s.below_cost) tsub += '<br><span class="tag fb">el movimiento no cubre la comision</span>';
  $('targetSub').innerHTML = tsub;

  const c = s.conviction;
  $('conv').textContent = c==null ? '—' : (c*100).toFixed(1)+'%';
  $('meter').innerHTML = meter(c);
  const d = s.latest_deliberation;
  $('convSub').innerHTML = d
    ? ('movimiento esperado '+(d.expected_move_pct==null?'—':Number(d.expected_move_pct).toFixed(2)+'%')
       +' · umbral de coste '+(s.cost_bps/100).toFixed(2)+'%')
    : 'sin veredicto del modelo todavia';

  $('eq').textContent = s.equity ? num(s.equity)+' USDT' : '—';
  let esub = 'BTC ' + num(s.price);
  if(s.equity_change_pct!=null) esub += '<br>desde el primer registro '+s.equity_change_pct+'%';
  if(s.btc_qty && Number(s.btc_qty)>0) esub += '<br>posicion '+s.btc_qty+' BTC';
  if(s.entry_price) esub += '<br>entrada '+num(s.entry_price);
  if(s.active_stop_price && s.position==='LONG') esub += '<br>stop '+num(s.active_stop_price);
  $('eqSub').innerHTML = esub;

  $('origin').innerHTML = originTag(s.origin);
  let osub = '';
  if(s.origin==='LLM') osub = s.deliberated ? 'razono a fondo antes de mover dinero'
                                            : 'pasada rapida, sin cambio de exposicion';
  else if(s.origin==='LLM_SOSTENIDO') osub = 'mantiene el veredicto anterior, sin nueva inferencia';
  else if(s.origin==='FALLBACK') osub = 'el modelo no respondio; decide el policy cuantitativo validado';
  else osub = 'una capa protectora corto antes de llegar al agente';
  if(s.last_llm_at) osub += '<br>ultimo veredicto propio: '+when(s.last_llm_at);
  if(s.standing_verdict_at && s.origin==='LLM_SOSTENIDO')
    osub += '<br>veredicto vigente desde: '+when(s.standing_verdict_at);
  $('originSub').innerHTML = osub;
  const oc = s.origin_counts||{};
  $('oLlm').textContent = oc.LLM ?? 0;
  $('oHold').textContent = oc.LLM_SOSTENIDO ?? 0;
  $('oFb').textContent = oc.FALLBACK ?? 0;
  $('oVeto').textContent = oc.VETADO ?? 0;

  let chtml='';
  for(const st of (s.stages||[])){
    const cls = st.state==='pass'?'passed':(st.state==='block'?'blocked':'idle');
    chtml += '<div class="stage '+cls+'"><span class="dot '+st.state+'"></span>'
      + '<span class="nm">'+esc(st.id)+'</span><span class="hint">'+esc(st.hint)+'</span></div>';
  }
  $('chain').innerHTML = chtml;

  let rhtml='';
  for(let k=0;k<4;k++){
    rhtml += '<div class="reg'+(s.active_regime===k?' on':'')+'"><div class="n">REGIMEN '+k+'</div>'
      + '<div class="t">'+esc(s.regime_names[k]||'—')+'</div>'
      + '<div class="h">'+esc(s.regime_hints[k]||'')+'</div></div>';
  }
  $('regs').innerHTML = rhtml;

  const memErr = (s.track_record||{}).error;
  if(d){
    let vb = '<span class="tag llm">'+esc(d.target_exposure)+'</span>';
    if(d.deliberated) vb += '<span class="tag deep">RAZONAMIENTO PROFUNDO</span>';
    if(d.overrode_quant) vb += '<span class="tag deep">CONTRADIJO AL ASESOR</span>';
    vb += '<span class="chip">conviccion '+(d.conviction==null?'—':(d.conviction*100).toFixed(0)+'%')+'</span>';
    vb += '<span class="chip">esperado '+(d.expected_move_pct==null?'—':Number(d.expected_move_pct).toFixed(2)+'%')+'</span>';
    vb += '<span class="chip">'+when(d.decided_at)+'</span>';
    $('vbar').innerHTML = vb;
    $('prose').textContent = d.reason || 'el modelo no dejo justificacion';
  } else if(memErr){
    // Never let a failed read look like "the agent has not reasoned yet". Those two
    // states call for completely different reactions.
    $('vbar').innerHTML = '<span class="tag veto">MEMORIA ILEGIBLE</span>';
    // The escapes are doubled because this page is a plain Python string: a single
    // backslash-n here would become a real newline inside a JavaScript string
    // literal, which is a syntax error that kills the entire script and freezes the
    // whole dashboard. That happened.
    $('prose').textContent = 'no se pudo leer la memoria del agente: ' + memErr
      + '\\n\\nEl agente puede estar decidiendo con normalidad; lo que falla es la lectura '
      + 'de este panel. Revisa los permisos del servicio del dashboard sobre data/live.';
  } else {
    $('vbar').innerHTML = '';
    $('prose').textContent = 'sin deliberaciones registradas todavia';
  }

  const L = s.track_record || {};
  const st2 = L.stats || {};
  $('mTot').textContent = st2.decisiones_totales ?? '—';
  $('mRes').textContent = st2.resueltas ?? '—';
  $('mAct').textContent = st2.ordenes_ejecutadas ?? '—';
  $('mAvg').textContent = st2.resultado_medio_pct==null ? '—'
    : (Number(st2.resultado_medio_pct)>=0?'+':'')+Number(st2.resultado_medio_pct).toFixed(2)+'%';
  $('ev').textContent = s.evaluations ?? '—';
  $('bs').textContent = (s.buys ?? 0)+' / '+(s.sells ?? 0);

  const cal = (L.calibration||{}).buckets || {};
  let calHtml='';
  for(const k of Object.keys(cal)){
    const b = cal[k];
    const cls = b.resultado_medio_pct>=0?'pos':'neg';
    calHtml += '<tr><td>'+esc(k)+'</td><td>'+b.casos+'</td><td>'+(b.acierto*100).toFixed(0)+'%</td>'
      + '<td class="'+cls+'">'+(b.resultado_medio_pct>=0?'+':'')+Number(b.resultado_medio_pct).toFixed(2)+'%</td></tr>';
  }
  $('calRows').innerHTML = calHtml || '<tr><td colspan="4">sin resultados resueltos todavia</td></tr>';

  let lhtml='';
  for(const l of (L.patterns||[])){
    lhtml += '<div class="pat '+(l.supported?'ok':'no')+'">'
      + '<span class="v">'+(l.supported?'CON RESPALDO':'NO CONCLUYENTE')+'</span>'
      + '<span>'+esc(l.scope)+' · '+l.samples+' casos · '
      + (l.mean_realized_pct>=0?'+':'')+Number(l.mean_realized_pct).toFixed(2)+'% · '
      + Number(l.effect_in_standard_errors).toFixed(1)+' EE</span></div>';
  }
  if(L.error){
    $('patterns').innerHTML = '<div class="sub warn">no se pudo leer la memoria: '+esc(L.error)+'</div>';
  } else {
    $('patterns').innerHTML = lhtml || '<div class="sub">sin patrones medidos todavia</div>';
  }
  $('patternGate').textContent = 'Estadistica sobre sus decisiones ya resueltas. Los pesos '
    + 'del modelo no cambian: esto se le muestra en el prompt, no lo aprende. Un patron pasa '
    + 'a CON RESPALDO con al menos ' + (L.min_samples ?? '?') + ' casos y un efecto de al menos '
    + (L.min_effect ?? '?') + ' errores estandar; el resto queda NO CONCLUYENTE.';

  let dhtml='';
  for(const r of (s.deliberations||[])){
    const res = r.realized_pct==null ? '' :
      '<span class="'+(r.realized_pct>=0?'pos':'neg')+'">'
      + (r.realized_pct>=0?'+':'')+Number(r.realized_pct).toFixed(2)+'%</span>';
    dhtml += '<tr><td>'+when(r.decided_at)+'</td>'
      + '<td class="act">'+esc(r.target_exposure)+(r.deliberated?' <span class="tag deep">D</span>':'')+'</td>'
      + '<td>'+(r.conviction==null?'':(r.conviction*100).toFixed(0)+'%')+'</td>'
      + '<td>'+(r.expected_move_pct==null?'':Number(r.expected_move_pct).toFixed(2)+'%')+'</td>'
      + '<td class="'+(r.overrode_quant?'ov':'')+'">'+esc(r.quant_says||'')
      + (r.overrode_quant?' (contradicho)':'')+'</td>'
      + '<td class="ord">'+(r.acted?esc(r.derived_order):'')+'</td>'
      + '<td>'+res+'</td></tr>';
  }
  $('delibRows').innerHTML = dhtml || ('<tr><td colspan="7">'
    + (memErr ? 'memoria ilegible: '+esc(memErr) : 'sin deliberaciones todavia')
    + '</td></tr>');

  drawChart(s.series);

  let html='';
  for(const r of (s.recent||[])){
    html += '<tr><td>'+when(r.at)+'</td><td>'+originTag(r.origin)+'</td>'
      + '<td class="act">'+esc(r.action)+'</td><td>'+esc(r.reason)+'</td>'
      + '<td>'+num(r.price)+'</td><td class="ord">'+esc(r.order||'')+'</td></tr>';
  }
  $('rows').innerHTML = html;
}
tick(); setInterval(tick, 5000);
// Independent of the poll, so the age keeps counting up when the poll is failing.
heartbeat(); setInterval(heartbeat, 1000);
</script>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    journal_path: str = "data/live/llm-agent-activity.jsonl"
    memory_path: str = "data/live/llm-agent-memory.sqlite3"
    model_name: str = "qwen3:30b-a3b"
    cost_bps: float = DEFAULT_COST_BPS

    def do_GET(self) -> None:
        if self.path.startswith("/api/state"):
            payload = json.dumps(
                build_state(
                    ActivityJournal(self.journal_path),
                    Path(self.memory_path),
                    model=self.model_name,
                    cost_bps=self.cost_bps,
                )
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path in {"/", "/index.html"}:
            body = LLM_AGENT_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # The page itself must not be cached. /api/state already said no-store
            # but the HTML did not, so a browser could hold an old copy of the page
            # indefinitely and keep running its old JavaScript against the current
            # API. That looks exactly like a frozen dashboard.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        """Silence per-request logging; the agent's journal is the record."""


def serve(
    journal: str,
    memory: str,
    *,
    model: str = "qwen3:30b-a3b",
    cost_bps: float = DEFAULT_COST_BPS,
    host: str = "127.0.0.1",
    port: int = 8787,
) -> ThreadingHTTPServer:
    handler = type(
        "BoundHandler",
        (_Handler,),
        {
            "journal_path": journal,
            "memory_path": memory,
            "model_name": model,
            "cost_bps": cost_bps,
        },
    )
    return ThreadingHTTPServer((host, port), handler)


__all__ = [
    "DECISION_CHAIN",
    "LLM_AGENT_PAGE",
    "REGIME_NAMES",
    "build_state",
    "classify_origin",
    "parse_reason",
    "recent_deliberations",
    "serve",
    "stage_states",
    "track_record_view",
]
