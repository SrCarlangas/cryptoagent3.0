# Runbook fixture-first offline

## Reglas de seguridad

- No configurar red, claves, firma, cuenta, trading, testnet, paper o live.
- No habilitar `PublicMarketDataAdapter`; sólo se validan fixtures versionados.
- No usar endpoints privados ni producir requests de ejecución.
- `SimulatedFill` es aritmética local sobre observaciones sintéticas, no paper trading.
- Un PASS técnico no implica edge, rentabilidad ni readiness live.

## Validación

Desde la raíz, con dependencias ya instaladas y sin realizar I/O externo:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
```

## Pipeline y replay

1. Construir `RawMarketEvent` desde fixtures inmutables.
2. Crear `JsonlDecisionLedger` en un directorio temporal/local nuevo.
3. Ejecutar `OfflineDecisionService.evaluate(OfflinePipelineRequest(...))`.
4. Comprobar `export.status`: `EXPORTED` sólo para append nuevo y completo;
   `DUPLICATE_SUPPRESSED` para la identidad ya registrada.
5. Repetir la corrida en otro directorio con los mismos inputs/versiones/reloj.
6. Comparar bytes de ambos JSONL y recargar ambos ledgers para verificar la cadena.

El replay no reutiliza una Decision expirada ni muta registros por late correction.

## Ledger

El ledger recibe contratos inmutables, no mapas de hashes del caller. Calcula hashes
internamente y exige manifest según acción/disposition. Para `ENTER_LONG` requiere
frame, contexto, costo, intent, Product/RiskMandate, portfolio, system state y
RiskVerdict. Un manifest incompleto, binding mismatch, collision o cadena rota
detiene exportación.

## Simulación local de fills

- Market: aportar `BookObservation` posterior a latencia con generation,
  `LIVE/FRESH/QUALIFIED` y provenance; se camina depth visible.
- Limit: aportar book y `TradeObservation` de la misma generación. BUY requiere
  trades `price <= limit`; SELL, `price >= limit`; traded-through debe superar
  queue-ahead.
- Sin evidencia de reach/queue hay `NO_FILL`; partial/cancel, fees y adverse
  selection permanecen explícitos.

## Fuera de alcance

`prepare_walk_forward` y `evaluate_frozen_gate` sólo tienen pruebas sintéticas. No
existe dataset histórico versionado; por tanto no se ejecuta ni reporta OOS. Tampoco
se ejecutan paper, testnet, live, ingestión pública realtime o integración de cuenta.

## Recuperación

- Stale/gap: Decision `HOLD/BLOCKED`; L2 revoca y exige generación nueva.
- Restart sin observación autoritativa: `UNKNOWN/IDLE/BLOCKED`.
- Late correction: conservar evidencia, no reescribir Decision histórica.
- Ledger mismatch/collision: detener exportación y conservar archivo para auditoría.
