# Runbook — agente event-driven en Binance DEMO

**Venue de ejecución:** `https://demo-api.binance.com` (fondos ficticios).  
**Market data:** stream público `wss://data-stream.binance.vision`.  
El capital real continúa bloqueado por código.

## Preparación

```bash
cd /Users/carlosrojas/Oracle/cryptoagent3.0
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e .
set -a; source .env; set +a
```

## Qué cambió

`scripts.run_demo` ya no puede colocar órdenes. Se retiró la operación mediante loops separados 4h/1d porque ambos podían controlar la misma cuenta y producir churn.

El único propietario de órdenes es `scripts.run_realtime_demo`:

1. Observa continuamente aggTrades, BBO y actualizaciones/cierres de kline 1m por WebSocket.
2. Mantiene evidencia desde 5 minutos hasta 30 días, con bootstrap REST de 1m y 1h.
3. Evalúa cuando llegan eventos, no por un reloj 4h/1d.
4. Exige calidad, cobertura y spread antes de consultar la dirección local; después conserva persistencia y estado de cuenta coherente como vetos.
5. Usa el softmax local BUY/HOLD/SELL como fuente final de dirección, sin permitirle definir sizing ni ejecución.
6. Aplica cooldown, stop inicial, break-even, trailing stop y breakers con precedencia sobre el modelo.
7. Usa un lock exclusivo: no pueden existir dos autoridades de órdenes.
8. Usa un `newClientOrderId` determinista y consulta la orden ante un resultado ambiguo.
9. Reconcilia saldos antes de ordenar y después del fill.

`LOCAL-SOFTMAX-BTC-1H-4H-V1` consume evidencia tabular multi-fuente del snapshot runtime. No es un modelo visual ni debe llamarse “multimodal visual”. La evidencia structural/tactical sigue alimentando features y gates de calidad, pero ya no decide la intención final mediante umbrales heurísticos. Consulta [local-ml-agent.md](local-ml-agent.md) para entrenamiento, schema, holdout y limitaciones históricas.

El estado protector se guarda atómicamente en `data/live/realtime-engine-state.json`: precio de entrada, máximo desde entrada, cooldown, breakers y candidato sobreviven reinicios. Si no existe checkpoint, el agente recupera entrada y high-water desde el journal.

Las órdenes estratégicas usan un ledger SQLite WAL (`data/live/realtime-execution-intents.sqlite3`): el intent se confirma en disco antes del POST y cualquier intent no terminal se resuelve contra Binance durante el arranque antes de habilitar decisiones.

Una posición LONG mantiene una orden `STOP_LOSS` market directamente en Binance DEMO. Esta protección sigue activa aunque el proceso o el servidor estén caídos. Al ejecutar una salida táctica, el agente cancela primero la protección, reconcilia free+locked y luego vende. Los filtros de precio, lot y notional se leen de `exchangeInfo`, no de constantes.

## Sizing dinámico

Cada BUY queda limitado simultáneamente por el porcentaje de efectivo y la pérdida máxima en el stop:

```text
por_efectivo = usdt_free × allocation_pct / 100
por_riesgo   = equity × risk_per_trade_pct / stop_loss_pct
quote_usdt   = floor(min(por_efectivo, por_riesgo), 0.01)
```

Los defaults son **80% de allocation** y **2% de equity en riesgo** con stop de 3%. Con 4,500 USDT, el cap de efectivo sería 3,600 pero el cap de riesgo sería 3,000; se compran 3,000. No existe un notional fijo.

Cada SELL intenta liquidar todo el BTC libre, redondeado hacia abajo al step configurado, para reducir residuos.

## Shadow/dry-run recomendado

```bash
set -a; source .env; set +a
.venv/bin/python -m scripts.run_realtime_demo --dry-run --allocation-pct 80 \
  --model-path data/models/local-softmax-v1.json --no-online-learning \
  --allow-unpromoted-model
```

Observa datos reales y registra decisiones, pero no coloca órdenes.

## Ejecutar órdenes en DEMO

Sólo un artefacto con `promotion_status=PROMOTED` puede llegar a órdenes. El modelo generado actualmente quedó `REJECTED` por el holdout, así que este comando fallará cerrado hasta obtener un entrenamiento promovido; `--allow-unpromoted-model` está restringido por código a dry-run.

```bash
set -a; source .env; set +a
.venv/bin/python -m scripts.run_realtime_demo \
  --i-understand-this-is-demo \
  --allocation-pct 80 \
  --model-path data/models/local-softmax-v1.json
```

Parámetros principales:

```text
--allocation-pct 80
--buy-confidence 0.72
--sell-confidence 0.42
--buy-persistence-seconds 120
--sell-persistence-seconds 180
--cooldown-seconds 3600
--model-path data/models/local-softmax-v1.json
--online-learning / --no-online-learning
--risk-per-trade-pct 2
--daily-loss-pct 5
--max-drawdown-pct 10
```

La entrada se arma únicamente cuando el modelo predice `BUY`; la salida estratégica, cuando predice `SELL`. Ambas exigen persistencia continua (120/180 segundos por defecto). Una interrupción mayor a 15 segundos reinicia esa confirmación. `HOLD` o una dirección incompatible con la posición actual no ordenan. El trailing de 2.5% se activa después de una excursión favorable de 1%; break-even se activa en 0.5% y antes gobierna el stop inicial de 3%. Breakers y stops dominan siempre la salida del modelo.

## Dashboard

```bash
.venv/bin/python -m scripts.run_dashboard --port 8787
# http://127.0.0.1:8787
# Agent Office: http://127.0.0.1:8787/floor
```

El journal por defecto es `data/live/realtime-demo-activity.jsonl`. El dashboard muestra posición post-fill, confianza, edge esperado, spread, porcentaje asignado, equity y órdenes.

## Validación corta

```bash
set -a; source .env; set +a
.venv/bin/python -m scripts.run_realtime_demo \
  --dry-run --max-events 20 \
  --journal data/live/realtime-smoke.jsonl \
  --lock-file data/live/realtime-smoke.lock
```

## Parar y recuperar

Usa `Ctrl+C`. Al reiniciar, el agente reconstruye la posición desde Binance DEMO y vuelve a cargar historia para su estado multi-escala. Si otro proceso conserva el lock, el segundo aborta sin operar.

## Límites

- Solo DEMO/testnet; `BINANCE_EXECUTION_VENUE=REAL` está bloqueado.
- Credenciales únicamente por entorno; `.env` no se registra.
- No hay retiros.
- Datos stale, BBO ausente, spread alto o historia insuficiente producen HOLD.
- Una señal experimental no autoriza capital real.
