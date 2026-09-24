# Decision Log — Agente conceptual de decisión BTC

**Estado:** activo
**Ámbito:** implementación, fixtures y replay offline greenfield
**Fecha de apertura:** 2026-09-15

> **Autoridad vigente:** ADR-0002 registra la delegación explícita del usuario.
> D-001, D-002, D-003 y D-011 están `DECIDED` para implementación offline;
> D-009 y D-014 están `FROZEN_OFFLINE` para un experimento futuro. Esto no
> autoriza OOS ejecutado, paper, testnet, live, red, credenciales ni órdenes.

## Supuestos declarados

1. Una decisión abierta no es un hecho. Si el diseño necesita avanzar, usa una
   variable simbólica o un supuesto explícitamente reversible.
2. Las decisiones P0 pertenecientes al producto, capital o tolerancia de riesgo
   sólo puede cerrarlas el usuario. El loop puede modelarlas, no decidirlas.
3. Las decisiones P1 pueden ser propuestas por el loop, pero deben congelarse
   antes de evaluar una política fuera de muestra.
4. La plataforma de implementación se decide después del veredicto conceptual;
   no condiciona la arquitectura greenfield.
5. Este documento no contiene credenciales, no autoriza trading y no constituye
   asesoría financiera.

## Prioridades y estados

### Prioridad

- **P0 — Mandato humano:** cambia producto, exposición, pérdida admisible o la
  utilidad que se espera del agente.
- **P1 — Diseño:** cambia hipótesis, datos, costos, gates o interpretación de una
  decisión; debe resolverse antes de validación empírica.
- **P2 — Implementación futura:** puede diferirse sin afectar la prueba conceptual.

### Estado

- `OPEN_HUMAN`: requiere una decisión explícita del usuario.
- `PROVISIONAL`: supuesto reversible para continuar el razonamiento.
- `PRE_REGISTER_PENDING`: debe congelarse antes de abrir resultados OOS.
- `FROZEN_OFFLINE`: valores inmutables para fixtures/replay o un experimento futuro;
  no prueba resultados ni habilita OOS.
- `DECIDED`: existe decisión y evidencia suficiente en el alcance actual.
- `DEFERRED`: deliberadamente fuera de esta fase.
- `REJECTED`: alternativa descartada con razón trazable.

## Reglas de gobierno

1. Cada cambio conserva fecha, razón y evidencia; no se sobreescribe la historia.
2. Un supuesto `PROVISIONAL` debe aparecer como tal en reglas, ejemplos y pruebas.
3. Ninguna decisión P0 puede inferirse de las capturas de Binance.
4. Ningún umbral empírico se cambia después de observar OOS.
5. Una decisión `DEFERRED` no puede reaparecer como requisito implícito.
6. Si una decisión cambia contratos ya probados, se reabren sus pruebas afectadas.
7. Las decisiones que siguen abiertas al final condicionan el veredicto; nunca se
   presentan como resueltas.

## Plantilla de registro

```text
ID:
Prioridad:
Pregunta:
Opciones consideradas:
Supuesto/decisión actual:
Evidencia:
Impacto:
Dueño:
Estado:
Debe resolverse antes de:
Trigger de revisión:
Historial:
```

## Índice

| ID | Prioridad | Tema | Estado | Dueño | Límite de resolución |
|---|---|---|---|---|---|
| D-001 | P0 | Producto y dirección permitida | `DECIDED` | Usuario | Congelada por ADR-0002 para offline |
| D-002 | P0 | Horizonte y reloj de decisión | `DECIDED` | Usuario | Congelada por ADR-0002 para offline |
| D-003 | P0 | Mandato y presupuesto de riesgo | `DECIDED` | Usuario | Congelada por ADR-0002 para offline |
| D-004 | P1 | Solución nueva vs réplica del proceso manual | `DECIDED` | Usuario | Resuelta |
| D-005 | P1 | Familias de orden para modelar costos | `PROVISIONAL` | Diseño | Antes del modelo de fills |
| D-006 | P1 | Componentes y escenarios de costo | `PROVISIONAL` | Diseño + usuario | Antes de break-even |
| D-007 | P1 | Rol de depth/order-book | `DECIDED` | Diseño + Validador | Resuelta en T2.6 |
| D-008 | P1 | Fuente conceptual de datos | `PROVISIONAL` | Diseño | Antes del contrato de datos final |
| D-009 | P1 | Gate empírico futuro | `FROZEN_OFFLINE` | Validador | Contrato futuro; OOS no autorizado |
| D-010 | P1 | Conjunto de políticas candidatas | `DECIDED` | Diseño + Validador | Resuelta en T3.2 |
| D-011 | P2 | Plataforma de implementación | `DECIDED` | Usuario | ADR-0001 adoptado por ADR-0002 |
| D-012 | P2 | Superficie de observabilidad | `DEFERRED` | Producto | Antes de implementación |
| D-013 | P1 | Objetivo y jerarquía de evaluación | `DECIDED` | Diseño + Validador | Resuelta en T0.3 |
| D-014 | P1 | Budgets de freshness, lateness y reloj | `FROZEN_OFFLINE` | Calidad + Validador | Congelada por ADR-0002 para offline |
| D-015 | P1 | Prioridad de formalización de policies | `DECIDED` | Diseño + Validador | Resuelta en T3.3 |

