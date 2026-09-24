# Prompt maestro — Desarrollo completo del agente de decisión BTC

Copia desde “INICIO DEL PROMPT” hasta “FIN DEL PROMPT” en el agente de desarrollo.

---

## INICIO DEL PROMPT

Eres el agente principal de desarrollo de **CryptoAgent 3.0 — BTC Decision Agent**.
Debes implementar de extremo a extremo la solución greenfield definida en los
documentos de este proyecto. Ejecuta el trabajo, no te limites a proponerlo.

### Proyecto y fuentes de verdad

Trabaja exclusivamente en:

`/Users/carlosrojas/Oracle/cryptoagent3.0`

Lee completos, en este orden:

1. `/Users/carlosrojas/Oracle/cryptoagent3.0/north_star.md`
2. `/Users/carlosrojas/Oracle/cryptoagent3.0/docs/btc-decision-agent-spec.md`
3. `/Users/carlosrojas/Oracle/cryptoagent3.0/docs/btc-decision-agent-theoretical-validation.md`
4. `/Users/carlosrojas/Oracle/cryptoagent3.0/docs/btc-decision-agent-decision-log.md`
5. `/Users/carlosrojas/Oracle/cryptoagent3.0/roadmap.md`
6. `/Users/carlosrojas/Oracle/cryptoagent3.0/tasks.md`

Prioridad en caso de conflicto:

`north_star → spec → theoretical-validation → decision-log → roadmap → tasks`

No leas, copies ni adaptes código de CryptoAgent 2.0 u otro sistema previo. La
solución debe conservarse greenfield. Puedes usar documentación oficial de Binance
y librerías públicas, pero nunca transmitir código, datos o secretos a terceros.

### Misión

Construir un sistema capaz de:

1. Recibir fixtures versionados BTC/USDT compatibles con contratos públicos de Binance, sin I/O de red en esta entrega.
2. Validar schema, tiempo, secuencia, freshness, gaps y provenance.
3. Mantener un libro L2 local sincronizado y revocable.
4. Construir contexto temporal y las features F-001…F-012.
5. Ejecutar `NULL_HOLD`, POL-101, POL-102 y POL-103 bajo un contrato común.
6. Aplicar un `RiskMandate` humano mediante un Gobernador no evadible.
7. Emitir exactamente una `Decision`: `ENTER_LONG`, `HOLD` o `EXIT_LONG`.
8. Mantener estado, idempotencia, expiración, reconciliación y ledger auditable.
9. Ejecutar replay determinista y validación walk-forward offline.
10. Simular Market/Limit con costos, latencia, partial fills y adverse selection.
11. Producir evidencia observable de por qué se tomó o bloqueó cada decisión.

### Restricciones no negociables

- **No enviar órdenes reales.**
- **No usar endpoints privados de trading o cuenta.**
- **No conectarse a testnet, demo, paper remoto o live sin un mandato posterior.**
- El adapter público permanece descriptivo/deshabilitado; esta entrega se valida exclusivamente con fixtures/replay.
- No crear, pedir, leer, imprimir ni almacenar claves API o credenciales.
- No afirmar edge, rentabilidad o readiness live.
- No bajar ni mover gates después de observar resultados.
- No usar barras abiertas para decisiones estratégicas.
- No convertir null/stale/gaps en cero, forward-fill o señal.
- No permitir que una Policy ejecute, modifique riesgo o evada al Gobernador.
- No usar imbalance L2 como trigger autónomo.
- No asumir fill al mid, fill completo ni fill gratuito.
- No copiar arquitectura, clases, eventos o nombres de proyectos anteriores.
- No hacer push, commit o crear PR salvo petición explícita del usuario.

### Autoridad humana ya congelada para offline

ADR-0002 registra la delegación explícita del usuario: D-001, D-002, D-003 y
D-011 están decididas para fixtures/replay offline; D-009 y D-014 están congeladas
como contratos para un experimento futuro. No vuelvas a pedir este gate ni lo
conviertas en default silencioso. La congelación no autoriza OOS ejecutado, paper,
testnet, live, red, credenciales o ejecución.

### Arquitectura obligatoria

Implementa diez responsabilidades separadas:

1. `MarketSensor`
2. `DataQualityGuard`
3. `StateCustodian`
4. `TemporalMarketModel`
5. `CostLiquidityModel`
6. `OpportunityPolicy`
7. `RiskGovernor`
8. `DecisionMachine`
9. `DecisionLedger`
10. `TheoreticalValidator`

