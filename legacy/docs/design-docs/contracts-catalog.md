# Catálogo de contratos implementados

Todos los contratos están en `src/btc_decision_agent/domain/contracts.py`, heredan `ContractModel`, son Pydantic v2 frozen, `extra=forbid`, versionados, serializables canónicamente y validan UTC. Valores monetarios/cantidades usan `Decimal`; enums son cerrados y case-sensitive.

Los envelopes conservan 18 contratos normativos. `QualifiedMarketFrame`, `MarketContext` y `CostEstimate` avanzan a `1.1.0` porque sus nuevos bindings de provenance son obligatorios; los demás conservan su versión vigente.

| Contrato | Schema vigente | Invariantes principales |
|---|---|---|
| `RawMarketEvent` | `raw-market-event/1.0.0` | source/channel/observed_at/raw presentes |
| `MarketEventV1` | `market-event/1.0.0` | sequence completa, tiempo causal, connection/precision/raw refs y metadata tipada de secuencia, entrega, calidad y provenance sin perder clasificaciones |
| `QualifiedMarketFrame` | `qualified-frame/1.1.0` | sequence/identity y provenance explícitos; el BBO aplicado conserva `bbo_event_id`/`bbo_observed_at` y pertenece a `event_ids`; `event_time_max` es el máximo real consumido; bid≤ask; QUALIFIED implica complete+fresh+sin gaps+BBO ligado |
| `PortfolioState` | `portfolio-state/1.0.0` | UNKNOWN no inventa qty/exposure; FLAT qty/exposure=0; LONG qty>0; order/fill refs únicas |
| `MarketContext` | `market-context/1.1.0` | `frame_ref` obligatorio; decision_time es la frontera de evaluación; ninguna feature posterior a decision_time; volatility/liquidity finitas y no negativas |
| `FeatureValue` | `feature-value/1.0.0` | formula hash, source watermarks y conditional profile; value/null_reason bicondicional; finite; no futuro |
| `CostEstimate` | `cost-estimate/1.1.0` | `frame_ref`, `input_event_ids` y `max_input_event_time` obligatorios; reloj causal no futuro; total exacto; punto dentro de rango conservador lower/upper |
| `CandidateIntent` | `candidate-intent/1.0.0` | vigencia, reason primaria incluida y sin duplicados |
| `ProductMandate` | `product-mandate/1.0.0` | Spot long/flat, leverage 0, restrictions/capabilities consistentes, vigencia/autoría |
| `RiskMandate` | `risk-mandate/1.0.0` | capital/límites positivos, exposición≤capital, liquidity/data-quality gates únicos, autoridad humana |
| `RiskVerdict` | `risk-verdict/1.0.0` | APPROVED iff qty positiva y mandate version presente |
| `SystemState` | `system-state/1.0.0` | combinaciones P/E/H normativas |
| `Decision` | `decision/1.0.0` | causalidad, referencias intent/context/cost/verdict aplicables, una acción/target/reason, record-before-export |
| `TargetPosition` | `target-position/1.0.0` | UNKNOWN sin qty; FLAT absoluta=0; LONG qty>0 |
| `DecisionRecord` | `decision-record/1.0.0` | completeness, outcome ref, hashes, transición y enlace anterior; COMPLETE liga context/cost al frame y exige inputs de features/cost subconjunto de `frame.event_ids` antes de persistir |
| `TestVerdict` | `test-verdict/1.0.0` | obligation/component/test IDs, status/evidence/reason explícitos |
| `FreshnessPolicy` | `freshness-policy/1.0.0` | recovery rule, on-stale/on-suspect, decision refs y presupuestos temporales válidos |
| `LocalBookView` | `local-book-view/1.0.0` | best bid/ask derivados y validados; sólo LIVE/QUALIFIED; sides ordenados; no crossed |

## Identidades

- `canonical_json`: UTF-8, claves ordenadas, sin whitespace, UTC `Z`, decimals sin notación local/exponente ambiguo.
- `event_id`: provider + source contract + event type + symbol + source identity + payload hash; excluye observed_at/attempt.
- `intent_id`, `verdict_id`, `decision_id`: SHA-256 de inputs, versiones, reloj y resultado normativos.
- `record_hash`: Decision + hashes de artefactos + transición + recorded_at + previous hash.

## Tipos auxiliares

Los contratos usan enums para acción, intent, position/evaluation/health, calidad/freshness, delivery, prioridad P0..P5, trigger, escenario de costo y estado L2. `domain/features.Bar`, `adapters.book.DepthDiff/DepthSnapshot` y estructuras de replay/simulación son value objects internos, no sustituyen los 18 envelopes normativos.