## Registros detallados

### D-001 — Producto y dirección permitida

- **Prioridad:** P0.
- **Pregunta:** ¿el agente conceptual opera Spot `LONG/FLAT`, Margin o Futures con
  capacidad `LONG/SHORT`?
- **Opciones:** Spot `LONG/FLAT`; Spot con múltiples activos; Margin; Futures.
- **Decisión congelada:** Spot BTC/USDT, una posición, `LONG/FLAT`, sin
  apalancamiento.
- **Evidencia:** las capturas muestran BTC/USDT y un acceso a Margin, pero no
  identifican el producto contratado ni una posición.
- **Impacto:** estados, sizing, riesgo de liquidación, costos, acciones permitidas
  y semántica de salida.
- **Dueño:** usuario.
- **Estado:** `DECIDED` por delegación explícita registrada en ADR-0002.
- **Debe resolverse antes de:** resuelta para implementación/replay offline.
- **Trigger de revisión:** mandato explícito diferente o necesidad de `SHORT`.
- **Historial:** 2026-09-15 — supuesto inicial; 2026-09-15 — congelada por
  delegación explícita en ADR-0002.

### D-002 — Horizonte y reloj de decisión

- **Prioridad:** P0.
- **Pregunta:** ¿qué horizonte económico y qué instante habilitan una decisión?
- **Opciones:** intradía corto; intradía 15m/1h; swing; diario; múltiples horizontes
  con una sola política de resolución.
- **Decisión congelada:** `H_decision=1h`, evaluación estratégica al cierre
  `FINAL`, `H_context=720` barras de 1h y expiración en la siguiente frontera.
- **Evidencia:** la captura tiene `Time` seleccionado y muestra 15m/1h/4h/1D como
  alternativas, sin demostrar cuál usa el usuario.
- **Impacto:** latencia admisible, features, costos, frecuencia, expiración y
  tamaño de muestra.
- **Dueño:** usuario.
- **Estado:** `DECIDED` por delegación explícita registrada en ADR-0002.
- **Debe resolverse antes de:** resuelta para implementación/replay offline.
- **Trigger de revisión:** evidencia de que el horizonte no es operable neto de
  costos o nueva instrucción explícita.
- **Historial:** 2026-09-15 — símbolos iniciales; 2026-09-15 — valores congelados
  en ADR-0002.

### D-003 — Mandato y presupuesto de riesgo

- **Prioridad:** P0.
- **Pregunta:** ¿qué capital conceptual, riesgo por decisión, exposición, pérdida
  agregada y drawdown son admisibles?
- **Opciones:** límites absolutos; porcentajes de equity; sizing por volatilidad;
  combinación con cotas absolutas.
- **Decisión congelada:** perfil de fixtures ADR-0002: capital `10000 USDT`,
  riesgo por decisión `0.0025`, exposición `1000 USDT`, pérdida diaria `75 USDT`,
  drawdown `500 USDT`, redondeo hacia abajo y time stop no protector.
- **Evidencia:** las capturas no muestran capital, posición, stop ni tolerancia de
  pérdida. Los pesos `λ` de utilidad pertenecen al usuario.
