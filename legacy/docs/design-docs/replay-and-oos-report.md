# Reporte de replay determinista y gate OOS

**Fecha:** 2026-09-15  
**Alcance:** fixtures y validación offline; sin red, cuenta, credenciales u órdenes

## Replay

### Procedimiento

1. Se construye el mismo `OfflinePipelineRequest` versionado con fixtures sintéticos.
2. Cada ejecución usa un ledger JSONL nuevo en directorios separados.
3. El pipeline recorre Sensor → Guardia → Frame/Context/Cost → POL-101 → Gobernador → Máquina → Ledger.
4. Se comparan Decision, `record_hash`, bytes JSONL y registro recargado.

### Resultado

`PASS`:

- mismo input, versiones y reloj produce el mismo `decision_id`;
- los dos ledgers son idénticos byte a byte;
- la hash chain y `record_hash` coinciden;
- invertir el orden de entrada del motor genérico conserva el orden determinista por `observed_at/event_time/identity`;
- repetir una decisión accionable no genera segunda exportación: `DUPLICATE_SUPPRESSED`;
- late correction no muta una decisión histórica;
- manifests con frame/context/costo no relacionados son rechazados antes de persistir.

Evidencia:

- `tests/test_offline_pipeline.py::test_complete_pipeline_replay_produces_identical_ledger_bytes`
- `tests/test_replay_engine.py`
- `tests/test_pipeline_replay.py`
- `src/btc_decision_agent/replay/engine.py`
- `src/btc_decision_agent/adapters/ledger.py`

## Gate OOS D-009

### Estado

`FROZEN_NOT_EXECUTED`.

El gate está pre-registrado por ADR-0002 y el decision log, pero no se abrió ningún dataset OOS. El evaluador se prueba sólo con métricas sintéticas para verificar que no relaja ni muta umbrales.

### Umbrales congelados

- episodios independientes `n_min = 100`;
- `delta_utility >= 0.01` sobre capital frente a `NULL_HOLD`;
- folds positivos `>= 0.70`;
- `PBO < 0.20`;
- cero breaches de pérdida diaria/drawdown;
- vecinos HIGH positivos y degradación mediana `<= 0.25`;
- coverage entre `0.01` y `0.30`;
- gross debe superar costo + incertidumbre bajo escenario ADVERSE.

### Resultado económico

No disponible. Por tanto:

- POL-101: `CANDIDATE_UNVALIDATED`;
- POL-102: `CANDIDATE_UNVALIDATED`;
- POL-103: `CANDIDATE_UNVALIDATED`;
- no hay policy ganadora, aprobada o rechazada económicamente;
- no existe claim de edge, retorno, drawdown empírico, PBO observado o harvestability.

### Condiciones antes de ejecutar OOS

1. Dataset histórico inmutable/versionado con event time, observed time, provenance, watermarks y calidad.
2. Search spaces y budgets train-only congelados para todas las candidatas.
3. Splits walk-forward, purga y embargo registrados antes de outcomes.
4. Cost/fill scenarios y D-014 versionados para el experimento.
5. Mismo estado inicial, RiskMandate, overlay protector y reloj para policies y `NULL_HOLD`.
6. Autorización humana separada para abrir el conjunto de prueba.

Un fallo del gate producirá `POLICY_FAIL`/`NO_GO` para la hipótesis; no se ajustarán umbrales para rescatarla.

## Paper y live

- Paper conectado: `NOT_RUN`, fuera de esta entrega.
- Testnet/live: `PROHIBITED`, sin executor, credenciales ni endpoints privados.
- La simulación local de fills es evidencia mecánica conservadora, no paper trading ni resultado económico.

**Conclusión:** replay determinista `PASS`; OOS `FROZEN_NOT_EXECUTED`; promoción operacional no autorizada.

## Actualización: OOS ejecutado (2026-09-16)

El estado `FROZEN_NOT_EXECUTED` fue superado. Se construyó y congeló un dataset
histórico real (BTC/USDT 1h, 2020-01-01 → 2026-09-16, `dataset_id sha256:53938d3d…`)
vía backfill público de solo lectura, y se ejecutó el gate D-009 sobre POL-101 con
parámetros pre-registrados.

Resultado: **`NO_GO` para POL-101 (`p101/1`)** — 6 episodios, edge bruto 24.84 bps < 64.24 bps
de costo, ΔU neta negativa; el gate falla 7 criterios. No se recalibró contra el test set.
Detalle completo en `docs/oos-run-report.md`. Sigue sin haber claim de edge, paper o live.
