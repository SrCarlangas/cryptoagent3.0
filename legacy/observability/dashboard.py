"""Zero-dependency live dashboard for the demo agent (stdlib http.server).

Serves:
  GET /            -> a self-refreshing HTML page
  GET /api/state   -> JSON summary derived from the activity journal

It only reads the journal file; it never trades or hits the network. Run it in a
separate process alongside the demo runner.
"""

from __future__ import annotations

import json
import mimetypes
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from btc_decision_agent.observability.floor import FLOOR_PAGE

from btc_decision_agent.observability.journal import ActivityJournal

D = Decimal
_STATIC_ROOT = Path(__file__).parent / "static" / "pixel-office"


def _entry_equity(entry: dict[str, Any]) -> Decimal | None:
    if entry.get("usdt_free") is None or entry.get("btc_qty") is None or entry.get("price") is None:
        return None
    usdt = D(entry["usdt_free"]) + D(entry.get("usdt_locked") or "0")
    return usdt + D(entry["btc_qty"]) * D(entry["price"])


def build_equity_series(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Strategy equity vs a buy&hold of the same starting capital at the first price.

    Buy&hold buys BTC once with the initial equity at the first observed price and
    holds; the strategy curve is the agent's real USDT+BTC*price at each evaluation.
    Both start at the same value so the comparison is apples to apples.
    """
    points: list[tuple[str, Decimal, Decimal]] = []
    initial_equity: Decimal | None = None
    initial_price: Decimal | None = None
    btc_hold: Decimal | None = None
    for entry in entries:
        equity = _entry_equity(entry)
        price = D(entry["price"]) if entry.get("price") is not None else None
        if equity is None or price is None or price <= 0:
            continue
        if initial_equity is None:
            initial_equity, initial_price = equity, price
            btc_hold = initial_equity / initial_price
        assert btc_hold is not None
        buy_hold = btc_hold * price
        points.append((entry["at"], equity, buy_hold))
    return [{"at": at, "strategy": format(s, "f"), "buy_hold": format(b, "f")} for at, s, b in points]


def build_floor(latest: dict[str, Any] | None) -> list[dict[str, str]]:
    """Map the latest evaluation to per-responsibility 'agent' activity states.

    Each responsibility is a character on the trading floor. Its status reflects
    what actually happened in the last evaluation (real data, not decoration):
      idle | working | alert | success
    """
    if latest is None:
        return [
            {"id": name, "status": "idle", "note": "waiting for first evaluation"}
            for name in ("sensor", "research", "policy", "risk", "execution", "ledger")
        ]
    action = latest.get("action", "HOLD")
    reason = latest.get("reason", "")
    has_order = bool(latest.get("order_side"))
    data_blocked = reason in {
        "DATA_BLOCKED",
        "DATA_STALE",
        "HISTORY_INSUFFICIENT",
        "BBO_MISSING",
        "SPREAD_TOO_WIDE",
    } or reason.startswith("DRY_RUN:DATA_BLOCKED")
    blocked_reasons = {
        "CAPITAL_INSUFFICIENT",
        "RESIDUAL_BELOW_MIN_NOTIONAL",
        "CONTEXT_INSUFFICIENT",
        "ORDER_NOT_FILLED",
        "POSITION_CHANGED",
    }

    sensor = "alert" if data_blocked else "working"
    research = "idle" if data_blocked else "working"  # SMAs computed each priced bar
    policy = "idle" if data_blocked else ("success" if action in ("ENTER_LONG", "EXIT_LONG") else "working")
    risk = "alert" if reason in blocked_reasons else ("working" if action in ("ENTER_LONG", "EXIT_LONG") else "idle")
    execution = "success" if has_order else ("alert" if reason in blocked_reasons else "idle")
    ledger = "working"  # every evaluation is journaled

    notes = {
        "sensor": "DATA_BLOCKED" if data_blocked else f"price {latest.get('price', '—')}",
        "research": (
            f"structural {latest.get('structural_confidence', latest.get('confidence', '—'))} · "
            f"tactical {latest.get('tactical_confidence', '—')} · "
            f"net edge {latest.get('expected_edge_bps', '—')} bps"
            if latest.get("confidence") is not None
            else f"fast {latest.get('fast_sma', '—')} / slow {latest.get('slow_sma', '—')}"
        ),
        "policy": f"{action} · {reason}",
        "risk": (
            ("blocked: " + reason)
            if reason in blocked_reasons
            else (
                f"allocation {latest.get('allocation_pct', '—')}%"
                if action in ("ENTER_LONG", "EXIT_LONG")
                else "monitoring"
            )
        ),
        "execution": (f"{latest.get('order_side')} {latest.get('order_quote_usdt', '')} @ {latest.get('order_avg_price', '')}") if has_order else "no order",
        "ledger": f"pos {latest.get('position_after') or latest.get('position_before', '—')}",
    }
    statuses = {"sensor": sensor, "research": research, "policy": policy, "risk": risk, "execution": execution, "ledger": ledger}
    return [{"id": name, "status": statuses[name], "note": notes[name]} for name in ("sensor", "research", "policy", "risk", "execution", "ledger")]


def build_state(journal: ActivityJournal, *, history: int = 50) -> dict[str, Any]:
    all_entries = journal.read()
    latest = all_entries[-1] if all_entries else None
    active_version = latest.get("confidence_model") if latest else None
    entries = (
        [entry for entry in all_entries if entry.get("confidence_model") == active_version]
        if active_version
        else all_entries
    )
    recent = entries[-history:]
    orders = [e for e in entries if e.get("order_side")]
    buys = [e for e in orders if e.get("order_side") == "BUY"]
    sells = [e for e in orders if e.get("order_side") == "SELL"]

    equity = None
    if latest is not None:
        latest_equity = _entry_equity(latest)
        equity = format(latest_equity, "f") if latest_equity is not None else None

    equity_series = build_equity_series(entries)
    strategy_vs_hold = None
    if len(equity_series) >= 2:
        first = equity_series[0]
        last = equity_series[-1]
        base = D(first["strategy"])
        if base > 0:
            strat_ret = (D(last["strategy"]) / base - D("1")) * D("100")
            hold_ret = (D(last["buy_hold"]) / base - D("1")) * D("100")
            strategy_vs_hold = {
                "strategy_return_pct": format(strat_ret, "f"),
                "buy_hold_return_pct": format(hold_ret, "f"),
                "excess_pct": format(strat_ret - hold_ret, "f"),
            }

    return {
        "floor": build_floor(latest),
        "equity_series": equity_series,
        "strategy_vs_hold": strategy_vs_hold,
        "generated_at": latest["at"] if latest else None,
        "venue": latest["venue"] if latest else None,
        "interval": latest["interval"] if latest else None,
        "position": (latest.get("position_after") or latest["position_before"]) if latest else None,
        "last_action": latest["action"] if latest else None,
        "last_reason": latest["reason"] if latest else None,
        "fast_sma": latest["fast_sma"] if latest else None,
        "slow_sma": latest["slow_sma"] if latest else None,
        "confidence": latest.get("confidence") if latest else None,
        "confidence_grade": latest.get("confidence_grade") if latest else None,
        "confidence_model": latest.get("confidence_model") if latest else None,
        "strategy_version": latest.get("strategy_version") if latest else None,
        "directional_model_version": latest.get("directional_model_version") if latest else None,
        "model_direction": latest.get("model_direction") if latest else None,
        "model_confidence": latest.get("model_confidence") if latest else None,
        "model_probabilities": latest.get("model_probabilities") if latest else None,
        "online_learning": latest.get("online_learning") if latest else None,
        "structural_confidence": latest.get("structural_confidence") if latest else None,
        "tactical_confidence": latest.get("tactical_confidence") if latest else None,
        "structural_return_bps": latest.get("structural_return_bps") if latest else None,
        "tactical_return_bps": latest.get("tactical_return_bps") if latest else None,
        "expected_edge_bps": latest.get("expected_edge_bps") if latest else None,
        "entry_price": latest.get("entry_price") if latest else None,
        "high_since_entry": latest.get("high_since_entry") if latest else None,
        "active_stop_price": latest.get("active_stop_price") if latest else None,
        "spread_bps": latest.get("spread_bps") if latest else None,
        "coverage": latest.get("coverage") if latest else None,
        "allocation_pct": latest.get("allocation_pct") if latest else None,
        "price": latest["price"] if latest else None,
        "usdt_free": latest["usdt_free"] if latest else None,
        "btc_qty": latest["btc_qty"] if latest else None,
        "btc_free": latest.get("btc_free") if latest else None,
        "btc_locked": latest.get("btc_locked") if latest else None,
        "usdt_locked": latest.get("usdt_locked") if latest else None,
        "protective_order_id": latest.get("protective_order_id") if latest else None,
        "risk_per_trade_pct": latest.get("risk_per_trade_pct") if latest else None,
        "breaker": latest.get("breaker") if latest else None,
        "equity_usdt": equity,
        "eval_count": len(entries),
        "total_eval_count": len(all_entries),
        "active_strategy_version": active_version,
        "order_count": len(orders),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "recent": list(reversed(recent)),
    }


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>BTC Decision Agent — Demo</title>
<style>
 :root{color-scheme:dark}
 body{margin:0;font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:#0d1117;color:#e6edf3}
 header{padding:16px 20px;border-bottom:1px solid #30363d;display:flex;justify-content:space-between;align-items:center}
 h1{font-size:16px;margin:0}
 .venue{font-size:12px;color:#7ee787;border:1px solid #238636;border-radius:6px;padding:2px 8px}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;padding:20px}
 .card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px}
 .k{font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:.05em}
 .v{font-size:20px;margin-top:4px}
 .long{color:#7ee787}.flat{color:#79c0ff}
 .enter{color:#7ee787}.exit{color:#ffa657}.hold{color:#8b949e}
 table{width:calc(100% - 40px);margin:0 20px 24px;border-collapse:collapse}
 th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #21262d;font-size:12px}
 th{color:#8b949e;font-weight:600}
 .muted{color:#8b949e}
 .chartwrap{margin:0 20px 8px;background:#161b22;border:1px solid #30363d;border-radius:10px;padding:12px}
 .charthead{display:flex;gap:16px;font-size:12px;color:#8b949e;margin-bottom:6px}
 .legend{display:flex;align-items:center;gap:6px}
 .dot{width:10px;height:10px;border-radius:2px;display:inline-block}
 .dot.strat{background:#7ee787}.dot.hold{background:#79c0ff}
 #chart{width:100%;height:260px;display:block}
 .pos{color:#7ee787}.neg{color:#ff7b72}
 footer{padding:0 20px 24px;color:#8b949e;font-size:12px}
</style></head>
<body>
<header><h1>BTC Decision Agent · <a href="/lab?build=v12" style="color:#7ee787">Geek Ops Lab V12 →</a></h1><span class="venue" id="venue">demo</span></header>
<div class="grid" id="cards"></div>
<div class="chartwrap">
 <div class="charthead"><span class="legend"><span class="dot strat"></span>strategy</span><span class="legend"><span class="dot hold"></span>buy &amp; hold</span></div>
 <svg id="chart" viewBox="0 0 1000 260" preserveAspectRatio="none"></svg>
</div>
<table><thead><tr><th>Time (UTC)</th><th>Pos</th><th>Action</th><th>Reason</th><th>Confidence</th><th>Edge bps</th><th>Price</th><th>Order</th></tr></thead>
<tbody id="rows"></tbody></table>
<footer>Auto-refresh every 5s · read-only view of the activity journal · demo funds only, no real capital.</footer>
<script>
 const fmt=(x)=> x==null?'—':(isNaN(x)?x:Number(x).toLocaleString(undefined,{maximumFractionDigits:2}));
 const cls=(a)=> a==='ENTER_LONG'?'enter':a==='EXIT_LONG'?'exit':'hold';
 async function tick(){
  try{
   const r=await fetch('/api/state');const s=await r.json();
   document.getElementById('venue').textContent=(s.venue||'demo').toLowerCase();
   const cards=[
    ['Position',`<span class="${s.position==='LONG'?'long':'flat'}">${s.position||'—'}</span>`],
    ['Last action',`<span class="${cls(s.last_action)}">${s.last_action||'—'}</span>`],
    ['Reason',`<span class="muted">${s.last_reason||'—'}</span>`],
    ['ML direction',s.model_direction==null?'—':`${s.model_direction} · ${fmt(Number(s.model_confidence)*100)}%`],
    ['ML version',s.directional_model_version||'—'],
    ['Online learning',s.online_learning?'enabled':'disabled'],
    ['BTC price',fmt(s.price)],
    ['Structural confidence',s.structural_confidence==null?'—':`${fmt(Number(s.structural_confidence)*100)}% · ${s.confidence_grade||'—'}`],
    ['Tactical confidence',s.tactical_confidence==null?'—':`${fmt(Number(s.tactical_confidence)*100)}%`],
    ['Net tactical edge',s.expected_edge_bps==null?'—':`${fmt(s.expected_edge_bps)} bps`],
    ['Active stop',fmt(s.active_stop_price)],
    ['Protective order',s.protective_order_id||'—'],
    ['Risk / trade',s.risk_per_trade_pct==null?'—':`${fmt(s.risk_per_trade_pct)}% equity`],
    ['Spread',s.spread_bps==null?'—':`${fmt(s.spread_bps)} bps`],
    ['Allocation',s.allocation_pct==null?'—':`${fmt(s.allocation_pct)}% of free USDT`],
    ['Fast SMA',fmt(s.fast_sma)],['Slow SMA',fmt(s.slow_sma)],
    ['USDT free',fmt(s.usdt_free)],['Equity (USDT)',fmt(s.equity_usdt)],
    ['Evaluations',fmt(s.eval_count)],['Orders',`${fmt(s.order_count)} (${fmt(s.buy_count)}B/${fmt(s.sell_count)}S)`],
    ['Interval',s.interval||'—'],['Updated',s.generated_at||'—'],
   ];
   const svh=s.strategy_vs_hold;
   if(svh){
     const ex=Number(svh.excess_pct);const c=ex>=0?'pos':'neg';const sign=ex>=0?'+':'';
     cards.push(['Strategy return',`${sign===''&&Number(svh.strategy_return_pct)>=0?'+':''}${fmt(svh.strategy_return_pct)}%`]);
     cards.push(['Buy & hold return',`${Number(svh.buy_hold_return_pct)>=0?'+':''}${fmt(svh.buy_hold_return_pct)}%`]);
     cards.push(['Excess vs hold',`<span class="${c}">${sign}${fmt(svh.excess_pct)}%</span>`]);
   }
   document.getElementById('cards').innerHTML=cards.map(([k,v])=>`<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
   drawChart(s.equity_series||[]);
   document.getElementById('rows').innerHTML=(s.recent||[]).map(e=>{
     const o=e.order_side?`${e.order_side} ${fmt(e.order_quote_usdt)} @ ${fmt(e.order_avg_price)}`:'—';
     const pos=e.position_after||e.position_before;
     const confidence=e.confidence==null?'—':`${fmt(Number(e.confidence)*100)}% ${e.confidence_grade||''}`;
     return `<tr><td>${e.at}</td><td>${pos}</td><td class="${cls(e.action)}">${e.action}</td><td class="muted">${e.reason}</td><td>${confidence}</td><td>${fmt(e.expected_edge_bps)}</td><td>${fmt(e.price)}</td><td>${o}</td></tr>`;
   }).join('');
  }catch(err){/* keep last view on transient errors */}
 }
 function drawChart(series){
  const svg=document.getElementById('chart');const W=1000,H=260,P=8;
  if(!series||series.length<2){svg.innerHTML=`<text x="12" y="24" fill="#8b949e" font-size="12">Not enough data yet — the equity curve appears after 2+ evaluations.</text>`;return;}
  const strat=series.map(p=>Number(p.strategy));const hold=series.map(p=>Number(p.buy_hold));
  const all=strat.concat(hold);let lo=Math.min(...all),hi=Math.max(...all);if(lo===hi){lo-=1;hi+=1;}
  const n=series.length;
  const x=i=> P + (W-2*P)*(i/(n-1));
  const y=v=> H-P - (H-2*P)*((v-lo)/(hi-lo));
  const path=arr=> arr.map((v,i)=>`${i===0?'M':'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  svg.innerHTML=`<path d="${path(hold)}" fill="none" stroke="#79c0ff" stroke-width="2"/>`+
                `<path d="${path(strat)}" fill="none" stroke="#7ee787" stroke-width="2"/>`;
 }
 tick();setInterval(tick,5000);
</script>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    journal: ActivityJournal

    def log_message(self, *args: Any) -> None:  # silence default logging
        return

    def do_GET(self) -> None:
        path_only = self.path.split("?", 1)[0]
        if path_only.startswith("/static/pixel-office/"):
            self._static(path_only.removeprefix("/static/pixel-office/"))
            return
        if path_only == "/api/state":
            payload = json.dumps(build_state(self.journal)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(payload)
            return
        if path_only in ("/", "/index.html"):
            self._html(_PAGE)
            return
        if path_only in ("/floor", "/floor.html", "/lab"):
            self._html(FLOOR_PAGE)
            return
        self.send_response(404)
        self.end_headers()

    def _static(self, relative_url: str) -> None:
        relative = Path(unquote(relative_url))
        if relative.is_absolute() or ".." in relative.parts:
            self.send_response(403)
            self.end_headers()
            return
        target = (_STATIC_ROOT / relative).resolve()
        if not target.is_relative_to(_STATIC_ROOT.resolve()) or not target.is_file():
            self.send_response(404)
            self.end_headers()
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, page: str) -> None:
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def serve(journal_path: str | Path, *, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    """Start the dashboard server bound to localhost by default."""
    handler = type("BoundHandler", (_Handler,), {"journal": ActivityJournal(journal_path)})
    server = ThreadingHTTPServer((host, port), handler)
    return server


__all__ = ["build_state", "serve"]