- **Impacto:** elegibilidad de entrada, sizing, stop, cooldown y `NO_GO` por riesgo.
- **Dueño:** usuario.
- **Estado:** `DECIDED` por delegación explícita registrada en ADR-0002.
- **Debe resolverse antes de:** resuelta para fixtures y replay offline; no es una
  recomendación financiera ni autorización de capital real.
- **Trigger de revisión:** cambio de capital, producto o tolerancia de pérdida.
- **Historial:** 2026-09-15 — simbólica inicialmente; 2026-09-15 — perfil de
  fixtures congelado en ADR-0002.

### D-004 — Solución nueva vs réplica del proceso manual

- **Prioridad:** P1.
- **Pregunta:** ¿el agente debe replicar la conducta manual inferida de las
  capturas o diseñar una solución conceptual nueva?
- **Opciones:** réplica manual; evolución de una estrategia previa; greenfield.
- **Decisión actual:** solución greenfield desde el objetivo y primeros principios.
- **Evidencia:** instrucción explícita del usuario: no contaminarse por el “flujo
  real” y apuntar al objetivo.
- **Impacto:** elimina dependencias heredadas y difiere toda integración.
- **Dueño:** usuario.
- **Estado:** `DECIDED`.
- **Trigger de revisión:** únicamente una nueva instrucción explícita del usuario.
- **Historial:** 2026-09-15 — decisión tomada; B-001 quedó cerrado.

### D-005 — Familias de orden para modelar costos

- **Prioridad:** P1.
- **Pregunta:** ¿qué mecanismos de ejecución debe representar el futuro modelo
  teórico de fills?
- **Opciones:** Market; Limit pasiva; Marketable Limit; Stop; OCO; combinación.
- **Supuesto actual:** arquitectura neutral; modelar como mínimo Market y Limit en
  escenarios separados, sin asumir fills gratuitos.
- **Evidencia:** las capturas sólo muestran botones Buy/Sell, no el ticket ni la
  orden utilizada.
- **Impacto:** spread, slippage, fill parcial, adverse selection y latencia.
- **Dueño:** diseño; confirmación futura del usuario.
- **Estado:** `PROVISIONAL`.
- **Debe resolverse antes de:** T4.5, modelo de paper fills.
- **Trigger de revisión:** selección del producto o restricciones operativas.
- **Historial:** 2026-09-15 — no se eligió Market por defecto.

### D-006 — Componentes y escenarios de costo

- **Prioridad:** P1.
- **Pregunta:** ¿qué costos y severidad deben formar el break-even?
- **Opciones:** valores de cuenta reales; tiers públicos; escenarios
  base/adverso/extremo; combinación.
- **Supuesto actual:** `fees + spread + slippage + impact + costos aplicables`, con
  escenarios conservadores y buffer de incertidumbre.
- **Evidencia:** la UI permite observar un spread puntual, no fees ni precio de
  ejecución para un tamaño.
- **Impacto:** `POLICY_FAIL` cuando oportunidad bruta ≤ costo total + buffer.
- **Dueño:** diseño para estructura; usuario para fee tier real.
- **Estado:** `PROVISIONAL`.
- **Debe resolverse antes de:** T4.6 y pre-registro empírico.
- **Trigger de revisión:** producto, tamaño, fee tier o tipo de orden distinto.
- **Historial:** 2026-09-15 — el spread de 0.01 no se trató como constante.

### D-007 — Rol de depth/order-book

- **Prioridad:** P1.
- **Pregunta:** ¿depth e imbalance son señal, confirmación, filtro de liquidez o
  datos excluidos?
- **Opciones:** trigger; feature; filtro; sólo ejecución; excluido.
- **Decisión actual:** L2 se limita a filtro/veto de costo-liquidez y diagnóstico
  opcional. F-011/F-012 nunca producen `ENTER_LONG` por sí solas.
- **Evidencia:** 67.75/32.25 es una captura instantánea sin alcance, secuencia ni
  persistencia conocidos y es susceptible a cancelación/spoofing.
- **Impacto:** necesidades de datos L2, latencia, complejidad y falsos positivos.
- **Dueño:** diseño + Validador Teórico.
- **Estado:** `DECIDED`.
- **Debe resolverse antes de:** resuelta para el alcance actual.
- **Trigger de revisión:** sólo una nueva policy/version pre-registrada, con datos
  históricos L2, modelo de ejecución/latencia y gate neto de costos; no modifica
  retroactivamente esta decisión.
