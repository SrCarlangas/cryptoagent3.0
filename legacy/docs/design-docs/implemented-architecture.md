# Arquitectura implementada — fixture-first offline

## Alcance y límites

La implementación materializa ADR-0001/0002 para fixtures y replay local. No
contiene executor, cliente HTTP/WebSocket activo, credenciales, endpoints privados,
cuentas ni envío de órdenes. `PublicMarketDataAdapter` permanece deshabilitado y
sólo describe requests públicos allowlisted; esa frontera descriptiva es una
limitación deliberada no bloqueante para esta entrega offline.

## Capas

```text
RawMarketEvent → MarketSensor → DataQualityGuard → QualifiedMarketFrame
                                      ↓
                         TemporalMarketModel + CostLiquidityModel
                                      ↓
OpportunityPolicy → CandidateIntent → RiskGovernor → RiskVerdict
                                      ↓
                               DecisionMachine
                                      ↓
                   DecisionLedger (COMPLETE) → export/suppression
```

`application.offline_pipeline.OfflineDecisionService` es la composición ejecutable.
El dominio no importa transporte/persistencia; las policies sólo proponen intents;
no existe ruta Policy→RiskMandate ni puerto de ejecución.

## Diez responsabilidades

| Responsabilidad | Implementación | Fallo seguro |
|---|---|---|
| MarketSensor | `MarketSensor` + `normalize` | schema/symbol/invariant error |
| DataQualityGuard | `DataQualityGuard` | stale/late/duplicate/gap no se aplican |
| StateCustodian | `StateCustodian` | conflicto/ausencia produce `STATE_UNKNOWN` |
| TemporalMarketModel | `TemporalMarketModel.build` | barras no causales producen contexto bloqueado |
| CostLiquidityModel | `CostLiquidityModel.estimate` | BBO inválido produce costo unknown |
| OpportunityPolicy | `policies/core.py` | `CandidateIntent`/`NO_INTENT`, nunca autorización |
| RiskGovernor | `RiskGovernor` | verdict rechazado y refs inmutables |
| DecisionMachine | `DecisionMachine` | P0→P5 y binding de autoridad vigente |
| DecisionLedger | `JsonlDecisionLedger` | manifest incompleto/collision bloquean export |
| TheoreticalValidator | `TheoreticalValidator` | PASS sin evidencia se convierte en FAIL |

## Flujo integrado y evidencia

1. El servicio normaliza fixtures S-03/S-04 sin red y clasifica quality/freshness.
2. Las barras conservan close/event time, quality, continuidad, gaps, source refs y
   watermarks; F-001..007 rechazan cualquier input no causal.
3. Frame, features, contexto y costo se construyen internamente.
4. POL-101 genera el intent; el Gobernador fija referencias de intent/state/
   portfolio/context/cost/mandato en el verdict.
5. La Máquina compara esas referencias con los objetos actuales antes de entrada.
6. El ledger recibe objetos inmutables, calcula hashes y verifica el catálogo por
   acción. Sólo `COMPLETE` puede exportarse.
7. Un append repetido informa `DUPLICATE_SUPPRESSED`; nunca exporta una segunda
   decisión accionable.
8. Dos corridas completas en directorios separados producen el mismo JSONL canónico.

## Calidad y L2

El watermark avanza desde progreso real de event time, no desde el reloj de
consulta. Una corrección sólo es late si ya existía una frontera finalizada.
`classify_bar` exige quality QUALIFIED, continuidad y watermark. El libro L2 revoca
por gap y bloquea cualquier diff que haga retroceder event time u observed time.

## Riesgo y simulación local de fills

Sizing es `min(qty_risk, qty_exposure, qty_cash)` cuantizado hacia abajo. Market
consume una generación `LIVE/FRESH/QUALIFIED` posterior a latencia. Limit exige
book y trades de la misma generación, price reach side-aware y volumen
traded-through estrictamente mayor que queue-ahead. Partial, cancel, fee y adverse
selection se conservan. Son funciones locales con fixtures, no paper trading ni
órdenes.

## Evidencia no producida

No hay dataset histórico versionado, resultado OOS, paper, testnet, live, market
data realtime ni claim de edge. D-009 está congelada para un experimento futuro,
pero esta entrega no lo ejecuta ni lo autoriza.
