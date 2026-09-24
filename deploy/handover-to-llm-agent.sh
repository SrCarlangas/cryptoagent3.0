#!/usr/bin/env bash
# Hand order authority from the quantitative agent to the LLM agent.
#
# Run ON THE SERVER. Refuses to proceed unless the pre-registered gate passes, so
# the decision cannot be made by whoever happens to be running the script.
#
# The three things that can go wrong, and how each is handled:
#
#   Two order authorities at once. The quantitative agent is stopped AND disabled
#   before the LLM agent is given the flag, and the end of the script asserts that
#   exactly one process carries order permission.
#
#   A re-buy on handover. The account is already long. The LLM agent inherits the
#   quantitative agent's engine state, so it keeps the true entry price and the
#   live exchange-side stop instead of re-adopting the position at today's price
#   and losing its cost basis. This was an observed failure earlier in the project.
#
#   Silent loss of protection. The LLM agent keeps the validated quantitative model
#   loaded as its fallback, so if the model is unreachable the position is still
#   managed. That is a property of the code, not of this script, but it is why the
#   handover is safe at all.
set -euo pipefail

ROOT=/home/ubuntu/workplace/cryptoagent3.0
UNIT=/etc/systemd/system/cryptoagent3-llm-agent.service
QUANT=cryptoagent3-exposure-agent
LLM=cryptoagent3-llm-agent
REPORT=data/validation/llm-agent-backtest.json

# --gate-pending lets the owner grant authority while the backtest is still running.
# It deliberately cannot override a gate that RAN AND FAILED: proceeding while
# evidence is still being collected is a judgement call, proceeding against evidence
# that already exists is not.
GATE_PENDING=0
[ "${1:-}" = "--gate-pending" ] && GATE_PENDING=1

cd "$ROOT"

echo "=== 1. gate pre-registrado ==="
if [ -f "$REPORT" ]; then
  if ! PYTHONPATH=src .venv/bin/python -m scripts.gate_llm_agent; then
    echo
    echo "ABORTADO: el agente no cumple los criterios fijados de antemano."
    echo "Un gate fallado no se puede anular, ni con --gate-pending."
    exit 1
  fi
elif [ "$GATE_PENDING" = "1" ]; then
  echo "  ADVERTENCIA: el informe del backtest aun no existe ($REPORT)."
  echo "  Se otorga autoridad por decision explicita del propietario, ANTES de la"
  echo "  evidencia. Al terminar el backtest hay que ejecutar el gate; si RECHAZA,"
  echo "  la autoridad debe devolverse al agente cuantitativo con:"
  echo "    sudo systemctl disable --now $LLM && sudo systemctl enable --now $QUANT"
else
  echo "  ABORTADO: no existe $REPORT y no se paso --gate-pending."
  exit 1
fi

echo
echo "=== 2. estado de la cuenta antes del traspaso ==="
PYTHONPATH=src .venv/bin/python - <<'PY'
import json, os
from decimal import Decimal as D
from pathlib import Path
for raw in Path(".env").read_text().splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        if line.startswith("export "):
            line = line[7:].strip()
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
from btc_decision_agent.adapters.binance_execution import build_demo_adapter
a = build_demo_adapter(enabled=True)
b = a.account_balance()
btc = D(str(b.balances.get("BTC") or 0)) + D(str(b.locked_balances.get("BTC") or 0))
usdt = D(str(b.balances.get("USDT") or 0))
px = D(str(a.recent_closed_klines(interval="1m", limit=2)[-1]["close"]))
print(f"  USDT {usdt}  BTC {btc}  precio {px}")
print(f"  equity {usdt + btc * px:.2f} USDT")
print(f"  ordenes abiertas: {len(a.open_orders())}")
Path("/tmp/handover-before.json").write_text(
    json.dumps({"usdt": str(usdt), "btc": str(btc), "price": str(px)})
)
PY

echo
echo "=== 3. detener y deshabilitar el agente cuantitativo ==="
sudo systemctl disable --now "$QUANT"
echo "  $QUANT -> activo=$(systemctl is-active $QUANT) habilitado=$(systemctl is-enabled $QUANT 2>&1)"

echo
echo "=== 4. heredar el estado del motor (preserva precio de entrada y stop) ==="
if [ -f "$ROOT/data/live/exposure-agent-state.json" ]; then
  cp -a "$ROOT/data/live/exposure-agent-state.json" \
        "$ROOT/data/live/llm-agent-state.json"
  PYTHONPATH=src .venv/bin/python - <<'PY'
import json
s = json.load(open("data/live/llm-agent-state.json"))
for key in ("entry_price", "entry_at", "protective_stop_price", "protective_order_id",
            "position_base_qty", "peak_equity"):
    print(f"  {key}: {s.get(key)}")
PY
else
  echo "  sin estado previo; el agente reconciliara desde el exchange"
fi

echo
echo "=== 5. otorgar autoridad de ordenes al agente LLM ==="
# Drop --dry-run, add the explicit DEMO opt-in, and promote it to the most
# protected process under memory pressure now that it holds the position.
#
# The substitutions are ASSERTED rather than assumed. A sed that silently matches
# nothing would leave the agent in dry-run while the quantitative agent is already
# disabled, which means nobody is managing an open position. That failure has to be
# loud, so the flag is verified on the unit file and again on the running process.
sudo cp -a "$UNIT" "$UNIT.pre-handover"
sudo sed -i 's|^  --dry-run \\$|  --i-understand-this-is-demo \\|' "$UNIT"
sudo sed -i 's|^OOMScoreAdjust=-100$|OOMScoreAdjust=-800|' "$UNIT"