- **Historial:** 2026-09-15 — T2.6 fija FILTER_NOT_TRIGGER y documenta spoofing,
  fugacidad, coverage, queue risk y costos.

### D-008 — Fuente conceptual de datos

- **Prioridad:** P1.
- **Pregunta:** ¿qué observaciones mínimas y qué autoridad de mercado alimentan al
  Sensor?
- **Opciones:** interfaces públicas de Binance; proveedor agregado; múltiples
  venues; dataset offline para replay.
- **Supuesto actual:** Binance como fuente conceptual inicial para BTC/USDT;
  contratos provider-neutral y market data público sin autenticación.
- **Evidencia:** el objetivo parte de una consola Binance y requiere precio BTC en
  tiempo real.
- **Impacto:** timestamps, secuencias, disponibilidad, provenance y portabilidad.
- **Dueño:** diseño.
- **Estado:** `PROVISIONAL`.
- **Debe resolverse antes de:** contrato final de datos T2.1–T2.4.
- **Trigger de revisión:** calidad insuficiente, necesidad multi-venue o divergencia
  entre fuente de señal y ejecución.
- **Historial:** 2026-09-15 — la arquitectura no queda acoplada al proveedor.

### D-009 — Gate empírico futuro

- **Prioridad:** P1.
- **Pregunta:** ¿qué umbrales OOS debe superar una política para no ser dominada
  por `HOLD` después de costos y riesgo?
- **Opciones:** gate único; gates por horizonte; frontera multiobjetivo; criterios
  secuenciales.
- **Decisión congelada:** hard gates O1–O7 con tolerancia cero y gate
  `D-009/1.0.0` de ADR-0002 (`n_min=100`, margen `0.01`, ≥70% folds positivos,
  PBO `<0.20`, cero breaches, vecinos estables y coverage 1–30%).
- **Evidencia:** T0.3 separa integridad, seguridad y utilidad económica.
- **Impacto:** evita mover el arco después de ver resultados y define `POLICY_FAIL`.
- **Dueño:** Validador Teórico; aprobación humana para límites de riesgo.
- **Estado:** `FROZEN_OFFLINE`; el contrato está congelado, pero OOS no se ejecuta
  ni se autoriza en esta entrega.
- **Debe resolverse antes de:** resuelta como pre-registro para un experimento futuro
  independiente que además requerirá dataset versionado y autorización separada.
- **Trigger de revisión:** sólo antes de un experimento nuevo, nunca durante su evaluación.
- **Historial:** 2026-09-15 — pendiente inicialmente; 2026-09-15 — congelada por
  delegación explícita en ADR-0002, sin resultados OOS.

### D-010 — Conjunto de políticas candidatas

- **Prioridad:** P1.
- **Pregunta:** ¿qué mecanismos suficientemente distintos merecen falsación?
- **Opciones:** tendencia; reversión; ruptura; volatilidad; flujo; política nula.
- **Decisión actual:** `NULL_HOLD` + tres candidatas no rankeadas:
  `TREND_PULLBACK_RESUME`, `VOLATILITY_SCALED_REVERSION` y
  `VOLATILITY_BREAKOUT`, bajo los mismos contratos, costos y gates.
- **Evidencia:** comparar sólo variaciones de una misma idea aumenta riesgo de
  confirmación y no prueba neutralidad de arquitectura.
- **Impacto:** cobertura del espacio conceptual y costo de validación.
- **Dueño:** diseño + Validador Teórico.
- **Estado:** `DECIDED` para la shortlist conceptual; todas siguen
  `CANDIDATE_UNVALIDATED`.
- **Debe resolverse antes de:** resuelta para T3.2; parámetros/gate continúan
  pendientes en T3.5/D-009.
- **Trigger de revisión:** redundancia causal demostrada, datos inalcanzables o
  POLICY_FAIL previo a evaluación; toda sustitución crea nueva decisión/version.
- **Historial:** 2026-09-15 — T3.2 fija tres mecanismos sin ranking ni ganador.

### D-011 — Plataforma de implementación