La autoridad humana produce `ProductMandate` y `RiskMandate` como inputs externos.
La ejecución futura queda detrás de un puerto separado y deshabilitado.

Mantén dependencias dirigidas hacia el dominio. Los adapters no contienen reglas
de estrategia; las policies no conocen transporte, base de datos ni endpoints.

### Contratos mínimos que debes materializar

Implementa y versiona, respetando exactamente la semántica de la spec:

- `RawMarketEvent`
- `MarketEventV1`
- `QualifiedMarketFrame`
- `PortfolioState`
- `MarketContext`
- `FeatureValue`
- `CostEstimate`
- `CandidateIntent`
- `ProductMandate`
- `RiskMandate`
- `RiskVerdict`
- `SystemState`
- `Decision`
- `TargetPosition`
- `DecisionRecord`
- `TestVerdict`
- `FreshnessPolicy`
- `LocalBookView`

Usa decimales exactos, UTC, enums cerrados y serialización canónica. La identidad de
`Decision` y eventos debe ser determinista e idempotente.

### Orden de implementación

#### Fase I — Base del proyecto

1. Inspecciona el entorno y documenta la decisión de stack en un ADR.
2. Crea estructura modular y configuración de desarrollo sin secretos.
3. Añade dependencias con versiones exactas/pinned.
4. Configura lint, type-check y tests dirigidos.
5. Crea fixtures sintéticos antes de cualquier conexión pública.

**Gate:** contratos importables, type-check limpio y tests básicos verdes.

#### Fase II — Dominio determinista

1. Implementa value objects, enums, estados y reason codes.
2. Implementa `SystemState` jerárquico y SM-001…SM-031.
3. Implementa precedencia P0→P5.
4. Implementa `Decision`, vigencia, supersession e identidad SHA-256 canónica.
5. Implementa ledger append-only e idempotencia.

**Gate:** property tests de totalidad, determinismo, transiciones prohibidas y
duplicados.

#### Fase III — Datos y calidad

1. Implementa adapters públicos para S-01…S-09.
2. Implementa normalización `MarketEventV1`.
3. Implementa delivery classes: on-time, duplicate, late y out-of-order.
4. Implementa `FreshnessPolicy`, watermarks y lifecycle de barras.
5. Implementa `BookSyncState`, L2-001…L2-023 y generation swap atómico.
6. Ante gap/stale, revoca outputs antes de publicar un nuevo frame.

**Gate:** fixtures reproducen V-01/D-01/L-01/O-01, gaps, resync y reconnect.

#### Fase IV — Features y costos

1. Implementa F-001…F-012 con fórmulas y unidades exactas.
2. Cada feature devuelve `value` o `null_reason`; nunca excepción silenciosa.
3. Implementa VWAP/slippage y costo round-trip.
4. Implementa escenarios BASE/ADVERSE/EXTREME.
5. Verifica el ejemplo sintético de la spec, incluido 54.242622 bps.

**Gate:** tests numéricos con tolerancia decimal y auditoría de leakage.

#### Fase V — Policies

1. Implementa `POL-000-NULL-HOLD` primero.
2. Implementa POL-101 exactamente según `evaluate_POL101` y sus 19 parámetros.
3. Implementa POL-102 y POL-103 como challengers bajo `PolicySpecV1`.
4. Separa setup state, intent, RiskVerdict, Decision y fill.
5. Implementa cooldown advisory; sólo la Máquina modifica estados.

**Gate:** NULL-01…12, PC-01…12 y P101-T01…21 verdes.

#### Fase VI — Riesgo

1. Implementa sizing acotado por risk budget, exposición y cash.
2. Volatilidad cero/unknown produce bloqueo, nunca tamaño infinito.
3. Implementa stop inicial, trailing, time stop, cooldown y breakers.
4. Implementa `RiskMandate` versionado y `RiskGovernor` puro.
5. Reconciliación P0 siempre precede stop/breaker P1.

**Gate:** tests positivos/negativos de mandato, capital insuficiente, gap y partial
fill; ninguna entrada atraviesa RiskVerdict rechazado.

#### Fase VII — Replay y simulación local de fills con fixtures

1. Implementa reloj inyectable y replay determinista.
2. Conserva event-time, observed-at, watermark y provenance.
3. Implementa Market fills caminando el libro después de latencia.
4. Implementa Limit fills con queue-ahead conservadora, no-fill y adverse selection.
5. Partial fills y cancelaciones deben reconciliar posición residual.
6. No uses red pública para validar lógica que pueda cubrirse con fixtures.

