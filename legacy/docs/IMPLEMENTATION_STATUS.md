# Estado de implementación — BTC Decision Agent

**Fecha:** 2026-09-15  
**Versión:** `0.1.0`  
**Runtime validado:** CPython 3.14.3 (`requires-python >=3.12,<3.15`)  
**Veredicto:** `IMPLEMENTED_FOR_OFFLINE_VALIDATION`

Este veredicto significa que los contratos, componentes, fixtures, replay y validaciones lógicas están implementados para trabajo offline reproducible. **No** afirma edge, rentabilidad, resultados OOS, calidad de fills reales, paper readiness ni live readiness; tampoco autoriza órdenes, credenciales o conexión a cuenta.

## Resultado ejecutivo

- 18/18 contratos normativos implementados con Pydantic v2, `Decimal`, UTC, enums cerrados, modelos frozen y JSON/SHA-256 canónicos.
- 10/10 responsabilidades separadas por dominio, aplicación, puertos y adapters.
- Pipeline fixture-first integrado: raw event → calidad → frame/contexto/costo → policy → riesgo → decisión → ledger.
- SM-001…SM-031, precedencia P0…P5, idempotencia, record-before-export y duplicate suppression implementados.
- S-01…S-09 normalizados desde fixtures públicos; red deshabilitada por defecto y sin endpoints privados.
- F-001…F-012, POL-000/POL-101/POL-102/POL-103, riesgo, replay, simulación conservadora y observabilidad implementados.
- Revisión semántica final: `APPROVED`, 0 issues (`semantic-review/2026-09-15-204048-pr-0.md`).

## Fases I–IX

| Fase | Estado | Evidencia principal |
|---|---|---|
| I — Base | PASS | `pyproject.toml`, `requirements.lock`, ADR-0001/0002, package importable |
| II — Dominio | PASS | `domain/contracts.py`, `state_machine.py`, `canonical.py`, ledger tests |
| III — Datos/calidad | PASS | `market_data.py`, `quality.py`, `book.py`, fixtures S-01…S-09 |
| IV — Features/costos | PASS | F-001…F-012 y `54.242622 bps` exactos |
| V — Policies | PASS_IMPLEMENTATION | NULL-01…12, PC-01…12, P101-T01…21; candidatas no validadas económicamente |
| VI — Riesgo | PASS | binding estado/portfolio/contexto/costo/mandatos, sizing y breakers |
| VII — Replay/simulador | PASS_OFFLINE | ledger byte-canónico; market/limit conservadores sin executor |
| VIII — Validación | PASS_LOGICAL | SC/BT/FMEA/red-team verdes; OOS no ejecutado |
| IX — Observabilidad | PASS | estado P/E/H, freshness, versiones, decisión, riesgo, costo y ledger |

## Definición de hecho

| Criterio explícito | Resultado | Evidencia |
|---|---|---|
| Todos los contratos normativos versionados | PASS | 18 importables; `docs/contracts-catalog.md` |
| Diez responsabilidades con ownership/tests | PASS | `application/services.py`, pipeline y suites por componente |
| Cero rutas Policy→Execution/RiskMandate | PASS | no existe execution port; policies sólo devuelven `CandidateIntent` |
| Transiciones/reasons deterministas | PASS | SM-001…031, P0…P5, property tests |
| 24 escenarios y 20 fronteras verdes | PASS | `test_normative_evidence.py`, `test_features_policies.py` |
| Tres ejemplos numéricos reproducibles | PASS | entrada, costo exacto `54.242622`, salida anchor/time/trend |
| Gap/stale/unknown nunca generan entrada | PASS | integración negativa y fault injection |
| Simulador no presume fills gratuitos | PASS | post-latency book, queue, price reach, partial/no-fill, fees y adverse selection |
| Ledger reconstruye cada decisión | PASS | manifest tipado, bindings frame/context/cost, hash chain, reload/collision tests |
| Type-check, lint y tests verdes | PASS | resultados en la sección Validación |
| Sin fallos críticos o TODOs de seguridad | PASS | búsqueda de TODO/FIXME/NotImplemented vacía; review final aprobado |
| Teoría/replay/OOS/paper/live diferenciados | PASS | sección Niveles de evidencia y reporte replay/OOS |
| Ninguna orden o credencial | PASS | denylist privada + test negativo; no executor ni network activation |