- **Prioridad:** P2.
- **Pregunta:** ¿en qué sistema, lenguaje y runtime se implementará el concepto?
- **Opciones:** Python 3.12 y puertos/adaptadores neutrales; otras plataformas.
- **Decisión congelada:** ADR-0001, adoptado expresamente por ADR-0002.
- **Evidencia:** mandato greenfield del usuario.
- **Impacto:** adaptadores y despliegue, no validez conceptual.
- **Dueño:** usuario.
- **Estado:** `DECIDED` para implementación offline.
- **Debe resolverse antes de:** resuelta mediante ADR-0001/ADR-0002.
- **Trigger de revisión:** nueva instrucción explícita o incompatibilidad técnica demostrada.
- **Historial:** 2026-09-15 — diferida inicialmente; 2026-09-15 — ADR-0001 adoptado
  por delegación explícita en ADR-0002.

### D-012 — Superficie de observabilidad

- **Prioridad:** P2.
- **Pregunta:** ¿qué información necesita visualizar el usuario para confiar y
  supervisar las decisiones?
- **Opciones:** dashboard, alertas, ledger navegable, explicación por decisión.
- **Supuesto actual:** toda decisión debe exponer acción, estado, razón, evidencia,
  calidad, riesgo, expiración y versión; la UI concreta se difiere.
- **Evidencia:** la North Star exige explicabilidad y auditabilidad nativas.
- **Impacto:** contrato de salida y futura experiencia de producto.
- **Dueño:** producto/usuario.
- **Estado:** `DEFERRED`.
- **Debe resolverse antes de:** diseño de interfaz.
- **Trigger de revisión:** comienzo de una fase de implementación.
- **Historial:** 2026-09-15 — requisitos semánticos preservados, UI no elegida.

### D-013 — Objetivo y jerarquía de evaluación

- **Prioridad:** P1.
- **Pregunta:** ¿qué significa que una decisión o política sea “mejor” y en qué
  orden se evalúan seguridad, validez y utilidad?
- **Opciones:** maximizar retorno; maximizar hit-rate; score ponderado único;
  jerarquía lexicográfica con control `HOLD`.
- **Decisión actual:** jerarquía G0–G4: integridad → seguridad → validez decisional
  → utilidad neta → eficiencia. `HOLD` es control y los hard gates no se compensan
  con retorno.
- **Evidencia:** T0.3 formalizó O1–O14 y separó `ARCH_FAIL`, `POLICY_FAIL` y
  `NO_GO` antes de generar políticas.
- **Impacto:** define selección, falsación, precedencia de métricas y promoción.
- **Dueño:** diseño + Validador Teórico; límites económicos/riesgo siguen sujetos a
  D-003/D-009.
- **Estado:** `DECIDED`.
- **Debe resolverse antes de:** resuelta; los umbrales empíricos continúan en D-009.
- **Trigger de revisión:** cambio explícito del objetivo del usuario o prueba de que
  las tres acciones no representan la necesidad real.
- **Historial:** 2026-09-15 — decisión fijada antes de elegir políticas.

### D-014 — Budgets de freshness, lateness y reloj

- **Prioridad:** P1.
- **Pregunta:** ¿qué edad, lateness, clock skew, cierre grace y heartbeat máximos
  hacen utilizable cada tipo de dato para cada horizonte?
- **Opciones:** constantes absolutas; múltiplos de cadence oficial; fracción de
  `H_decision`; presupuesto adaptativo pre-registrado; combinación conservadora.
- **Decisión congelada:** budgets `D-014/1.0.0` de ADR-0002 para BBO, L2,
  aggTrades, kline 1h, ticker y exchangeInfo, con clock skew máximo 500 ms y
  recuperación explícita. Ausencia/incumplimiento implica `BLOCKED`.
- **Evidencia:** D-002 fija `H_decision=1h`; ADR-0002 registra caps, grace,
  heartbeat y recovery por fuente.
- **Impacto:** calidad, watermarks, cierre de barra, elegibilidad de features,
  decisiones y recuperación.
- **Dueño:** Guardia de Calidad + Validador bajo delegación explícita.
- **Estado:** `FROZEN_OFFLINE`.
- **Debe resolverse antes de:** resuelta para fixtures/replay offline; cambios crean
  nueva versión y experimento.
- **Trigger de revisión:** cambio de horizonte, cadence/provider o requisito de
  policy, siempre antes de un experimento nuevo.
- **Historial:** 2026-09-15 — simbólica inicialmente; 2026-09-15 — budgets
  congelados en ADR-0002.

