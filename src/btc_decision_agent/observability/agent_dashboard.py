"""Pixel-styled live dashboard for the local exposure agent (stdlib only).

The previous dashboard drew an isometric office with six departments, which
described the retired deterministic pipeline: a market-data desk, a research lab, a
strategy desk and so on. There is no such pipeline any more. One learned agent
decides, and a chain of deterministic layers can only veto it.

So this dashboard keeps the pixel aesthetic and changes the subject. It shows the
agent's four learned regimes as lit or dim cells, its current conviction, the veto
chain with the stage that actually stopped a decision, and the book it is running.

Serves:
  GET /            self-refreshing HTML
  GET /api/state   the same data as JSON

Read-only: it parses the activity journal and the policy document. It never trades,
never holds credentials, and runs in its own process.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from btc_decision_agent.observability.journal import ActivityJournal

D = Decimal
_REGIME = re.compile(r"_R(\d+)_")
_CONVICTION = re.compile(r"_P(\d+)$")

REGIME_NAMES: dict[int, str] = {
    0: "RECOVERY CHOP",
    1: "DEEP BEAR",
    2: "CONSOLIDATION",
    3: "STRONG BULL",
}
REGIME_HINTS: dict[int, str] = {
    0: "below 200d avg, short-term up",
    1: "far below trend, high volatility",
    2: "above trend, momentum flat",
    3: "above trend, momentum up",
}

VETO_CHAIN: tuple[tuple[str, str], ...] = (
    ("BREAKER", "portfolio disaster / daily loss"),
    ("PROTECTIVE_STOP", "exchange-side stop hit"),
    ("DATA", "evidence quality gate"),
    ("PERCEPTION", "200 completed daily closes"),
    ("AGENT", "the only source of direction"),
    ("CADENCE", "commit at the validated frequency"),
)

_DATA_VETOES = {"DATA_STALE", "HISTORY_INSUFFICIENT", "BBO_MISSING", "SPREAD_TOO_WIDE", "PRICE_MISSING"}


def _clean_reason(entry: dict[str, Any]) -> str:
    return str(entry.get("reason", "")).removeprefix("DRY_RUN:")


def _equity(entry: dict[str, Any]) -> Decimal | None:
    if entry.get("price") is None:
        return None
    usdt = D(entry.get("usdt_free") or "0") + D(entry.get("usdt_locked") or "0")
    return usdt + D(entry.get("btc_qty") or "0") * D(entry["price"])


def stage_states(entry: dict[str, Any] | None) -> list[dict[str, str]]:
    """Which veto stage stopped the last decision, and which ones it passed.

    Derived from the reason code rather than guessed, so a green chain genuinely
    means the agent's decision reached execution.
    """
    if entry is None:
        return [
            {"id": name, "hint": hint, "state": "idle"} for name, hint in VETO_CHAIN
        ]
    reason = _clean_reason(entry)
    blocked_at: str | None = None
    if reason.startswith("BREAKER") or "DRAWDOWN" in reason or "DAILY_LOSS" in reason:
        blocked_at = "BREAKER"
    elif reason == "PROTECTIVE_STOP":
        blocked_at = "PROTECTIVE_STOP"
    elif reason in _DATA_VETOES:
        blocked_at = "DATA"
    elif reason == "PERCEPTION_INSUFFICIENT":
        blocked_at = "PERCEPTION"
    elif reason.endswith("AWAITING_CADENCE"):
        blocked_at = "CADENCE"

    order = [name for name, _ in VETO_CHAIN]
    states: list[dict[str, str]] = []
    stop_index = order.index(blocked_at) if blocked_at else len(order)
    for index, (name, hint) in enumerate(VETO_CHAIN):
        if index < stop_index:
            state = "pass"
        elif index == stop_index:
            state = "block"
        else:
            state = "idle"
        states.append({"id": name, "hint": hint, "state": state})
    return states


def build_state(
    journal: ActivityJournal, policy_path: Path | None = None, *, history: int = 40
) -> dict[str, Any]:
    entries = journal.read()
    latest = entries[-1] if entries else None
    orders = [entry for entry in entries if entry.get("order_side")]

    policy: dict[str, Any] = {}
    if policy_path is not None and policy_path.is_file():
        raw: object = json.loads(policy_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            policy = raw
    metadata = policy.get("metadata", {}) if isinstance(policy.get("metadata"), dict) else {}
    evidence = metadata.get("promotion_evidence", {}) if isinstance(metadata.get("promotion_evidence"), dict) else {}

    regime: int | None = None
    conviction: float | None = None
    if latest is not None:
        reason = _clean_reason(latest)
        if match := _REGIME.search(reason):
            regime = int(match.group(1))
        if match := _CONVICTION.search(reason):
            conviction = int(match.group(1)) / 100.0
        probabilities = latest.get("model_probabilities") or {}
        if isinstance(probabilities, dict) and probabilities.get("TARGET_LONG"):
            conviction = float(probabilities["TARGET_LONG"])

    equity = _equity(latest) if latest else None
    first_equity = next((_equity(entry) for entry in entries if _equity(entry)), None)

    recent = []
    for entry in reversed(entries[-history:]):
        recent.append(
            {
                "at": entry.get("at"),
                "action": entry.get("action"),
                "reason": _clean_reason(entry),
                "price": entry.get("price"),
                "order": (
                    f"{entry.get('order_side')} {entry.get('order_base_qty')} @ {entry.get('order_avg_price')}"
                    if entry.get("order_side")
                    else None
                ),
            }
        )

    return {
        "policy_version": policy.get("policy_version") or (latest or {}).get("directional_model_version"),
        "strategy_version": (latest or {}).get("strategy_version"),
        "promotion_status": metadata.get("promotion_status"),
        "regimes": int(policy.get("regimes") or 0),
        "trained_steps": policy.get("trained_steps"),
        "online_learning": bool((latest or {}).get("online_learning")),
        "expected_oos_return_pct": evidence.get("seed_stability_mean_pct"),
        "chosen_config": evidence.get("chosen_config"),
        "active_regime": regime,
        "regime_names": {str(key): value for key, value in REGIME_NAMES.items()},
        "regime_hints": {str(key): value for key, value in REGIME_HINTS.items()},
        "conviction": conviction,
        "action": (latest or {}).get("action"),
        "reason": _clean_reason(latest) if latest else None,
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
        "order_count": len(orders),
        "buys": sum(1 for entry in orders if entry.get("order_side") == "BUY"),
        "sells": sum(1 for entry in orders if entry.get("order_side") == "SELL"),
        "evaluations": len(entries),
        "last_seen": (latest or {}).get("at"),
        "stages": stage_states(latest),
        "recent": recent,
    }


AGENT_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>EXPOSURE AGENT</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
@font-face{font-family:pixel;src:local('Monaco')}
:root{color-scheme:dark;--ink:#e8edf8;--muted:#9da9bd;--panel:#080d1a;--line:#263751;--cyan:#5eead4;--amber:#ffcc66;--red:#ff6b6b;--dim:#1b2740}
*{box-sizing:border-box}
html,body{margin:0;background:#060913;color:var(--ink);font-family:pixel,'SFMono-Regular',Consolas,monospace;font-size:13px}
body{padding:16px;max-width:1120px;margin:0 auto}
a{color:var(--cyan)}
.px{background:rgba(8,13,26,.93);border:2px solid var(--line);box-shadow:3px 3px 0 #02040a}
header{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:14px}
.brand{padding:9px 13px;font-weight:800;letter-spacing:.08em}
.brand b{color:var(--cyan)}
.chip{padding:7px 10px;font-size:11px;color:var(--muted)}
.chip b{color:var(--ink)}
.spacer{flex:1}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;margin-bottom:12px}
.card{padding:13px}
h2{font-size:11px;margin:0 0 10px;color:var(--cyan);letter-spacing:.14em;font-weight:700}
.big{font-size:26px;letter-spacing:.02em}
.sub{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.5}
.row{display:flex;justify-content:space-between;gap:10px;padding:4px 0;font-size:12px;border-bottom:1px dashed #1b2740}
.row:last-child{border-bottom:0}
.row span:last-child{color:var(--ink)}
.row span:first-child{color:var(--muted)}
/* regime cells: pixel blocks that light up */
.regimes{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
.reg{border:2px solid var(--dim);padding:9px;background:#070b16}
.reg.on{border-color:var(--cyan);background:#07231f;box-shadow:inset 0 0 0 2px #0b3a33}
.reg .n{font-size:10px;color:var(--muted);letter-spacing:.1em}
.reg.on .n{color:var(--cyan)}
.reg .t{font-size:12px;margin-top:4px;font-weight:700}
.reg .h{font-size:10px;color:#6b7a91;margin-top:4px;line-height:1.4}
/* conviction meter in pixel blocks */
.meter{display:flex;gap:3px;margin-top:8px}
.meter i{flex:1;height:14px;background:var(--dim);display:block}
.meter i.f{background:var(--cyan)}
.meter i.h{background:#0f766e}
/* veto chain */
.chain{display:flex;flex-direction:column;gap:6px}
.stage{display:flex;align-items:center;gap:9px;font-size:11px}
.dot{width:12px;height:12px;border:2px solid var(--dim);flex:0 0 auto}
.dot.pass{background:var(--cyan);border-color:var(--cyan)}
.dot.block{background:var(--red);border-color:var(--red)}
.stage .nm{min-width:126px;letter-spacing:.06em}
.stage .hint{color:#6b7a91;font-size:10px}
.stage.blocked .nm{color:var(--red)}
.stage.passed .nm{color:var(--ink)}
.stage.idle .nm{color:#4a5872}
table{width:100%;border-collapse:collapse;font-size:11px}
th,td{text-align:left;padding:5px 7px;border-bottom:1px solid #16203a}
th{color:var(--muted);font-weight:400;letter-spacing:.08em;font-size:10px}
td.act{color:var(--cyan)}
td.ord{color:var(--amber)}
.warn{border-color:var(--red)!important;color:var(--red)}
footer{margin-top:14px;font-size:10px;color:#4a5872;line-height:1.6}
</style></head>
<body>
<header>
  <div class="px brand">PIXEL <b>EXPOSURE AGENT</b></div>
  <div class="px chip">policy <b id="pv">—</b></div>
  <div class="px chip">regimes <b id="rg">—</b></div>
  <div class="px chip">learning <b id="ol">—</b></div>
  <div class="spacer"></div>
  <div class="px chip" id="seen">—</div>
</header>

<div class="grid">
  <div class="px card">
    <h2>EXPOSURE</h2>
    <div class="big" id="pos">—</div>
    <div class="sub" id="posSub">—</div>
  </div>
  <div class="px card">
    <h2>CONVICTION · P(LONG)</h2>
    <div class="big" id="conv">—</div>
    <div class="meter" id="meter"></div>
    <div class="sub" id="convSub">the agent's own probability of wanting exposure</div>
  </div>
  <div class="px card">
    <h2>BOOK</h2>
    <div class="big" id="eq">—</div>
    <div class="sub" id="eqSub">—</div>
  </div>
</div>

<div class="grid">
  <div class="px card">
    <h2>LEARNED REGIMES</h2>
    <div class="regimes" id="regs"></div>
    <div class="sub">The gate assigns the market to one of these. Labels are
      descriptions of learned behaviour, never inputs.</div>
  </div>
  <div class="px card">
    <h2>DECISION PATH</h2>
    <div class="chain" id="chain"></div>
    <div class="sub">Deterministic layers may only veto. Only the AGENT stage can
      originate a buy or a sell.</div>
  </div>
  <div class="px card">
    <h2>ACTIVITY</h2>
    <div class="row"><span>evaluations</span><span id="ev">—</span></div>
    <div class="row"><span>orders</span><span id="oc">—</span></div>
    <div class="row"><span>buys / sells</span><span id="bs">—</span></div>
    <div class="row"><span>training steps</span><span id="ts">—</span></div>
    <div class="row"><span>expected OOS return</span><span id="oos">—</span></div>
    <div class="row"><span>config</span><span id="cfg">—</span></div>
  </div>
</div>

<div class="px card">
  <h2>RECENT DECISIONS</h2>
  <table><thead><tr><th>time</th><th>action</th><th>reason</th><th>price</th><th>order</th></tr></thead>
  <tbody id="rows"></tbody></table>
</div>

<footer>
  Read-only view of the activity journal. The agent is the sole order authority on a
  Binance DEMO account. Expected return is the multi-seed walk-forward out-of-sample
  mean, not a promise.
</footer>

<script>
const $ = id => document.getElementById(id);
function meter(p){
  const cells = 20, on = Math.round((p||0)*cells);
  let out = '';
  for(let i=0;i<cells;i++){
    const cls = i<on ? (p>=0.5?'f':'h') : '';
    out += '<i class="'+cls+'"></i>';
  }
  return out;
}
async function tick(){
  let s;
  try { s = await (await fetch('/api/state',{cache:'no-store'})).json(); }
  catch(e){ return; }

  $('pv').textContent = s.policy_version || '—';
  $('rg').textContent = s.regimes || '—';
  $('ol').textContent = s.online_learning ? 'online' : 'off';
  const seen = $('seen');
  seen.textContent = s.last_seen ? ('last seen ' + s.last_seen.replace('T',' ').slice(0,19)) : 'no activity';
  const stale = s.last_seen && (Date.now() - Date.parse(s.last_seen)) > 900000;
  seen.classList.toggle('warn', !!stale);

  $('pos').textContent = s.position || '—';
  $('posSub').innerHTML = (s.action ? ('last action <b>'+s.action+'</b><br>'+ (s.reason||'')) : '—')
    + (s.active_stop_price && s.position==='LONG' ? '<br>stop '+Number(s.active_stop_price).toLocaleString() : '');

  const c = s.conviction;
  $('conv').textContent = c==null ? '—' : (c*100).toFixed(1)+'%';
  $('meter').innerHTML = meter(c);
  if(s.active_regime!=null){
    $('convSub').textContent = 'in regime '+s.active_regime+' · '+(s.regime_names[s.active_regime]||'');
  }

  $('eq').textContent = s.equity ? Number(s.equity).toLocaleString(undefined,{maximumFractionDigits:2})+' USDT' : '—';
  $('eqSub').innerHTML = 'BTC ' + (s.price?Number(s.price).toLocaleString():'—')
    + (s.equity_change_pct!=null ? ('<br>since first record '+s.equity_change_pct+'%') : '')
    + (s.btc_qty ? ('<br>holding '+s.btc_qty+' BTC') : '');

  let rhtml='';
  for(let k=0;k<(s.regimes||4);k++){
    const on = (s.active_regime===k) ? ' on' : '';
    rhtml += '<div class="reg'+on+'"><div class="n">REGIME '+k+'</div>'
      + '<div class="t">'+(s.regime_names[k]||'—')+'</div>'
      + '<div class="h">'+(s.regime_hints[k]||'')+'</div></div>';
  }
  $('regs').innerHTML = rhtml;

  let chtml='';
  for(const st of (s.stages||[])){
    const cls = st.state==='pass'?'passed':(st.state==='block'?'blocked':'idle');
    chtml += '<div class="stage '+cls+'"><span class="dot '+st.state+'"></span>'
      + '<span class="nm">'+st.id+'</span><span class="hint">'+st.hint+'</span></div>';
  }
  $('chain').innerHTML = chtml;

  $('ev').textContent = s.evaluations ?? '—';
  $('oc').textContent = s.order_count ?? '—';
  $('bs').textContent = (s.buys ?? 0)+' / '+(s.sells ?? 0);
  $('ts').textContent = s.trained_steps ?? '—';
  $('oos').textContent = s.expected_oos_return_pct!=null ? (Number(s.expected_oos_return_pct).toFixed(1)+'%') : '—';
  $('cfg').textContent = s.chosen_config || '—';

  let html='';
  for(const r of (s.recent||[])){
    html += '<tr><td>'+(r.at||'').replace('T',' ').slice(0,19)+'</td>'
      + '<td class="act">'+(r.action||'')+'</td><td>'+(r.reason||'')+'</td>'
      + '<td>'+(r.price?Number(r.price).toLocaleString():'')+'</td>'
      + '<td class="ord">'+(r.order||'')+'</td></tr>';
  }
  $('rows').innerHTML = html;
}
tick(); setInterval(tick, 5000);
</script>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    journal_path: str = "data/live/exposure-agent-activity.jsonl"
    policy_path: str = "data/models/local-exposure-agent-v1.json"

    def do_GET(self) -> None:
        if self.path.startswith("/api/state"):
            payload = json.dumps(
                build_state(
                    ActivityJournal(self.journal_path), Path(self.policy_path)
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
            body = AGENT_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        """Silence per-request logging; the agent's journal is the record."""


def serve(
    journal: str,
    policy: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
) -> ThreadingHTTPServer:
    handler = type(
        "BoundHandler", (_Handler,), {"journal_path": journal, "policy_path": policy}
    )
    return ThreadingHTTPServer((host, port), handler)


__all__ = ["AGENT_PAGE", "build_state", "serve", "stage_states"]
