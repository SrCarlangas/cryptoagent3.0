# Matriz de evidencia ejecutable

Fecha de implementación: 2026-09-15. La evidencia es fixture-first, offline,
sintética y determinista. No usa red, credenciales, cuentas o executor; no contiene
OOS real, paper, testnet, live, edge ni claims de rentabilidad.

| Obligación | Código | Evidencia de comportamiento |
|---|---|---|
| Contratos/canonical SHA-256 | `domain/contracts.py`, `domain/canonical.py` | `test_contracts_state.py`, `test_contract_enrichment.py` |
| SM-001..031 y P0..P5 | `domain/state_machine.py`, `application/decision.py` | properties + negativos de autoridad en `test_pipeline_replay.py` |
| S-01..S-09 fixture-first | `adapters/market_data.py` | `test_market_l2.py` + fixture público versionado; adapter de red permanece descriptivo/deshabilitado |
| Watermark/bar causal | `adapters/quality.py` | progreso real, late sólo tras watermark previo, quality/gap impiden FINAL |
| L2 monotónico/revocable | `adapters/book.py` | gap y regresión event/observed time bloquean y revocan publicación |
| F-001..F-012 | `domain/features.py` | numéricos y negativos de barra forming/blocked/futura/discontinua; BBO F-008 conserva event ID y clock real aunque anteceda la frontera |
| NULL/POL-101/POL-102/POL-103 | `policies/core.py` | totalidad, cost cap, régimen, timeout, falling knife; costo unknown en LONG sale para ambos challengers y POL-103 usa false break relativo buffer−fail |
| Risk binding | `domain/risk.py`, `application/decision.py` | intent/state/portfolio/context/cost/mandates stale o mismatch nunca entran; costo causal `as_of_time <= decision_time` sólo si context/cost comparten frame calificado |
| Ledger completo/idempotente | `adapters/ledger.py`, `application/services.py` | manifest real; COMPLETE exige frame_ref de context/cost y provenance de inputs contenida en frame; negativo de frame ajeno, hash interno, cadena, reload, collision y duplicate suppressed |
| Pipeline Sensor→Ledger | `application/offline_pipeline.py` | `test_offline_pipeline.py`: entrada, BBO 500 ms anterior, historia de 0/1 barras con COMPLETE, stale, gap, restart/unknown y duplicate no bloqueante |
| Replay byte-canónico real | pipeline + ledger | dos directorios separados producen JSONL idéntico byte a byte y hash chain idéntica |
| Market/Limit conservador | `simulation/fills.py` | BUY/SELL, post-latency, LIVE/fresh, side-aware reach/traded-through, queue, partial/no-fill/cancel y generation mismatch |
| Observabilidad versionada | `observability/snapshot.py` | product/risk/policy/context, freshness, autorización, costo y reconciliación en `test_observability.py` |
| 54.242622 bps | `round_trip_cost` | ejemplo Decimal exacto en `test_features_policies.py` |
| 24 SC / 20 BT / 14 FMEA / 10 red-team | componentes y hard gates | catálogos existentes reforzados por negativos dedicados e integración end-to-end; no sustituyen OOS |
| purga/embargo y D-009 | `validation/offline.py` | pruebas unitarias con muestras/métricas sintéticas; no validación OOS |
| ausencia de private/live | allowlist + adapter disabled | `test_public_adapter_disabled_and_no_private_paths` |

## Estado de evidencia

Comandos normativos:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
```

La integración completa focaliza POL-101 y conserva la interfaz de policies
intercambiables. POL-102/POL-103 están cubiertas como máquinas deterministas, pero
ninguna policy está validada económicamente. D-009 está congelada sólo como contrato
futuro; no existe dataset histórico versionado y no se ejecuta OOS.

## Cierre de validación

Snapshot final validado en CPython 3.14.3:

- pytest: **59 passed, 164 subtests passed**;
- cobertura branch-aware: **86%**;
- Ruff: **All checks passed**;
- mypy strict: **26 source files, 0 issues**;
- compileall/pip check/build wheel: **PASS**;
- revisión semántica final: **APPROVED, 0 issues**;
- 18 contratos importables y costo exacto **54.242622 bps**.

Ver `IMPLEMENTATION_STATUS.md` y `docs/replay-and-oos-report.md`. Estos resultados
validan implementación offline; no constituyen evidencia OOS, paper o live.