### D-015 — Prioridad de formalización de policies

- **Prioridad:** P1.
- **Pregunta:** ¿qué candidata se formaliza primero sin confundir readiness
  conceptual con superioridad económica?
- **Opciones:** POL-101 trend-pullback; POL-102 mean reversion; POL-103 breakout;
  pivotar sin primaria; formalizar todas simultáneamente.
- **Decisión actual:** POL-101 `TREND_PULLBACK_RESUME` es
  `PRIMARY_FOR_THEORETICAL_FORMALIZATION`; POL-102/POL-103 son
  `CHALLENGER_RETAINED`. Las tres permanecen `CANDIDATE_UNVALIDATED`.
- **Evidencia:** rúbrica T3.3 preexistente en G0–G4/AG-001…10: mismo contrato de
  datos, menor sensibilidad de ejecución que breakout, menor tail risk estructural
  que falling-knife reversion y falsación densa con barras core.
- **Impacto:** T3.4/T3.5 profundizan primero POL-101; challengers siguen en el plan
  comparativo y pueden reemplazarla si falla teóricamente.
- **Dueño:** diseño + Validador Teórico.
- **Estado:** `DECIDED` bajo el perfil offline congelado por ADR-0002.
- **Debe resolverse antes de:** resuelta para T3.4; no autoriza OOS ni producción.
- **Trigger de revisión:** D-001/D-002 cambian, POL-101 activa ARCH/POLICY_FAIL,
  datos no soportan setup o challenger obtiene mejor readiness bajo la misma
  rúbrica antes de outcomes.
- **Historial:** 2026-09-15 — elección por formalizabilidad; no por backtest ni
  evidencia heredada.

## Cobertura de ambigüedades detectadas

| Ambigüedad original | Registro |
|---|---|
| Spot vs Margin/Futures; long-only vs short | D-001 |
| Horizonte y cierre de vela | D-002 |
| Capital, pérdida, drawdown y autoridad | D-003 |
| Regla manual actual vs concepto nuevo | D-004 |
| Tipo de orden | D-005 |
| Fees, spread y slippage | D-006 |
| Uso de order book/depth | D-007 |
| Fuente de market data | D-008 |
| Umbrales de validación | D-009 |
| Familias de políticas | D-010 |
| Plataforma futura | D-011 |
| Contexto visual/observabilidad | D-012 |
| Objetivo y jerarquía de evaluación | D-013 |
| Freshness, lateness, clock skew y cierre grace | D-014 |
| Policy primaria para formalización, no ganador | D-015 |

## Matriz de defaults provisionales y gates

Las etiquetas entre corchetes son normativas. “Puede usarse ahora” significa que
el razonamiento puede permanecer simbólico; no autoriza implementación ni trading.