## Validación ejecutada

```text
pytest:      59 passed, 164 subtests passed
coverage:    86% total branch-aware
ruff:        All checks passed
mypy:        Success: no issues found in 26 source files
compileall:  PASS
pip check:   No broken requirements found
contracts:   18
exact cost:  54.242622 bps
wheel:       dist/btc_decision_agent-0.1.0-py3-none-any.whl
wheel SHA256: 75bb318a0a05ddeaa72de4a1039e8ac58cd9c1986cd845043a881bc4eb38d0d7
```

Comandos reproducibles:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e .
.venv/bin/pytest -q --cov=btc_decision_agent --cov-report=term
.venv/bin/ruff check src tests
.venv/bin/mypy src
```

## Niveles de evidencia

| Nivel | Estado | Qué demuestra |
|---|---|---|
| Teoría/contratos | PASS | totalidad, causalidad, safety, fórmulas e invariantes |
| Fixtures/integración | PASS | pipeline offline y fallos seguros observables |
| Replay determinista | PASS | mismo input/version/reloj ⇒ JSONL y hash chain byte-idénticos |
| OOS | NOT_RUN | no existe dataset histórico versionado; no se abre el conjunto de prueba |
| Paper conectado | NOT_RUN / OUT_OF_SCOPE | no cuenta, red privada, órdenes ni feedback autoritativo |
| Live | PROHIBITED / OUT_OF_SCOPE | requiere ciclo y autorización humana independientes |

## Decisiones aplicadas

- D-001: Spot BTC/USDT, LONG/FLAT, sin apalancamiento.
- D-002: `H_decision=1h`, `H_context=720` barras; estrategia sólo con barras FINAL.
- D-003: perfil conceptual 10,000 USDT; riesgo 0.25%, exposición 10%, pérdida diaria 0.75%, drawdown 5%.
- D-009: gate OOS congelado, no ejecutado.
- D-014: freshness/clock budgets congelados para fixtures/replay.
- D-011: Python/asyncio/Pydantic/pytest-Hypothesis/puertos-adapters/JSONL local.

Defaults rechazados: Margin/Futures/SHORT, float monetario, costo unknown=0, fill al mid/completo, barra forming, último L2 tras gap, entrada sin mandato/verdict, optimización OOS y red privada.

## Policies y hallazgos

- `POL-000-NULL-HOLD`: control implementado.
- `POL-101`: implementación primaria completa, `CANDIDATE_UNVALIDATED`.
- `POL-102` y `POL-103`: challengers completos a nivel contractual, `CANDIDATE_UNVALIDATED`.
- Policies aprobadas/rechazadas económicamente: **ninguna**; no se ejecutó OOS.
- L2 direccional autónomo: rechazado por D-007; sólo calidad/costo/veto/diagnóstico.

## Riesgos residuales y trabajo futuro

1. Conseguir y versionar un dataset histórico causal con cobertura/calidad suficientes.
2. Validar D-014 con latencias observadas sin mover el gate del experimento activo.
3. Ejecutar walk-forward purgado/embargado y D-009 en un ciclo autorizado separado.
4. Calibrar fees, impacto, queue y adverse selection con evidencia, no defaults.
5. Sólo después de PASS OOS: diseñar shadow/paper conectado con feedback autoritativo y revisión humana.
6. El adapter de red pública permanece descriptivo y deshabilitado; activarlo exige nueva validación operacional.

No hay blockers lógicos abiertos para validación offline. Los puntos anteriores son blockers de promoción empírica/operacional, no defectos ocultos de esta entrega.

## Artefactos

- Código: `src/btc_decision_agent/`
- Tests/fixtures: `tests/`
- Configuración/lock: `pyproject.toml`, `requirements.lock`, `.gitignore`
- ADRs: `docs/adr/0001-stack-and-persistence.md`, `docs/adr/0002-conservative-human-gate.md`
- Arquitectura: `docs/implemented-architecture.md`
- Contratos: `docs/contracts-catalog.md`
- Evidencia: `docs/executable-evidence-matrix.md`
- Replay/OOS: `docs/replay-and-oos-report.md`
- Runbook: `docs/offline-runbook.md`
- Estado: `IMPLEMENTATION_STATUS.md`

**Veredicto final: `IMPLEMENTED_FOR_OFFLINE_VALIDATION`.**