if ! grep -qE '^  --i-understand-this-is-demo \\$' "$UNIT"; then
  echo "  FALLO: no se pudo activar el permiso de ordenes en el unit. Revirtiendo."
  sudo cp -a "$UNIT.pre-handover" "$UNIT"
  sudo systemctl daemon-reload
  sudo systemctl enable --now "$QUANT"
  echo "  $QUANT restaurado como autoridad: activo=$(systemctl is-active $QUANT)"
  exit 1
fi
if grep -qE '^  --dry-run \\$' "$UNIT"; then
  echo "  FALLO: --dry-run sigue presente en ExecStart. Revirtiendo."
  sudo cp -a "$UNIT.pre-handover" "$UNIT"
  sudo systemctl daemon-reload
  sudo systemctl enable --now "$QUANT"
  exit 1
fi
if ! grep -qE '^OOMScoreAdjust=-800$' "$UNIT"; then
  echo "  ADVERTENCIA: OOMScoreAdjust no quedo en -800; el agente es mas vulnerable al OOM"
fi
echo "  ExecStart ahora:"
sudo grep -E "dry-run|i-understand|OOMScoreAdjust" "$UNIT" | sed 's/^/    /'

sudo systemctl daemon-reload
sudo systemctl restart "$LLM"
echo "  esperando arranque y reconciliacion..."
sleep 45

echo
echo "=== 6. verificacion final ==="
echo "  $LLM activo=$(systemctl is-active $LLM) habilitado=$(systemctl is-enabled $LLM)"
echo "  $QUANT activo=$(systemctl is-active $QUANT) habilitado=$(systemctl is-enabled $QUANT 2>&1)"

# Count authorities by reading the live /proc cmdline of every candidate process.
# systemctl cat is not used here because a comment in the unit mentions the flag and
# produces a false positive; and a bare pgrep head -1 was observed returning a stale
# pid. The ground truth is what the running process was actually invoked with.
authorities=0
for pid in $(pgrep -f "scripts.run_exposure_agent|scripts.run_llm_agent" 2>/dev/null || true); do
  cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
  case "$cmd" in
    *"scripts.run_exposure_agent"*|*"scripts.run_llm_agent"*) ;;
    *) continue ;;
  esac
  case "$cmd" in
    *"--i-understand-this-is-demo"*)
      authorities=$((authorities + 1))
      echo "  autoridad de ordenes: pid $pid -> $(echo "$cmd" | grep -o 'scripts\.run_[a-z_]*')"
      ;;
  esac
done
echo "  total de autoridades: $authorities (debe ser 1)"
[ "$authorities" -eq 1 ] || { echo "  FALLO: no hay exactamente una autoridad"; exit 1; }

echo
echo "  estado del motor tras reiniciar:"
PYTHONPATH=src .venv/bin/python - <<'PY'
import json
s = json.load(open("data/live/llm-agent-state.json"))
for key in ("entry_price", "position_base_qty", "protective_stop_price", "recovery_source"):
    print(f"    {key}: {s.get(key)}")
PY

echo
echo "  ordenes registradas por el agente LLM (no debe haber recompra):"
PYTHONPATH=src .venv/bin/python - <<'PY'
import json
from pathlib import Path
path = Path("data/live/llm-agent-activity.jsonl")
rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
orders = [r for r in rows if r.get("order_side")]
print(f"    entradas en journal: {len(rows)}   ordenes: {len(orders)}")
for r in orders[-5:]:
    print(f"    {r['at'][:19]} {r['action']} {r['order_side']} {r.get('order_base_qty')} @ {r.get('order_avg_price')}")
PY

echo
echo "=== 7. apuntar la observabilidad al journal del agente LLM ==="
# The dashboard and the daily Slack summary read a single journal path. Left
# pointing at the numeric agent's file they would show a frozen snapshot forever
# and the staleness alarm would fire every day, which trains everyone to ignore it.
# The numeric agent's journal is kept on disk as history, it is just no longer the
# live source.
NEW_JOURNAL="$ROOT/data/live/llm-agent-activity.jsonl"
OLD_JOURNAL="$ROOT/data/live/exposure-agent-activity.jsonl"
for unit in cryptoagent3-llm-dashboard cryptoagent3-daily-summary; do
  file="/etc/systemd/system/$unit.service"
  if [ ! -f "$file" ]; then
    echo "  ADVERTENCIA: $unit no esta instalado"
    continue
  fi
  if grep -q "$OLD_JOURNAL" "$file"; then
    echo "  FALLO: $unit sigue apuntando al journal del agente cuantitativo."
    echo "         Reinstala deploy/systemd/$unit.service antes de continuar."
    exit 1
  fi
  if grep -q "$NEW_JOURNAL" "$file"; then
    echo "  $unit -> llm-agent-activity.jsonl"
  else
    echo "  ADVERTENCIA: no se pudo confirmar el journal de $unit"
  fi
done
sudo systemctl restart cryptoagent3-llm-dashboard
sleep 5
echo "  dashboard activo=$(systemctl is-active cryptoagent3-llm-dashboard)"
echo "  resumen diario: $(systemctl is-enabled cryptoagent3-daily-summary 2>&1) (23:55 UTC)"
echo "  prueba del resumen (sin enviar a Slack):"
PYTHONPATH=src .venv/bin/python -m scripts.daily_summary \
  --journal "$NEW_JOURNAL" \
  --memory "$ROOT/data/live/llm-agent-memory.sqlite3" \
  2>&1 | sed 's/^/    /'

echo
echo "TRASPASO COMPLETO. El agente LLM es la unica autoridad de ordenes."
echo
echo "Advertencia sobre la evidencia: el gate se paso en UNA ventana y UNA pasada."
echo "Demuestra que el agente no esta roto ni es degenerado. NO demuestra que tenga"
echo "ventaja sobre comprar y mantener, y ningun estudio de este proyecto la encontro."