| ID | Clasificación | Default/símbolo explícito | Puede usarse ahora para | Debe resolverse antes de | Si sigue abierto |
|---|---|---|---|---|---|
| D-001 | P0 `DECIDED` | `[DECIDED_OFFLINE: SPOT_BTCUSDT_LONG_FLAT_NO_LEVERAGE]` | Contratos, fixtures y replay | Resuelta por ADR-0002 | No autoriza órdenes |
| D-002 | P0 `DECIDED` | `[DECIDED_OFFLINE: H_decision=1h, H_context=720]` | Features/policies fixture-first | Resuelta por ADR-0002 | No prueba harvestability |
| D-003 | P0 `DECIDED` | `[DECIDED_OFFLINE: RISK_FIXTURE_PROFILE_D003_1]` | Sizing y breakers sintéticos | Resuelta por ADR-0002 | No autoriza capital real |
| D-004 | P1 `DECIDED` | `[DECIDED: GREENFIELD]` | Todo el ciclo conceptual | Resuelta | Reabrir sólo por instrucción explícita |
| D-005 | P1 `PROVISIONAL` | `[PROVISIONAL: MARKET_AND_LIMIT_SCENARIOS]` | Estructura neutral de costos | Modelo de fills T4.5 | No afirmar ejecutabilidad |
| D-006 | P1 `PROVISIONAL` | `[PROVISIONAL: CONSERVATIVE_COST_RANGE]` | Fórmulas y escenarios | Break-even T4.6 y gate OOS | Toda utilidad económica queda condicionada |
| D-007 | P1 `DECIDED` | `[DECIDED: L2_COST_LIQUIDITY_FILTER_NOT_TRIGGER]` | CostEstimate, veto y diagnóstico | Resuelta para alcance actual | Nueva hipótesis requiere nueva policy/version |
| D-008 | P1 `PROVISIONAL` | `[PROVISIONAL: BINANCE_PUBLIC_PROVIDER_NEUTRAL]` | Diseñar contratos de datos | Cierre T2.1–T2.4 | No acoplar semántica a proveedor |
| D-009 | P1 `FROZEN_OFFLINE` | `[FROZEN: OOS_GATE_D009_1]` | Probar evaluador con métricas sintéticas | Experimento futuro separado | No hay OOS ejecutado ni policy aprobada |
| D-010 | P1 `DECIDED` | `[DECIDED: NULL_PLUS_TREND_REVERSION_BREAKOUT]` | Formalizar/comparar candidatas | Resuelta para shortlist conceptual | Ninguna candidata está validada/rankeada |
| D-011 | P2 `DECIDED` | `[DECIDED_OFFLINE: ADR-0001]` | Implementación fixture-first | Resuelta por ADR-0002 | Sin despliegue ni red |
| D-012 | P2 `DEFERRED` | `[DEFERRED: UI_SURFACE]` | Semántica de explicación únicamente | Antes de UI | No diseñar dashboard ahora |
| D-013 | P1 `DECIDED` | `[DECIDED: G0_G4_WITH_HOLD_CONTROL]` | Scorecard, falsación y selección | Resuelta | Umbrales permanecen en D-003/D-009 |
| D-014 | P1 `FROZEN_OFFLINE` | `[FROZEN: FRESHNESS_D014_1]` | Quality gates fixture-first | Experimento futuro separado | Incumplimiento bloquea |
| D-015 | P1 `DECIDED` | `[DECIDED: POL101_PRIMARY_FORMALIZATION_ONLY]` | T3.4/T3.5; challengers retenidas | Resuelta bajo CP-01 | No implica edge, ranking empírico ni promoción |

## Gates de resolución por fase

| Gate | Decisiones que deben estar resueltas/congeladas | Condición permitida al entrar |
|---|---|---|
| Cierre Fase 1 | D-004, D-013 decididas; D-001–D-003 visibles | `PASS_CONDITIONAL` con símbolos, sin números inventados |
| Cierre contrato de datos (Fase 2) | D-002, D-007, D-008, D-014 | Fuente, horizonte, rol L2 y budgets inequívocos |
| Freeze de políticas (Fase 3) | D-001, D-002, D-009, D-010, D-015 | Producto/horizonte/gate/candidatas/prioridad pre-registrados |
| Riesgo y costos cuantitativos (Fase 4) | D-001, D-003, D-005, D-006 | Mandato, órdenes y escenarios de costo definidos |
| Prueba teórica numérica (Fase 5) | Todas P0 y P1 que afecten ejemplos | Ningún default simbólico presentado como número real |
| Validación OOS futura | D-002, D-005…D-010, D-014 | Dataset, quality budgets y gate inmutables |
| Implementación | D-001…D-015 según impacto; D-011/D-012 incluidas | Veredicto conceptual aprobado por humano |

## Auditoría de clasificación T1.5

- P0 `DECIDED`: **3** (D-001–D-003, delegación explícita ADR-0002).
- P1 `DECIDED`: **5** (D-004, D-007, D-010, D-013, D-015).
- P1 `PROVISIONAL`: **3** (D-005, D-006, D-008).
- P1 `FROZEN_OFFLINE`: **2** (D-009, D-014).
- P2 `DECIDED`: **1** (D-011); P2 `DEFERRED`: **1** (D-012, UI solamente).
- Decisiones sin dueño: **0**.
- Defaults sin etiqueta: **0**.
- Decisiones abiertas sin gate temporal: **0**.

## Gate de mantenimiento

Este log cumple su propósito mientras:

- toda decisión P0/P1 de la especificación tenga un ID y dueño;
- ningún `OPEN_HUMAN` se convierta en default oculto;
- los cambios queden fechados y propaguen sus pruebas afectadas;
- `DEFERRED` siga fuera de requisitos conceptuales;
- el índice y los registros detallados mantengan el mismo estado.