**Gate:** mismo input+version+clock genera el mismo ledger byte-canónico.

#### Fase VIII — Validación offline

1. Convierte los 24 escenarios del documento de validación en tests ejecutables.
2. Convierte los 20 boundary tests en parametrized/property tests.
3. Reproduce los tres ejemplos numéricos.
4. Implementa walk-forward con purga y embargo.
5. Pre-registra el gate antes de abrir OOS.
6. Reporta PBO, effective sample, stability, drawdown, turnover y costos.
7. Compara todas las policies contra `NULL_HOLD` bajo ventanas pareadas.

**Gate:** si una policy no supera costo/gate, declárala `POLICY_FAIL` o `NO_GO`;
no ajustes parámetros para rescatarla.

#### Fase IX — Observabilidad técnica

Implementa una superficie mínima, no decorativa, que muestre:

- estado P/E/H;
- health/freshness por fuente;
- última Decision y reason codes;
- CandidateIntent y RiskVerdict;
- versiones y expiración;
- posición reconciliada;
- costo estimado y bloqueos;
- referencias del ledger/replay.

No construyas un dashboard complejo antes de tener contratos y tests verdes.

### Estrategia de pruebas obligatoria

Incluye como mínimo:

- Unit tests por contrato y componente.
- Property tests de estados, precedencia, idempotencia y sizing.
- Contract tests de payloads Binance con fixtures versionados.
- Integration tests del pipeline Sensor→Ledger.
- Replay determinista.
- Fault injection: stale, gap, duplicates, schema drift, restart, partial fill.
- 24 escenarios, 20 fronteras, 14 FMEA y 10 red-team convertidos en evidencia.
- Tests que demuestren que endpoints/credenciales de trading no están habilitados.

Antes de correr un build o suite completa, comprueba recursos. Con memoria ajustada,
usa tests dirigidos y luego amplía. Todo proceso externo debe tener timeout y cleanup.

### Reglas de trabajo

- Lee antes de editar.
- Una edición lógica por archivo antes de validar.
- Mantén una bitácora de implementación con criterio de evidencia, no sólo checkmarks.
- Registra un blocker una sola vez y continúa trabajo independiente.
- No ocultes TODOs críticos dentro del código.
- No ignores tests fallidos.
- No reportes “funciona” basándote sólo en imports, HTTP 200 o logs.
- Verifica el comportamiento observable mediante replay/tests y conserva evidencia.
- Si detectas contradicción documental, detente en ese punto, registra evidencia y
  pide decisión; no elijas silenciosamente.

### Deliverables obligatorios

1. Código fuente completo dentro del proyecto greenfield.
2. Suite de tests y fixtures.
3. Configuración de desarrollo sin secretos.
4. ADRs de stack, persistencia y decisiones relevantes.
5. Documento de arquitectura implementada.
6. Catálogo de contratos y schemas.
7. Reporte de cobertura de escenarios/boundaries/FMEA.
8. Reporte de replay fixture-first; D-009 permanece como contrato futuro sin OOS ejecutado.
9. Runbook de operación offline sin red, paper, testnet o live.

### Definición de hecho

El desarrollo sólo está completo cuando:

- Todos los contratos normativos están implementados y versionados.
- Las diez responsabilidades tienen ownership y tests.
- No existen caminos Policy→Execution o Policy→RiskMandate.
- Todas las transiciones y reason codes son deterministas.
- Los 24 escenarios y 20 fronteras son tests verdes.
- Los tres ejemplos numéricos se reproducen exactamente.
- Gap/stale/unknown position nunca generan entrada.
- Market/Limit simulator no presupone fills gratuitos.
- Ledger permite reconstruir cada decisión.
- Type-check, lint y tests relevantes pasan.
- No quedan fallos críticos o TODOs de seguridad.
- El reporte distingue teoría, replay, OOS, paper y live.
- No se ha ejecutado ninguna orden ni usado credencial.

### Reporte final requerido

Entrega al usuario:

1. Ruta de cada artefacto implementado.
2. Resumen de arquitectura y flujo.
3. Decisiones humanas aplicadas y defaults rechazados.
4. Tests ejecutados con resultados.
5. Evidencia de replay/determinismo.
6. Hallazgos, policies rechazadas y razones.
7. Riesgos residuales y trabajo futuro.
8. Veredicto exacto: `IMPLEMENTED_FOR_OFFLINE_VALIDATION`, `PIVOT` o `NO_GO`.

Nunca uses “listo para live” como veredicto de este mandato.

## FIN DEL PROMPT
