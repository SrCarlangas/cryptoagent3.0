# Especificación del agente de decisión BTC

**Estado:** borrador de ideación — Fase 0
**Alcance actual:** evidencia observable de las capturas (T0.1)
**Fecha de evidencia:** 2026-09-15

> **Actualización de implementación offline:** ADR-0002 supersede las etiquetas
> históricas `OPEN_HUMAN`/`PRE_REGISTER_PENDING` de las fases conceptuales para
> D-001/D-002/D-003/D-009/D-011/D-014. El perfil queda congelado exclusivamente
> para fixtures/replay; no autoriza OOS ejecutado, paper, testnet, live o red.

## Supuestos declarados

1. El conjunto relevante contiene tres capturas móviles de Binance del mismo
   intervalo aproximado, 12:45–12:46. La captura adicional del modal “Set a goal”
   pertenece a KiroCrew y se excluye del análisis de mercado.
2. Los separadores numéricos se interpretan según el formato visual de la app:
   por ejemplo, `76.866,86` representa 76,866.86 USDT. Esto sólo normaliza la
   lectura; no afirma precisión ni vigencia fuera del instante capturado.
3. Una captura prueba qué mostraba la interfaz, no qué regla usa el operador, qué
   producto contrató ni qué orden ejecutó.
4. `cryptoagent3.0` es un workspace conceptual greenfield. La ausencia de código
   heredado es intencional para esta etapa: primero se congela qué debe hacer la
   solución; después se decide dónde y cómo implementarla.
5. Esta sección no recomienda comprar o vender y no convierte patrones visuales
   en una señal de trading.
6. Ningún nombre, evento, componente o límite de una solución anterior constituye
   una restricción de diseño para esta especificación.

## Current state — evidencia de las capturas

### OBSERVADO

| Aspecto | Evidencia visible | Certeza | Implicación permitida para el agente |
|---|---|---:|---|
| Instrumento | Encabezado `BTC/USDT` en las tres capturas. | Alta | El contrato de datos puede usar BTC/USDT como símbolo provisional. |
| Instante | Reloj del teléfono 12:45–12:46; eje del gráfico fechado `2026-09-15`. | Alta | Las capturas son snapshots cercanos, no una serie independiente de escenarios. |
| Precio mostrado | Aproximadamente 76,866.86; 76,874.01 y 76,893.07 USDT. | Alta | El precio cambia entre snapshots; no constituye un feed ni prueba latencia. |
| Cambio mostrado | Aproximadamente −2.48 % a −2.50 %. | Alta | Hay contexto negativo para el periodo calculado por Binance; la captura no define su uso estratégico. |
| Estadísticas 24h | High 79,600.00; Low 75,605.00; volumen 18,254.91 BTC y ~1.41B USDT. | Alta | Son datos de contexto recuperables por API, no disparadores definidos. |
| Vista temporal | `Time` aparece seleccionada; `15m`, `1h`, `4h` y `1D` aparecen como alternativas. | Alta | No se puede afirmar que 15m o 1h sea la temporalidad usada para decidir. |
| Forma del gráfico | Línea amarilla de precio, no velas OHLC visibles. | Alta | La UI no aporta aperturas, máximos, mínimos y cierres por barra en estas capturas. |
| Media | Etiqueta `MA60 76.498,70` visible en una captura; línea blanca bajo el precio al final. | Alta | Precio y MA60 son datos observables; su cruce o distancia no son todavía una regla. |
| Relación puntual precio/MA | En el snapshot principal, el precio está ~368.16 USDT (~0.48 %) sobre la MA60 mostrada. | Alta | Describe el instante; no prueba tendencia persistente ni edge. |
| Volumen | Panel `VOL` seleccionado, barras de volumen y referencias `MA(5)`/`MA(10)` visibles. | Alta | El agente podría calcular volumen relativo, pero falta definir ventana y umbral. |
| Movimiento visual | Ascenso rápido, pico, retroceso y rebote parcial dentro de la ventana mostrada. | Media | Es una descripción ex post del trazo, no una condición causal formal. |
| Rendimientos | Today y 7 Days negativos; 30/90/180 Days positivos; 1 Year negativo. | Alta | Son horizontes de contexto; no se observa una regla que los combine. |
| Libro | Mejor bid/ask visible cerca de 76,874.00/76,874.01 y selector `0.01`. | Alta | Permite describir spread visible de ~0.01 USDT en ese instante. |
| Imbalance UI | Barra `67.75 %` bid frente a `32.25 %` ask. | Alta | Es una medida instantánea de la UI; no demuestra presión ejecutada ni intención durable. |
| Profundidad | Curvas acumuladas verdes (bid) y rojas (ask), centradas cerca de 76,893.06. | Alta | Hay información de profundidad visible, pero no historial, secuencia ni persistencia. |
| Acciones UI | Botones `Buy` y `Sell`; accesos `More`, `Hub` y `Margin`. | Alta | La interfaz permite iniciar acciones, pero no revela producto ni orden finalmente elegidos. |
| Indicadores disponibles | MA, EMA, BOLL, SAR, AVL, SUPER, VOL, MACD, RSI y otros aparecen en el selector. | Alta | Disponibilidad no equivale a indicador activo ni a criterio usado por el operador. |

### AMBIGUO

| Aspecto | Qué no puede resolverse desde las capturas | Tratamiento seguro |
|---|---|---|
| Producto | No se confirma Spot frente a Margin; el acceso `Margin` puede ser sólo navegación. | Mantener Spot como supuesto provisional y exigir decisión antes de cualquier fase ejecutable. |
| Semántica de `Time` | No se conoce intervalo, granularidad ni ventana exacta de esa vista. | No derivar reglas temporales de ella; definir temporalidad mediante contrato explícito. |
| Semántica de MA60 | No se confirma si son 60 muestras, qué muestra usa `Time` ni cómo trata datos incompletos. | Especificar fórmula y barras cerradas antes de usarla. |
| Medias de volumen | `MA(5)`/`MA(10)` son visibles, pero su unidad depende de la granularidad no identificada. | No copiar sus números como parámetros del agente. |
| Alcance del 67.75/32.25 | No se identifica cuántos niveles, profundidad nocional ni ventana usa Binance. | Recalcular desde un libro sincronizado y documentar niveles/notional. |
| Spread efectivo | Se ve ~0.01 USDT en un instante, pero no su persistencia ni el slippage para un tamaño real. | Medir serie y profundidad; no asumir costo constante. |
| Mercado real o demo | La pantalla no revela si el origen es producción, demo o testnet. | Separar fuente de market data y entorno de ejecución en el diseño. |
| Uso de indicadores | No se sabe si el operador decide con MA60, volumen, profundidad, rendimientos u otra información. | Registrar como decisión humana pendiente; no inferir preferencias. |
| Señal del movimiento | La combinación “precio sobre MA + pico de volumen + más bids” admite lecturas opuestas. | Tratarla como hipótesis falsable, nunca como recomendación. |
| Moneda/configuración regional | La app mezcla etiquetas y formatos; no se conoce configuración completa. | Normalizar unidades y UTC en el contrato de datos. |

### NO MOSTRADO

| Información ausente | Por qué es necesaria antes de una decisión ejecutable |
|---|---|
| Regla manual de entrada/salida | Sin ella no puede afirmarse que el diseño reproduzca el proceso actual del usuario. |
| Tipo de orden | Market, Limit, Stop-Limit, OCO y trailing tienen costos y riesgos distintos. |
| Posición y precio de entrada | Determinan si `ENTER`, `HOLD` o `EXIT` es siquiera una acción válida. |
| Balance y capital disponible | Son necesarios para sizing y límites de exposición. |
| Órdenes abiertas, fills y rechazos | Son necesarios para reconciliación e idempotencia. |
| Stop-loss, take-profit y trailing | Sin reglas de salida protectora la pérdida no queda acotada. |
| Apalancamiento y riesgo de liquidación | Imprescindibles si el producto no fuera Spot. |
| Fee tier y descuentos | El costo round-trip no puede calcularse desde la pantalla. |
| Slippage y latencia | Una fotografía del top of book no modela el precio ejecutado. |
| Historial OHLCV completo | Hace falta para calcular features causalmente y evaluar regímenes. |
| Historial/sincronización L2 | Hace falta para persistencia del imbalance y detección de gaps/spoofing. |
| Trades ejecutados/aggressor side | Hace falta para distinguir órdenes publicadas de flujo realmente negociado. |
| Freshness, sequence IDs y calidad del feed | Sin ellos el agente no puede detectar datos stale o incompletos. |
| Límites de riesgo aprobados por el usuario | Los defaults técnicos existentes no son autorización de negocio. |
| Objetivo y horizonte de evaluación | Sin ellos no existe criterio para preferir una estrategia ni medir éxito. |
| Evidencia de rentabilidad | Ninguna captura demuestra edge, robustez OOS o rentabilidad neta de costos. |

## Conclusiones permitidas de T0.1

1. El futuro agente debe leer APIs oficiales, no interpretar píxeles ni operar la
   interfaz móvil.
2. Para reproducir lo visible necesita como mínimo precio/bid-ask, klines OHLCV,
   estadísticas 24h y, si se conserva como filtro, profundidad sincronizada.
3. El dato estratégico debe basarse en barras cerradas y estado temporal
   explícito; la vista `Time` no define una temporalidad utilizable.
4. MA60 y volumen son candidatos observados para formular hipótesis. No existe
   evidencia de que la combinación mostrada sea la regla manual o tenga edge.
5. El imbalance 67.75/32.25 no puede disparar una entrada: es instantáneo,
   dependiente del alcance de la UI y susceptible a cancelación/spoofing.
6. No puede elegirse `ENTER_LONG`, `HOLD` o `EXIT_LONG` sin posición reconciliada,
   política de riesgo, costos y reglas deterministas.

## Arquitectura conceptual greenfield — T0.2

### Mandato

Diseñar un sistema de decisión sobre BTC/USDT que pueda explicarse y probarse sin
presuponer framework, bus, base de datos, estrategia heredada ni plataforma de
ejecución. La arquitectura organiza responsabilidades conceptuales; no es todavía
un diseño de despliegue.

### Pregunta de diseño

> Dado un flujo de mercado con calidad conocida, un estado de posición y un
> mandato humano de riesgo, ¿qué decisión única, segura, causal y explicable debe
> emitir el sistema ahora: `ENTER_LONG`, `HOLD` o `EXIT_LONG`?

### Responsabilidades conceptuales

| Componente conceptual | Responsabilidad única | Inputs | Output | Fallo seguro |
|---|---|---|---|---|
| **Sensor de Mercado** | Recibir y normalizar observaciones sin interpretarlas. | Trades, bid/ask, OHLCV y depth opcional. | `RawMarketEvent`. | Marcar ausencia; nunca rellenar un dato inventado. |
| **Guardia de Calidad** | Validar orden temporal, duplicados, gaps, freshness, precisión y coherencia. | `RawMarketEvent` + reloj monotónico. | `QualifiedMarketFrame` o `DATA_BLOCKED`. | Bloquear nuevas entradas. |
| **Custodio de Estado** | Reconciliar posición, órdenes/fills y capital conocido sin decidir estrategia. | Observaciones de cuenta/posición + decisiones previas. | `PortfolioState` versionado o `STATE_UNKNOWN`. | Bloquear entradas y priorizar reconciliación. |
| **Modelo Temporal de Mercado** | Convertir frames válidos en contexto causal sobre ventanas cerradas. | Frames calificados + historial permitido. | `MarketContext` versionado. | `CONTEXT_INSUFFICIENT`; no extrapolar. |
| **Modelo de Costos y Liquidez** | Estimar un rango conservador de costo ejecutable, independiente de la política. | Frame calificado + acción/tamaño/horizonte hipotéticos. | `CostEstimate` con rango y calidad. | `COST_UNKNOWN`; ninguna entrada elegible. |
| **Política de Oportunidad** | Evaluar una hipótesis intercambiable sin controlar riesgo ni ejecución. | `MarketContext` + `PortfolioState` + `CostEstimate`. | `CandidateIntent` con evidencia e invalidación. | `NO_INTENT`. |
| **Gobernador de Riesgo** | Aplicar mandato humano, exposición, pérdida admisible, liquidez y calidad. | Intento + `RiskMandate` + `PortfolioState` + `CostEstimate`. | `RiskVerdict`: aprobado o rechazado. | Rechazar ante incertidumbre. |
| **Máquina de Decisión** | Resolver prioridades y producir una sola transición válida. | Estado actual + `RiskVerdict` + eventos protectores. | `Decision` y próximo estado. | `HOLD/BLOCKED`; nunca dos acciones. |
| **Ledger de Decisiones** | Conservar inputs, versiones, razones, rechazos y transición para auditoría. | Todos los artefactos de la evaluación. | `DecisionRecord` inmutable. | Declarar trazabilidad incompleta y bloquear promoción. |
| **Validador Teórico** | Falsar contratos, invariantes y políticas con escenarios y fronteras. | Especificación + casos + supuestos. | `TestVerdict` PASS/FAIL por obligación. | FAIL explícito; no ajustar el criterio. |

### Flujo conceptual

```text
Observaciones del mercado → Sensor → RawMarketEvent
                                      ↓
                             Guardia de Calidad
                      DATA_BLOCKED ↙   ↓ QualifiedMarketFrame
                                  HOLD  ├→ Modelo Temporal → MarketContext
                                        └→ Modelo de Costos → CostEstimate

Observaciones de cuenta/posición → Custodio de Estado → PortfolioState
Mandato humano --------------------------------------→ RiskMandate

MarketContext + PortfolioState + CostEstimate
                      ↓
          Política de Oportunidad
          NO_INTENT ↙  ↓ CandidateIntent
                 HOLD  ↓
 Gobernador de Riesgo ← RiskMandate + PortfolioState + CostEstimate
 REJECTED ↙            ↓ RiskVerdict aprobado
      HOLD/EXIT     Máquina de Decisión
                         ↓
              ENTER_LONG | HOLD | EXIT_LONG
                         ↓
                Ledger → DecisionRecord → Validador Teórico
```

### Contratos mínimos independientes de tecnología

#### `QualifiedMarketFrame`

- `symbol`, `event_time`, `observed_at`, `sequence_or_identity`.
- Precio/bid/ask y barras cerradas necesarias para la política activa.
- Flags de completitud, freshness, gaps, duplicados y sincronización.
- Provenance y versión del esquema.

#### `PortfolioState`

- Posición conocida (`FLAT`/`LONG`), cantidad, precio de referencia y timestamp.
- Capital/equity conceptual disponible y exposición agregada.
- Estado de reconciliación, órdenes/fills pendientes y versión.
- `STATE_UNKNOWN` si dos observaciones autoritativas se contradicen.

#### `MarketContext`

- Horizonte y timestamp de decisión.
- Features causales con valor, unidad, ventana y timestamp máximo consumido.
- Estado de volatilidad/liquidez y calidad agregada.
- Razones explícitas si el contexto no es suficiente.

#### `CostEstimate`

- Acción, tamaño e horizonte hipotéticos a los que aplica.
- Fee, spread, slippage, impact y otros costos como rango, no punto optimista.
- Timestamp, fuente, supuestos y calidad de estimación.
- `COST_UNKNOWN` cuando no puede acotarse conservadoramente.

#### `CandidateIntent`

- `ENTRY_CANDIDATE`, `EXIT_CANDIDATE` o `NO_INTENT`.
- Hipótesis/política y versión.
- Evidencia a favor, condición de invalidación y expiración.
- Movimiento bruto esperado como hipótesis, nunca como hecho.

#### `RiskMandate`

- Capital conceptual disponible y exposición máxima.
- Riesgo máximo por decisión, pérdida agregada y condiciones de bloqueo.
- Restricciones de producto, dirección, liquidez y calidad de datos.
- Autoría humana y versión; una política no puede modificarlo.

#### `Decision`

- Una sola acción: `ENTER_LONG`, `HOLD` o `EXIT_LONG`.
- Estado anterior/siguiente, timestamp efectivo y expiración.
- Motivo principal, códigos de razones secundarias y evidencia referenciada.
- Política, contexto y mandato de riesgo versionados.
- Identidad idempotente para detectar repeticiones conceptualmente.

### Principios estructurales

1. **Policy-agnostic:** cambiar tendencia por reversión o ruptura no altera datos,
   riesgo, estados ni ledger.
2. **Riesgo no evadible:** la única ruta hacia una entrada atraviesa el Gobernador.
3. **Salida protectora prioritaria:** proteger una posición tiene precedencia sobre
   buscar una nueva oportunidad.
4. **Default seguro:** sin datos, contexto, mandato o estado reconciliado, `HOLD` y
   bloqueo de entrada.
5. **Determinismo:** una versión y los mismos inputs producen la misma decisión.
6. **Explicabilidad nativa:** la razón no se reconstruye después; nace con la
   decisión.
7. **Falsabilidad:** cada política declara qué evidencia futura la refutaría.
8. **Portabilidad:** la implementación posterior puede usar cualquier tecnología
   si preserva estos contratos e invariantes.

### Fuera de la frontera conceptual actual

- APIs concretas, clases, topics, tablas, frameworks y topología de despliegue.
- Adaptación a cualquier plataforma existente.
- Selección de una política ganadora o calibración de parámetros.
- Simulación, paper trading y ejecución real.

### Evidencia de cierre de T0.2

- La frontera responde qué observa, transforma, propone, bloquea, decide y explica.
- Cada responsabilidad tiene input, output y fallo seguro.
- La solución no contiene nombres ni restricciones de un flujo heredado.
- La integración futura puede diseñarse como adaptador sin cambiar el concepto.

## Auditoría de cobertura y cierre de Fase 0 — T0.5

### Hallazgos de la revisión

| Hallazgo | Severidad | Gap detectado | Resolución |
|---|---|---|---|
| F0-01 | Crítica | `PortfolioState` era consumido, pero nadie era responsable de producirlo o reconciliarlo. | Se añadió **Custodio de Estado** y contrato `PortfolioState`; estado desconocido bloquea entradas. |
| F0-02 | Crítica | Fees/slippage/impact podían quedar calculados por la propia Política, creando incentivo optimista. | Se añadió **Modelo de Costos y Liquidez** independiente y contrato `CostEstimate`; costo desconocido bloquea entradas. |
| F0-03 | Alta | El origen de producto/riesgo no estaba dentro ni fuera de la frontera con claridad. | `ProductMandate`/`RiskMandate` se declaran inputs externos de autoridad humana, gobernados por el decision log. |
| F0-04 | Media | `Decision` no tenía consumidor dentro del alcance documental. | Se declara output de frontera para supervisión y futura ejecución; el Ledger siempre lo consume antes de exportarlo. |
| F0-05 | Media | Fills/posición futura podían confundirse con datos de mercado. | Se separan observaciones de cuenta hacia Custodio y observaciones de mercado hacia Sensor. |

### Matriz necesidad → responsabilidad → contrato

| ID | Necesidad del objetivo | Responsable | Input | Output | Fallo seguro | Objetivos cubiertos |
|---|---|---|---|---|---|---|
| N-01 | Observar BTC/USDT sin interpretación | Sensor de Mercado | Observación externa de mercado | `RawMarketEvent` | `DATA_UNAVAILABLE` | O1, O2, O14 |
| N-02 | Distinguir datos utilizables de datos corruptos/stale | Guardia de Calidad | Evento raw + reloj | `QualifiedMarketFrame` | `DATA_BLOCKED` → `HOLD` | O1, O2 |
| N-03 | Conocer posición/capital y reconciliarlos | Custodio de Estado | Cuenta, posición, fills y decisiones previas | `PortfolioState` | `STATE_UNKNOWN` → bloquea entrada | O3, O5, O6, O7 |
| N-04 | Construir contexto causal en ventanas cerradas | Modelo Temporal | Frame calificado + historial permitido | `MarketContext` | `CONTEXT_INSUFFICIENT` | O1, O3, O4, O11 |
| N-05 | Acotar costos y liquidez sin sesgo de la política | Modelo de Costos y Liquidez | Frame + acción/tamaño/horizonte | `CostEstimate` | `COST_UNKNOWN` → bloquea entrada | O9, O10, O12, O13 |
| N-06 | Formular una oportunidad falsable | Política de Oportunidad | Contexto + estado + costo | `CandidateIntent` | `NO_INTENT` → `HOLD` | O9, O11, O12, O13 |
| N-07 | Aplicar autoridad y cotas de riesgo | Gobernador de Riesgo | Intent + mandato + estado + costo | `RiskVerdict` | Rechazo conservador | O5, O6, O10 |
| N-08 | Resolver una única acción y transición | Máquina de Decisión | Estado + verdict + eventos protectores | `Decision` | `HOLD/BLOCKED` | O3, O4, O7, O14 |
| N-09 | Explicar y reconstruir cada evaluación | Ledger de Decisiones | Artefactos N-01…N-08 | `DecisionRecord` | Promoción bloqueada | O8 |
| N-10 | Intentar falsar diseño y políticas | Validador Teórico | Specs + casos + records | `TestVerdict` | FAIL explícito | O1–O14 |
| N-11 | Definir producto, capital y tolerancia | Autoridad humana + Decision Log | Decisiones P0/P1 | `ProductMandate` + `RiskMandate` | Mandato ausente → bloquea entrada | O5, O10, O13 |

### Contabilidad de artefactos

| Artefacto | Productor único | Consumidores declarados | ¿Huérfano? |
|---|---|---|---|
| `RawMarketEvent` | Sensor | Guardia | No |
| `QualifiedMarketFrame` | Guardia | Modelo Temporal, Modelo de Costos, Ledger | No |
| `PortfolioState` | Custodio | Política, Gobernador, Máquina, Ledger | No |
| `MarketContext` | Modelo Temporal | Política, Ledger | No |
| `CostEstimate` | Modelo de Costos | Política, Gobernador, Ledger | No |
| `CandidateIntent` | Política | Gobernador, Ledger | No |
| `RiskVerdict` | Gobernador | Máquina, Ledger | No |
| `Decision` | Máquina | Ledger y boundary de supervisión/ejecución futura | No |
| `DecisionRecord` | Ledger | Validador y auditor humano | No |
| `TestVerdict` | Validador | Gate de diseño y veredicto final | No |
| `ProductMandate`/`RiskMandate` | Autoridad humana | Política cuando aplique, Gobernador, Máquina, Ledger | No |

### Fronteras explícitas

**Fuentes externas permitidas:** observaciones de mercado, observaciones de
cuenta/posición, reloj y mandatos humanos versionados.

**Output exportado:** `Decision` sólo después de pasar Máquina y Ledger. La futura
ejecución no forma parte del sistema conceptual validado en este ciclo.

**Feedback futuro:** fills y estado de cuenta retornan exclusivamente al Custodio;
nunca entran como precio o feature por el Sensor.

### Resultado del gate de Fase 0

- Necesidades cubiertas: **11/11**.
- Artefactos con productor y consumidor: **11/11**.
- Responsabilidades conceptuales sin output útil: **0**.
- Inputs internos sin productor: **0**.
- Dependencias de tecnología o arquitectura heredada: **0**.
- Blockers activos: **0**.
- Decisiones humanas P0 visibles y parametrizadas simbólicamente: **3/3**.

**Veredicto de Fase 0: `PASS_CONDITIONAL`.** La arquitectura puede avanzar al
contrato funcional usando mandatos simbólicos. D-001–D-003 deben resolverse antes
de congelar política, sizing o ejemplos numéricos definitivos; no bloquean la
coherencia conceptual actual.

### Evidencia de cierre de T0.5

- La auditoría encontró y resolvió dos gaps críticos en vez de autoaprobarse.
- Toda necesidad tiene exactamente un responsable primario y un fallo seguro.
- Todo artefacto tiene productor y consumidor o está declarado como boundary.
- La Fase 0 queda cerrada sin tecnología heredada ni decisiones humanas ocultas.

## Objetivo medible, principios y falsación — T0.3

### Objetivo de decisión

El agente no tiene como objetivo “adivinar el próximo precio” ni operar con la
máxima frecuencia. Su objetivo es:

> Convertir un contexto de mercado causal y confiable, una posición conocida y un
> mandato humano de riesgo en una única decisión oportuna, segura, explicable y
> económicamente defendible, absteniéndose cuando la evidencia no alcance.

El éxito se evalúa de forma **lexicográfica**, no con una suma que permita comprar
rentabilidad a cambio de romper seguridad:

1. **G0 — Integridad:** datos, tiempo, estado y mandato son válidos.
2. **G1 — Seguridad:** la acción respeta exposición, pérdida y prioridades.
3. **G2 — Validez decisional:** existe una sola transición determinista y auditable.
4. **G3 — Utilidad económica:** entre acciones que pasan G0–G2, preferir la de
   mayor utilidad neta conservadora.
5. **G4 — Eficiencia:** minimizar complejidad, turnover y datos innecesarios para
   utilidad equivalente.

Una candidata que falla G0, G1 o G2 queda excluida aunque prometa mayor retorno.
`HOLD` es el control seguro y siempre compite contra cualquier entrada o salida no
protectora.

### Función conceptual de utilidad

Sólo para decisiones elegibles después de los hard gates:

```text
R_net = R_gross
        - fees
        - spread
        - slippage
        - market_impact
        - otros_costos_aplicables

U(d, t) = E[R_net(d, t)]
          - λ_dd   · riesgo_drawdown
          - λ_tail · riesgo_cola
          - λ_turn · turnover
          - λ_unc  · incertidumbre_datos_modelo
```

Los pesos `λ` pertenecen al mandato humano y no se inventan en esta fase. La
fórmula es una regla de comparación futura, no una afirmación de que sea posible
estimar hoy `E[R_net]` con precisión.

### Scorecard de objetivos

| ID | Objetivo | Métrica conceptual | Dirección | Límite/gate | Evidencia futura requerida |
|---|---|---|---|---|---|
| O1 | Causalidad temporal | Inputs con timestamp posterior al instante de decisión | = 0 | Hard gate: cero look-ahead | Auditoría de features y replay con reloj controlado |
| O2 | Calidad de datos | Entradas emitidas con frame stale, incompleto o desincronizado | = 0 | Hard gate | Casos de gaps, retrasos, duplicados y reconexión |
| O3 | Totalidad | Estados relevantes sin decisión definida | = 0 | Hard gate | Tabla exhaustiva de estados y fronteras |
| O4 | Determinismo | Acciones distintas para mismos inputs, estado y versión | = 0 | Hard gate | Repetición y property tests futuros |
| O5 | Riesgo no evadible | Entradas sin `RiskMandate` válido o fuera de cota | = 0 | Hard gate | Pruebas adversariales del Gobernador |
| O6 | Estado reconciliado | Entradas con posición desconocida o contradictoria | = 0 | Hard gate | Escenarios de restart, fill parcial y desincronización |
| O7 | Idempotencia | Decisiones activables duplicadas para una identidad | = 0 | Hard gate | Replay duplicado y concurrencia futura |
| O8 | Auditabilidad | Decisiones sin inputs, versiones, razones o transición reconstruibles | = 0 | 100 % de registros completos | Revisión de ledger y replay explicativo |
| O9 | Utilidad neta | Retorno/utility neta después de todos los costos | > control `HOLD` por margen pre-registrado | Gate empírico futuro | Walk-forward OOS con costos conservadores |
| O10 | Downside | Drawdown, pérdida de cola y pérdida por decisión | ≤ mandato humano | Límite humano P0 | Replay OOS, stress y escenarios extremos |
| O11 | Robustez | Degradación y cambio de signo entre regímenes/folds | Dentro de gate pre-registrado | Gate empírico futuro | Múltiples periodos, purga, embargo y sensibilidad |
| O12 | Selectividad | Relación cobertura/calidad de decisiones | No maximizar frecuencia; frontera pre-registrada | Gate empírico futuro | Curvas coverage–precision–utility |
| O13 | Oportunidad | Costo de abstención de `HOLD` frente a candidatas seguras | Minimizar sin romper O1–O12 | Nunca supera hard gates | Comparación OOS contra política nula |
| O14 | Oportunidad temporal | Decisiones emitidas después de expirar su horizonte | = 0 | Límite dependiente del horizonte P0 | Medición end-to-end futura |

### Tipos de umbral

- **Hard gates congelados ahora:** O1–O7 tienen tolerancia cero. No son parámetros
  optimizables.
- **Mandato humano pendiente:** capital, pérdida, drawdown, producto y horizonte se
  registrarán como P0 en el decision log; no se adivinan.
- **Gates empíricos pendientes:** margen sobre `HOLD`, estabilidad, tamaño de
  muestra y sensibilidad se fijarán antes de abrir resultados OOS.
- **Métricas diagnósticas:** pueden explicar un fallo, pero nunca sustituir un hard
  gate incumplido.

### Principios de diseño

1. **Objetivo antes que estrategia:** primero se define qué debe demostrar una
   política; luego se crean candidatas.
2. **Seguridad lexicográfica:** retorno nunca compensa datos inválidos, riesgo sin
   cota o una transición ilegal.
3. **Causalidad verificable:** cada feature declara ventana y timestamp máximo.
4. **Abstención con significado:** `HOLD` es una decisión explícita con razón, no
   ausencia de respuesta.
5. **Separación de poderes:** Política propone; Gobernador limita; Máquina decide;
   Ledger registra; Validador intenta falsar.
6. **Una sola acción:** cada evaluación termina en exactamente una acción y un
   estado siguiente.
7. **Costos desde el origen:** ninguna política se evalúa primero “sin fricción”.
8. **Complejidad ganada:** cada dato, feature o parámetro adicional debe demostrar
   valor incremental fuera de muestra.
9. **Pre-registro:** hipótesis, parámetros permitidos, gates y motivos de rechazo se
   congelan antes de evaluar OOS.
10. **Falsación activa:** se buscan contraejemplos y regímenes hostiles, no sólo
    confirmaciones.
11. **Explicación contemporánea:** razones y evidencia nacen con la decisión.
12. **Soberanía humana:** producto, dirección, capital y tolerancia de pérdida no
    pueden ser elegidos ni ampliados por el agente.

### Condiciones de falsación

#### Falla de arquitectura (`ARCH_FAIL`)

La arquitectura queda refutada y debe corregirse si aparece cualquiera de estos
casos:

- A1. Un estado relevante no tiene salida o permite dos acciones simultáneas.
- A2. Una decisión necesita información futura o una vela no cerrada sin declararlo.
- A3. La Política puede ejecutar, modificar límites o evadir al Gobernador.
- A4. Datos stale/incompletos o posición desconocida pueden producir una entrada.
- A5. El mismo evento puede activar decisiones duplicadas.
- A6. No puede reconstruirse exactamente por qué y con qué versión se decidió.
- A7. Existe una trayectoria de exposición o pérdida sin cota conceptual.
- A8. Un fallo crítico no tiene estado seguro ni responsable único.

#### Falla de política (`POLICY_FAIL`)

Una política candidata se descarta —sin culpar a la arquitectura— si:

- P1. No declara mecanismo causal ni condición observable de invalidación.
- P2. Su oportunidad bruta no supera costos conservadores más buffer de
  incertidumbre.
- P3. No supera a `HOLD` bajo el gate OOS pre-registrado.
- P4. El efecto cambia de signo o colapsa fuera de un régimen sin abstención válida.
- P5. El tamaño de muestra efectivo es insuficiente.
- P6. Pequeñas variaciones razonables de parámetros destruyen el resultado.
- P7. Su valor depende de leakage, selección retrospectiva o fills inalcanzables.
- P8. Añade complejidad sin utilidad incremental OOS.

#### Falla del producto (`NO_GO`) o necesidad de `PIVOT`

El mandato completo termina en `NO_GO` o `PIVOT` si:

- M1. Todas las políticas honestas son dominadas por `HOLD` después de costos.
- M2. Los datos necesarios no pueden obtenerse con calidad o latencia suficientes.
- M3. El horizonte útil es menor que la latencia/costo realizable.
- M4. El riesgo requerido para capturar la oportunidad viola el mandato humano.
- M5. Las tres acciones no representan la decisión que realmente necesita el
  usuario.
- M6. Sólo puede “aprobarse” moviendo gates después de ver resultados.

`ARCH_FAIL`, `POLICY_FAIL` y `NO_GO` no son equivalentes: una arquitectura puede
ser válida aunque una política falle; varias políticas pueden fallar sin invalidar
el producto; pero si ninguna supera honestamente el control, no se fabrica una.

### Niveles de evidencia

| Nivel | Qué puede demostrar | Estado en este ciclo |
|---|---|---|
| T — Teórico | Coherencia, totalidad, causalidad, cotas, contratos y contraejemplos | En alcance |
| E — Empírico offline | Edge OOS, costos, estabilidad, sensibilidad y drawdown | Sólo se diseña el protocolo |
| S — Shadow/Paper | Latencia, calidad real, fills y comportamiento operativo | Fuera de alcance |
| L — Live | Resultado con capital y riesgo real | Prohibido en este objetivo |

Una conclusión T nunca se redacta como si fuera E, S o L.

### Evidencia de cierre de T0.3

- Hay una jerarquía de éxito que impide intercambiar seguridad por retorno.
- Los 14 objetivos declaran métrica, dirección, gate y evidencia pendiente.
- Los hard gates se congelaron; los límites humanos siguen explícitamente abiertos.
- Arquitectura, política y producto tienen condiciones de falsación separadas.
- Ninguna estrategia concreta fue favorecida antes de definir cómo puede fallar.

## Contrato funcional del producto — T1.1

### Supuestos contractuales

1. `symbol = BTC/USDT`, `product = SPOT`, `directions = LONG/FLAT` y
   `leverage = 0` son valores provisionales de D-001, no decisiones cerradas.
2. `H_decision` y `H_context` representan horizonte de decisión y contexto hasta
   que D-002 sea resuelta; ninguna regla sustituye esos símbolos en silencio.
3. `ProductMandate` y `RiskMandate` son inputs externos versionados. Si faltan, una
   nueva entrada no puede ser autorizada.
4. El producto definido aquí **decide y explica**. No coloca, cancela ni modifica
   órdenes, no custodia fondos y no maneja credenciales.
5. Una salida protectora puede evaluarse con mayor frecuencia que una oportunidad
   estratégica; esto no autoriza usar barras abiertas como señal estratégica.

### Actor primario y resultado esperado

**Actor primario:** operador humano de BTC que fija producto, dirección, horizonte
y riesgo; supervisa decisiones y conserva autoridad para habilitar cualquier fase
posterior.

**Resultado funcional:** ante una evaluación, el sistema devuelve exactamente una
acción (`ENTER_LONG`, `HOLD` o `EXIT_LONG`), su estado, vigencia, razones, evidencia
y trazabilidad. La ausencia de evidencia suficiente produce `HOLD`, no silencio ni
una predicción inventada.

### Actores y fronteras

| Actor/sistema | Responsabilidad | Puede decidir | No puede hacer en este alcance |
|---|---|---|---|
| **Autoridad humana** | Fijar `ProductMandate`, `RiskMandate` y decisiones P0. | Producto, dirección, capital, pérdida y promoción. | Delegar silenciosamente esos límites al agente. |
| **Entorno de mercado** | Proveer observaciones de precio, trades, bid/ask, barras y depth opcional. | Nada dentro del agente. | Autorizar una decisión. |
| **Sistema de decisión** | Validar, contextualizar, proponer, gobernar, resolver y explicar. | Una acción contractual dentro de los mandatos. | Ejecutar órdenes o ampliar mandatos. |
| **Operador/auditor** | Leer `DecisionRecord`, revisar bloqueos y aceptar/rechazar fases futuras. | Continuación del proceso de producto. | Alterar retrospectivamente evidencia de una decisión. |
| **Ejecutor futuro** | Traducir una `Decision` vigente a órdenes en otra fase. | Sólo mecánica de ejecución autorizada. | Reinterpretar política, riesgo o decisión; está fuera de alcance. |

### Inputs funcionales

| Input | Autoridad/productor | Requisito mínimo | Si falta o es inválido |
|---|---|---|---|
| `ProductMandate` | Humano | Símbolo, producto, direcciones y restricciones versionadas. | `HOLD/BLOCKED`; salida protectora permitida si existe posición conocida. |
| `RiskMandate` | Humano | Cotas de exposición/pérdida y vigencia. | Nunca `ENTER_LONG`. |
| `QualifiedMarketFrame` | Guardia | Causal, fresco, completo para la evaluación y sin gaps abiertos. | `HOLD/DATA_BLOCKED`. |
| `PortfolioState` | Custodio | Posición/capital conocidos y reconciliación válida. | `HOLD/STATE_UNKNOWN`; no nueva entrada. |
| `MarketContext` | Modelo Temporal | Horizonte, features y timestamp máximo consumido. | `HOLD/CONTEXT_INSUFFICIENT`. |
| `CostEstimate` | Modelo de Costos | Rango conservador aplicable a acción/tamaño/horizonte. | `HOLD/COST_UNKNOWN` para entrada. |
| `CandidateIntent` | Política | Hipótesis, evidencia, invalidación, expiración y versión. | `HOLD/NO_INTENT`. |
| `RiskVerdict` | Gobernador | Aprobación/rechazo, razones, sizing máximo y mandato usado. | Entrada bloqueada. |

### Triggers de evaluación

#### `STRATEGIC_EVALUATION`

- Ocurre en un límite definido por `H_decision` y usa únicamente información
  estratégicamente cerrada.
- Puede producir `ENTER_LONG`, `HOLD` o `EXIT_LONG`.
- Una repetición con la misma identidad y versiones debe ser idempotente.

#### `PROTECTIVE_EVALUATION`

- Ocurre ante cambio material de riesgo, posición, calidad, vigencia o condición de
  invalidación protectora.
- Puede producir `EXIT_LONG` o `HOLD/BLOCKED`; nunca iniciar una posición.
- Tiene prioridad sobre una evaluación estratégica concurrente.

### Separación de recomendación, autorización, decisión y ejecución

| Etapa | Responsable | Artefacto | Qué afirma | Qué no afirma |
|---|---|---|---|---|
| Observación | Sensor/Guardia | `QualifiedMarketFrame` | “Estos datos son utilizables bajo estas condiciones.” | Que exista una oportunidad. |
| Contexto | Modelo Temporal/Costos/Custodio | `MarketContext`, `CostEstimate`, `PortfolioState` | “Este es el estado causal, costo y posición conocidos.” | Qué acción tomar. |
| **Recomendación** | Política | `CandidateIntent` | “Esta hipótesis propone entrar/salir y así podría invalidarse.” | Que riesgo la autorice o que se ejecutará. |
| **Autorización** | Gobernador | `RiskVerdict` | “El intento cabe/no cabe en mandato y cotas actuales.” | Que sea la acción final ni que exista orden. |
| **Decisión** | Máquina | `Decision` | “Dadas prioridades y estados, ésta es la única acción vigente.” | Que haya sido ejecutada o llenada. |
| Evidencia | Ledger | `DecisionRecord` | “Esto ocurrió, con estos inputs, versiones y razones.” | Resultado económico futuro. |
| **Ejecución futura** | Fuera de frontera | `ExecutionRequest/Result` futuros | Traducción mecánica y resultado de orden. | Cambiar la decisión; no existe en este objetivo. |

### Acciones contractuales

#### `ENTER_LONG`

Propone transición `FLAT → LONG_PENDING` sólo cuando datos, estado, contexto,
costos, mandato e intento están vigentes y el Gobernador aprueba. No significa que
la posición ya exista; eso requiere una ejecución y reconciliación futuras.

#### `HOLD`

Mantiene el estado económico conocido. Debe incluir un motivo: `NO_INTENT`,
`RISK_REJECTED`, `DATA_BLOCKED`, `STATE_UNKNOWN`, `CONTEXT_INSUFFICIENT`,
`COST_UNKNOWN`, `DUPLICATE`, `COOLDOWN` u otra razón versionada. `BLOCKED` es un
status de `HOLD`, no una cuarta acción.

#### `EXIT_LONG`

Propone transición de una posición `LONG` hacia `EXIT_PENDING`. Puede originarse
por invalidación estratégica o protección de riesgo. Una salida protectora válida
tiene prioridad sobre entrada, cooldown y recomendación estratégica.

### Requisitos funcionales verificables

- **FR-001 — Mandato de instrumento:** toda evaluación referencia un
  `ProductMandate` versionado; no hay símbolo implícito.
- **FR-002 — Mandato de dirección:** una acción fuera de las direcciones permitidas
  es imposible de representar como decisión válida.
- **FR-003 — Reloj estratégico:** `STRATEGIC_EVALUATION` declara `H_decision`,
  instante efectivo y último timestamp consumido.
- **FR-004 — Reloj protector:** `PROTECTIVE_EVALUATION` nunca produce entrada y
  puede preemptar una evaluación estratégica.
- **FR-005 — Calidad fail-safe:** frame inválido/stale bloquea entrada.
- **FR-006 — Estado fail-safe:** posición desconocida o contradictoria bloquea
  entrada y crea razón de reconciliación.
- **FR-007 — Contexto causal:** ninguna feature estratégica supera el instante de
  decisión ni usa barra abierta sin declararla no estratégica.
- **FR-008 — Recomendación limitada:** la Política sólo produce `CandidateIntent`;
  no sizing definitivo, autorización, decisión ni orden.
- **FR-009 — Riesgo independiente:** sólo el Gobernador produce `RiskVerdict` y la
  Política no puede modificar su mandato.
- **FR-010 — Entrada gobernada:** `ENTER_LONG` requiere intent vigente, verdict
  aprobado, costo conocido, estado `FLAT` y ausencia de bloqueo prioritario.
- **FR-011 — Acción única:** cada evaluación produce exactamente una acción y una
  transición válida o explícitamente nula.
- **FR-012 — Prioridad protectora:** una salida protectora válida domina entrada,
  hold estratégico e intent concurrente.
- **FR-013 — Vigencia:** una decisión expirada no puede considerarse accionable.
- **FR-014 — Idempotencia:** repetir identidad+versiones no produce otra decisión
  activable.
- **FR-015 — Ledger obligatorio:** ninguna decisión se exporta antes de crear un
  `DecisionRecord` completo.
- **FR-016 — Ejecución separada:** ningún artefacto de esta fase constituye orden,
  fill, balance ni confirmación de posición.
- **FR-017 — Degradación segura:** input requerido ausente produce `HOLD/BLOCKED` o
  salida protectora; nunca una entrada por default.
- **FR-018 — Supuestos visibles:** D-001–D-003 permanecen referenciadas en toda
  regla que dependa de producto, horizonte o riesgo.

### Escenarios contractuales mínimos

| Escenario | Intent | Riesgo/estado | Decisión esperada |
|---|---|---|---|
| Entrada válida | `ENTRY_CANDIDATE` vigente | Aprobado, `FLAT`, costo/datos válidos | `ENTER_LONG` |
| Riesgo rechaza | `ENTRY_CANDIDATE` | `REJECTED` | `HOLD/RISK_REJECTED` |
| Datos stale | Cualquiera | `DATA_BLOCKED` | `HOLD/DATA_BLOCKED` |
| Posición desconocida | Cualquiera | `STATE_UNKNOWN` | `HOLD/STATE_UNKNOWN` |
| Protección con posición long | Cualquiera o ninguno | Evento protector válido, `LONG` | `EXIT_LONG` |
| Intent duplicado | Intent ya evaluado | Misma identidad/versiones | `HOLD/DUPLICATE` |
| Sin oportunidad | `NO_INTENT` | Sistema sano | `HOLD/NO_INTENT` |
| Decisión expirada | Intent/verdict previos | Fuera de vigencia | `HOLD/EXPIRED` |

### Límites funcionales

- No promete predecir retorno ni encontrar una política rentable.
- No resuelve todavía horizonte, capital, thresholds, sizing o tipo de orden.
- No ejecuta, simula, autentica ni se conecta a una cuenta.
- No convierte una captura, indicador o imbalance aislado en una decisión.
- No adapta contratos a una plataforma hasta superar el veredicto conceptual.

### Evidencia de cierre de T1.1

- Actor, objetivo, símbolo, producto, dirección y horizonte están definidos o
  referenciados como decisiones abiertas, nunca implícitos.
- Recomendación, autorización, decisión, evidencia y ejecución tienen propietarios
  y artefactos distintos.
- Los 18 requisitos son observables y falsables mediante casos posteriores.
- La ejecución queda fuera de frontera y no puede reinterpretar la decisión.
- D-001–D-003 continúan abiertas sin impedir el razonamiento simbólico.

## Glosario canónico, unidades y tiempo — T1.2

### Carácter normativo

Las definiciones de esta sección son la única semántica válida para el resto de la
especificación. Un término no puede cambiar de significado entre política, riesgo,
validación y futura implementación. Todo alias nuevo debe mapearse aquí o
rechazarse.

### Convención temporal UTC

1. Todos los instantes se expresan en **UTC**. La forma documental canónica es
   RFC 3339 con sufijo `Z`, por ejemplo `2026-09-15T17:46:00.000Z`.
2. Un transporte futuro puede usar Unix epoch en milisegundos, pero debe convertir
   sin pérdida a UTC y nombrar el campo con unidad explícita.
3. `event_time` es cuándo ocurrió el hecho en su fuente autoritativa.
4. `observed_at` es cuándo el sistema recibió/observó el hecho. Es el único nombre
   canónico; `ingest_time`, `received_at` y `arrival_time` quedan como aliases
   prohibidos salvo adaptación documentada en la frontera.
5. `decision_time` es cuándo la Máquina resolvió la evaluación.
6. `expires_at` es el primer instante en el que la decisión deja de ser vigente.
7. Una barra ocupa el intervalo semiabierto `[bar_open_time, bar_close_time)`.
8. Una barra sólo es `CLOSED` cuando la fuente la marca completa, no hay gap abierto
   y `decision_time ≥ bar_close_time`.
9. Para una decisión causal debe cumplirse:

```text
max(input.event_time) ≤ decision_time < expires_at
bar_close_time ≤ decision_time                 (features de barra cerrada)
event_time ≤ observed_at                       (salvo clock fault explícito)
```

10. Toda tolerancia de clock skew, latencia o staleness debe declarar valor y unidad;
    “tiempo real” sin límite temporal no es un requisito válido.

### Convención numérica y de unidades

- Cantidades monetarias y de activo se representan conceptualmente como decimales
  exactos; una futura implementación no debe introducir redondeo binario implícito.
- Los separadores de miles/decimales son sólo presentación. Los contratos usan
  punto decimal y no incluyen símbolos monetarios.
- Retornos, ratios y probabilidades se almacenan como fracción decimal: `0.01`
  significa 1 %. El porcentaje es sólo formato de presentación.
- Un basis point es `1 bp = 0.0001 = 0.01 %`.
- Toda métrica dependiente del horizonte incluye `H` o el timeframe en su metadata.
- Precio/cantidad se cuantizan únicamente al final contra `tick_size`/`step_size`;
  nunca durante el cálculo de features.

### Unidades canónicas para BTC/USDT provisional

| Magnitud | Símbolo/campo | Unidad canónica | Dominio/invariante |
|---|---|---|---|
| Precio | `price`, `bid`, `ask`, OHLC | USDT/BTC | Decimal > 0 |
| Cantidad base | `base_qty` | BTC | Decimal ≥ 0 |
| Notional quote | `quote_notional` | USDT | `price × base_qty` |
| Volumen base | `base_volume` | BTC por barra/ventana | ≥ 0 |
| Volumen quote | `quote_volume` | USDT por barra/ventana | ≥ 0 |
| Spread absoluto | `spread_abs` | USDT/BTC | `ask - bid ≥ 0` |
| Spread relativo | `spread_bps` | basis points | `10_000 × (ask-bid)/mid` |
| Retorno | `return_H` | fracción decimal por `H` | > -1 para long spot sin errores |
| Volatilidad | `volatility_H` | fracción por horizonte declarado | ≥ 0; nunca “anualizada” implícitamente |
| ATR | `atr_H` | USDT/BTC | ≥ 0; ventana/horizonte obligatorios |
| Fee | `fee_rate` | fracción del notional por lado | ≥ 0 |
| Slippage | `slippage_bps` | basis points por lado | Puede ser adverso; signo documentado |
| Imbalance | `imbalance` | ratio adimensional | Convención fija `[-1, 1]` |
| Confianza | `confidence` | ratio `[0, 1]` | Sólo si tiene interpretación calibrada |
| Tiempo | `*_time`, `*_at` | instante UTC | RFC3339 docs / epoch ms transporte |
| Duración | `*_ms` o duración ISO 8601 | milisegundos o ISO 8601 | Unidad siempre en nombre/schema |

### Glosario

| Término canónico | Definición única | No confundir con |
|---|---|---|
| **Acción (`action`)** | Uno de `ENTER_LONG`, `HOLD`, `EXIT_LONG` emitido por la Máquina. | Intent, orden o fill. |
| **Ask** | Menor precio visible al que un vendedor ofrece cantidad en el alcance definido. | Precio ejecutado o costo total. |
| **ATR** | Promedio de true range sobre ventana y timeframe declarados, en unidad de precio. | Volatilidad porcentual. |
| **Barra cerrada** | Agregado OHLCV completo para `[open, close)`, marcado cerrado y sin gap conocido. | Barra en formación. |
| **Bid** | Mayor precio visible al que un comprador ofrece cantidad en el alcance definido. | Precio ejecutado o señal alcista. |
| **CandidateIntent** | Propuesta falsable de la Política: entrar, salir o no proponer, con evidencia e invalidación. | Decisión o autorización. |
| **Close (`close_price`)** | Último precio elegible dentro de una barra cerrada según la fuente. | `last_trade_price` actual. |
| **Confidence** | Medida con semántica calibrada y población de referencia explícitas. | Score arbitrario o probabilidad sin calibrar. |
| **CostEstimate** | Rango conservador versionado de fees, spread, slippage, impact y otros costos para acción/tamaño/horizonte. | Costo observado final. |
| **Decision** | Única acción resuelta por la Máquina, con estado, vigencia, razones y referencias. | CandidateIntent, orden o fill. |
| **DecisionRecord** | Evidencia inmutable necesaria para reconstruir una evaluación y su decisión. | Log textual incompleto. |
| **Decision time** | Instante UTC en que la Máquina resolvió la evaluación. | Event time u observed_at. |
| **Depth** | Cantidad ofertada por lado y nivel dentro de alcance y snapshot/secuencia definidos. | Liquidez ejecutable garantizada. |
| **Event time** | Instante UTC autoritativo en que ocurrió un hecho. | Momento de recepción. |
| **Execution** | Proceso futuro que traduce una Decision vigente a órdenes y recibe resultados. | Decisión. Está fuera del alcance actual. |
| **Feature** | Transformación causal y versionada de inputs, con fórmula, ventana, unidad y timestamp máximo. | Evidencia de edge por sí sola. |
| **Fill** | Confirmación de ejecución de una cantidad a un precio, con fee y timestamp. | Orden enviada o Decision. |
| **Fresh** | Dato cuya edad y secuencia cumplen el límite explícito de su consumidor. | “Reciente” sin umbral. |
| **Gap** | Ausencia detectada en una secuencia o intervalo esperado que rompe completitud. | Periodo sin trades legítimo. |
| **H_context** | Horizonte de historia usado para construir contexto. | Frecuencia de decisión. |
| **H_decision** | Horizonte económico y reloj en que se evalúa una política estratégica. | Latencia del sistema. |
| **HOLD** | Acción explícita que conserva estado económico y siempre incluye reason code. | Ausencia de respuesta. |
| **Imbalance** | Diferencia normalizada entre cantidades bid/ask bajo niveles, nocional y tiempo definidos. | Presión ejecutada o dirección futura. |
| **Kline** | Representación de una barra OHLCV provista por una fuente; sólo es utilizable estratégicamente si está cerrada. | Trade individual. |
| **Last trade price** | Precio del trade elegible más reciente por event_time. | Mid, bid, ask o close. |
| **MarketContext** | Snapshot causal versionado de features, régimen descriptivo, calidad y horizonte. | Predicción o Decision. |
| **Mid** | `(bid + ask) / 2` para bid/ask válidos del mismo frame. | Precio necesariamente ejecutable. |
| **Notional** | Valor quote de cantidad base a un precio declarado. | Equity o riesgo máximo. |
| **OHLCV** | Open, high, low, close y volumen de una barra con unidad/fuente explícitas. | Serie de ticks sin agregado. |
| **Order** | Instrucción futura a un venue con lado, tipo, cantidad, precio/condiciones e identidad. | Decision o Fill. |
| **Policy** | Hipótesis versionada que transforma contexto/estado/costo en CandidateIntent. | Gobernador, Máquina o estrategia ejecutora. |
| **PortfolioState** | Vista reconciliada y versionada de posición, capital, exposición y pendientes conocidos. | Balance aislado o Decision previa. |
| **Position** | Exposición económica confirmada; provisionalmente `FLAT` o `LONG` con cantidad y referencia. | Orden pendiente. |
| **Price (`price`)** | Valor de intercambio que siempre especifica clase: bid, ask, mid, trade u OHLC. | “Precio actual” sin clase. |
| **ProductMandate** | Restricciones humanas versionadas de símbolo, producto, dirección y capacidades. | Configuración inferida por el agente. |
| **QualifiedMarketFrame** | Conjunto sincronizado de observaciones que pasó controles de calidad para un uso/horizonte. | Evento raw individual. |
| **RawMarketEvent** | Observación normalizada pero aún no calificada procedente del mercado. | Dato seguro para decidir. |
| **Return_H** | `P(t)/P(t-H)-1` con precio, horizonte y timestamps declarados. | PnL de una posición. |
| **RiskMandate** | Cotas humanas versionadas de exposición, pérdida, drawdown y bloqueos. | RiskVerdict. |
| **RiskVerdict** | Resultado del Gobernador para un intent concreto: aprobado/rechazado y cotas aplicables. | Decision final. |
| **Signal** | Evidencia direccional intermedia definida por fórmula; término desaconsejado si no tiene contrato propio. | CandidateIntent o Decision. |
| **Slippage** | Diferencia entre precio de referencia declarado y precio ejecutado/estimado atribuible a ejecución. | Spread o fee. |
| **Spread** | Diferencia ask-bid del mismo frame; absoluto o bps según campo. | Costo round-trip completo. |
| **Stale** | Dato cuya edad, secuencia o vigencia excede un límite explícito. | Dato simplemente antiguo en pantalla. |
| **Symbol** | Par ordenado base/quote; provisionalmente BTC/USDT. | Producto Spot/Futures. |
| **Tick size** | Incremento mínimo permitido de precio para un producto/venue. | Spread observado. |
| **Trade** | Ejecución de mercado observada con precio, cantidad y event_time. | Order book quote. |
| **Turnover** | Notional negociado agregado dividido por capital/base de comparación declarada. | Número de decisiones. |
| **Volume** | Cantidad agregada de trades ejecutados en base o quote durante ventana declarada. | Depth u órdenes no ejecutadas. |
| **Volatility_H** | Dispersión de retornos bajo estimador, ventana y horizonte declarados. | ATR o volumen. |

### Términos ambiguos prohibidos

| Expresión prohibida sin calificador | Forma exigida |
|---|---|
| “precio actual” | `last_trade_price`, `bid`, `ask`, `mid` o `close_price` + timestamp |
| “volumen alto” | `base_volume`, `quote_volume`, ratio o z-score + ventana/umbral |
| “tendencia fuerte” | Feature, fórmula, ventana, dirección y threshold explícitos |
| “mercado volátil” | `volatility_H` o `atr_H` + estimador/umbral |
| “spread bajo” | `spread_bps ≤ threshold_bps` bajo frame/tamaño declarados |
| “en tiempo real” | Latencia/staleness máxima con unidad y percentil objetivo |
| “confianza alta” | Métrica calibrada, población y threshold registrados |
| “señal de compra” | Feature → CandidateIntent → RiskVerdict → Decision, sin saltos |
| “entrada” | Aclarar intent, Decision, Order o Fill |
| “salida” | Aclarar intent, Decision, Order, Fill o posición reconciliada |
| “ganancia” | Return, PnL bruto/neto o utility; moneda, periodo y costos explícitos |

### Invariantes semánticos

- `bid ≤ ask`; si no, el frame es incoherente hasta explicar venue/timestamps.
- `low ≤ open, close ≤ high` para una barra válida.
- `base_volume ≥ 0`, `quote_volume ≥ 0`, `spread_abs ≥ 0`.
- `Decision ≠ Order ≠ Fill ≠ Position`.
- `CandidateIntent ≠ RiskVerdict ≠ Decision`.
- `HOLD` siempre tiene reason code; `BLOCKED` es status, no acción.
- Una Policy nunca produce `RiskVerdict`; el Gobernador nunca inventa intent.
- Una cifra sin unidad, horizonte o timestamp requerido no pasa a contrato.
- Display local puede formatear números/zonas; el ledger conserva decimal canónico
  y UTC.

### Evidencia de cierre de T1.2

- Precio, bid/ask, spread, kline, feature, signal, decisión, posición, orden y fill
  tienen una sola definición y están diferenciados.
- UTC, event/observed/decision/expiry time y cierre de barra son normativos.
- Unidades de precio, cantidad, notional, retorno, volatilidad, costos y duración
  están fijadas.
- Se prohíben aliases y frases que oculten unidad, ventana, clase de precio o etapa.
- Los invariantes permiten detectar contradicciones semánticas en fases posteriores.

## Máquina de estados jerárquica — T1.3

### Decisión de modelado

Una lista plana mezclaría posición económica, evaluación temporal y salud de los
datos. El estado canónico es un vector de tres dimensiones:

```text
SystemState = (PositionState, EvaluationState, HealthState)
```

Cada dimensión tiene un único dueño conceptual y sólo cambia mediante eventos
documentados. Una “candidata” nunca equivale a posición ni fill.

### Dimensión 1 — `PositionState`

| Estado | Definición | Invariante |
|---|---|---|
| `UNKNOWN` | La posición autoritativa no está reconciliada o existen fuentes contradictorias. | Nunca permite entrada; health = `BLOCKED`. |
| `FLAT` | Está confirmado que la exposición BTC objetivo es cero. | Cantidad confirmada = 0; puede evaluar entrada si todo lo demás está listo. |
| `ENTRY_PENDING` | Existe `ENTER_LONG` registrada y vigente esperando resultado futuro de ejecución/reconciliación. | No equivale a `LONG`; no permite otra entrada. |
| `LONG` | Existe exposición BTC positiva confirmada y cuantificada. | Cantidad > 0 y referencia/observed_at conocidos. |
| `EXIT_PENDING` | Existe `EXIT_LONG` registrada y vigente para reducir/cerrar una posición confirmada. | No equivale a `FLAT`; conserva cantidad residual conocida. |

### Dimensión 2 — `EvaluationState`

| Estado | Definición | Combinaciones permitidas |
|---|---|---|
| `IDLE` | No hay hipótesis transitoria esperando resolución. | Cualquier PositionState. |
| `ENTRY_CANDIDATE` | Una Política propuso entrar; aún no hay autorización ni Decision. | Sólo `FLAT + READY`. |
| `EXIT_CANDIDATE` | Hay propuesta de salida estratégica o protectora; aún no es fill. | Sólo `LONG`; health puede ser READY/DEGRADED/BLOCKED si el trigger protector es autoritativo. |
| `COOLDOWN` | Ventana temporal que impide nuevas entradas tras evento definido. | Sólo `FLAT`; no impide reconciliación. |

### Dimensión 3 — `HealthState`

| Estado | Definición | Acciones permitidas |
|---|---|---|
| `READY` | Mandatos vigentes, estado conocido y datos suficientes para el uso solicitado. | Entrada, hold o salida según guards. |
| `DEGRADED` | Parte de la información perdió calidad, pero posición y riesgo protector siguen interpretables. | Hold o salida; nunca entrada. |
| `BLOCKED` | Falta mandato, posición reconciliada, schema conocido o calidad mínima segura. | Hold; salida protectora sólo con posición y trigger autoritativos suficientes. |

`BLOCKED` y `DEGRADED` son estados de salud, no acciones. La acción contractual
sigue siendo `HOLD` o, en condiciones protectoras explícitas, `EXIT_LONG`.

### Configuraciones válidas principales

| Position | Evaluation | Health | Significado |
|---|---|---|---|
| `UNKNOWN` | `IDLE` | `BLOCKED` | Inicio o conflicto de reconciliación. |
| `FLAT` | `IDLE` | `READY` | Puede buscar oportunidad de entrada. |
| `FLAT` | `ENTRY_CANDIDATE` | `READY` | Intent de entrada en evaluación. |
| `FLAT` | `COOLDOWN` | `READY/DEGRADED` | Entrada temporalmente prohibida. |
| `ENTRY_PENDING` | `IDLE` | `READY/DEGRADED/BLOCKED` | Espera feedback; no duplica entrada. |
| `LONG` | `IDLE` | `READY` | Puede mantener o evaluar salida. |
| `LONG` | `IDLE` | `DEGRADED/BLOCKED` | No aumenta exposición; conserva vía protectora condicionada. |
| `LONG` | `EXIT_CANDIDATE` | `READY/DEGRADED/BLOCKED` | Salida en evaluación. |
| `EXIT_PENDING` | `IDLE` | `READY/DEGRADED/BLOCKED` | Espera feedback de cierre/reducción. |
| `FLAT` | `IDLE` | `DEGRADED/BLOCKED` | Sólo hold hasta recuperación. |

Cualquier combinación no listada es inválida y produce transición a
`(UNKNOWN, IDLE, BLOCKED)` con razón `INVALID_STATE_COMBINATION`, salvo que una
regla más conservadora mantenga una posición confirmada para permitir salida.

### Eventos canónicos

| Familia | Eventos | Autoridad |
|---|---|---|
| Reconciliación | `POSITION_SYNC_FLAT`, `POSITION_SYNC_LONG`, `POSITION_CONFLICT` | Custodio de Estado |
| Calidad | `QUALITY_READY`, `QUALITY_DEGRADED`, `QUALITY_BLOCKED`, `UNKNOWN_SCHEMA` | Guardia |
| Evaluación | `STRATEGIC_TICK`, `PROTECTIVE_TRIGGER`, `NO_INTENT`, `ENTRY_INTENT`, `EXIT_INTENT` | Reloj/Política/Riesgo |
| Gobierno | `RISK_APPROVED`, `RISK_REJECTED`, `MANDATE_EXPIRED` | Gobernador/autoridad humana |
| Decisión | `DECISION_RECORDED`, `DECISION_EXPIRED`, `DUPLICATE_IDENTITY` | Máquina/Ledger |
| Feedback futuro | `ENTRY_FILLED`, `EXIT_PARTIAL`, `EXIT_FILLED`, `EXECUTION_REJECTED`, `EXECUTION_CANCELLED` | Custodio mediante fuente autoritativa futura |
| Control | `COOLDOWN_STARTED`, `COOLDOWN_EXPIRED` | Máquina bajo regla versionada |

### Orden de precedencia

Si llegan eventos concurrentes se resuelven en este orden, sin usar “último en
llegar gana”:

1. Conflicto/reconciliación autoritativa de posición.
2. Trigger protector para una posición confirmada.
3. Bloqueo de calidad o expiración de mandato.
4. Fill/rechazo/cancelación autoritativos de una decisión pendiente.
5. Expiración o duplicado de decisión.
6. Salida estratégica.
7. Entrada estratégica.
8. `NO_INTENT`/self-loop de hold.

Un evento de menor prioridad no puede revertir otro de mayor prioridad dentro del
mismo `decision_time`.

### Tabla de transiciones

Notación: `P/E/H` = Position/Evaluation/Health. “—” mantiene la dimensión actual.

| ID | Estado actual | Evento | Guarda | Acción/efecto | Estado siguiente |
|---|---|---|---|---|---|
| SM-001 | `UNKNOWN/IDLE/BLOCKED` | `POSITION_SYNC_FLAT` | Fuente autoritativa y cantidad = 0 | Reconciliar; `HOLD/STATE_RECOVERED` | `FLAT/IDLE/BLOCKED` |
| SM-002 | `UNKNOWN/IDLE/BLOCKED` | `POSITION_SYNC_LONG` | Cantidad > 0 y referencia válida | Reconciliar; `HOLD/STATE_RECOVERED` | `LONG/IDLE/BLOCKED` |
| SM-003 | Cualquiera | `POSITION_CONFLICT` | Dos verdades incompatibles | Invalidar candidates; `HOLD/STATE_UNKNOWN` | `UNKNOWN/IDLE/BLOCKED` |
| SM-004 | `FLAT/IDLE/BLOCKED` | `QUALITY_READY` | Mandatos vigentes y estado reconciliado | `HOLD/READY` | `FLAT/IDLE/READY` |
| SM-005 | `LONG/IDLE/BLOCKED` | `QUALITY_READY` | Mandatos vigentes y estado reconciliado | `HOLD/READY` | `LONG/IDLE/READY` |
| SM-006 | `P/*/READY` | `QUALITY_DEGRADED` | `P` conocido | Cancelar candidate; bloquear entrada | `P/IDLE/DEGRADED` |
| SM-007 | `P/IDLE/DEGRADED` | `QUALITY_READY` | Todas las causas resueltas | `HOLD/READY` | `P/IDLE/READY` |
| SM-008 | `P/*/*` | `QUALITY_BLOCKED` o `MANDATE_EXPIRED` | `P` conocido | Cancelar candidate; no entrada | `P/IDLE/BLOCKED` |
| SM-009 | `FLAT/IDLE/READY` | `STRATEGIC_TICK + NO_INTENT` | Frame/context válidos | `HOLD/NO_INTENT` | `FLAT/IDLE/READY` |
| SM-010 | `FLAT/IDLE/READY` | `ENTRY_INTENT` | Intent vigente y costo conocido | Registrar candidate, sin Decision | `FLAT/ENTRY_CANDIDATE/READY` |
| SM-011 | `FLAT/ENTRY_CANDIDATE/READY` | `RISK_REJECTED` | Verdict corresponde al intent | `HOLD/RISK_REJECTED` | `FLAT/IDLE/READY` |
| SM-012 | `FLAT/ENTRY_CANDIDATE/READY` | `DECISION_EXPIRED` o pérdida de guard | Antes de Decision exportada | Cancelar candidate; `HOLD/EXPIRED` | `FLAT/IDLE/DEGRADED` o `BLOCKED` según causa |
| SM-013 | `FLAT/ENTRY_CANDIDATE/READY` | `RISK_APPROVED + DECISION_RECORDED` | FR-010 completo | Emitir `ENTER_LONG` una vez | `ENTRY_PENDING/IDLE/READY` |
| SM-014 | `ENTRY_PENDING/IDLE/*` | `STRATEGIC_TICK`, `ENTRY_INTENT` o duplicado | Feedback pendiente | `HOLD/PENDING_OR_DUPLICATE` | Sin cambio |
| SM-015 | `ENTRY_PENDING/IDLE/*` | `ENTRY_FILLED` | Fill autoritativo, cantidad > 0 | Reconciliar exposición | `LONG/IDLE/—` |
| SM-016 | `ENTRY_PENDING/IDLE/*` | `EXECUTION_REJECTED`, `CANCELLED` o expiración sin fill | Cantidad confirmada = 0 | `HOLD/ENTRY_NOT_FILLED`; iniciar cooldown | `FLAT/COOLDOWN/—` |
| SM-017 | `FLAT/COOLDOWN/*` | `COOLDOWN_EXPIRED` | Tiempo monotónico y causa resuelta | `HOLD/COOLDOWN_DONE` | `FLAT/IDLE/—` |
| SM-018 | `FLAT/COOLDOWN/*` | `STRATEGIC_TICK` o `ENTRY_INTENT` | Cooldown vigente | `HOLD/COOLDOWN` | Sin cambio |
| SM-019 | `LONG/IDLE/READY` | `STRATEGIC_TICK + NO_INTENT` | Posición reconciliada | `HOLD/NO_INTENT` | Sin cambio |
| SM-020 | `LONG/IDLE/READY` | `EXIT_INTENT` | Intent vigente | Registrar candidate, sin Decision | `LONG/EXIT_CANDIDATE/READY` |
| SM-021 | `LONG/*/*` | `PROTECTIVE_TRIGGER` | Trigger autoritativo y posición conocida | Preemptar evaluación menor | `LONG/EXIT_CANDIDATE/—` |
| SM-022 | `LONG/EXIT_CANDIDATE/READY` | `RISK_REJECTED` o intent inválido | Sólo salida estratégica no protectora | `HOLD/EXIT_REJECTED` | `LONG/IDLE/READY` |
| SM-023 | `LONG/EXIT_CANDIDATE/*` | `DECISION_RECORDED` | Salida aprobada o protectora válida | Emitir `EXIT_LONG` una vez | `EXIT_PENDING/IDLE/—` |
| SM-024 | `EXIT_PENDING/IDLE/*` | `EXIT_PARTIAL` | Orden sigue activa y residual > 0 | Actualizar `PortfolioState`; no duplicar | `EXIT_PENDING/IDLE/—` |
| SM-025 | `EXIT_PENDING/IDLE/*` | `EXIT_FILLED` | Cantidad residual confirmada = 0 | Reconciliar flat; iniciar cooldown | `FLAT/COOLDOWN/—` |
| SM-026 | `EXIT_PENDING/IDLE/*` | Rechazo/cancelación/expiración con residual > 0 | Posición residual conocida | Reevaluar protección; no fingir flat | `LONG/EXIT_CANDIDATE/DEGRADED` |
| SM-027 | `LONG/*/*` | `POSITION_SYNC_FLAT` inesperado | Fuente autoritativa | Reconciliar y registrar anomalía | `FLAT/COOLDOWN/DEGRADED` |
| SM-028 | `FLAT/*/*` | `POSITION_SYNC_LONG` inesperado | Fuente autoritativa | Reconciliar; bloquear nuevas acciones | `LONG/IDLE/BLOCKED` |
| SM-029 | Cualquiera | `DUPLICATE_IDENTITY` | Identidad+versiones ya registradas | `HOLD/DUPLICATE`; no exportar | Sin cambio |
| SM-030 | Cualquiera | Evento conocido no aplicable | Schema válido; sin guarda satisfecha | `HOLD/NO_STATE_CHANGE` | Sin cambio |
| SM-031 | Cualquiera | `UNKNOWN_SCHEMA` o combinación inválida | No puede interpretarse con seguridad | Cancelar evaluation; bloquear | `P/IDLE/BLOCKED`, o `UNKNOWN/IDLE/BLOCKED` si `P` no es confiable |

En la tabla, `—` sólo conserva una dimensión si sus invariantes siguen válidos; si
no, SM-003/SM-031 prevalece.

### Transiciones explícitamente prohibidas

- `UNKNOWN → ENTRY_CANDIDATE` o `ENTRY_PENDING`.
- `FLAT → LONG` sin `ENTRY_FILLED` o reconciliación autoritativa.
- `LONG → FLAT` sin `EXIT_FILLED` o reconciliación autoritativa.
- `ENTRY_CANDIDATE → LONG` y `EXIT_CANDIDATE → FLAT` directamente.
- `DEGRADED/BLOCKED → ENTRY_CANDIDATE`.
- `COOLDOWN → ENTRY_CANDIDATE` antes de `COOLDOWN_EXPIRED`.
- `ENTRY_PENDING → ENTRY_CANDIDATE` o segunda `ENTER_LONG`.
- `EXIT_PENDING → ENTRY_CANDIDATE` mientras exista exposición/pending desconocido.
- `FLAT → EXIT_CANDIDATE` y `LONG → ENTRY_CANDIDATE` bajo mandato long-only.
- Candidate vigente después de cambio de calidad, mandato, estado o versión.
- Decision expirada o duplicada → transición económica.
- Política → cambio directo de PositionState, HealthState o RiskMandate.
- Gobernador → Order/Fill/Position; sólo produce `RiskVerdict`.
- Ejecutor futuro → reinterpretar action/reason; sólo reporta feedback.
- `BLOCKED` como cuarta acción o sin reason code.

### Totalidad y determinismo

1. Las 10 configuraciones válidas tienen comportamiento para reconciliación,
   calidad, intent, riesgo, feedback, expiración y cooldown.
2. SM-030 cubre eventos **conocidos pero no aplicables** mediante self-loop seguro.
3. SM-031 cubre eventos desconocidos/combinaciones inválidas mediante bloqueo; no
   los oculta como self-loop benigno.
4. La precedencia resuelve concurrencia sin depender del orden de llegada.
5. Para `(state, event, guards, versions)` existe como máximo una transición.
6. Toda transición económica requiere evidencia autoritativa: Decision no equivale
   a Fill y Pending no equivale a posición final.

### Escenarios de frontera de T1.3

| Caso | Estado inicial | Eventos concurrentes | Resultado obligatorio |
|---|---|---|---|
| Entrada y calidad degradada | `FLAT/ENTRY_CANDIDATE/READY` | Approval + `QUALITY_DEGRADED` | SM-006/precedencia 3: cancelar; nunca `ENTER_LONG` |
| Entrada duplicada | `ENTRY_PENDING/IDLE/READY` | Tick + mismo intent | SM-014/029: hold, una sola exportación |
| Salida protectora durante intent de entrada imposible | `LONG/IDLE/READY` | `ENTRY_INTENT` + protector | SM-021: `EXIT_CANDIDATE` |
| Fill parcial de salida | `EXIT_PENDING/IDLE/READY` | `EXIT_PARTIAL` | Sigue pending con residual reconciliado |
| Cancelación de salida con residual | `EXIT_PENDING/IDLE/READY` | cancel | `LONG/EXIT_CANDIDATE/DEGRADED` |
| Estado externo contradictorio | Cualquiera | `POSITION_CONFLICT` | `UNKNOWN/IDLE/BLOCKED` |
| Evento de schema desconocido | Cualquiera | `UNKNOWN_SCHEMA` | SM-031, nunca ignorar ni entrar |

### Evidencia de cierre de T1.3

- Position, Evaluation y Health están separados y tienen invariantes propios.
- `FLAT`, `ENTRY_CANDIDATE`, `LONG`, `EXIT_CANDIDATE`, `COOLDOWN`, `DEGRADED` y
  `BLOCKED` tienen semántica no ambigua.
- Hay 31 transiciones con guarda, efecto y estado siguiente.
- Quince clases de transición ilegal están prohibidas explícitamente.
- Concurrencia, eventos irrelevantes y schemas desconocidos tienen resolución
  determinista y fail-safe.
- `ENTER_LONG`/`EXIT_LONG` conducen a pending; sólo feedback autoritativo cambia la
  posición confirmada.

## Contratos de decisión — T1.4

### Principio

`Decision` expresa una transición económica deseada y explicada. No es una orden,
no garantiza fill y no cambia `PortfolioState`. Sólo feedback autoritativo futuro
puede confirmar la posición resultante.

### Envelope común `Decision`

| Campo | Tipo conceptual | Obligatorio | Regla |
|---|---|---:|---|
| `schema_version` | string semver | Sí | Versiona semántica y serialización. |
| `decision_id` | hash determinista | Sí | Derivado de identidad y versiones; nunca aleatorio. |
| `evaluation_id` | string/hash | Sí | Identifica trigger y frontera temporal evaluada. |
| `action` | enum | Sí | Exactamente `ENTER_LONG`, `HOLD` o `EXIT_LONG`. |
| `disposition` | enum | Sí | `ACTIONABLE`, `NO_CHANGE` o `BLOCKED`. |
| `priority_class` | enum ordenado | Sí | Resuelve concurrencia según tabla de prioridad. |
| `trigger_type` | enum | Sí | `STRATEGIC_EVALUATION` o `PROTECTIVE_EVALUATION`. |
| `symbol` | base/quote | Sí | Provisionalmente `BTC/USDT`; tomado de ProductMandate. |
| `product_mandate_version` | version ref | Sí | Producto/direcciones vigentes usados. |
| `risk_mandate_version` | version ref/null | Sí | `null` sólo permite hold/bloqueo o salida protectora admisible. |
| `policy_id` / `policy_version` | ref/null | Sí | `null` permitido para hold sistémico o protección no estratégica. |
| `state_before` | `SystemState` ref | Sí | Vector P/E/H y versión evaluados. |
| `target_position` | objeto | Sí | Objetivo económico; nunca campos de orden. |
| `primary_reason` | enum | Sí | Una y sólo una razón primaria. |
| `reason_codes` | lista ordenada | Sí | Incluye primaria; sin duplicados; orden normativo. |
| `evidence_refs` | lista ordenada | Sí | Contexto, intent, verdict, calidad y costo aplicables. |
| `event_time_max` | UTC | Sí | Mayor event_time consumido. |
| `decision_time` | UTC | Sí | Input explícito del reloj; no `now()` interno. |
| `effective_at` | UTC | Sí | Primer instante de vigencia; `≥ decision_time`. |
| `expires_at` | UTC | Sí | Primer instante no vigente; `> effective_at`. |
| `supersedes_decision_id` | ref/null | Sí | Reemplazo explícito; no inferido por llegada. |
| `quality_status` | enum | Sí | `READY`, `DEGRADED` o `BLOCKED` coherente con state. |
| `ledger_precondition` | enum | Sí | Debe ser `RECORD_BEFORE_EXPORT`. |

Campos expresamente excluidos: `order_type`, `limit_price`, `time_in_force`, venue,
client order id, fill price y fee realizado. Pertenecen a ejecución futura.

### `target_position`

```text
TargetPosition = {
  mode: ABSOLUTE | UNCHANGED,
  asset: BTC,
  direction: FLAT | LONG | UNKNOWN,
  base_quantity: Decimal | null,
  source: RISK_VERDICT | CURRENT_RECONCILED_STATE | PROTECTIVE_FULL_EXIT,
  portfolio_state_version: string
}
```

Reglas:

- `ENTER_LONG`: `mode=ABSOLUTE`, `direction=LONG`, cantidad > 0 y no superior a la
  cota aprobada por `RiskVerdict`.
- `HOLD` con estado conocido: `mode=UNCHANGED`, cantidad y dirección coinciden con
  `PortfolioState`.
- `HOLD/STATE_UNKNOWN`: `mode=UNCHANGED`, `direction=UNKNOWN`, cantidad `null`.
- `EXIT_LONG`: `mode=ABSOLUTE`, `direction=FLAT`, cantidad objetivo = 0.
- Target describe estado económico deseado después de ejecución/reconciliación;
  no afirma que ya se alcanzó.

### Precedencia de decisiones

Menor ordinal significa mayor prioridad:

| Clase | Ordinal | Acción posible | Ejemplos |
|---|---:|---|---|
| `P0_RECONCILIATION_BLOCK` | 0 | `HOLD` | Position conflict, schema desconocido. |
| `P1_PROTECTIVE_EXIT` | 1 | `EXIT_LONG` | Cota de riesgo, invalidación protectora, mandato revocado. |
| `P2_SYSTEM_BLOCK` | 2 | `HOLD` | Data/cost/mandate insuficiente sin salida autoritativa. |
| `P3_STRATEGIC_EXIT` | 3 | `EXIT_LONG` | Hipótesis long invalidada en evaluación estratégica. |
| `P4_ENTRY` | 4 | `ENTER_LONG` | Oportunidad aprobada bajo todos los gates. |
| `P5_NO_CHANGE` | 5 | `HOLD` | No intent, cooldown o estado estable. |

Una clase inferior nunca es reemplazada por una superior durante el mismo
`evaluation_id`. Entre decisiones de igual clase, gana la que tenga estado/mandato
más reciente y luego el `decision_id` lexicográficamente menor; no se usa arrival
order.

### Taxonomía de razones

#### Entrada

- `OPPORTUNITY_APPROVED` — única razón primaria válida para `ENTER_LONG`.
- Razones secundarias deben venir de la política y referenciar evidencia; no pueden
  sustituir aprobación de costo/riesgo/calidad.

#### Hold sin cambio

- `NO_INTENT`, `COOLDOWN`, `PENDING_FEEDBACK`, `DUPLICATE`, `NO_STATE_CHANGE`,
  `DECISION_EXPIRED`.

#### Hold bloqueado

- `DATA_BLOCKED`, `STATE_UNKNOWN`, `INVALID_STATE_COMBINATION`,
  `CONTEXT_INSUFFICIENT`, `COST_UNKNOWN`, `RISK_REJECTED`, `MANDATE_MISSING`,
  `MANDATE_EXPIRED`, `UNKNOWN_SCHEMA`, `ENTRY_NOT_FILLED`.

#### Salida estratégica

- `POLICY_INVALIDATED`, `TIME_EXIT`, `OBJECTIVE_REACHED`.

#### Salida protectora

- `RISK_LIMIT_BREACH`, `PROTECTIVE_INVALIDATION`, `MANDATE_REVOKED`,
  `POSITION_ANOMALY`, `DATA_RISK_WITH_KNOWN_POSITION`.

Una razón específica de política puede añadirse con namespace versionado, por
ejemplo `policy:<id>:<reason>`, pero no reemplaza la taxonomía primaria.

### Contrato `ENTER_LONG`

| Aspecto | Regla normativa |
|---|---|
| Estado requerido | `FLAT/ENTRY_CANDIDATE/READY`. |
| Trigger | Sólo `STRATEGIC_EVALUATION`. |
| Disposition | `ACTIONABLE`. |
| Prioridad | `P4_ENTRY`. |
| Guarda | Product/Risk mandates vigentes, context/frame/cost válidos, intent vigente, RiskVerdict aprobado, sin pending/cooldown. |
| Razón primaria | `OPPORTUNITY_APPROVED`. |
| Target | `LONG`, cantidad absoluta > 0 derivada del verdict. |
| Vigencia máxima | `expires_at ≤` próxima frontera de `H_decision` y antes de cualquier input/mandato que la invalide. |
| Próximo estado al registrar | `ENTRY_PENDING/IDLE/READY`. |
| Prohibido | Emitir con cantidad 0/null, state no FLAT, health no READY o trigger protector. |

### Contrato `HOLD`

| Aspecto | Regla normativa |
|---|---|
| Estado requerido | Cualquier configuración, incluidos unknown/degraded/blocked/pending. |
| Trigger | Estratégico o protector. |
| Disposition | `NO_CHANGE` si sano; `BLOCKED` si falta un gate. |
| Prioridad | `P0_RECONCILIATION_BLOCK`, `P2_SYSTEM_BLOCK` o `P5_NO_CHANGE`. |
| Guarda | Ninguna acción económica de mayor prioridad es válida. |
| Razón primaria | Una de las razones hold de taxonomía; nunca vacía. |
| Target | `UNCHANGED`; refleja estado reconciliado o UNKNOWN. |
| Vigencia máxima | Hasta el primer nuevo evento relevante, próxima evaluación o `expires_at`, lo que ocurra primero. |
| Próximo estado | Self-loop o transición de health/evaluation definida por SM. |
| Prohibido | Usar HOLD para ocultar schema desconocido sin status BLOCKED o para fingir posición conocida. |

### Contrato `EXIT_LONG`

| Aspecto | Regla normativa |
|---|---|
| Estado requerido | `LONG/EXIT_CANDIDATE/*` con cantidad residual > 0. |
| Trigger | Estratégico o protector. |
| Disposition | `ACTIONABLE`. |
| Prioridad | `P1_PROTECTIVE_EXIT` o `P3_STRATEGIC_EXIT`. |
| Guarda | Posición reconciliada; intent/veto protector vigente; Decision registrada. Una salida reductora no requiere condiciones de entrada. |
| Razón primaria | Una razón estratégica o protectora de salida. |
| Target | `FLAT`, cantidad absoluta objetivo = 0. |
| Vigencia máxima | Protectora: deadline del RiskMandate; estratégica: antes de próxima frontera `H_decision`; siempre explícita. |
| Próximo estado al registrar | `EXIT_PENDING/IDLE/<health conservado>`. |
| Prohibido | Emitir desde FLAT/UNKNOWN, declarar FLAT antes de fill o degradar prioridad protectora por una entrada concurrente. |

### Vigencia e invalidación

Una Decision es consumible sólo si todas son verdaderas:

```text
effective_at ≤ consume_time < expires_at
state_before.version == current_state.version
product_mandate_version == current_product_mandate.version
risk_mandate_version == current_risk_mandate.version   (si aplica)
no existe Decision vigente que la superseda
ledger_precondition == RECORD_BEFORE_EXPORT
decision_id no fue consumido previamente
```

Cambios en calidad, posición, mandato, policy/context/cost version o trigger de
mayor prioridad invalidan la Decision aunque `expires_at` no haya llegado. La
invalidación produce una nueva evaluación; nunca muta el registro histórico.

### Identidad y determinismo

```text
decision_id = SHA256(canonical_json({
  schema_version,
  evaluation_id,
  action,
  priority_class,
  state_before.version,
  product_mandate_version,
  risk_mandate_version,
  policy_id,
  policy_version,
  market_context_version,
  cost_estimate_version,
  risk_verdict_version,
  decision_time,
  effective_at,
  expires_at,
  target_position,
  primary_reason,
  sorted(reason_codes),
  sorted(evidence_refs)
}))
```

Reglas de serialización canónica:

- claves ordenadas, UTF-8 y enums case-sensitive;
- decimales normalizados sin notación local ni ceros ambiguos;
- timestamps UTC con precisión definida por schema;
- listas de reason/evidence ordenadas y sin duplicados;
- campos `null` presentes cuando el schema los exige;
- ninguna fuente de aleatoriedad ni lectura interna de `now()`.

Por tanto, mismos inputs, estado, reloj explícito y versiones producen el mismo
`decision_id` y contenido canónico.

### Matriz de coherencia

| Acción | Posición actual | Target | Disposition | Primary reason | Resultado sin fill |
|---|---|---|---|---|---|
| `ENTER_LONG` | `FLAT` | `LONG`, qty > 0 | `ACTIONABLE` | `OPPORTUNITY_APPROVED` | Sigue `ENTRY_PENDING`, no LONG confirmado |
| `HOLD` | conocida | `UNCHANGED` | `NO_CHANGE/BLOCKED` | reason hold obligatorio | Posición no cambia |
| `HOLD` | `UNKNOWN` | `UNKNOWN/null` | `BLOCKED` | `STATE_UNKNOWN` o más específico | Continúa sin entrada |
| `EXIT_LONG` | `LONG`, qty > 0 | `FLAT`, qty = 0 | `ACTIONABLE` | reason exit obligatorio | Sigue `EXIT_PENDING`, no FLAT confirmado |

### Invariantes del contrato

- Exactamente una `action`, una `primary_reason` y un target coherente.
- `primary_reason ∈ reason_codes`; reason codes no se repiten.
- `event_time_max ≤ decision_time ≤ effective_at < expires_at`.
- `ENTER_LONG ⇒ disposition=ACTIONABLE ∧ target.qty>0 ∧ health=READY`.
- `EXIT_LONG ⇒ disposition=ACTIONABLE ∧ current.qty>0 ∧ target.qty=0`.
- `HOLD ⇒ target=UNCHANGED`; si state unknown, nunca inventa cantidad.
- `BLOCKED ⇒ action=HOLD`; la inversa no es obligatoria.
- Ninguna Decision contiene semántica de Order o Fill.
- Ninguna Decision vigente sobrevive a cambio de versiones que afecta su guarda.
- Exportación ocurre después de ledger, nunca antes.

### Evidencia de cierre de T1.4

- Las tres acciones comparten envelope y tienen guardas, prioridad, vigencia,
  razones, target y siguiente estado específicos.
- La taxonomía distingue hold normal, bloqueo, salida estratégica y protectora.
- La posición objetivo no se confunde con posición confirmada ni orden.
- La regla de identidad hace verificable “mismos inputs/versiones → misma Decision”.
- Las condiciones de consumo e invalidación impiden actuar sobre estado obsoleto.

## Gobernanza de decisiones y cierre de Fase 1 — T1.5

La fuente normativa de estados, dueños e historial es
`docs/btc-decision-agent-decision-log.md`. Esta sección define cómo afectan al
contrato funcional; no duplica la autoridad para cambiarlas.

### Cobertura contractual de decisiones

| Tema exigido | IDs | Prioridad/estado | Etiqueta vigente | Uso permitido ahora | Gate que bloquea |
|---|---|---|---|---|---|
| Mercado/producto | D-001 | P0 `OPEN_HUMAN` | `[PROVISIONAL: SPOT_BTCUSDT_LONG_FLAT_NO_LEVERAGE]` | Ejemplos estructurales condicionados | Política ejecutable, sizing, implementación |
| Dirección long-only/short | D-001 | P0 `OPEN_HUMAN` | Incluida en perfil provisional | Máquina long-only y transiciones actuales | Cualquier soporte short/derivados |
| Horizonte | D-002 | P0 `OPEN_HUMAN` | `[SYMBOLIC: H_decision, H_context]` | Contratos temporales algebraicos | Features, políticas y performance numéricas |
| Cierre de vela | D-002 | P0 con regla decidida | Barra estratégica cerrada | Causalidad y estados | Excepciones requieren nueva decisión |
| Riesgo/capital | D-003 | P0 `OPEN_HUMAN` | `[SYMBOLIC: RiskMandate, λ_*]` | Invariantes y cotas simbólicas | Sizing, stops, pérdida/drawdown aceptables |
| Objetivo conceptual | D-004 | P1 `DECIDED` | `[DECIDED: GREENFIELD]` | Todo el diseño | Integración heredada prohibida en esta fase |
| Tipos de orden | D-005 | P1 `PROVISIONAL` | `[PROVISIONAL: MARKET_AND_LIMIT_SCENARIOS]` | Modelo neutral de ejecución futura | Fills y break-even definitivo |
| Costos | D-006 | P1 `PROVISIONAL` | `[PROVISIONAL: CONSERVATIVE_COST_RANGE]` | Fórmulas/rangos | Utilidad o política “aprobada” |
| Order book/depth | D-007 | P1 `DECIDED` | `[DECIDED: L2_COST_LIQUIDITY_FILTER_NOT_TRIGGER]` | CostEstimate, veto y diagnóstico | Trigger autónomo L2 prohibido |
| Fuente de datos | D-008 | P1 `PROVISIONAL` | `[PROVISIONAL: BINANCE_PUBLIC_PROVIDER_NEUTRAL]` | Contrato conceptual inicial | Acoplamiento a proveedor |
| Gate empírico | D-009 | P1 `PRE_REGISTER_PENDING` | `[PENDING: OOS_GATE]` | Diseñar protocolo | Abrir OOS o declarar ganadora |
| Políticas candidatas | D-010 | P1 `DECIDED` | `[DECIDED: NULL_PLUS_TREND_REVERSION_BREAKOUT]` | Formalización/comparación | Ninguna validada/rankeada |
| Plataforma | D-011 | P2 `DEFERRED` | `[DEFERRED: IMPLEMENTATION_PLATFORM]` | Ninguno | Implementación |
| Observabilidad/UI | D-012 | P2 `DEFERRED` | `[DEFERRED: UI_SURFACE]` | Semántica de explicación | Diseño de interfaz |
| Objetivo de evaluación | D-013 | P1 `DECIDED` | `[DECIDED: G0_G4_WITH_HOLD_CONTROL]` | Scorecard, falsación, selección | Umbrales dependen D-003/D-009 |
| Freshness/lateness/reloj | D-014 | P1 `PRE_REGISTER_PENDING` | `[PENDING: FRESHNESS_BUDGETS_BY_SOURCE_AND_H]` | Semántica y fórmulas fail-safe | Cierre Fase 2 y freeze de sources |
| Primary para formalización | D-015 | P1 `DECIDED` | `[DECIDED: POL101_PRIMARY_FORMALIZATION_ONLY]` | T3.4/T3.5 | No implica edge ni ranking empírico |

### Perfil condicional para ejemplos conceptuales

```text
ConditionalProfile CP-01 = {
  product:        [PROVISIONAL: SPOT],
  symbol:         [PROVISIONAL: BTC/USDT],
  directions:     [PROVISIONAL: LONG/FLAT],
  leverage:       [PROVISIONAL: 0],
  H_decision:     [SYMBOLIC],
  H_context:      [SYMBOLIC],
  RiskMandate:    [SYMBOLIC],
  execution:      [PROVISIONAL: MARKET_AND_LIMIT_SCENARIOS],
  costs:          [PROVISIONAL: CONSERVATIVE_RANGE],
  depth_role:     [DECIDED: L2_COST_LIQUIDITY_FILTER_NOT_TRIGGER],
  evaluation:     [DECIDED: G0_G4_WITH_HOLD_CONTROL],
  freshness:      [PENDING: BY_SOURCE_AND_H],
  policy_set:      [DECIDED: NULL_PLUS_TREND_REVERSION_BREAKOUT],
  primary_formalization: [DECIDED: POL101_ONLY_FOR_T3_4_T3_5]
}
```

`CP-01` sirve únicamente para que tablas y pruebas estructurales sean legibles. No
es configuración recomendada, aprobada ni ejecutable. Cada resultado que dependa
de CP-01 debe rotularse `CONDITIONAL_ON_CP-01`.

### Reglas contra defaults ocultos

1. Una regla que dependa de D-001–D-003 referencia el ID y versión del mandato.
2. Un valor `SYMBOLIC` no puede convertirse en número durante un ejemplo sin una
   decisión/log separado.
3. Un valor `PROVISIONAL` puede ser sustituido sin cambiar la arquitectura; si no,
   la arquitectura estaba indebidamente acoplada.
4. `DECIDED` sólo cambia mediante historial nuevo en el decision log.
5. `DEFERRED` no puede aparecer como precondición de una prueba conceptual.
6. `PRE_REGISTER_PENDING` impide abrir resultados, no impide diseñar el protocolo.
7. Todo documento futuro incluye etiqueta o ID al usar un supuesto no decidido.
8. La ausencia de una decisión requerida produce `HOLD/BLOCKED` o veredicto
   condicional; nunca selección silenciosa.

### Auditoría de Fase 1

| Entregable | Evidencia | Resultado |
|---|---|---|
| Contrato funcional | T1.1: FR-001…FR-018 y separación recomendación/autorización/decisión/ejecución | PASS |
| Lenguaje y unidades | T1.2: glosario, UTC, unidades e invariantes semánticos | PASS |
| Máquina de estados | T1.3: 3 dimensiones, SM-001…SM-031 y transiciones prohibidas | PASS |
| Contratos de acciones | T1.4: envelope, prioridad, vigencia, reasons, target e identidad | PASS |
| Decisiones abiertas | T1.5/T2.4: D-001…D-014, defaults etiquetados y gates temporales | PASS_CONDITIONAL |

### Resultado del gate de Fase 1

- Decisiones catalogadas: **15/15**.
- P0 abiertas y visibles: **3/3**.
- P1/P2 con dueño y gate: **12/12**.
- Defaults provisionales sin etiqueta: **0**.
- Decisiones abiertas sin fecha/gate lógico: **0**.
- Contradicciones conocidas entre contrato, estados y decisiones: **0**.
- Blockers activos: **0**.

**Veredicto de Fase 1: `PASS_CONDITIONAL`.** Puede comenzar el contrato de datos
manteniendo `H_decision`, `H_context` y `RiskMandate` simbólicos. No pueden
congelarse políticas, sizing, performance ni implementación hasta resolver los
gates correspondientes del decision log.

### Evidencia de cierre de T1.5

- Spot/derivados, dirección, horizonte, cierre de vela, órdenes, riesgo y objetivo
  de evaluación tienen ID, clasificación y gate explícitos.
- Los defaults usados por el diseño están rotulados y centralizados en CP-01.
- Las decisiones humanas abiertas no bloquean contratos genéricos ni se presentan
  como aprobadas.
- La Fase 1 queda cerrada de forma condicional y la siguiente tarea es T2.1.

## Contratos oficiales de fuentes de mercado — T2.1

### Alcance y provenance

Esta sección describe fuentes públicas; no abre conexiones ni implementa un
adapter. Snapshot documental consultado el **2026-09-15**:

1. Binance Spot WebSocket Streams:
   https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md
2. Binance Spot REST API:
   https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md
3. Binance Spot Filters:
   https://github.com/binance/binance-spot-api-docs/blob/master/filters.md
4. Portal oficial equivalente:
   https://developers.binance.com/docs/binance-spot-api-docs

`provider_contract_version = BINANCE_SPOT_DOCS_2026-09-15`. URLs, pesos, límites y
frecuencias son configuración versionada del proveedor; no son invariantes de la
arquitectura greenfield.

### Seguridad y autenticación

- Los streams y endpoints enumerados tienen seguridad pública `NONE`; no requieren
  API key, firma, cuenta ni secreto.
- Para REST market data público, Binance recomienda
  `https://data-api.binance.vision`.
- Para WebSocket sólo market data existe `wss://data-stream.binance.vision`.
- Esta especificación no utiliza endpoints `TRADE`, `USER_DATA` ni `USER_STREAM`.
- Ninguna credencial se acepta como campo de estos contratos ni se registra en el
  Ledger.

### Contrato global WebSocket

| Propiedad oficial | Valor documentado | Regla conceptual |
|---|---|---|
| Endpoints principales | `wss://stream.binance.com:9443` o `:443` | Endpoint es configuración, no identidad del dato. |
| Raw stream | `/ws/<streamName>` | Payload directo. |
| Combined stream | `/stream?streams=<s1>/<s2>` | Desenvolver `{"stream":...,"data":...}` antes de normalizar. |
| Símbolos en stream | Lowercase, p. ej. `btcusdt` | Normalizar a símbolo canónico BTC/USDT. |
| Vida de conexión | 24 horas | Rotación/reconexión planificada antes del límite. |
| Ping | Cada 20 s desde servidor | Responder pong con el mismo payload. |
| Timeout pong | 1 minuto | Desconexión implica `DEGRADED/BLOCKED` según fuentes requeridas. |
| Mensajes entrantes | Máximo 5/s, incluyendo ping, pong y control JSON | Rate-limit de suscripciones; no churn. |
| Streams/conexión | Máximo 1024 | Configuración monitoreada. |
| Intentos de conexión | 300 por 5 minutos por IP | Backoff con jitter; evitar tormenta de reconexión. |
| Tiempo | Milisegundos por defecto; `timeUnit=MICROSECOND` opcional | Un adapter elige una unidad y normaliza a UTC; nunca mezcla ambas. |

### Contrato global REST

| Propiedad oficial | Regla conceptual |
|---|---|
| Seguridad no especificada | `NONE`, market data público. |
| Timestamps | Milisegundos por defecto; header `X-MBX-TIME-UNIT: MICROSECOND` opcional. |
| Rate limits | Leer `rateLimits` de `exchangeInfo` y headers `X-MBX-USED-WEIGHT-*`; no hardcodear el presupuesto global. |
| HTTP 429 | Respetar `Retry-After`, detener polling y degradar la fuente. |
| HTTP 418 | IP auto-baneada por violaciones repetidas; bloquear y no reintentar agresivamente. |
| Data source | Memory/Database según endpoint; conservarlo como provenance. |
| Timeout/error | Respuesta ausente o schema inesperado no se rellena; genera source health degradado. |

### Registro de fuentes

| ID | Fuente oficial | Rol | Update/cadencia oficial | Unidad principal | Límite/peso destacado | Auth |
|---|---|---|---|---|---|---|
| S-01 | WS `<symbol>@aggTrade` | Flujo ejecutado agregado | Real-time | precio USDT/BTC, qty BTC | Límites globales WS | `NONE` |
| S-02 | WS `<symbol>@kline_<interval>` | Barra actual y evento de cierre | 1000 ms para 1s; 2000 ms para otros intervalos | OHLC USDT/BTC, vol BTC/USDT | Intervalos oficiales | `NONE` |
| S-03 | REST `GET /api/v3/klines` | Backfill/reconciliación de barras | On-demand | OHLCV canónico | Weight 2; limit máx. 1000 | `NONE` |
| S-04 | WS `<symbol>@bookTicker` | Best bid/ask y qty | Real-time | precio USDT/BTC, qty BTC | No trae event time | `NONE` |
| S-05 | WS `<symbol>@depth` o `@depth@100ms` | Diffs para libro local | 1000 ms o 100 ms | niveles precio/qty | Secuencia `U..u` obligatoria | `NONE` |
| S-06 | REST `GET /api/v3/depth` | Snapshot bootstrap/resync | On-demand | niveles precio/qty | Máx. 5000; weight 5–250 | `NONE` |
| S-07 | WS `<symbol>@ticker` | Contexto rolling 24h | 1000 ms | precio, retorno %, vol BTC/USDT | No es día UTC | `NONE` |
| S-08 | REST `GET /api/v3/ticker/24hr` | Snapshot rolling 24h | On-demand | precio, retorno %, vol BTC/USDT | 1 símbolo weight 2; sin símbolo 80 | `NONE` |
| S-09 | REST `GET /api/v3/exchangeInfo` | Símbolo, estado, filtros y rate limits | Startup + refresh por evento/TTL futuro | metadata | Weight 20 | `NONE` |

### S-01 — Aggregate trades

**Provider stream:** `btcusdt@aggTrade`.

Un evento agrega trades asociados a una misma orden taker según la definición del
proveedor; no equivale a un tick individual ni a una orden visible.

| Campo Binance | Campo canónico | Tipo/unidad | Regla |
|---|---|---|---|
| `E` | `provider_emitted_at` | UTC ms | Tiempo de emisión del payload por el proveedor. |
| `T` | `event_time` (`trade_time`) | UTC ms | Tiempo autoritativo del trade agregado. |
| `s` | `symbol` | base/quote | Debe corresponder al mandato. |
| `a` | `source_event_id` | integer | Aggregate trade ID; parte de deduplicación. |
| `p` | `price` | Decimal USDT/BTC | > 0. |
| `q` | `base_qty` | Decimal BTC | > 0. |
| `f`, `l` | `first_trade_id`, `last_trade_id` | integer | `f ≤ l`. |
| `m` | `buyer_is_maker` | boolean | Si true, agresor inferido es SELL; si false, BUY. |
| local | `observed_at` | UTC | Asignado al recibir; no reemplaza `T`. |

**Uso permitido:** volumen ejecutado, dirección del agresor bajo la convención
documentada y features causales que declaren ventana. **No permitido:** tratar qty
agregada como profundidad o asumir que predice el próximo retorno.

### S-02 — Kline WebSocket

**Provider stream:** `btcusdt@kline_<interval>` en UTC+0.

Intervalos documentados: `1s`, `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`,
`6h`, `8h`, `12h`, `1d`, `3d`, `1w`, `1M`.

| Campo Binance | Campo canónico | Tipo/unidad | Regla |
|---|---|---|---|
| `E` | `event_time` | UTC ms | Emisión del update. |
| `k.t`, `k.T` | `bar_open_time`, `bar_close_time` | UTC ms | Intervalo de barra. |
| `k.i` | `interval` | enum | Debe coincidir con contrato solicitado. |
| `k.o/h/l/c` | `open/high/low/close_price` | Decimal USDT/BTC | Validar OHLC. |
| `k.v` | `base_volume` | Decimal BTC | ≥ 0. |
| `k.q` | `quote_volume` | Decimal USDT | ≥ 0. |
| `k.n` | `trade_count` | integer | ≥ 0. |
| `k.V`, `k.Q` | `taker_buy_base/quote_volume` | BTC / USDT | No confundir con volumen total. |
| `k.f`, `k.L` | `first_trade_id`, `last_trade_id` | integer | Para integridad/reconciliación. |
| `k.x` | `is_closed` | boolean | Sólo `true` habilita feature estratégica de barra cerrada. |

Updates con `x=false` sirven para observabilidad o protección explícitamente
separada; nunca se presentan como close estratégico final.

### S-03 — Kline REST

**Endpoint:** `GET /api/v3/klines`.

- Requiere `symbol` e `interval`; `limit` default 500, máximo 1000; weight 2.
- Fuente oficial: Database.
- Klines se identifican por open time.
- `startTime`/`endTime` se interpretan en UTC incluso si se envía `timeZone`.
- Para esta especificación, `timeZone=0`/UTC es obligatorio; no se usan UI klines.
- Uso: backfill inicial, reparación/reconciliación y replay; no polling de precio.
- Una barra REST no se mezcla con WS sin comparar identidad, intervalo y cierre.

### S-04 — Book ticker

**Provider stream:** `btcusdt@bookTicker`.

| Campo Binance | Campo canónico | Unidad/regla |
|---|---|---|
| `u` | `source_sequence` | Update ID monotónico esperado. |
| `s` | `symbol` | BTC/USDT normalizado. |
| `b`, `B` | `bid_price`, `bid_qty` | USDT/BTC, BTC. |
| `a`, `A` | `ask_price`, `ask_qty` | USDT/BTC, BTC. |
| local | `observed_at` | UTC asignado al recibir. |

El payload documentado **no contiene event time**. No se fabrica `event_time`; se
registra `null`/ausente y se conserva `observed_at`. Esto impide afirmar orden
temporal exacto frente a aggTrades sólo por arrival order.

Guardas: `bid_price ≤ ask_price`, cantidades ≥ 0, sequence no regresiva. Su uso es
BBO, spread y costo; no prueba fill disponible para un tamaño mayor a top-of-book.

### S-05/S-06 — Libro local: diff + snapshot

**Diff stream:** `btcusdt@depth` (1000 ms) o `btcusdt@depth@100ms` (100 ms).
Campos: `E`, `s`, `U` primer update ID, `u` último update ID, `b` bids y `a` asks.
Cada nivel es `[price, new_quantity]`; qty 0 elimina el nivel.

**Snapshot:** `GET /api/v3/depth?symbol=BTCUSDT&limit=N`, fuente Memory.

| Limit solicitado | Request weight oficial |
|---:|---:|
| 1–100 | 5 |
| 101–500 | 25 |
| 501–1000 | 50 |
| 1001–5000 | 250 |

Máximo 5000 niveles por lado. Los niveles fuera del snapshot inicial pueden quedar
desconocidos hasta cambiar; nunca se describe el snapshot como “libro completo”.

Contrato de pairing para T2.3:

1. Buffer diffs y anotar primer `U`.
2. Obtener snapshot con `lastUpdateId`.
3. Reintentar snapshot si `lastUpdateId < first_U`.
4. Descartar diffs con `u ≤ lastUpdateId`.
5. Primer diff aplicable debe contener `lastUpdateId` dentro de `[U, u]`.
6. Si un diff futuro tiene `U > local_update_id + 1`, declarar gap, descartar libro
   local y reiniciar bootstrap.
7. Nunca usar features L2 durante bootstrap/gap/resync.

T2.3 formalizará estados y ejemplos; T2.1 congela la autoridad oficial.

### S-07/S-08 — Ticker rolling 24h

**WS:** `btcusdt@ticker`, update 1000 ms. **REST:**
`GET /api/v3/ticker/24hr?symbol=BTCUSDT`, fuente Memory, weight 2 para un símbolo.
Omitir symbol cuesta weight 80 y queda prohibido para este alcance single-symbol.

Campos relevantes: last/open/high/low/weighted average price, price change,
price-change percent, bid/ask, base/quote volume, window open/close times y trade
count. En REST `type=FULL|MINI`; el contrato inicial exige FULL cuando se requiera
bid/ask/change.

Es una ventana móvil de 24 horas, **no** el día calendario UTC. Sólo aporta contexto
y observabilidad; no reemplaza klines ni constituye trigger por sí sola.

### S-09 — Exchange information

**Endpoint:** `GET /api/v3/exchangeInfo?symbol=BTCUSDT`, fuente Memory, weight 20.

Campos mínimos: timezone/serverTime, `rateLimits`, symbol/status, base/quote assets
y precisiones, orderTypes, capacidades Spot/Margin, permissions/permissionSets y
filters. Estado distinto de `TRADING`, símbolo ausente o permisos incompatibles
bloquean nueva entrada.

Filtros relevantes, siempre dinámicos:

| Filter | Campos | Invariante futuro |
|---|---|---|
| `PRICE_FILTER` | `minPrice`, `maxPrice`, `tickSize` | Precio dentro de rango y múltiplo de tick si regla habilitada. |
| `LOT_SIZE` | `minQty`, `maxQty`, `stepSize` | Cantidad dentro de rango y múltiplo de step. |
| `MARKET_LOT_SIZE` | min/max/step para Market | No asumir que LOT_SIZE basta para Market. |
| `MIN_NOTIONAL` | `minNotional`, `applyToMarket`, `avgPriceMins` | Notional mínimo bajo precio de referencia aplicable. |
| `NOTIONAL` | min/max, aplicación a Market, `avgPriceMins` | Rango notional completo. |
| `PERCENT_PRICE(_BY_SIDE)` | multipliers y ventana | Restricción dinámica de precio, no señal de estrategia. |

Valores de filtros nunca se hardcodean ni se convierten en features predictivas.
`exchangeInfo` se hashea/versiona; un cambio invalida decisions pendientes que
dependan de cuantización o elegibilidad.

### Criticidad y degradación parcial

| Tier | Fuentes | Efecto si no están sanas |
|---|---|---|
| Metadata obligatoria | S-09 | `BLOCKED`; no se conoce producto/filtros. |
| Precio/BBO core | S-04 | No entrada ni CostEstimate ejecutable. |
| Barras core por política | S-02 + S-03 reconciliado | Política de barras produce `CONTEXT_INSUFFICIENT`. |
| Flujo ejecutado dependiente de política | S-01 | Sólo policies que lo requieran quedan bloqueadas. |
| L2 opcional | S-05 + S-06 | Depth features deshabilitadas; nunca fallback a snapshot viejo. |
| Contexto 24h | S-07 o S-08 | Se omite contexto; no bloquear si ninguna guarda lo requiere. |

Una política declara su `required_source_set`. No existe fallback silencioso que
reemplace una fuente por otra con semántica diferente.

### Reglas de normalización

- Provider symbol `BTCUSDT`/`btcusdt` → canónico `BTC/USDT`, preservando raw value.
- Strings decimales → Decimal exacto; no float binario.
- Timestamps → UTC con unidad del contrato de conexión; prohibido mezclar ms/µs.
- Cada evento añade `observed_at`, `provider`, `source_contract_id`, schema version
  y raw identity.
- Campos “ignore” del proveedor no alimentan features.
- Un campo nuevo/desconocido se conserva en raw, pero un cambio incompatible del
  schema genera `UNKNOWN_SCHEMA`.
- REST response y WS event nunca comparten identidad sólo por tener mismo precio.

### Límites que deben permanecer configurables

- Endpoint/base URL y elección raw/combined.
- Time unit ms/µs.
- Stream update speed disponible.
- Connection lifetime, ping/pong, message/stream/connection limits.
- REST request weights, rateLimits y backoff.
- Kline interval y backfill limit.
- Depth cadence y snapshot limit.
- TTL/refresh de exchangeInfo y ticker REST.

El adapter futuro debe validar estos valores contra documentación/metadata al
inicio; la especificación no promete que permanezcan constantes.

### Evidencia de cierre de T2.1

- Nueve fuentes tienen autoridad, finalidad, campos, frecuencia, unidades, límites
  y autenticación documentados.
- Todas usan market data público `NONE`; no se introdujeron secretos.
- BookTicker sin event time, ticker rolling 24h y snapshot L2 limitado tienen sus
  restricciones explícitas.
- Depth snapshot/diff tiene contrato oficial de pairing y fail-safe.
- ExchangeInfo gobierna filtros/rate limits dinámicos; no se hardcodean.
- Fuentes opcionales degradan sólo las policies que las declaran requeridas.
- Las tres fuentes oficiales y fecha de consulta permiten revalidar schema drift.

## Schema canónico de eventos de mercado — T2.2

### Objetivo

`MarketEventV1` separa el hecho económico de su entrega. Es inmutable, provider-
neutral y suficiente para deduplicar, ordenar, auditar y degradar sin inventar
datos. El payload raw puede preservarse por referencia, pero nunca sustituye el
contrato normalizado.

### Envelope `MarketEventV1`

| Campo | Tipo | Null | Semántica/invariante |
|---|---|---:|---|
| `schema_version` | string semver | No | Inicial: `market-event/1.0.0`. |
| `event_id` | hash | No | Identidad determinista del hecho, excluye `observed_at`. |
| `event_type` | enum | No | Uno de los tipos canónicos registrados. |
| `source_contract_id` | `S-01…S-09` | No | Contrato oficial usado para mapear. |
| `provider` | enum/string | No | Inicial: `BINANCE_SPOT`; no implica acoplamiento del payload. |
| `provider_contract_version` | string | No | Snapshot documental/adapter aplicado. |
| `transport` | enum | No | `WEBSOCKET` o `REST`. |
| `channel` | string | No | Stream o path REST exacto, sin secretos/query sensible. |
| `connection_id` | opaque ref | Sí | Sesión de entrega; no forma parte de identidad económica. |
| `symbol` | objeto | No | Canónico, provider raw, base y quote. |
| `event_time` | UTC instant | Sí | Cuándo ocurrió el hecho; null sólo si la fuente no lo ofrece. |
| `provider_emitted_at` | UTC instant | Sí | Cuándo el proveedor emitió el payload, si existe. |
| `observed_at` | UTC instant | No | Cuándo fue recibido localmente; nunca identidad del hecho. |
| `source_identity` | objeto | No | IDs/ventana/secuencia específicos de la fuente. |
| `sequence` | objeto | Sí | Scope, kind, first, last y continuidad. |
| `precision_ref` | version ref | No | Hash/versión de metadata S-09 usada para decimales. |
| `payload` | objeto tipado | No | Sólo campos canónicos del tipo de evento. |
| `payload_hash` | hash | No | Hash de canonical payload para integridad/dedup. |
| `provenance` | objeto | No | Data source, raw schema, endpoint class y transform version. |
| `delivery` | objeto | No | Clasificación temporal y de duplicado de esta entrega. |
| `quality` | objeto | No | Schema, invariants, continuity, freshness y flags. |
| `raw_ref` | opaque ref/hash | Sí | Referencia a raw inmutable; nunca incluye credenciales. |

### Tipos de evento canónicos

| Event type | Fuentes | Identidad económica mínima | Payload canónico mínimo |
|---|---|---|---|
| `AGG_TRADE` | S-01 | aggregate trade ID + symbol | price, base_qty, trade IDs, aggressor inference |
| `KLINE_UPDATE` | S-02 | interval + open time + provider emission + payload hash | OHLCV, trade count, taker volumes, is_closed |
| `KLINE_CLOSED` | S-02/S-03 | symbol + interval + open time | OHLCV final, close time, trade range |
| `BBO_UPDATE` | S-04 | symbol + update ID | bid/ask price y qty |
| `DEPTH_DIFF` | S-05 | symbol + `[U,u]` | bid/ask level replacements |
| `DEPTH_SNAPSHOT` | S-06 | symbol + lastUpdateId + payload hash | bids/asks + coverage limit |
| `TICKER_24H` | S-07/S-08 | symbol + window close + payload hash | rolling OHLC, change, volume, trade count |
| `SYMBOL_METADATA` | S-09 | symbol + response hash | status, assets, precision, filters, capabilities |

S-02 puede producir muchos `KLINE_UPDATE` para una misma barra, pero exactamente
un estado lógico `KLINE_CLOSED` por `(symbol, interval, open_time, metadata/schema
version)`. Un duplicado idéntico del cierre no crea otro hecho.

### Objetos comunes

#### `symbol`

```json
{
  "canonical": "BTC/USDT",
  "provider_raw": "BTCUSDT",
  "base_asset": "BTC",
  "quote_asset": "USDT"
}
```

#### `sequence`

```json
{
  "scope": "BINANCE_SPOT:BTCUSDT:DEPTH",
  "kind": "RANGE",
  "first": 157,
  "last": 160,
  "continuity": "CONTIGUOUS"
}
```

`kind`: `SINGLE`, `RANGE`, `WINDOW_KEY` o `NONE`. `continuity`:
`NOT_APPLICABLE`, `CONTIGUOUS`, `REGRESSIVE`, `GAP`, `UNVERIFIED`.

#### `delivery`

| Campo | Dominio | Definición |
|---|---|---|
| `classification` | `ON_TIME`, `DUPLICATE`, `OUT_OF_ORDER`, `LATE` | Resultado respecto a seen-set, high-water mark y watermark. |
| `lateness_ms` | integer/null | `observed_at - event_time` cuando event_time existe. |
| `watermark_at` | UTC/null | Frontera de completitud usada por el consumidor. |
| `delivery_attempt` | integer ≥ 1 | Entregas idénticas incrementan intento, no event_id. |

#### `quality`

```json
{
  "schema": "VALID",
  "invariants": "VALID",
  "continuity": "CONTIGUOUS",
  "freshness": "FRESH",
  "status": "QUALIFIED",
  "flags": []
}
```

Dominios de `status`: `QUALIFIED`, `DEGRADED`, `BLOCKED`, `REJECTED`. Un evento
`DUPLICATE` puede ser schema-valid pero no se vuelve a aplicar.

### Identidad determinista

```text
source_key = canonical_json({
  provider,
  source_contract_id,
  event_type,
  symbol.canonical,
  source_identity,
  payload_hash
})

event_id = SHA256(source_key)
```

Identidad por fuente:

| Tipo | `source_identity` |
|---|---|
| AGG_TRADE | `{aggregate_trade_id}` |
| KLINE_UPDATE | `{interval, open_time, provider_emitted_at, is_closed}` + payload hash |
| KLINE_CLOSED | `{interval, open_time}` + contenido final |
| BBO_UPDATE | `{update_id}` |
| DEPTH_DIFF | `{first_update_id, final_update_id}` |
| DEPTH_SNAPSHOT | `{last_update_id}` + payload hash |
| TICKER_24H | `{window_open, window_close}` + payload hash |
| SYMBOL_METADATA | `{symbol, response_hash}` |

`observed_at`, `connection_id` y `delivery_attempt` no participan en event_id; de
otro modo una retransmisión sería falsamente un hecho nuevo.

### Orden temporal y watermarks

- **High-water mark:** mayor sequence/event key observada para un scope; no prueba
  por sí sola completitud.
- **Watermark:** instante/event key hasta el cual un consumidor declara que no
  espera datos on-time adicionales, bajo `allowed_lateness_ms` explícito.
- **OUT_OF_ORDER:** evento nuevo por debajo del high-water mark pero aún dentro de
  la ventana de reorder y sin violar continuidad.
- **LATE:** evento nuevo que llega después de que su ventana fue finalizada por
  watermark. Se conserva para auditoría/corrección futura, pero no reescribe una
  Decision histórica.
- **DUPLICATE:** event_id ya visto y payload_hash igual; no actualiza features.
- Mismo source identity con payload distinto es `IDENTITY_COLLISION`, quality
  `BLOCKED`, nunca “último gana”.

`allowed_lateness_ms` es configuración por fuente/horizonte y se definirá en T2.4;
no se inventa un número aquí.

### Pipeline de normalización y clasificación

1. Capturar `observed_at` con reloj UTC/monotónico asociado.
2. Identificar source contract por channel/path, no por inspección oportunista.
3. Parsear raw sin coerciones silenciosas.
4. Mapear símbolo, timestamps y decimales según metadata versionada.
5. Validar schema requerido y enums.
6. Validar invariantes de tipo (OHLC, bid≤ask, qty≥0, rangos de sequence).
7. Construir payload canónico y `payload_hash`.
8. Derivar `event_id`.
9. Consultar seen-set: clasificar duplicate/collision.
10. Evaluar sequence, high-water mark, reorder y watermark.
11. Asignar quality/status; sólo `QUALIFIED` entra a un frame utilizable.
12. Persistir record inmutable y delivery attempt por separado.

Un fallo en pasos 3–10 no produce un evento “parcialmente bueno” para entrada.

### Ejemplo V-01 — Evento válido/on-time

```json
{
  "schema_version": "market-event/1.0.0",
  "event_id": "sha256:<digest-canonical>",
  "event_type": "AGG_TRADE",
  "source_contract_id": "S-01",
  "provider": "BINANCE_SPOT",
  "provider_contract_version": "BINANCE_SPOT_DOCS_2026-09-15",
  "transport": "WEBSOCKET",
  "channel": "btcusdt@aggTrade",
  "connection_id": "ws-session:<opaque>",
  "symbol": {
    "canonical": "BTC/USDT",
    "provider_raw": "BTCUSDT",
    "base_asset": "BTC",
    "quote_asset": "USDT"
  },
  "event_time": "2026-09-15T17:46:20.100Z",
  "provider_emitted_at": "2026-09-15T17:46:20.110Z",
  "observed_at": "2026-09-15T17:46:20.140Z",
  "source_identity": {"aggregate_trade_id": 12345},
  "sequence": {
    "scope": "BINANCE_SPOT:BTCUSDT:AGG_TRADE",
    "kind": "SINGLE",
    "first": 12345,
    "last": 12345,
    "continuity": "CONTIGUOUS"
  },
  "precision_ref": "exchange-info:<hash>",
  "payload": {
    "price": "76874.01",
    "base_qty": "0.01000000",
    "first_trade_id": 20001,
    "last_trade_id": 20003,
    "buyer_is_maker": false,
    "aggressor_side": "BUY"
  },
  "payload_hash": "sha256:<payload-digest>",
  "provenance": {"data_source": "MATCHING_STREAM", "transform_version": "1.0.0"},
  "delivery": {
    "classification": "ON_TIME",
    "lateness_ms": 40,
    "watermark_at": null,
    "delivery_attempt": 1
  },
  "quality": {
    "schema": "VALID",
    "invariants": "VALID",
    "continuity": "CONTIGUOUS",
    "freshness": "FRESH",
    "status": "QUALIFIED",
    "flags": []
  },
  "raw_ref": "sha256:<raw-digest>"
}
```

Los digests se abrevian sólo para legibilidad documental; una implementación debe
usar SHA-256 completo.

### Ejemplo D-01 — Duplicado

Segundo delivery del mismo aggregate trade:

```json
{
  "event_id": "sha256:<mismo-digest-canonical>",
  "observed_at": "2026-09-15T17:46:20.300Z",
  "payload_hash": "sha256:<mismo-payload-digest>",
  "delivery": {
    "classification": "DUPLICATE",
    "delivery_attempt": 2
  },
  "quality": {
    "schema": "VALID",
    "status": "QUALIFIED",
    "flags": ["DO_NOT_REAPPLY"]
  }
}
```

Resultado: registrar delivery attempt, no recalcular features, no avanzar sequence
y no disparar evaluación.

### Ejemplo L-01 — Evento tardío

`KLINE_CLOSED` de 12:30–12:45 llega después de que el watermark cerró esa ventana y
una Decision posterior ya fue registrada:

```json
{
  "event_type": "KLINE_CLOSED",
  "event_time": "2026-09-15T12:44:59.999Z",
  "observed_at": "2026-09-15T12:47:10.000Z",
  "source_identity": {"interval": "15m", "open_time": "2026-09-15T12:30:00Z"},
  "delivery": {
    "classification": "LATE",
    "lateness_ms": 130001,
    "watermark_at": "2026-09-15T12:45:30.000Z"
  },
  "quality": {
    "status": "DEGRADED",
    "flags": ["NO_RETROACTIVE_DECISION", "RECONCILE_FUTURE_CONTEXT"]
  }
}
```

Resultado: preservar y comparar con barra previa; no mutar Decision/ledger pasado.
Si contradice el cierre usado, crear incidente de data quality y bloquear promoción
de la evidencia afectada.

### Ejemplo O-01 — Fuera de orden

BBO update `u=400900216` llega después de `u=400900217`, es nuevo y está dentro de
la ventana de reorder:

```json
{
  "event_type": "BBO_UPDATE",
  "event_time": null,
  "observed_at": "2026-09-15T17:46:20.180Z",
  "source_identity": {"update_id": 400900216},
  "sequence": {
    "scope": "BINANCE_SPOT:BTCUSDT:BBO",
    "kind": "SINGLE",
    "first": 400900216,
    "last": 400900216,
    "continuity": "REGRESSIVE"
  },
  "delivery": {"classification": "OUT_OF_ORDER"},
  "quality": {
    "status": "DEGRADED",
    "flags": ["DO_NOT_ROLL_BACK_CURRENT_BBO"]
  }
}
```

Resultado: no retroceder el BBO actual. Puede conservarse para auditoría/reorder si
la política de fuente lo permite; nunca reemplaza `u=400900217` por arrival order.

### Casos de rechazo adicionales

| Caso | Clasificación | Efecto |
|---|---|---|
| Mismo event_id, payload_hash distinto | `IDENTITY_COLLISION` | `BLOCKED`; investigación, no last-write-wins. |
| Decimal no parseable | `REJECTED_SCHEMA` | No MarketEvent utilizable. |
| Bid > ask en mismo BBO | `REJECTED_INVARIANT` | Fuente degradada/bloqueada. |
| Depth `U > local_id+1` | `GAP_DETECTED` | Invalidar libro y resync T2.3. |
| Timestamp en unidad no declarada | `TIME_UNIT_UNKNOWN` | `BLOCKED`; no heurística por magnitud. |
| Símbolo distinto al mandato | `SYMBOL_MISMATCH` | Rechazar para este pipeline. |
| Kline `x=false` presentada como closed | `BAR_NOT_CLOSED` | No feature estratégica. |

### Versionado y evolución

- Cambio aditivo opcional: minor version; consumidores antiguos pueden ignorarlo.
- Cambio de significado, tipo, unidad, nulabilidad o identidad: major version.
- Campos desconocidos se preservan en raw, pero no entran al payload canónico hasta
  tener contrato.
- Un major desconocido genera `UNKNOWN_SCHEMA` y Health `BLOCKED` para policies que
  requieren la fuente.
- Transform version y provider contract version forman parte de provenance y del
  replay, aunque no cambien la identidad económica original.

### Evidencia de cierre de T2.2

- Envelope define tiempo del hecho, recepción, identidad, secuencia, precisión,
  provenance, delivery y quality sin aliases.
- Ocho tipos de evento cubren S-01…S-09.
- Event ID excluye observed_at y permite deduplicación real.
- Válido, duplicado, tardío y fuera de orden tienen ejemplos y efectos distintos.
- Late/out-of-order nunca reescriben una Decision histórica por arrival order.
- Schema drift, collision, gap y unidad desconocida bloquean de forma explícita.
- `T` de aggTrade queda como event_time; `E` como provider_emitted_at.

## Sincronización del libro local L2 — T2.3

### Objetivo y frontera

Construir una vista local auditable a partir de S-05 `DEPTH_DIFF` y S-06
`DEPTH_SNAPSHOT`, sin confundir snapshot limitado con libro completo. El libro es
un dato derivado revocable; nunca es autoridad de posición ni ejecución.

### Estado de sincronización `BookSyncState`

| Estado | Significado | ¿Publica `LocalBookView`? |
|---|---|---:|
| `UNINITIALIZED` | No existe conexión, buffer ni snapshot. | No |
| `BUFFERING` | Stream abierto; diffs se acumulan mientras se solicita snapshot. | No |
| `SNAPSHOT_PENDING` | Request snapshot en vuelo; buffer sigue creciendo. | No |
| `REPLAYING` | Snapshot cargado; se filtran/aplican diffs buffered. | No |
| `LIVE` | Snapshot + diffs continuos e invariantes válidos. | Sí |
| `GAP_DETECTED` | Falta al menos un update ID o el buffer perdió continuidad. | No; revocación inmediata |
| `RESYNC_BACKOFF` | Generación descartada; espera controlada antes de reiniciar. | No |
| `BLOCKED` | Schema/invariantes/fallos repetidos impiden resync seguro. | No |

`LIVE` no significa libro completo: sólo secuencia continua desde un snapshot de
cobertura limitada.

### Generación atómica

Cada intento crea un `book_generation_id` nuevo. Snapshot, buffer, niveles y
`last_update_id` pertenecen a una sola generación y no se mezclan con otra.

```text
BookGeneration = {
  book_generation_id,
  connection_id,
  symbol,
  metadata_version,
  snapshot_last_update_id,
  last_update_id,
  snapshot_limit,
  first_buffered_U,
  state,
  bids,
  asks,
  buffered_event_count,
  created_at,
  last_event_time,
  last_observed_at,
  quality_flags
}
```

La generación se construye fuera de la vista publicada. Sólo un swap atómico tras
replay e invariantes permite exponerla como `LocalBookView`.

### `LocalBookView`

| Campo | Regla |
|---|---|
| `book_generation_id` | Inmutable para la generación publicada. |
| `symbol` / `metadata_version` | Deben corresponder al ProductMandate y S-09 vigente. |
| `last_update_id` | Monotónico dentro de generación. |
| `bids`, `asks` | Mapas price→qty con qty > 0; decimales exactos. |
| `best_bid`, `best_ask` | Derivados de niveles, nunca copiados de otra fuente. |
| `snapshot_limit` | Cobertura inicial declarada, máximo oficial 5000. |
| `coverage` | `LIMITED`; niveles fuera del snapshot no se asumen conocidos. |
| `event_time_max`, `observed_at` | Tiempo del último diff aplicado y publicación. |
| `sync_status` | Debe ser `LIVE`. |
| `quality` | Invariantes, continuity, freshness y metadata refs. |

### Algoritmo normativo de bootstrap

1. Crear nueva generación en `UNINITIALIZED`.
2. Abrir stream S-05 y pasar a `BUFFERING`; capturar cada diff sin aplicar.
3. Anotar `first_buffered_U` del primer diff válido.
4. Solicitar S-06 y pasar a `SNAPSHOT_PENDING`; el buffer continúa.
5. Si falla snapshot, buffer excede límite o cambia connection/schema, invalidar la
   generación y pasar a `RESYNC_BACKOFF`.
6. Si `snapshot.lastUpdateId < first_buffered_U`, el snapshot es demasiado viejo:
   solicitar otro snapshot; no publicar ni descartar diffs aún si caben en buffer.
7. Cargar snapshot en estructura privada y fijar `local_id = lastUpdateId`.
8. Descartar buffered events con `u ≤ local_id`.
9. El primer evento aplicable debe satisfacer `U ≤ local_id + 1 ≤ u`. Si
   `U > local_id + 1`, existe gap y la generación se descarta.
10. Aplicar buffered events restantes mediante la regla incremental.
11. Validar invariantes y que no quede gap; pasar a `LIVE` mediante swap atómico.
12. Procesar diffs futuros sólo con la regla incremental; no tomar otro snapshot
    sobre la misma generación sin reiniciar el proceso.

### Regla incremental para `DEPTH_DIFF(U,u)`

```text
if event.symbol != generation.symbol:
    BLOCKED(SYMBOL_MISMATCH)
else if event.u <= local_id:
    IGNORE(ALREADY_APPLIED)
else if event.U > local_id + 1:
    GAP_DETECTED(missing = [local_id + 1, event.U - 1])
else:  # event.U <= local_id + 1 <= event.u, incluido overlap
    for [price, qty] in bids and asks:
        if qty == 0: remove(price)
        else: upsert(price, qty)
    local_id = event.u
    validate_invariants()
```

No se suma qty: cada diff trae **nueva cantidad absoluta** para el nivel. Qty cero
elimina el nivel.

### Invariantes L2

- `last_update_id` nunca disminuye dentro de una generación.
- Todo diff aplicado contiene `local_id + 1` en `[U,u]` o solapa continuidad.
- Precios > 0; cantidades almacenadas > 0; qty cero sólo elimina.
- Niveles respetan precision/tick metadata vigente.
- `best_bid ≤ best_ask`; un crossed book persistente invalida la generación.
- Bids se consultan en precio descendente; asks en ascendente.
- Sólo un writer muta una generación; lectores ven snapshots inmutables/versionados.
- `event_time_max` y `observed_at` no retroceden al publicar una vista.
- Snapshot/diffs usan símbolo, provider contract y metadata compatibles.
- Features L2 referencian `book_generation_id` y `last_update_id` exactos.
- Ninguna Decision previa se reescribe tras resync.

### Máquina de transiciones L2

| ID | Estado actual | Evento/guarda | Efecto | Estado siguiente |
|---|---|---|---|---|
| L2-001 | `UNINITIALIZED` | `WS_OPEN` | Crear buffer/generación. | `BUFFERING` |
| L2-002 | `BUFFERING` | Primer `DEPTH_DIFF` válido | Guardar `first_buffered_U`; buffer. | `BUFFERING` |
| L2-003 | `BUFFERING` | `SNAPSHOT_REQUESTED` | Mantener buffering. | `SNAPSHOT_PENDING` |
| L2-004 | `SNAPSHOT_PENDING` | Diff válido | Añadir al buffer ordenado por entrega, sin aplicar. | Sin cambio |
| L2-005 | `SNAPSHOT_PENDING` | Snapshot error/timeout | Descartar generación; programar backoff. | `RESYNC_BACKOFF` |
| L2-006 | `SNAPSHOT_PENDING` | `lastUpdateId < first_U` | Reintentar snapshot si buffer sano. | `SNAPSHOT_PENDING` |
| L2-007 | `SNAPSHOT_PENDING` | Snapshot bridgeable | Cargar privado; filtrar `u≤id`. | `REPLAYING` |
| L2-008 | `REPLAYING` | Primer diff contiene `id+1` | Aplicar y avanzar local_id. | `REPLAYING` |
| L2-009 | `REPLAYING` | Todos buffered continuos + invariantes | Swap atómico. | `LIVE` |
| L2-010 | `REPLAYING` | `U > local_id+1` | Registrar missing range; revocar generación. | `GAP_DETECTED` |
| L2-011 | `LIVE` | `u ≤ local_id` | Ignorar duplicado/overlap ya aplicado. | `LIVE` |
| L2-012 | `LIVE` | `U ≤ id+1 ≤ u` | Aplicar niveles, validar, avanzar id. | `LIVE` |
| L2-013 | `LIVE` | `U > id+1` | Revocar vista antes de cualquier feature nueva. | `GAP_DETECTED` |
| L2-014 | `LIVE` | WS close/serverShutdown inesperado | Marcar vista stale/revocada. | `GAP_DETECTED` |
| L2-015 | Cualquiera activa | Heartbeat/transport stale | No asumir “mercado quieto”; revocar. | `GAP_DETECTED` |
| L2-016 | Cualquiera activa | Buffer overflow | Continuidad ya no demostrable. | `GAP_DETECTED` |
| L2-017 | Cualquiera activa | Schema/metadata/symbol incompatible | Bloquear fuente. | `BLOCKED` |
| L2-018 | Cualquiera activa | Invariante crítica falla | Conservar evidencia; no publicar. | `BLOCKED` |
| L2-019 | `GAP_DETECTED` | Entry action | Prohibir; emitir health event. | `RESYNC_BACKOFF` |
| L2-020 | `RESYNC_BACKOFF` | Timer + presupuesto disponible | Nueva connection/generation. | `UNINITIALIZED` |
| L2-021 | `RESYNC_BACKOFF` | Presupuesto agotado/repetición crítica | Alertar; esperar intervención/política. | `BLOCKED` |
| L2-022 | `BLOCKED` | Causa resuelta + reset explícito | Nueva generación, nunca reusar la vieja. | `UNINITIALIZED` |
| L2-023 | `LIVE(old)` | Nueva generación paralela llega LIVE | Swap old→new; cerrar old. | `LIVE(new)` |

### Gap y efecto sobre decisiones

Al detectar gap:

1. Revocar `LocalBookView` antes de publicar otro frame.
2. Emitir quality event `L2_GAP` con rango faltante y generation ID.
3. Marcar `L2Health=BLOCKED` y Health global al menos `DEGRADED`.
4. Invalidar `CostEstimate`, intent o Decision vigente que referencie esa generación.
5. Prohibir `ENTER_LONG` para toda Policy cuyo `required_source_set` incluya L2.
6. No usar último imbalance, spread-depth o microprice como fallback.
7. Preservar eventos para auditoría y comenzar resync con nueva generación.

Una Policy que declara explícitamente no depender de L2 puede continuar sólo si
todos sus demás gates están sanos y una nueva evaluación independiente lo decide.
El evento de gap jamás dispara entrada.

### Reconnect, rotación y heartbeat

- Toda reconexión crea `connection_id` y `book_generation_id` nuevos.
- No se unen buffers de conexiones distintas aunque los update IDs parezcan
  continuos.
- Ante límite de 24h, puede construirse una generación paralela y hacer handoff
  sólo cuando la nueva alcance `LIVE` (L2-023).
- Ping/pong prueba transporte, no freshness económica. Se mantienen dos relojes:
  `last_transport_activity_at` y `last_depth_event_observed_at`.
- Los thresholds de heartbeat/staleness se parametrizan en T2.4; no se fijan aquí.
- Backoff usa jitter y presupuesto acotado; nunca reconecta en tight loop.
- `serverShutdown` planificado inicia handoff; desconexión sin handoff revoca vista.

### Ejemplos de secuencia

#### L2-E1 — Bootstrap feliz

```text
buffer: [U=101,u=103], [U=104,u=105]
snapshot.lastUpdateId = 100
apply 101..103 → local_id=103
apply 104..105 → local_id=105
invariants PASS → LIVE(generation=A, id=105)
```

#### L2-E2 — Duplicado y overlap

```text
local_id=105
[U=103,u=105] → ignore (u≤local_id)
[U=104,u=107] → apply overlap containing 106; local_id=107
```

Aplicar el segundo evento es válido porque `U ≤ 106 ≤ u`; niveles contienen valores
absolutos, no deltas sumables.

#### L2-E3 — Gap

```text
local_id=107
next [U=110,u=112]
missing=[108,109] → GAP_DETECTED → view revoked → no L2-dependent entry
```

#### L2-E4 — Snapshot demasiado viejo

```text
first_buffered_U=200
snapshot.lastUpdateId=150
150<200 → refetch snapshot; no publish
```

#### L2-E5 — Eliminación de nivel

```text
bid update ["76874.00", "0"] → remove price 76874.00
next best bid se deriva del mapa resultante
```

#### L2-E6 — Reconnect

```text
LIVE generation=A, connection=1
connection closes → revoke A
new connection=2 + snapshot/buffer → generation=B
B LIVE → sólo B puede alimentar features
```

### Límites de memoria y concurrencia

- `max_buffer_events`/bytes y timeout de snapshot son configuración obligatoria de
  T2.4; overflow fuerza resync.
- Buffer conserva orden de recepción más identidad de secuencia; replay usa reglas
  de sequence, no sort ciego que pudiera ocultar gaps.
- Snapshot y replay ocurren en generación privada; lectores nunca ven estado a
  medio aplicar.
- La publicación debe ser compare-and-swap sobre generation/version; un worker
  atrasado no puede sobrescribir una generación más nueva.

### Evidencia de cierre de T2.3

- Bootstrap, bridge, replay, live, gap, reconnect, heartbeat y backoff están
  definidos con 23 transiciones.
- Cualquier gap revoca la vista antes de otra feature/entrada dependiente de L2.
- Snapshot limitado no se describe como libro completo.
- Updates son reemplazos absolutos y qty cero elimina niveles.
- Reconnect/generation evita mezclar sesiones y handoff parcial.
- Seis ejemplos cubren happy path, overlap, gap, snapshot viejo, delete y reconnect.
- No hay fallback a imbalance antiguo ni resync que reescriba Decisions pasadas.

## Cierre de vela y política de freshness — T2.4

### Principio

“Reciente” no es una propiedad absoluta. Un dato es utilizable sólo para un uso,
horizonte y decisión concretos bajo una `FreshnessPolicy` versionada. Si el budget
requerido no está definido, el resultado es `BLOCKED`, no un default implícito.

### Relojes y edades canónicas

```text
event_age_ms     = decision_time - event_time          # si event_time existe
observed_age_ms  = decision_time - observed_at
emission_delay_ms = observed_at - provider_emitted_at  # si existe
lateness_ms      = observed_at - event_time             # si event_time existe
transport_idle_ms = decision_time - last_transport_activity_at
source_idle_ms    = decision_time - last_source_event_observed_at
close_delay_ms    = observed_at - bar_close_time
```

- Una edad negativa más allá de `clock_skew_budget_ms` es `CLOCK_FAULT` y bloquea.
- Para S-04 bookTicker, que no trae event_time, sólo `observed_age_ms` es válido.
- `source_idle_ms` no prueba fallo para fuentes event-driven sin cadence garantizada.
- Todos los budgets se evalúan con reloj monotónico asociado a timestamps UTC.

### Estados de freshness

| Estado | Definición | Uso permitido |
|---|---|---|
| `FRESH` | Edad, secuencia, schema y watermark cumplen el budget del uso. | Puede entrar al `QualifiedMarketFrame`. |
| `SUSPECT` | Se aproxima o excede warning budget, pero no el hard budget. | Observabilidad; entrada bloqueada si la fuente es requerida. |
| `STALE` | Excede hard budget o perdió continuidad/vigencia. | No usar; invalida dependencias. |
| `MISSING` | Nunca se recibió el dato/campo requerido o es null no permitido. | No usar; source requirement incumplido. |
| `NOT_REQUIRED` | La Policy no declaró esa fuente/campo para esta evaluación. | Se omite explícitamente; no penaliza health. |

`DEGRADED/BLOCKED` son estados agregados del sistema; `SUSPECT/STALE/MISSING` son
estados de un dato o fuente para un uso concreto.

### Schema `FreshnessPolicy`

```text
FreshnessPolicy = {
  policy_version,
  source_contract_id,
  event_type,
  usage: STRATEGIC | PROTECTIVE | COST | CONTEXT | METADATA,
  required: bool,
  clock_basis: EVENT_TIME | OBSERVED_AT | BAR_CLOSE | SEQUENCE,
  expected_cadence_ms: integer | null,
  warning_age_ms: integer | formula,
  max_age_ms: integer | formula,
  allowed_lateness_ms: integer | formula,
  clock_skew_budget_ms: integer,
  close_grace_ms: integer | formula | null,
  heartbeat_timeout_ms: integer | null,
  recovery_rule,
  on_suspect,
  on_stale,
  decision_refs: [D-002, D-014]
}
```

Invariantes:

- `0 ≤ warning_age_ms ≤ max_age_ms`.
- `allowed_lateness_ms ≥ 0`, `clock_skew_budget_ms ≥ 0`.
- Campos/formulas no resueltos ⇒ Policy status `UNCONFIGURED` ⇒ fuente `BLOCKED`.
- Cambiar un budget crea nueva version e invalida frames/experimentos dependientes.
- Budgets se congelan antes de abrir OOS; no se ajustan observando performance.

### Parámetros simbólicos D-014

| Símbolo | Significado | Gate de resolución |
|---|---|---|
| `BBO_CAP_MS` | Edad absoluta máxima del BBO. | D-002 + latencia/uso de costo |
| `DEPTH_CAP_MS` | Edad absoluta máxima de LocalBookView LIVE. | D-002 + cadence elegida |
| `FLOW_LATENESS_MS` | Lateness aceptada para ventana de aggTrades. | Horizonte/feature de flujo |
| `BAR_CLOSE_GRACE_MS(H)` | Espera tras bar close antes de reparación REST. | Cadence + clock skew |
| `TICKER24_TTL_MS` | TTL de contexto rolling 24h. | Sólo si requerido |
| `METADATA_TTL_MS` | TTL máximo de exchangeInfo. | Antes de entrada/quantization |
| `CLOCK_SKEW_MS` | Desviación temporal tolerable. | Reloj/infra futura |
| `β_bbo`, `β_depth` | Fracción máxima de `H_decision` consumible por edad. | Pre-registro por horizonte |
| `RECOVERY_EVIDENCE_N` | Eventos/periodos sanos requeridos tras stale. | Por fuente; ≥1 |

No tienen valor numérico todavía. La única cifra operativa heredada del proveedor
es el timeout de transporte WebSocket: el servidor desconecta si no recibe pong en
1 minuto; esto no sustituye budgets de frescura económica.

### Política por fuente

| Fuente | Clock/continuidad | Regla FRESH | STALE/MISSING | Efecto seguro |
|---|---|---|---|---|
| S-01 aggTrade | `event_time=T`, sequence aggregate ID, transport | Ventana requerida completa bajo watermark y `FLOW_LATENESS_MS` | Silencio sólo no prueba stale; gap/transport fault sí | Feature de flujo `CONTEXT_INSUFFICIENT`; no inventar volumen salvo ventana continua confirmada |
| S-02 kline WS | bar close + `x`, cadence 1s/2s | Estratégico sólo `x=true`, continuidad válida y cierre finalizado | `x=false`, close ausente tras grace, gap o conflicto | No feature estratégica; iniciar S-03 reconcile |
| S-03 kline REST | identidad `(interval,open_time)` | Repara/confirma barra cerrada y coincide con schema/metadata | Request falla, conflicto no resuelto o barra aún abierta | Barra `INVALID/RECONCILING`; no decisión dependiente |
| S-04 bookTicker | `observed_at`, update ID | `observed_age ≤ min(BBO_CAP_MS, β_bbo·H_decision)` y sequence no regresiva | Budget faltante/excedido, regress/crossed BBO | `CostEstimate` bloqueado; no entrada |
| S-05/S-06 L2 | sequence + `BookSyncState` + observed_at | Sólo generation `LIVE` y age ≤ `min(DEPTH_CAP_MS, β_depth·H_decision)` | Gap, no LIVE, age excedida, heartbeat fault | Revocar view; bloquear policies que requieren L2 |
| S-07 ticker WS | event_time, cadence 1000 ms | Dentro de budget/TTL pre-registrado | Cadence perdida/age excedida | Omitir si opcional; bloquear sólo policy que lo exige |
| S-08 ticker REST | window close + observed_at | Snapshot dentro de `TICKER24_TTL_MS` | TTL faltante/excedido o request error | Igual S-07; nunca usar cache indefinida |
| S-09 exchangeInfo | observed_at + metadata hash | TTL vigente, symbol `TRADING`, filtros parseables | TTL faltante/excedido, status incompatible, schema drift | Bloquear nuevas entradas y quantization |

### Cierre de vela `BarLifecycle`

| Estado | Condición | Uso estratégico |
|---|---|---:|
| `FORMING` | WS `x=false` o `decision_time < bar_close_time`. | No |
| `CLOSE_SEEN` | Primer WS `x=true`, schema/invariantes válidos. | Aún espera continuidad/watermark. |
| `RECONCILING` | Close ausente/conflictivo; se consulta S-03. | No |
| `FINAL` | Close confirmado, sin gap, watermark cerrado y metadata compatible. | Sí |
| `LATE_CORRECTION` | Llega contenido distinto después de FINAL/Decision. | No retroactivo; incidente y futura corrección. |
| `INVALID` | OHLC/volumen/identidad/schema no reconciliables. | No; fuente bloqueada para esa ventana. |

Una barra se vuelve `FINAL` sólo si:

1. `is_closed=true` o S-03 confirma que el intervalo terminó;
2. `bar_close_time ≤ decision_time`;
3. no hay gap conocido en el required source set de esa barra;
4. OHLCV, trade range, symbol, interval y metadata pasan invariantes;
5. el watermark relevante superó `bar_close_time + allowed_lateness`;
6. cualquier WS/REST conflicto fue resuelto por regla versionada.

`FORMING` puede mostrarse, pero no alimentar señales estratégicas. Una Decision no
se recalcula retroactivamente por `LATE_CORRECTION`; se marca evidencia afectada y
se impide promoción del experimento si cambia el resultado.

### Watermark compuesto para evaluación

```text
required_sources = Policy.required_source_set
frame_watermark = min(source_watermark[s] for s in required_sources)
strategic_boundary = end_of(H_decision)
can_finalize_frame = frame_watermark >= strategic_boundary
```

- Fuente `NOT_REQUIRED` no participa en el mínimo.
- Fuente required sin watermark/budget ⇒ `MISSING/BLOCKED`.
- Arrival order nunca adelanta watermark.
- Un watermark finaliza completitud bajo D-014; no certifica verdad económica.

### Null, cero, NaN e infinito

| Valor | Semántica |
|---|---|
| `null` en campo required | `MISSING`; no imputación silenciosa. |
| `null` en campo optional | Omitir con flag `OPTIONAL_MISSING`; feature dependiente no existe. |
| `0` | Valor real potencialmente válido (volumen/cantidad), sujeto a invariantes. |
| `NaN`/`±Inf` | `REJECTED_INVARIANT`; nunca entra a feature. |
| Decimal no parseable | `REJECTED_SCHEMA`. |
| Timestamp null permitido (S-04 event_time) | Usar observed_at sólo bajo policy específica; no inventar event_time. |

Cero volumen sólo puede inferirse si el intervalo completo está probado continuo;
“no llegaron trades” con transporte/sequence inciertos es `MISSING`, no cero.

### Agregación de health

```text
for source in required_source_set:
    if freshness(source) in {STALE, MISSING} or quality in {BLOCKED, REJECTED}:
        policy_eligible = false
        health >= DEGRADED

if any core mandate/state/metadata source is invalid:
    health = BLOCKED
```

- Required `SUSPECT` bloquea nueva entrada y permite únicamente hold/protección
  bajo sus propios datos autoritativos.
- Optional stale se omite con flag; no se reemplaza por otra semántica.
- El mismo dato puede ser FRESH para contexto lento y STALE para costo inmediato;
  freshness siempre incluye `usage`.

### Invalidación y recuperación

Al pasar a `STALE/MISSING/BLOCKED`:

1. Invalidar frames, contexts, CostEstimates, intents y Decisions vigentes que
   referencian fuente/version afectada.
2. Emitir quality event con source, uso, age, budget y reason.
3. No revivir una Decision cuando vuelve la fuente; iniciar evaluación nueva.
4. Preservar ledger/evidencia histórica sin mutación.

Recuperación requiere `recovery_rule` de la FreshnessPolicy:

- S-05/S-06: nueva generación L2 `LIVE`.
- S-02/S-03: barra reconciliada `FINAL` y continuidad posterior.
- S-04/S-07: eventos válidos suficientes `RECOVERY_EVIDENCE_N` bajo budget.
- S-09: metadata nueva parseada, status/filtros válidos y hash versionado.
- Transport: nueva sesión sana; no basta un pong aislado para declarar datos fresh.

### Heartbeat y silencio

- `transport_health` y `data_freshness` son dimensiones distintas.
- Ping/pong sano no convierte un BBO viejo en fresh.
- Ausencia de aggTrade puede ser mercado sin trades; sólo continuidad+watermark
  permiten cerrar una ventana con volumen cero.
- Ausencia de kline update más allá de cadence/grace inicia reconcile.
- Ausencia de depth diff no es gap por sí sola, pero age budget puede volver stale
  la vista aunque la sequence anterior fuera continua.
- Server shutdown/WS close invalida la continuidad hasta nueva sesión/generación.

### Escenarios T2.4

| ID | Situación | Clasificación | Resultado |
|---|---|---|---|
| FRSH-01 | Kline `x=true`, continuidad y watermark superan cierre | `FINAL/FRESH` | Elegible para estrategia |
| FRSH-02 | Kline `x=false` antes de close | `FORMING` | Sólo observabilidad; no intent estratégico |
| FRSH-03 | No llega close tras `BAR_CLOSE_GRACE_MS` | `RECONCILING` | Consultar S-03; hold dependiente |
| FRSH-04 | BBO excede budget observado | `STALE` | CostEstimate/entrada bloqueados |
| FRSH-05 | No aggTrades pero stream continuo y ventana finalizada | `FRESH`, volumen 0 | Cero legítimo bajo evidencia de continuidad |
| FRSH-06 | No aggTrades y transport/sequence inciertos | `MISSING` | No imputar cero; feature ausente |
| FRSH-07 | Gap L2 aunque age sea pequeña | `STALE/BLOCKED` | Revocar generación; resync; no entrada L2-dependent |
| FRSH-08 | Ticker 24h opcional stale | `STALE` optional | Omitir contexto; no fallback cache |
| FRSH-09 | ExchangeInfo TTL vencido | `STALE` core | Bloquear entrada/quantization |
| FRSH-10 | Late correction cambia barra usada | `LATE_CORRECTION` | No retroacción; marcar evidencia y promoción |
| FRSH-11 | observed_at anterior a event_time fuera de skew | `CLOCK_FAULT` | Bloquear fuente; revisar clock/unit |
| FRSH-12 | Fuente se recupera después de Decision expirada | `FRESH` nuevo | Nueva evaluación; Decision vieja sigue inválida |

### Evidencia de cierre de T2.4

- Freshness tiene schema, uso, clocks, budgets, estados y recuperación explícitos.
- Cada fuente S-01…S-09 tiene regla de frescura y fallo seguro.
- Barra FORMING jamás se usa como cerrada; FINAL exige watermark y continuidad.
- Null/stale/missing/zero tienen semánticas diferentes y no se imputan en silencio.
- Transport heartbeat no se confunde con frescura económica.
- D-014 registra budgets numéricos pendientes; ausencia de valor bloquea.
- Doce escenarios cubren cierre, stale, silencio, gap, metadata, clock y recovery.

## Features mínimas causales — T2.5

### Principio

Una feature describe datos bajo una fórmula versionada; no constituye intent,
Decision ni edge. Toda feature declara unidad, ventana, timestamp máximo, fuentes,
parámetros y calidad. Si una precondición falla, devuelve `null + reason`, no cero,
forward-fill ni estimación optimista.

### Envelope `FeatureValue`

```text
FeatureValue = {
  feature_id,
  feature_version,
  formula_hash,
  value: Decimal | null,
  unit,
  symbol,
  as_of_time,
  max_input_event_time,
  horizon,
  window_definition,
  parameter_values,
  input_event_ids,
  source_contract_ids,
  source_watermarks,
  quality: QUALIFIED | DEGRADED | BLOCKED,
  null_reason: string | null,
  conditional_profile_ref
}
```

Invariantes:

- `max_input_event_time ≤ as_of_time`.
- Inputs de barra son `FINAL`; fuentes required están `FRESH`.
- `value=null ⇔ null_reason != null`.
- Parámetros pertenecen a una versión pre-registrada; no se optimizan durante OOS.
- Cambiar fórmula, ventana, unidad o tratamiento de null cambia feature version.

### Registro de features

| ID | Nombre canónico | Unidad | Required sources | Rol permitido |
|---|---|---|---|---|
| F-001 | `sma_N` | USDT/BTC | S-02/S-03 | Nivel descriptivo de precio suavizado |
| F-002 | `distance_to_sma_N` | ratio decimal | S-02/S-03 | Distancia normalizada, no trigger solo |
| F-003 | `sma_slope_N_K` | ratio por barra | S-02/S-03 | Dirección/ritmo descriptivo |
| F-004 | `volume_ratio_N` | ratio | S-02/S-03 | Volumen cerrado vs historia previa |
| F-005 | `true_range` | USDT/BTC | S-02/S-03 | Rango con gap respecto a close previo |
| F-006 | `atr_N` / `atr_fraction_N` | USDT/BTC / ratio | S-02/S-03 | Escala de movimiento/riesgo |
| F-007 | `realized_volatility_N` | ratio por barra | S-02/S-03 | Dispersión de log returns |
| F-008 | `spread_abs` / `spread_bps` | USDT/BTC / bps | S-04 | Costo top-of-book instantáneo |
| F-009 | `depth_vwap_slippage_Q` | USDT/BTC / bps | S-05/S-06 | Costo de barrer cantidad hipotética |
| F-010 | `round_trip_cost_bps_Q` | bps | S-04 + costos + L2 si requerido | Break-even conservador |
| F-011 | `depth_imbalance_B` | ratio [-1,1] | S-05/S-06 | Filtro L2, nunca trigger aislado |
| F-012 | `persistent_imbalance_B_W` | ratio [-1,1] | S-05/S-06 | Persistencia time-weighted con coverage |

### F-001 — Simple Moving Average

Para `N ≥ 2` barras consecutivas `FINAL`:

```text
SMA_N(t) = (1/N) · Σ[i=0..N-1] Close(t-i)
```

- Unidad: USDT/BTC.
- `null_reason=INSUFFICIENT_FINAL_BARS` si faltan N barras.
- No se rellena una barra faltante ni se usa close de barra forming.

### F-002 — Distancia precio/SMA

```text
distance_to_sma_N(t) = Close(t) / SMA_N(t) - 1
```

- Unidad: ratio decimal.
- Requiere `SMA_N(t) > 0`.
- Positivo significa close sobre media, no expectativa de subida.

### F-003 — Pendiente normalizada de SMA

Para lag `K ≥ 1` barras:

```text
sma_slope_N_K(t) = (SMA_N(t) / SMA_N(t-K) - 1) / K
```

- Unidad: retorno relativo por barra.
- Ambos SMA usan sólo barras FINAL disponibles en sus respectivos as_of.
- No se anualiza ni se compara entre timeframes sin conversión explícita.

### F-004 — Volumen relativo

La barra actual se compara contra las **N barras anteriores**, excluyéndose del
denominador:

```text
mean_prev_volume_N(t) = (1/N) · Σ[i=1..N] BaseVolume(t-i)
volume_ratio_N(t) = BaseVolume(t) / mean_prev_volume_N(t)
```

- Unidad: ratio.
- Si el promedio previo = 0: `null_reason=ZERO_VOLUME_BASELINE`.
- Volumen cero actual es válido sólo si continuidad de la barra fue demostrada.
- Quote/base volume no se mezclan en una misma versión.

### F-005 — True Range

```text
TR(t) = max(
  High(t) - Low(t),
  abs(High(t) - Close(t-1)),
  abs(Low(t)  - Close(t-1))
)
```

- Unidad: USDT/BTC.
- Requiere barra t y close previo FINAL.
- Captura gap entre barras; no es retorno ni volatilidad porcentual.

### F-006 — ATR y ATR normalizado

```text
ATR_N(t) = (1/N) · Σ[i=0..N-1] TR(t-i)
atr_fraction_N(t) = ATR_N(t) / Close(t)
```

- Unidades: ATR en USDT/BTC; fracción ATR como ratio decimal.
- Requiere N true ranges y `Close(t)>0`.
- Esta versión usa promedio simple; Wilder smoothing sería otra feature version.

### F-007 — Volatilidad realizada

```text
r(t) = ln(Close(t) / Close(t-1))
mean_r = (1/N) · Σ r_i
realized_volatility_N = sqrt( Σ(r_i - mean_r)^2 / (N-1) )
```

- Unidad: ratio por barra del timeframe declarado.
- `N ≥ 2`; no anualización implícita.
- Una versión anualizada debe declarar factor y calendario; no pertenece a F-007.

### F-008 — Mid y spread

Para bid/ask del mismo BBO FRESH:

```text
mid = (bid + ask) / 2
spread_abs = ask - bid
spread_bps = 10_000 · spread_abs / mid
buy_cross_bps  = 10_000 · (ask - mid) / mid
sell_cross_bps = 10_000 · (mid - bid) / mid
```

- Requiere `0 < bid ≤ ask` y mismo `source_sequence`/frame.
- No usa last trade como sustituto del mid.
- Spread no incluye fee, depth slippage ni market impact.

### F-009 — VWAP y slippage de profundidad

Para cantidad hipotética `Q > 0` y libro generation `LIVE`:

```text
VWAP_buy(Q)  = Σ ask_price_i · fill_qty_i / Q
VWAP_sell(Q) = Σ bid_price_i · fill_qty_i / Q

buy_depth_slippage_bps(Q)  = 10_000 · (VWAP_buy(Q) - best_ask) / best_ask
sell_depth_slippage_bps(Q) = 10_000 · (best_bid - VWAP_sell(Q)) / best_bid
```

Los niveles se consumen en orden de mejor a peor hasta completar Q.

- Si depth acumulada < Q: `null_reason=INSUFFICIENT_VISIBLE_DEPTH`.
- La estimación se limita a cobertura conocida; no asume niveles fuera del snapshot.
- Slippage se mide **más allá del best quote** para no contar spread dos veces.
- No representa queue position, latency ni reacción del mercado; esos componentes
  pertenecen al impact buffer.

### F-010 — Costo round-trip conservador

```text
round_trip_cost_bps(Q) =
    entry_fee_bps
  + exit_fee_bps
  + buy_cross_bps
  + sell_cross_bps
  + buy_depth_slippage_bps(Q)
  + sell_depth_slippage_bps(Q)
  + impact_buffer_bps(Q)
  + other_costs_bps
```

- Cada término declara lado, size, fuente y scenario (`BASE/ADVERSE/EXTREME`).
- Un término desconocido ⇒ `COST_UNKNOWN`; no se reemplaza por cero.
- Es break-even mecánico, no predicción de retorno.
- Una política cuya oportunidad bruta ≤ costo + uncertainty buffer activa
  `POLICY_FAIL-P2`.

### F-011 — Imbalance simétrico por banda

Para banda `B` bps alrededor del mid y notional visible:

```text
bid_notional_B = Σ price_i·qty_i  donde price_i ≥ mid·(1 - B/10_000)
ask_notional_B = Σ price_i·qty_i  donde price_i ≤ mid·(1 + B/10_000)

depth_imbalance_B =
  (bid_notional_B - ask_notional_B) /
  (bid_notional_B + ask_notional_B)
```

- Dominio `[-1,1]`; denominador 0 ⇒ null.
- La banda es simétrica y pre-registrada; no se eligen niveles después de ver señal.
- Requiere generation LIVE, coverage suficiente y metadata/timestamps exactos.
- Bajo D-007 es filtro/diagnóstico, no trigger autónomo.

### F-012 — Imbalance persistente time-weighted

Para ventana temporal W y snapshots válidos `I_j` mantenidos durante `Δt_j`:

```text
coverage_time = Σ Δt_j
coverage_ratio = coverage_time / W
persistent_imbalance_B_W = Σ(I_j · Δt_j) / coverage_time
```

- `Δt_j` se corta en fronteras de W y no cruza gaps/generations.
- Requiere `coverage_ratio ≥ min_coverage`, ambos pre-registrados.
- Si hay gap/resync/stale: null, no forward-fill del último imbalance.
- Time weighting evita sobreponderar periodos con más mensajes.

### Registro de parámetros pendientes

| Parámetro | Dominio | Dueño/gate | Regla anti-overfit |
|---|---|---|---|
| `N_sma`, `K_slope` | enteros ≥2 / ≥1 | Policy freeze D-010 | Grid/rango pre-registrado train-only |
| `N_volume` | entero ≥1 | Policy freeze | Barra actual siempre excluida del baseline |
| `N_atr`, `N_vol` | enteros ≥2 | Policy/risk design | No elegir por OOS |
| `Q` | BTC >0 | D-003 + sizing | Escenario, no capital inferido |
| `B` | bps >0 | D-007 | Banda simétrica pre-registrada |
| `W` | duración >0 | D-002/D-007 | No cruzar generations/gaps |
| `min_coverage` | ratio (0,1] | D-014 | Congelado antes de evaluar |
| fees/impact | bps ≥0 | D-005/D-006 | Unknown nunca se vuelve cero |

No hay valores “óptimos” en T2.5. Los números del ejemplo siguiente son didácticos
y no constituyen parámetros propuestos.

### Ejemplo manual reproducible (datos sintéticos)

Barras FINAL de una unidad de precio genérica equivalente a USDT/BTC:

| Barra | High | Low | Close | Base volume |
|---|---:|---:|---:|---:|
| t-4 | 102 | 99 | 100 | 10 |
| t-3 | 103 | 100 | 102 | 12 |
| t-2 | 104 | 100 | 101 | 8 |
| t-1 | 105 | 101 | 104 | 15 |
| t | 107 | 103 | 106 | 20 |

Con `N=3`, `K=1`:

```text
SMA_3(t)   = (101 + 104 + 106) / 3 = 103.666667
SMA_3(t-1) = (102 + 101 + 104) / 3 = 102.333333

distance_to_sma = 106 / 103.666667 - 1 = 0.022508
sma_slope_3_1   = 103.666667 / 102.333333 - 1 = 0.013029

volume_ratio_3 = 20 / ((12 + 8 + 15) / 3) = 1.714286
```

True ranges:

```text
TR(t-2) = max(104-100, |104-102|, |100-102|) = 4
TR(t-1) = max(105-101, |105-101|, |101-101|) = 4
TR(t)   = max(107-103, |107-104|, |103-104|) = 4
ATR_3   = 4
atr_fraction_3 = 4 / 106 = 0.037736
```

Log returns y volatilidad sample:

```text
r1 = ln(101/102) = -0.009852
r2 = ln(104/101) =  0.029270
r3 = ln(106/104) =  0.019048
realized_volatility_3 ≈ 0.020291 por barra
```

BBO sintético `bid=105.90`, `ask=106.10`:

```text
mid = 106.00
spread_abs = 0.20
spread_bps = 10_000·0.20/106 = 18.867925 bps
buy_cross_bps = sell_cross_bps = 9.433962 bps
```

Depth sintética para Q=1 BTC:

```text
asks: (106.10,0.5), (106.20,0.4), (106.40,0.6)
VWAP_buy(1) = 0.5·106.10 + 0.4·106.20 + 0.1·106.40 = 106.17
buy_depth_slippage = 10_000·(106.17-106.10)/106.10 = 6.597550 bps

bids: (105.90,0.6), (105.80,0.5)
VWAP_sell(1) = 0.6·105.90 + 0.4·105.80 = 105.86
sell_depth_slippage = 10_000·(105.90-105.86)/105.90 = 3.777148 bps
```

Sólo para demostrar suma dimensional, usando fees sintéticas 10 bps por lado e
impact buffer sintético 5 bps:

```text
round_trip_cost = 10 + 10 + 9.433962 + 9.433962
                  + 6.597550 + 3.777148 + 5
                = 54.242622 bps
```

No es estimación de Binance ni recomendación; `EXAMPLE_ONLY`.

Imbalance con banda que incluye los niveles anteriores:

```text
bid_notional = 0.6·105.90 + 0.5·105.80 = 116.44
ask_notional = 0.5·106.10 + 0.4·106.20 + 0.6·106.40 = 159.37
imbalance = (116.44 - 159.37) / (116.44 + 159.37) ≈ -0.155650
```

Persistencia sintética `I=[-0.10,-0.20,-0.15]`, duraciones `[10,20,30]` segundos:

```text
persistent = (-0.10·10 + -0.20·20 + -0.15·30) / 60
           = -0.158333
coverage_ratio = 60/60 = 1.0
```

Un imbalance negativo en este ejemplo no implica `EXIT_LONG`; sigue siendo una
feature descriptiva bajo D-007.

### Guards comunes y leakage

- As-of join usa el último dato FRESH con `event_time ≤ as_of_time`; nunca el más
  cercano de ambos lados.
- Denominadores históricos excluyen la barra objetivo cuando así lo define fórmula.
- Backfill/late corrections no cambian FeatureValue usado por una Decision pasada.
- No forward-fill a través de gap, generation o session incompatible.
- Features de diferente timeframe conservan timestamps y watermarks propios.
- Si una política combina features, su frame watermark es el mínimo requerido.
- Toda normalización se aprende/calibra sólo en train; no con media/desvío OOS.
- Un feature value extremo no se winsoriza salvo regla/version pre-registrada.

### Evidencia de cierre de T2.5

- Doce features tienen fórmula, unidad, fuentes, guards y null behavior.
- SMA, pendiente, volumen, ATR, volatilidad, spread, slippage/costo e imbalance
  persistente están cubiertos sin convertirse en señales.
- El ejemplo manual permite recalcular cada familia dimensionalmente.
- Costos desconocidos, depth insuficiente y denominadores cero retornan null.
- Parámetros estratégicos siguen pendientes y gobernados; no hay tuning OOS.
- Leakage, late data, gaps y cross-timeframe joins tienen prohibiciones explícitas.

## Admisión de features, exclusiones y rol L2 — T2.6

### Gate de admisión

Una feature no entra al conjunto candidato por aparecer en Binance, ser popular o
mejorar una métrica in-sample. Debe aprobar todos los criterios aplicables antes
del freeze de una Policy.

| ID | Criterio | Evidencia exigida | Fallo |
|---|---|---|---|
| AG-001 | Causalidad temporal | Fórmula, ventana y `max_input_event_time ≤ as_of_time`. | `PROHIBITED_LEAKAGE` |
| AG-002 | Contrato de fuente | S-ID, schema, unidad, identity y freshness definidos. | `DEFERRED_NO_SOURCE_CONTRACT` |
| AG-003 | Invariantes/nulls | Dominio, guards y null_reason completos. | `REJECTED_UNDEFINED_SEMANTICS` |
| AG-004 | Mecanismo falsable | Explicación causal y condición observable de invalidación. | `DEFERRED_NO_HYPOTHESIS` |
| AG-005 | Disponibilidad/muestra | Cobertura suficiente por régimen/horizonte, predefinida. | `DEFERRED_INSUFFICIENT_SAMPLE` |
| AG-006 | Harvestability | Cadence, latency, queue/fill y tamaño compatibles con el uso. | `REJECTED_UNHARVESTABLE` |
| AG-007 | Cost viability | Movimiento bruto plausible puede superar F-010 + buffer. | `POLICY_FAIL-P2` |
| AG-008 | Valor incremental | Aporta información OOS frente al set más simple. | `EXCLUDED_REDUNDANT` |
| AG-009 | Complejidad/sensibilidad | Parámetros acotados y estabilidad ante perturbaciones. | `DEFERRED_PARAMETER_FRAGILITY` |
| AG-010 | Auditabilidad/fail-safe | Required sources, provenance, quality y conducta stale declaradas. | `REJECTED_UNAUDITABLE` |

AG-006/AG-007 se evalúan aunque la correlación o hit-rate bruto parezcan altos. Una
feature predictiva pero no cosechable no es edge utilizable.

### Estados de catálogo

| Estado | Significado |
|---|---|
| `CORE_DESCRIPTIVE` | Necesaria para contexto/riesgo/costo; aún no es señal. |
| `POLICY_CANDIDATE` | Puede entrar a una hipótesis pre-registrada y falsable. |
| `OPTIONAL_FILTER` | Puede vetar/diagnosticar bajo regla explícita; no dispara sola. |
| `DEFERRED_HYPOTHESIS` | Requiere fuente, muestra, mecanismo o modelo adicional. |
| `EXCLUDED_REDUNDANT` | Duplica información sin valor incremental demostrado. |
| `PROHIBITED` | Introduce leakage, semántica inválida o bypass de gates. |

### Clasificación de F-001…F-012

| Features | Estado | Rol actual | Restricción |
|---|---|---|---|
| F-001…F-003 | `CORE_DESCRIPTIVE` | Precio suavizado, distancia y pendiente. | No forman intent hasta pertenecer a Policy. |
| F-004 | `POLICY_CANDIDATE` | Volumen relativo cerrado. | Requiere mecanismo y denominador pre-registrados. |
| F-005…F-007 | `CORE_DESCRIPTIVE` | Escala de rango/volatilidad para contexto y riesgo. | No predicen dirección por definición. |
| F-008…F-010 | `CORE_DESCRIPTIVE` | Liquidez, costo y break-even. | Son gates/vetos, no oportunidad. |
| F-011…F-012 | `OPTIONAL_FILTER` | Diagnóstico/veto L2 bajo D-007. | Nunca evidence set único de ENTER/EXIT. |

### Features/ideas no admitidas por defecto

| Candidata excluida o diferida | Estado | Razón |
|---|---|---|
| Copiar “MA60” de la vista `Time` | `PROHIBITED` | Timeframe/muestras no definidos; semántica visual no es contrato. |
| Indicadores sobre barra forming | `PROHIBITED` | Violan cierre estratégico y pueden repaint. |
| Ventanas centradas o normalización con dataset completo | `PROHIBITED` | Leakage futuro/global. |
| Balance/PnL como feature de mercado | `PROHIBITED` | Pertenece a PortfolioState/Risk, no describe oportunidad externa. |
| Imbalance de una sola captura o barra 67.75/32.25 | `PROHIBITED` como trigger | Sin alcance, persistencia, sequence ni prueba de ejecución. |
| “Walls” visuales de depth | `PROHIBITED` como trigger | Cancelables, coverage limitada y sin queue position. |
| Conteo bruto de mensajes L2 | `DEFERRED_HYPOTHESIS` | Event-rate depende de venue/cadence y sesga muestreo. |
| Último trade/aggressor aislado | `DEFERRED_HYPOTHESIS` | Ruido micro; requiere ventana, costo y falsación. |
| EMA/MACD derivados del mismo close | `EXCLUDED_REDUNDANT` por default | Alta colinealidad/parameter search; deben probar incremento OOS. |
| RSI/Bollinger/SAR/Supertrend | `DEFERRED_HYPOTHESIS` | No se agregan como “indicator zoo”; cada uno necesita mecanismo/gate. |
| Rendimiento rolling 24h como trigger | `DEFERRED_HYPOTHESIS` | Contexto móvil, no día UTC; mecanismo direccional no definido. |
| Sentiment/news/social | `DEFERRED_NO_SOURCE_CONTRACT` | Sin provenance, timestamp y universo de revisión. |
| On-chain/funding | `DEFERRED_NO_SOURCE_CONTRACT` | Fuera de fuentes S-01…S-09 y cadence actual. |
| Cross-venue spread/arbitrage | `DEFERRED_HYPOTHESIS` | Requiere clocks, libros, balances y ejecución multi-venue. |
| “AI confidence” no calibrada | `PROHIBITED` | Score sin población/calibración no es probabilidad. |

Excluir por default no afirma que una familia nunca funcione; impide introducirla
sin cumplir el mismo gate y crear nueva feature/policy version.

### Rol normativo del order book

D-007 queda `DECIDED` para este alcance:

1. **Calidad:** continuidad, spread/crossed-book, coverage y freshness.
2. **Costo:** F-008/F-009/F-010 para spread, depth slippage y break-even.
3. **Veto de liquidez:** bloquear entrada si costo/depth/quality no cumplen gates.
4. **Diagnóstico:** F-011/F-012 pueden explicar contexto, con generation y coverage.
5. **Research-only:** una policy L2 direccional futura exige nueva decisión/version.

Reglas no negociables actuales:

- `ENTER_LONG` no puede tener sólo F-011/F-012 en `evidence_refs`.
- F-011/F-012 no pueden ser `primary_reason=OPPORTUNITY_APPROVED`.
- Imbalance positivo no crea intent; como máximo no activa un veto ya definido.
- Imbalance negativo no crea `EXIT_LONG`; una salida necesita Policy o protección.
- `STALE`, gap, resync o coverage insuficiente producen null/veto, no último valor.
- L2 nunca modifica RiskMandate ni el target size por sí solo.

### Por qué imbalance puede mentir

| Mecanismo | Qué observa el agente | Qué puede ocurrir realmente | Riesgo |
|---|---|---|---|
| Spoofing/cancelación | Gran qty bid/ask visible | Se cancela antes de trade. | Intención aparente falsa. |
| Hidden/iceberg liquidity | Poca qty visible | Liquidez real se repone/no aparece. | Depth subestima capacidad. |
| Queue position desconocida | Precio/qty de nivel | Orden propia estaría detrás de otras. | Fill irrealista. |
| Snapshot limitado | Hasta 5000 niveles | Fuera de cobertura queda desconocido. | “Libro completo” falso. |
| Latencia | Imbalance al event_time/observed_at | Mercado cambia antes de decidir/ejecutar. | Edge no cosechable. |
| Event-time sampling | Muchos updates en ráfaga | Media por mensaje sobrepondera actividad. | Sesgo; usar time-weighting. |
| Market sweep | Bids abundantes | Aggressor grande consume niveles. | Imbalance cambia durante fill. |
| Adverse selection | Limit parece barata | Fill ocurre precisamente antes de movimiento adverso. | Modelo maker optimista. |
| Cost dominance | Dirección acertada pocos bps | Spread+fees+slippage superan movimiento. | Predicción sin utilidad. |
| Regime dependence | Patrón histórico estable | Participantes/cadence cambian. | Inversión/decay OOS. |

### Contraejemplos obligatorios L2

| ID | Setup | Lectura ingenua | Resultado compatible | Conclusión |
|---|---|---|---|---|
| CE-L2-01 | Imbalance +0.70 por gran bid | “Comprar” | Bid se cancela; precio cae. | Snapshot no demuestra intención. |
| CE-L2-02 | Ask visible pequeño | “Subirá fácil” | Iceberg ask repone continuamente. | Visible depth incompleta. |
| CE-L2-03 | Bids dominan por notional | “Soporte” | Market sell barre bids. | Qty publicada no es flujo ejecutado. |
| CE-L2-04 | Predictor acierta +3 bps | “Edge” | Round-trip cuesta 20 bps. | Falla AG-007. |
| CE-L2-05 | Maker backtest llena al bid | “Spread capturado” | Orden queda atrás/no llena. | Queue/fill model obligatorio. |
| CE-L2-06 | Imbalance medio por mensajes +0.4 | “Persistente” | Ráfaga de 100 updates duró 10 ms. | Event sampling sesgado. |
| CE-L2-07 | Último libro parece LIVE | “Usar último valor” | Gap de sequence no observado. | Revocar; no fallback. |
| CE-L2-08 | F-012 positivo 30 s | “Confirmación” | Horizon es horas y patrón decae. | Mismatch temporal. |
| CE-L2-09 | Señal funciona en baja vol | “Robusta” | En alta vol slippage se multiplica. | Condicionar/falsar por régimen. |
| CE-L2-10 | BBO sano, depth sano | “Ejecutable” | Metadata/filter cambió y tamaño inválido. | S-09 y CostEstimate siguen requeridos. |

### Ruta para reabrir una policy L2 direccional

Se requiere **nuevo** decision-log record y policy version con:

- mecanismo causal distinto de “más bids ⇒ sube”;
- dataset histórico L2 con timestamps/sequence/cobertura suficientes;
- split temporal, purga/embargo y parámetros congelados;
- modelo de latency, queue, fill, adverse selection y cancelación;
- costos maker/taker y tamaño realistas;
- comparación neta contra `HOLD` y policy más simple;
- estabilidad por régimen y sensibilidad;
- contraejemplos CE-L2-01…10 ejecutados;
- aprobación de AG-001…AG-010.

Sólo entonces D-007 puede revisarse para una nueva versión; el alcance actual no
cambia retroactivamente.

### Auditoría y gate de Fase 2

| Entregable | Evidencia | Resultado |
|---|---|---|
| Fuentes oficiales | T2.1: S-01…S-09, campos/unidades/limits/auth | PASS |
| Schema de eventos | T2.2: MarketEventV1 + delivery classes | PASS |
| Libro L2 | T2.3: 8 estados, L2-001…023, revocación por gap | PASS |
| Freshness/cierre | T2.4: S-01…09, BarLifecycle, D-014 | PASS_CONDITIONAL |
| Features | T2.5: F-001…F-012, fórmulas y cálculo manual | PASS |
| Admisión/exclusiones | T2.6: AG-001…010, D-007 y CE-L2-01…10 | PASS |

Resultados agregados:

- Source contracts: **9/9**.
- Event types canónicos: **8/8**.
- Features mínimas formalizadas: **12/12**.
- Features sin fórmula/unidad/null behavior: **0**.
- Features L2 autorizadas como trigger autónomo: **0**.
- Exclusiones sin razón/gate de reapertura: **0**.
- Blockers activos: **0**.

**Veredicto de Fase 2: `PASS_CONDITIONAL`.** El contrato de datos/features está
completo para ideación. D-002 (horizonte), D-008 (fuente final) y D-014 (budgets
numéricos) deben resolverse antes de congelar policies o abrir OOS. El trabajo
conceptual puede avanzar usando símbolos y etiquetas explícitas.

### Evidencia de cierre de T2.6

- Cada feature entra, se difiere, excluye o prohíbe mediante AG-001…AG-010.
- Indicator zoo, forming bars, leakage y señales visuales sin contrato no entran.
- L2 tiene cinco roles permitidos y seis prohibiciones decisionales.
- Diez mecanismos y diez contraejemplos impiden “imbalance = dirección”.
- D-007 está resuelta y la reapertura requiere nueva policy/version + gate completo.
- Fase 2 cierra condicionalmente sin fabricar edge ni ocultar decisiones pendientes.

## Política nula `NULL_HOLD` — T3.1

### Propósito

`NULL_HOLD` es el control negativo de toda comparación. Demuestra cuánto valor,
riesgo y costo añade una policy candidata frente a no proponer oportunidades. No
predice, no usa indicadores y no crea exposición.

No equivale a “apagar el sistema”: calidad, Custodio, Gobernador, Máquina y Ledger
siguen operando. Una salida protectora independiente puede producir `EXIT_LONG`
aunque la Política nula emita `NO_INTENT`.

### Identidad y contrato

```text
NullPolicy = {
  policy_id: "POL-000-NULL-HOLD",
  policy_version: "1.0.0",
  hypothesis: "No existe oportunidad suficientemente demostrada",
  required_source_set: [],
  parameters: {},
  allowed_intents: [NO_INTENT],
  deterministic: true
}
```

Output canónico:

```text
CandidateIntent = {
  intent_type: NO_INTENT,
  policy_id: POL-000-NULL-HOLD,
  policy_version: 1.0.0,
  evaluation_id,
  state_ref,
  market_context_ref: null,
  cost_estimate_ref: null,
  evidence_refs: [],
  expected_gross_return: null,
  invalidation_condition: null,
  primary_reason: POLICY_NULL_CONTROL,
  reason_codes: [POLICY_NULL_CONTROL],
  effective_at: decision_time,
  expires_at: next_evaluation_boundary,
  quality: QUALIFIED
}
```

No requerir fuentes no significa que el sistema pueda entrar sin datos: significa
que esta Policy no solicita entrada. Los gates sistémicos siguen determinando el
reason final de `HOLD` o una eventual salida protectora.

### Función total

```text
NULL_HOLD.evaluate(evaluation_id, state_ref, decision_time)
    -> canonical NO_INTENT
```

La función ignora valores de features para decidir, pero conserva referencias de
estado/evaluación necesarias para idempotencia. Para los mismos inputs/versiones y
reloj explícito produce el mismo CandidateIntent.

### Comportamiento por configuración de estado

| Position/Evaluation/Health | Output de NULL_HOLD | Decision esperada sin evento superior | Excepción de mayor prioridad |
|---|---|---|---|
| `UNKNOWN/IDLE/BLOCKED` | `NO_INTENT` | `HOLD/STATE_UNKNOWN` | Reconciliación autoritativa |
| `FLAT/IDLE/READY` | `NO_INTENT` | `HOLD/NO_INTENT` | Ninguna entrada |
| `FLAT/ENTRY_CANDIDATE/READY` | `NO_INTENT` | Cancelar candidate; `HOLD/NO_INTENT` | Candidate previo queda inválido por cambio de policy/version |
| `FLAT/COOLDOWN/*` | `NO_INTENT` | `HOLD/COOLDOWN` | `COOLDOWN_EXPIRED` sólo vuelve a IDLE |
| `ENTRY_PENDING/IDLE/*` | `NO_INTENT` | `HOLD/PENDING_FEEDBACK` | Fill/reject autoritativo |
| `LONG/IDLE/READY` | `NO_INTENT` | `HOLD/NO_INTENT`, target unchanged | Salida protectora/mandato |
| `LONG/IDLE/DEGRADED` | `NO_INTENT` | `HOLD` con health reason | Trigger protector válido |
| `LONG/IDLE/BLOCKED` | `NO_INTENT` | `HOLD/BLOCKED` | Salida protectora con datos autoritativos suficientes |
| `LONG/EXIT_CANDIDATE/*` | `NO_INTENT` estratégico | Policy no crea salida; Máquina conserva prioridad existente | Candidate protector no se cancela |
| `EXIT_PENDING/IDLE/*` | `NO_INTENT` | `HOLD/PENDING_FEEDBACK` | Fill/cancel/reject autoritativo |
| `FLAT/IDLE/DEGRADED` | `NO_INTENT` | `HOLD` con quality reason | Recuperación de fuente |
| `FLAT/IDLE/BLOCKED` | `NO_INTENT` | `HOLD/BLOCKED` | Recuperación/reconciliación |

Así, cada configuración válida tiene output sin inventar oportunidad. La Policy
nunca produce `ENTRY_INTENT`, `EXIT_INTENT`, target size o RiskVerdict.

### Invariantes de seguridad

- `intent_type == NO_INTENT` en toda evaluación.
- `required_source_set == []`; stale market data no se transforma en intent.
- `parameters == {}`; no existe tuning ni selección in-sample.
- `expected_gross_return == null`; no se afirma retorno cero esperado.
- No crea `ENTER_LONG`, `EXIT_LONG`, Order, Fill ni Position.
- Si PositionState es `FLAT`, permanece FLAT salvo reconciliación externa.
- Si PositionState es `LONG`, conserva exposición salvo decisión protectora externa.
- No bloquea ni degrada una salida protectora de mayor prioridad.
- Toda evaluación produce intent y ledger record idempotentes.

### Baselines económicos derivados

La misma policy produce dos trayectorias según el estado inicial; no deben
mezclarse:

| Baseline | Estado inicial | Comportamiento | Costos propios de policy |
|---|---|---|---|
| `NULL_CASH` | `FLAT` | Nunca entra; exposición 0. | Turnover y trading costs = 0. |
| `NULL_KEEP_POSITION` | `LONG` | Mantiene posición confirmada salvo overlay protector común. | Sin costo por self-loop; salida protectora se contabiliza en overlay común. |

Las candidatas se comparan con el baseline que parte del **mismo** PortfolioState,
RiskMandate, datos, reloj y overlay protector. No se permite elegir baseline ex post.

### Métricas del control

| Métrica | Definición bajo NULL_HOLD |
|---|---|
| `new_entry_count` | 0, hard invariant. |
| `policy_exit_count` | 0; exits protectores se atribuyen al overlay. |
| `policy_turnover` | 0. |
| `policy_transaction_cost` | 0. |
| `gross/net_return` | Depende de estado inicial: cash o posición mantenida. |
| `drawdown` | 0 para cash nominal; para long depende del mercado/overlay. |
| `blocked_decision_count` | Diagnóstico del sistema, no fallo de NULL_HOLD. |
| `opportunity_regret` | Sólo métrica ex post; nunca input de Policy. |

### Incremento de utilidad de una candidata

Para ventanas OOS emparejadas:

```text
DeltaU(policy) = U_net(policy | same initial state, mandate, data, overlay)
                 - U_net(NULL_HOLD | same conditions)
```

Una candidata sólo añade valor si `DeltaU` supera el margen pre-registrado D-009,
con costos, riesgo y uncertainty incluidos. Return bruto o hit-rate no reemplazan
esta comparación.

### Costo de oportunidad y regret

Para análisis diagnóstico posterior:

```text
opportunity_cost_HOLD(window) =
    U_net(pre_registered_counterfactual, window)
    - U_net(NULL_HOLD, window)
```

Reglas:

1. El counterfactual se define **antes** de abrir outcomes; no se usa “mejor acción
   en hindsight” entre muchas alternativas.
2. Paga fees, spread, slippage, impact y restricciones de fill igual que la Policy.
3. Parte del mismo estado, capital, mandato y timestamp.
4. Un regret positivo no convierte retrospectivamente HOLD en error ni crea label
   de entrada para la misma muestra.
5. Regret negativo significa que abstenerse fue mejor neto de utility/costos.
6. La distribución de regret se reporta junto con coverage; no sólo promedio.
7. Hard gates siguen dominando: oportunidad perdida nunca justifica romper safety.

### Equidad de comparación

| Dimensión | Requisito pareado |
|---|---|
| Dataset/splits | Mismos periodos, purga, embargo y eventos disponibles. |
| Initial state | Idéntico PortfolioState y capital. |
| Risk | Mismo RiskMandate y overlay protector. |
| Costs | Mismo modelo y scenario aplicable; candidata paga su turnover. |
| Freshness | Misma evidencia/quality; no imputación especial. |
| Decision clock | Mismos evaluation boundaries y latencia modelada. |
| Missing data | Misma política de bloqueo; no excluir sólo pérdidas de candidata. |
| Metrics | Mismo utility, drawdown, coverage y uncertainty. |

### Casos de prueba de totalidad

| ID | Caso | Resultado obligatorio |
|---|---|---|
| NULL-01 | FLAT/READY con todos los features alcistas | `NO_INTENT` → `HOLD`; features ignoradas por control. |
| NULL-02 | FLAT/BLOCKED | `NO_INTENT` → `HOLD/BLOCKED`. |
| NULL-03 | LONG/READY sin protector | `NO_INTENT` → mantener target. |
| NULL-04 | LONG + trigger protector | Policy `NO_INTENT`; Máquina puede `EXIT_LONG`. |
| NULL-05 | ENTRY_PENDING | `NO_INTENT`; no segunda entrada. |
| NULL-06 | EXIT_PENDING | `NO_INTENT`; espera feedback. |
| NULL-07 | COOLDOWN | `NO_INTENT`; hold por cooldown. |
| NULL-08 | Datos late/out-of-order | Output idéntico; health/ledger registran calidad. |
| NULL-09 | Mismo evaluation repetido | Mismo intent ID; duplicate no reaplica. |
| NULL-10 | Features null/NaN | Output sigue `NO_INTENT`; no excepción ni entrada. |
| NULL-11 | Cambio de Policy a NULL_HOLD con candidate previo | Candidate previo expira; no se hereda. |
| NULL-12 | RiskMandate ausente | `NO_INTENT`; final hold/bloqueo, nunca entrada. |

### Condiciones de fallo del control

`NULL_HOLD` falla su contrato si:

- produce cualquier intent distinto de `NO_INTENT`;
- requiere un feature para completar evaluación;
- cambia PositionState o target directamente;
- impide una salida protectora de mayor prioridad;
- genera IDs distintos para inputs/versiones idénticos;
- atribuye costo/retorno protector a la Policy de forma desigual;
- usa regret u outcomes futuros como input.

### Relación con `NO_GO`

Que `NULL_HOLD` sea seguro no demuestra que el producto sea útil. Si todas las
policies candidatas tienen `DeltaU ≤ gate` frente al control después de costos y
riesgo, el resultado correcto es `NO_GO` o `PIVOT`, no declarar ganador a HOLD ni
fabricar una entrada.

### Evidencia de cierre de T3.1

- La policy nula tiene contrato, output y comportamiento para todas las
  configuraciones válidas.
- Nunca crea exposición, predicción o parámetro.
- Protección sistémica permanece operativa y separada.
- Cash vs keep-position están separados por estado inicial.
- Delta utility y opportunity cost tienen comparación pareada sin hindsight libre.
- Doce casos y siete condiciones de fallo hacen falsable el control.

## Políticas candidatas greenfield — T3.2

### Estado y alcance

D-010 fija una shortlist conceptual, no un ranking:

| Policy ID | Nombre | Mecanismo hipotético | Estado |
|---|---|---|---|
| `POL-000` | `NULL_HOLD` | Abstención/control | `CONTROL_DECIDED` |
| `POL-101` | `TREND_PULLBACK_RESUME` | Persistencia después de pullback | `CANDIDATE_UNVALIDATED` |
| `POL-102` | `VOLATILITY_SCALED_REVERSION` | Reversión de dislocación temporal | `CANDIDATE_UNVALIDATED` |
| `POL-103` | `VOLATILITY_BREAKOUT` | Continuación tras ruptura/expansión | `CANDIDATE_UNVALIDATED` |

Ninguna candidata puede describirse como edge, ganadora o superior hasta completar
freeze, falsación y validación futura. T3.2 sólo demuestra diversidad causal y
especificabilidad.

### Contrato común `PolicySpecV1`

```text
PolicySpecV1 = {
  policy_id,
  policy_version,
  status: CANDIDATE_UNVALIDATED,
  hypothesis,
  mechanism,
  falsification_claim,
  product_profile_ref: CP-01,
  allowed_position_states,
  required_source_set,
  optional_source_set,
  required_features,
  policy_local_features,
  setup_states,
  entry_guards,
  exit_guards,
  setup_invalidation,
  position_invalidation,
  parameter_registry,
  cost_gate: F-010,
  risk_interface: CandidateIntent_only,
  reason_namespace,
  expected_failure_modes,
  prohibited_shortcuts,
  preregistration_status
}
```

Reglas comunes:

1. Sólo consume barras `FINAL` y features `QUALIFIED/FRESH` al as_of.
2. Sólo propone `CandidateIntent`; nunca RiskVerdict, Decision, target size u Order.
3. Entrada requiere `FLAT/READY`, no pending/cooldown y F-010 conocido.
4. Salida estratégica requiere `LONG`; salida protectora sigue siendo externa.
5. L2 no es trigger ni primary reason bajo D-007.
6. Parámetros y required sources se congelan antes de abrir OOS.
7. Missing/null no se convierte en condición false favorable; produce `NO_INTENT`.
8. Todas pagan los mismos costos, usan el mismo RiskMandate y se comparan con
   `POL-000` bajo ventanas pareadas.
9. Cada setup expira; no se mantiene armado indefinidamente.
10. Toda hipótesis declara qué observación la refutaría.

### Output común de candidata

```text
CandidateIntent = {
  intent_type: ENTRY_CANDIDATE | EXIT_CANDIDATE | NO_INTENT,
  policy_id,
  policy_version,
  setup_id,
  setup_state,
  evaluation_id,
  state_ref,
  market_context_ref,
  cost_estimate_ref,
  evidence_refs,
  hypothesis_ref,
  invalidation_condition,
  expected_horizon: H_decision,
  effective_at,
  expires_at,
  primary_reason: policy:<policy_id>:<reason>,
  quality
}
```

`expected_gross_return` permanece null hasta que exista estimador empírico
pre-registrado; una regla técnica no inventa expectativa numérica.

## POL-101 — `TREND_PULLBACK_RESUME`

### Hipótesis y mecanismo

Mercados con underreaction/ajuste gradual pueden exhibir persistencia direccional.
Dentro de una tendencia positiva ya observada, un pullback acotado seguido de
reanudación podría ofrecer mejor asimetría que entrar tras extensión extrema.

Esto es una hipótesis de **continuación condicionada**, no “precio sobre SMA = buy”.

### Fuentes/features

- Required: S-02/S-03 barras, S-04 BBO, S-09 metadata, F-001/F-002/F-003/F-004,
  F-006/F-008/F-010.
- Optional filter: F-011/F-012 sólo para veto/diagnóstico bajo D-007.
- No usa barra forming ni 24h ticker como trigger.

### State machine del setup

```text
TREND_IDLE
  -- positive trend context --> PULLBACK_ARMED
PULLBACK_ARMED
  -- bounded pullback + resume confirmation --> ENTRY_CANDIDATE
  -- trend breaks / timeout / cost fails --> INVALIDATED
```

### Predicados simbólicos

```text
trend_context :=
    sma_slope_N_K >= theta_slope
    and Close > SMA_N
    and atr_fraction_N in [atr_min, atr_max]

pullback_armed :=
    distance_to_sma_N in [pullback_low, pullback_high]
    and trend_context

resume :=
    distance_to_sma_N > resume_level
    and prior_distance <= resume_level
    and volume_ratio_N >= volume_confirm

entry_setup := trend_context and pullback_armed_previously and resume
               and round_trip_cost_bps(Q) <= cost_cap
```

No se fija dirección si `pullback_low/high`, `resume_level` o `theta_slope` no
están pre-registrados.

### Exit e invalidación

- Exit candidate: slope cruza `trend_exit_level`, close pierde anchor por
  `exit_atr_multiple`, expira `max_holding_bars` o hipótesis se invalida.
- Setup se invalida antes de entrada si slope deja de ser positiva, pullback excede
  `pullback_fail_atr`, costo pasa cap, datos degradan o `arm_timeout_bars` expira.
- Target/protección quedan en Gobernador, no en Policy.

### Parámetros pendientes

`N_sma`, `K_slope`, `theta_slope`, `atr_min/max`, `pullback_low/high`,
`resume_level`, `volume_confirm`, `cost_cap`, `arm_timeout_bars`,
`exit_atr_multiple`, `max_holding_bars`.

### Falsificación esperada

- No hay DeltaU neta frente a NULL_HOLD en ventanas con setup.
- La continuación desaparece al incluir costos/latencia.
- Parámetros vecinos cambian signo o coverage colapsa.
- Resultado sólo existe en una tendencia/regime retrospectivamente seleccionado.

### Failure modes

Whipsaw lateral, entrada tardía, trend exhaustion, gaps contra posición, alto
turnover, colinealidad SMA/slope/distance y selección de bandas ex post.

## POL-102 — `VOLATILITY_SCALED_REVERSION`

### Hipótesis y mecanismo

Desequilibrios temporales de liquidez pueden alejar precio de un anchor más de lo
justificado por volatilidad reciente y revertir parcialmente. La policy long-only
espera confirmación de estabilización; no compra toda caída.

### Features locales

```text
dislocation_atr_N = (Close - SMA_N) / ATR_N
reversion_velocity = dislocation_atr_N(t) - dislocation_atr_N(t-1)
```

- Required: S-02/S-03, S-04, S-09, F-001/F-003/F-004/F-006/F-007/F-008/F-010.
- F-011/F-012 opcionales sólo como veto de liquidez.

### State machine del setup

```text
REVERSION_IDLE
  -- negative dislocation, admissible regime --> DISLOCATION_ARMED
DISLOCATION_ARMED
  -- stabilization/reversion confirmation --> ENTRY_CANDIDATE
  -- falling-knife invalidation / timeout --> INVALIDATED
```

### Predicados simbólicos

```text
admissible_context :=
    sma_slope_N_K >= slope_floor
    and realized_volatility_N <= vol_ceiling

dislocation := dislocation_atr_N <= entry_dislocation
stabilization :=
    reversion_velocity >= min_reversion_velocity
    and Close >= prior_Close_or_confirmation_level

entry_setup := admissible_context and dislocation_armed_previously
               and stabilization
               and round_trip_cost_bps(Q) <= cost_cap
```

### Exit e invalidación

- Exit candidate al alcanzar `reversion_target_atr`, expirar `max_holding_bars` o
  romper anchor/regime.
- Setup/posición estratégica se invalida si dislocation cruza `hard_fail_atr`,
  slope cae bajo `trend_break_floor`, volatilidad excede ceiling o costo se vuelve
  desconocido.
- “Más negativo” no es mejor setup: sin stabilization no hay intent.

### Parámetros pendientes

`N_anchor`, `N_atr`, `N_vol`, `slope_floor`, `vol_ceiling`, `entry_dislocation`,
`min_reversion_velocity`, `confirmation_level`, `reversion_target_atr`,
`hard_fail_atr`, `trend_break_floor`, `arm_timeout_bars`, `max_holding_bars`,
`cost_cap`.

### Falsificación esperada

- Dislocaciones continúan en vez de revertir neto de costos.
- Confirmación sólo retrasa pérdidas sin mejorar tail risk.
- Edge depende de elegir anchor/threshold ex post.
- Drawdown/falling-knife viola RiskMandate o domina utility.

### Failure modes

Tendencia estructural bajista, cambio de anchor, gaps, volatilidad explosiva,
muestra escasa de extremos, payoff asimétrico adverso y múltiples pruebas de
thresholds.

## POL-103 — `VOLATILITY_BREAKOUT`

### Hipótesis y mecanismo

Compresión seguida de ruptura confirmada puede representar transición a un nuevo
régimen de información/volatilidad con continuación suficiente para superar
costos. No compra simplemente un nuevo máximo; exige cierre, expansión y volumen.

### Features locales

Para `N_breakout` barras previas FINAL, excluyendo t:

```text
prior_high_N(t) = max(High(t-i), i=1..N_breakout)
breakout_distance_atr = (Close(t) - prior_high_N(t)) / ATR_N(t)
compression_ratio = ATR_short(t-1) / ATR_long(t-1)
```

- Required: S-02/S-03, S-04, S-09, F-004/F-006/F-007/F-008/F-010.
- Prior high excluye barra actual para evitar tautología/leakage.
- L2 opcional sólo veta costo/liquidez.

### State machine del setup

```text
BREAKOUT_IDLE
  -- pre-break compression/context --> COMPRESSION_ARMED
COMPRESSION_ARMED
  -- closed breakout + expansion + volume --> ENTRY_CANDIDATE
  -- compression expires / false break / cost fails --> INVALIDATED
```

### Predicados simbólicos

```text
compression := compression_ratio <= compression_ceiling
breakout := Close > prior_high_N + breakout_buffer_atr * ATR_N
expansion := atr_fraction_N >= prior_atr_fraction * min_expansion_ratio
confirmation := volume_ratio_N >= volume_confirm

entry_setup := compression_armed_previously and breakout and expansion
               and confirmation
               and round_trip_cost_bps(Q) <= cost_cap
```

### Exit e invalidación

- Exit candidate por cierre de vuelta bajo `breakout_level - fail_atr*ATR`, trailing
  conceptual, time stop o pérdida de regime.
- Setup expira tras `compression_timeout` o si price rompe antes sin cierre/volumen.
- Gap por encima no se asume ejecutable al close observado; F-009/F-010 deben
  representar costo/slippage.

### Parámetros pendientes

`N_breakout`, `N_atr_short/long`, `compression_ceiling`, `breakout_buffer_atr`,
`min_expansion_ratio`, `volume_confirm`, `false_break_atr`, `trail_atr`,
`compression_timeout`, `max_holding_bars`, `cost_cap`.

### Falsificación esperada

- False-break rate/costos eliminan DeltaU.
- Continuación sólo existe antes de modelar gap/slippage.
- Compression/breakout parameters son frágiles.
- Resultados dependen de eventos excepcionales y no tienen muestra efectiva.

### Failure modes

Breakout crowding, gaps, slippage, reversión inmediata, volatilidad sin dirección,
entrada tardía, concentración en pocos trades y sensibilidad a lookback/buffer.

### Distinción causal — no ranking

| Dimensión | POL-101 Trend | POL-102 Reversion | POL-103 Breakout |
|---|---|---|---|
| Dependencia hipotética | Autocorrelación positiva/underreaction | Reversión tras dislocación | Cambio de régimen tras ruptura |
| Setup | Tendencia + pullback | Desviación + estabilización | Compresión + nivel roto |
| Entry confirmation | Reanudación + volumen | Velocidad de reversión | Cierre + expansión + volumen |
| Principal adversario | Whipsaw/exhaustion | Falling knife | False breakout/slippage |
| Exit conceptual | Trend invalidation | Retorno al anchor/fallo | Reentrada al rango/trailing |
| Parámetro dominante | Slope/pullback bands | Dislocation/anchor | Lookback/buffer/compression |

La tabla demuestra mecanismos distintos; no puntúa ni selecciona.

### Reglas de igualdad experimental

- Mismo CP-01, splits, RiskMandate, cost model, freshness y decision clock.
- Cada policy tiene su propio setup state, pero la misma Machine/Decision contract.
- Mismo tratamiento de missing/late/gaps y mismo overlay protector.
- Search budget comparable y registrado; no dar más intentos a una favorita.
- Todas compiten contra POL-000 y luego entre sí sólo bajo T3.3/D-009.
- Una policy con menos coverage reporta la abstención; no elimina ventanas perdedoras.

### Casos conceptuales mínimos

| ID | Policy | Caso | Resultado esperado |
|---|---|---|---|
| PC-01 | POL-101 | Slope positivo sin pullback previo | `NO_INTENT` |
| PC-02 | POL-101 | Pullback armado + resume + gates | `ENTRY_CANDIDATE` |
| PC-03 | POL-101 | Pullback excede fail band | Setup invalidado |
| PC-04 | POL-102 | Dislocation sin estabilización | `NO_INTENT` |
| PC-05 | POL-102 | Dislocation armada + reversión | `ENTRY_CANDIDATE` |
| PC-06 | POL-102 | Slope rompe floor/falling knife | Setup invalidado |
| PC-07 | POL-103 | Nuevo high sin compresión | `NO_INTENT` |
| PC-08 | POL-103 | Compresión + breakout cerrado + volumen | `ENTRY_CANDIDATE` |
| PC-09 | POL-103 | Breakout sin costo conocido | `NO_INTENT/COST_UNKNOWN` |
| PC-10 | Todas | L2 imbalance positivo aislado | `NO_INTENT`; D-007 |
| PC-11 | Todas | Health DEGRADED/BLOCKED | No entrada |
| PC-12 | Todas | Trigger protector con LONG | Policy subordinada; Machine puede `EXIT_LONG` |

### Gate de T3.2

- Policies candidatas formalizadas: **3/3**.
- Mecanismos causales distintos: **3/3**.
- Policies rankeadas/validadas: **0**.
- Parámetros numéricos elegidos: **0**.
- Dependencias L2 direccionales: **0**.
- Candidate con mecanismo, invalidación y failure modes: **3/3**.

### Evidencia de cierre de T3.2

- NULL_HOLD y las tres candidatas comparten contrato, costos, riesgo y datos.
- Trend, reversion y breakout no son simples thresholds de la misma idea.
- Cada candidata tiene setup state, entry, exit, invalidación, parámetros y fallos.
- Doce casos prueban que una feature favorable aislada no basta.
- D-010 está resuelta como shortlist, no como ganador.

## Comparación conceptual y prioridad de formalización — T3.3

### Qué se selecciona y qué no

Esta etapa selecciona **orden de especificación**, no una política rentable. No hay
backtest, datos OOS, parámetros congelados ni estimación de DeltaU. Por tanto:

- `PRIMARY_FOR_THEORETICAL_FORMALIZATION` ≠ winner.
- `CHALLENGER_RETAINED` ≠ rejected.
- `CANDIDATE_UNVALIDATED` sigue siendo el estado económico de las tres.

### Rúbrica preexistente

La comparación deriva de G0–G4, AG-001…AG-010 y POLICY_FAIL definidos antes de las
candidatas. No se crean criterios para favorecer un resultado.

#### Hard gates de especificabilidad

| Gate | Pregunta | Si falla |
|---|---|---|
| H1 Causalidad | ¿Inputs y setup pueden calcularse sin futuro? | No formalizar; `PROHIBITED_LEAKAGE`. |
| H2 Fuentes | ¿Existe contrato/freshness para cada input? | Diferir o reducir policy. |
| H3 Mecanismo | ¿Tiene hipótesis e invalidación observables? | `DEFERRED_NO_HYPOTHESIS`. |
| H4 Costo | ¿Incluye F-010 y fallo por costo desconocido? | No elegible. |
| H5 Riesgo | ¿Policy sólo propone y permite protección? | `ARCH_FAIL`. |
| H6 Falsabilidad | ¿Puede fallar sin mover el gate? | No elegible. |

Las tres pasan **sólo a nivel de especificación**; AG-005…AG-009 empíricos siguen
sin demostrar.

#### Orden lexicográfico de readiness

Tras hard gates:

1. Menor dependencia de fuentes/features aún no contratadas.
2. Menor sensibilidad inevitable a latencia/fill para expresar la hipótesis.
3. Tail risk más observable/acotable antes de entrar.
4. Menor burden de parámetros y menor fragilidad esperada.
5. Mayor densidad potencial de setups para una muestra efectiva.
6. Condición de falsación más directa.
7. Menor turnover/costo esperado, todo lo demás igual.

No se suman puntos ni se asignan pesos ex post. La primera diferencia material
resuelve prioridad de formalización; no retorno esperado.

### Matriz comparativa

| Dimensión | POL-101 Trend-pullback | POL-102 Reversion | POL-103 Breakout |
|---|---|---|---|
| Mecanismo | Persistencia tras pullback/reanudación | Reversión tras dislocación estabilizada | Continuación tras compresión/ruptura |
| Core data | OHLCV + BBO + metadata | OHLCV + BBO + metadata | OHLCV + BBO + metadata |
| Features locales | Ninguna imprescindible fuera F-001…10 | `dislocation_atr`, velocity | prior high, compression, breakout ATR |
| Dependencia L2 | Opcional veto | Opcional veto | Opcional veto |
| Horizonte plausible | Medio; D-002 pendiente | Corto/medio; D-002 pendiente | Corto/medio; D-002 pendiente |
| Setup density conceptual | Media | Baja–media por extremos | Baja–media por rupturas |
| Turnover esperado | Medio | Medio–alto si bands estrechas | Bajo–medio, concentrado en eventos |
| Sensibilidad a costos | Media | Media–alta | Alta por gap/slippage |
| Sensibilidad a ejecución | Media | Media | Alta en ruptura rápida |
| Tail risk principal | Reversal/whipsaw | Falling knife/structural drift | Gap/false breakout |
| Tail observability pre-entry | Media | Baja–media | Media |
| Burden indicativo de parámetros | 13 | 14 | 12 |
| Fragilidad esperada | Bandas y lag | Anchor/extreme thresholds | Lookback/buffer/compression |
| Régimen favorable hipotético | Drift persistente | Rango/liquidity dislocation | Volatility expansion direccional |
| Régimen adverso | Lateral/reversal | Tendencia bajista | Chop/gap reversal |
| Evidencia empírica actual | Ninguna | Ninguna | Ninguna |
| Falsificación directa | No continuación neta tras setup | No reversión neta/tail domina | False breaks/costos dominan |

Los conteos de parámetros son burden de revisión, no búsqueda aprobada; T3.5 puede
reducirlos antes de freeze.

### Costos y harvestability

| Policy | Camino de costo dominante | Riesgo de modelo optimista | Mitigación conceptual |
|---|---|---|---|
| POL-101 | Reentradas por whipsaw y lag | Ignorar turnover lateral | Armado/timeout + F-010 + cooldown futuro |
| POL-102 | Repetir entradas en caída | Subestimar tail/falling knife | Stabilization obligatoria + hard invalidation |
| POL-103 | Gap, spread y slippage al romper | Fill al close imposible | F-009/F-010 al size + invalidar gap inalcanzable |

POL-103 queda detrás en readiness por sensibilidad estructural a ejecución, no por
resultado conocido. POL-102 queda detrás de POL-101 por tail risk menos observable
y mayor burden, no porque se haya medido menor retorno.

### Muestra y cobertura futura

| Policy | Unidad de muestra | Riesgo de muestra | Evidencia mínima futura |
|---|---|---|---|
| POL-101 | Pullback armado + resume | Setups correlacionados dentro de trend | Nº de episodios independientes por régimen + DeltaU pareada |
| POL-102 | Dislocación + estabilización | Pocos extremos y clustering de crisis | Effective sample, tail outcomes y estabilidad de anchor |
| POL-103 | Compresión + ruptura | Eventos escasos/concentrados | False-break rate, gap/slippage y coverage por régimen |

No se permite contar cada barra dentro de un mismo setup como observación
independiente.

### Evidencia que podría cambiar la prioridad

Antes de outcomes OOS, D-015 se reabre sólo si:

- D-001/D-002 cambia producto/horizonte y altera harvestability;
- una source/feature required resulta inalcanzable;
- el pseudocódigo total revela estado ambiguo o ARCH_FAIL;
- una candidata requiere muchos menos parámetros tras simplificación;
- una prueba teórica demuestra pérdida no acotada o contradicción.

Después de abrir OOS, la prioridad de esta ronda queda congelada. Un challenger
sólo puede promoverse en una ronda nueva y registrada, no sustituyendo al primary
al ver resultados.

### Veredicto de selección conceptual

| Policy | Veredicto T3.3 | Razón | Próxima acción |
|---|---|---|---|
| POL-000 | `CONTROL` | Baseline nulo obligatorio. | Mantener en toda comparación. |
| POL-101 | `PRIMARY_FOR_THEORETICAL_FORMALIZATION` | Core data completo, ejecución media, tail observable y muestra potencial mayor. | Pseudocódigo total T3.4 + reducción de parámetros T3.5. |
| POL-102 | `CHALLENGER_RETAINED` | Mecanismo distinto/falsable; tail y burden mayores. | Mantener contrato y casos; no profundizar primero. |
| POL-103 | `CHALLENGER_RETAINED` | Mecanismo distinto; ejecución/gap dominan readiness. | Mantener contrato y modelo de costo adverso. |

**No hay `PIVOT` en T3.3** porque existe al menos una candidata completamente
especificable con fuentes contratadas. **No hay winner** porque falta toda evidencia
empírica.

### Criterios de no-promoción

POL-101 no puede pasar de “primary de formalización” por:

- ser la más simple o familiar;
- producir más setups teóricos;
- coincidir con una estrategia previa;
- obtener un ejemplo favorable;
- tener menor parameter count sin DeltaU;
- fallar challengers.

Promoción futura exige D-009, parámetros congelados y validación OOS neta de costos.

### Gate de T3.3

- Candidatas comparadas en todas las dimensiones: **3/3**.
- Primary de formalización: **1**.
- Challengers retenidas: **2**.
- Winner/edge declarado: **0**.
- Evidencia empírica usada para selección: **0**.
- Criterios creados después de ver outcomes: **0**.
- PIVOT requerido ahora: **No**.

### Evidencia de cierre de T3.3

- Datos, horizonte, turnover, costos, régimen, fallos, complejidad y evidencia están
  comparados bajo una rúbrica previa.
- POL-101 avanza sólo por readiness de formalización y bajo CP-01 condicional.
- POL-102/POL-103 conservan igualdad contractual y no se descartan.
- D-015 registra selección, límites y triggers de revisión.
- T3.4 puede escribir pseudocódigo total sin afirmar rentabilidad.

## Pseudocódigo total de POL-101 — T3.4

### Alcance

Esta sección formaliza `TREND_PULLBACK_RESUME` sin fijar valores de parámetros.
Toda comparación usa identificadores de T3.5. No ejecuta, no calcula sizing y no
convierte la policy en una estrategia validada.

### Estado interno de Policy

```text
TrendPolicyState = {
  state: IDLE | PULLBACK_ARMED | ENTRY_EMITTED,
  state_version,
  setup_id: hash | null,
  armed_at_bar_id: string | null,
  armed_at_time: UTC | null,
  armed_feature_refs: list,
  bars_since_arm: integer,
  pullback_extreme_distance: Decimal | null,
  entry_intent_id: hash | null,
  last_evaluation_id: hash | null,
  parameter_version,
  policy_version
}
```

Invariantes:

- `IDLE` ⇒ setup/arm/entry fields null y `bars_since_arm=0`.
- `PULLBACK_ARMED` ⇒ setup_id y arm fields no null; entry_intent_id null.
- `ENTRY_EMITTED` ⇒ entry_intent_id no null; no segundo intent para setup_id.
- Cambiar policy/parameter version invalida state previo y vuelve a IDLE con razón.
- Setup ID es determinista sobre policy version, parameter version, symbol,
  `armed_at_bar_id` y state_before version.

### Inputs `POL101EvaluationContext`

```text
{
  evaluation_id,
  trigger_type,
  decision_time,
  strategic_boundary,
  system_state,
  portfolio_state,
  product_mandate,
  risk_mandate_ref,
  market_context,
  feature_values: {
    sma_N,
    distance_to_sma_N,
    sma_slope_N_K,
    volume_ratio_N,
    atr_fraction_N,
    spread_bps,
    round_trip_cost_bps_Q
  },
  prior_feature_values,
  policy_state,
  parameter_set,
  latest_entry_outcome,
  holding_bars,
  duplicate_seen
}
```

### Output `PolicyEvaluationResult`

```text
{
  candidate_intent,
  next_policy_state,
  cooldown_advisory: {
    requested: bool,
    reason: enum | null,
    duration_bars_parameter: string | null
  },
  evaluation_reason,
  audit_predicates
}
```

La Máquina decide si aplica cooldown; la Policy sólo emite advisory versionado.

### Parámetros referenciados

| ID simbólico | Uso | Restricción estructural |
|---|---|---|
| `P101_N_SMA` | Ventana SMA | entero ≥ 2 |
| `P101_K_SLOPE` | Lag slope | entero ≥ 1 |
| `P101_THETA_SLOPE_ENTER` | Contexto de tendencia | > `P101_THETA_SLOPE_EXIT` |
| `P101_THETA_SLOPE_EXIT` | Invalidación long | valor pre-registrado |
| `P101_ATR_MIN/MAX` | Rango admisible de atr_fraction | `0 ≤ min < max` |
| `P101_PULLBACK_LOW/HIGH` | Banda para armar | `fail < low ≤ high < resume` |
| `P101_PULLBACK_FAIL` | Invalida setup | < pullback_low |
| `P101_RESUME_LEVEL` | Cruce de reanudación | > pullback_high |
| `P101_VOLUME_CONFIRM` | Mínimo F-004 | > 0 |
| `P101_COST_CAP_BPS` | Máximo F-010 | > 0; D-006/D-009 |
| `P101_ARM_TIMEOUT_BARS` | Expiración setup | entero ≥ 1 |
| `P101_EXIT_ATR_MULTIPLE` | Pérdida de anchor | > 0 |
| `P101_MAX_HOLDING_BARS` | Time exit | entero ≥ 1 |
| `P101_CD_SETUP_FAIL` | Cooldown tras fallo setup | entero ≥ 0 |
| `P101_CD_ENTRY_REJECT` | Cooldown tras intent rechazado | entero ≥ 0 |
| `P101_CD_EXIT` | Cooldown tras exit fill | entero ≥ 0 |
| `P101_CD_PROTECTIVE_EXIT` | Cooldown tras exit protector | entero ≥ 0 |

T3.5 asignará dominios/rangos/freeze. Parámetro ausente o inconsistente produce
`NO_INTENT/POL101_PARAMETER_INVALID` y policy health BLOCKED.

### Reason codes exhaustivos

| Categoría | Reason codes |
|---|---|
| Preflight | `POL101_DUPLICATE`, `POL101_VERSION_CHANGED`, `POL101_PARAMETER_INVALID`, `POL101_TRIGGER_NOT_STRATEGIC` |
| Estado | `POL101_POSITION_UNKNOWN`, `POL101_PENDING_FEEDBACK`, `POL101_COOLDOWN_ACTIVE`, `POL101_HEALTH_NOT_READY` |
| Datos | `POL101_FEATURE_MISSING`, `POL101_FEATURE_NOT_FRESH`, `POL101_COST_UNKNOWN`, `POL101_COST_CAP_EXCEEDED` |
| Setup | `POL101_TREND_CONTEXT_FALSE`, `POL101_PULLBACK_NOT_IN_BAND`, `POL101_PULLBACK_ARMED`, `POL101_ARM_WAITING` |
| Confirmación | `POL101_RESUME_NOT_CROSSED`, `POL101_VOLUME_NOT_CONFIRMED`, `POL101_ENTRY_SETUP_COMPLETE` |
| Invalidation | `POL101_ARM_TIMEOUT`, `POL101_TREND_INVALIDATED`, `POL101_PULLBACK_FAILED`, `POL101_SETUP_VERSION_INVALID` |
| Long | `POL101_LONG_HOLD`, `POL101_EXIT_TREND`, `POL101_EXIT_ANCHOR`, `POL101_EXIT_TIME` |
| Protección | `POL101_PROTECTIVE_DEFERRED_TO_SYSTEM` |
| Outcome | `POL101_ENTRY_REJECTED`, `POL101_ENTRY_EXPIRED`, `POL101_ENTRY_FILLED`, `POL101_EXIT_FILLED` |

No se permiten reasons libres como “trend strong”, “volume high” o “setup good”.

### Predicados puros

```text
parameters_valid(p):
  return p.N_SMA >= 2
     and p.K_SLOPE >= 1
     and 0 <= p.ATR_MIN < p.ATR_MAX
     and p.PULLBACK_FAIL < p.PULLBACK_LOW
     and p.PULLBACK_LOW <= p.PULLBACK_HIGH
     and p.PULLBACK_HIGH < p.RESUME_LEVEL
     and p.THETA_SLOPE_EXIT < p.THETA_SLOPE_ENTER
     and p.VOLUME_CONFIRM > 0
     and p.COST_CAP_BPS > 0
     and p.ARM_TIMEOUT_BARS >= 1
     and p.EXIT_ATR_MULTIPLE > 0
     and p.MAX_HOLDING_BARS >= 1
     and all(cooldowns >= 0)

required_features_valid(f, boundary):
  required = [sma, distance, slope, volume_ratio,
              atr_fraction, spread_bps, round_trip_cost]
  return all(x.value != null for x in required)
     and all(x.quality == QUALIFIED for x in required)
     and all(x.as_of_time == boundary for x in required)
     and all(x.max_input_event_time <= boundary for x in required)

trend_context(f,p):
  return f.sma_slope >= p.THETA_SLOPE_ENTER
     and f.close_price > f.sma
     and p.ATR_MIN <= f.atr_fraction <= p.ATR_MAX

in_pullback_band(f,p):
  return p.PULLBACK_LOW <= f.distance_to_sma <= p.PULLBACK_HIGH

pullback_failed(f,p):
  return f.distance_to_sma < p.PULLBACK_FAIL

resume_crossed(f,prior,p):
  return prior.distance_to_sma <= p.RESUME_LEVEL
     and f.distance_to_sma > p.RESUME_LEVEL

volume_confirmed(f,p):
  return f.volume_ratio >= p.VOLUME_CONFIRM

cost_admissible(f,p):
  return f.round_trip_cost_bps <= p.COST_CAP_BPS

trend_exit(f,p):
  return f.sma_slope <= p.THETA_SLOPE_EXIT

anchor_exit(f,p):
  return f.distance_to_sma
         <= -p.EXIT_ATR_MULTIPLE * f.atr_fraction

time_exit(ctx,p):
  return ctx.holding_bars >= p.MAX_HOLDING_BARS
```

### Helpers de output

```text
no_intent(reason, next_state, cooldown=None):
  return PolicyEvaluationResult(
    CandidateIntent(NO_INTENT, primary_reason=reason),
    next_state,
    cooldown or NONE,
    reason,
    audit_predicates
  )

entry_intent(ctx, state):
  return CandidateIntent(
    ENTRY_CANDIDATE,
    setup_id=state.setup_id,
    evidence_refs=exact_feature_ids,
    invalidation_condition=POL101_ENTRY_INVALIDATION_V1,
    effective_at=ctx.decision_time,
    expires_at=ctx.strategic_boundary.next,
    primary_reason=POL101_ENTRY_SETUP_COMPLETE
  )

exit_intent(ctx, reason):
  return CandidateIntent(
    EXIT_CANDIDATE,
    evidence_refs=exact_exit_feature_ids,
    invalidation_condition=null,
    effective_at=ctx.decision_time,
    expires_at=ctx.strategic_boundary.next,
    primary_reason=reason
  )
```

### Función total `evaluate_POL101`

```text
function evaluate_POL101(ctx, p):

  # 0 — Determinismo/versiones
  if ctx.duplicate_seen:
      return no_intent(POL101_DUPLICATE, ctx.policy_state)

  if ctx.policy_state.policy_version != POL101_VERSION
     or ctx.policy_state.parameter_version != p.version:
      return no_intent(
          POL101_VERSION_CHANGED,
          IDLE_STATE,
          cooldown=None
      )

  if not parameters_valid(p):
      return no_intent(POL101_PARAMETER_INVALID, IDLE_STATE)

  # 1 — Trigger protector pertenece al sistema, nunca a Policy entry
  if ctx.trigger_type == PROTECTIVE_EVALUATION:
      return no_intent(
          POL101_PROTECTIVE_DEFERRED_TO_SYSTEM,
          ctx.policy_state
      )

  if ctx.trigger_type != STRATEGIC_EVALUATION:
      return no_intent(POL101_TRIGGER_NOT_STRATEGIC, ctx.policy_state)

  # 2 — Estado económico/operacional
  if ctx.system_state.position == UNKNOWN:
      return no_intent(POL101_POSITION_UNKNOWN, IDLE_STATE)

  if ctx.system_state.position in {ENTRY_PENDING, EXIT_PENDING}:
      return no_intent(POL101_PENDING_FEEDBACK, ctx.policy_state)

  if ctx.system_state.evaluation == COOLDOWN:
      return no_intent(POL101_COOLDOWN_ACTIVE, IDLE_STATE)

  if ctx.system_state.health != READY:
      next = IDLE_STATE if ctx.system_state.position == FLAT
              else ctx.policy_state
      return no_intent(POL101_HEALTH_NOT_READY, next)

  # 3 — Resolver outcomes de intent previo
  if ctx.policy_state.state == ENTRY_EMITTED:
      if ctx.latest_entry_outcome == FILLED:
          return no_intent(POL101_ENTRY_FILLED, IDLE_STATE)
      if ctx.latest_entry_outcome in {REJECTED, CANCELLED}:
          return no_intent(
              POL101_ENTRY_REJECTED,
              IDLE_STATE,
              cooldown=P101_CD_ENTRY_REJECT
          )
      if ctx.latest_entry_outcome == EXPIRED:
          return no_intent(
              POL101_ENTRY_EXPIRED,
              IDLE_STATE,
              cooldown=P101_CD_ENTRY_REJECT
          )
      return no_intent(POL101_PENDING_FEEDBACK, ctx.policy_state)

  # 4 — Rama de posición LONG: salida estratégica o abstención
  if ctx.system_state.position == LONG:
      if not exit_features_valid(ctx.features, ctx.strategic_boundary):
          return no_intent(POL101_FEATURE_MISSING, ctx.policy_state)

      if time_exit(ctx,p):
          return result(exit_intent(ctx, POL101_EXIT_TIME), IDLE_STATE)

      if trend_exit(ctx.features,p):
          return result(exit_intent(ctx, POL101_EXIT_TREND), IDLE_STATE)

      if anchor_exit(ctx.features,p):
          return result(exit_intent(ctx, POL101_EXIT_ANCHOR), IDLE_STATE)

      return no_intent(POL101_LONG_HOLD, IDLE_STATE)

  # 5 — Sólo FLAT puede construir entrada
  assert ctx.system_state.position == FLAT

  if not required_features_valid(ctx.features, ctx.strategic_boundary):
      reason = classify_missing_or_stale(ctx.features)
      # FEATURE_MISSING / FEATURE_NOT_FRESH / COST_UNKNOWN
      next = IDLE_STATE if ctx.policy_state.state == IDLE
             else invalidate_setup(ctx.policy_state)
      return no_intent(reason, next)

  # 6 — IDLE: armar únicamente dentro de trend context + pullback band
  if ctx.policy_state.state == IDLE:
      if not trend_context(ctx.features,p):
          return no_intent(POL101_TREND_CONTEXT_FALSE, IDLE_STATE)

      if not in_pullback_band(ctx.features,p):
          return no_intent(POL101_PULLBACK_NOT_IN_BAND, IDLE_STATE)

      armed = new_armed_state(
          setup_id=deterministic_setup_id(ctx,p),
          armed_at_bar_id=ctx.market_context.current_bar_id,
          armed_feature_refs=current_feature_ids,
          pullback_extreme_distance=ctx.features.distance_to_sma,
          bars_since_arm=0
      )
      return no_intent(POL101_PULLBACK_ARMED, armed)

  # 7 — PULLBACK_ARMED: invalidaciones antes que confirmación
  if ctx.policy_state.state == PULLBACK_ARMED:
      armed = increment_bar_count_and_extreme(ctx.policy_state, ctx)

      if armed.bars_since_arm > p.ARM_TIMEOUT_BARS:
          return no_intent(
              POL101_ARM_TIMEOUT,
              IDLE_STATE,
              cooldown=P101_CD_SETUP_FAIL
          )

      if not trend_context(ctx.features,p):
          return no_intent(
              POL101_TREND_INVALIDATED,
              IDLE_STATE,
              cooldown=P101_CD_SETUP_FAIL
          )

      if pullback_failed(ctx.features,p):
          return no_intent(
              POL101_PULLBACK_FAILED,
              IDLE_STATE,
              cooldown=P101_CD_SETUP_FAIL
          )

      if ctx.features.round_trip_cost_bps == null:
          return no_intent(POL101_COST_UNKNOWN, IDLE_STATE)

      if not cost_admissible(ctx.features,p):
          return no_intent(
              POL101_COST_CAP_EXCEEDED,
              IDLE_STATE,
              cooldown=P101_CD_SETUP_FAIL
          )

      if not resume_crossed(ctx.features, ctx.prior_features,p):
          return no_intent(POL101_RESUME_NOT_CROSSED, armed)

      if not volume_confirmed(ctx.features,p):
          return no_intent(POL101_VOLUME_NOT_CONFIRMED, armed)

      intent = entry_intent(ctx, armed)
      emitted = armed.with(
          state=ENTRY_EMITTED,
          entry_intent_id=intent.intent_id
      )
      return result(
          intent,
          emitted,
          evaluation_reason=POL101_ENTRY_SETUP_COMPLETE
      )

  # 8 — Estado imposible bajo schema conocido
  return no_intent(POL101_SETUP_VERSION_INVALID, IDLE_STATE)
```

### Orden normativo de salida LONG

1. Trigger protector se delega al sistema antes de entrar en rama estratégica.
2. `TIME_EXIT` se evalúa primero porque no depende de interpretar trend.
3. `EXIT_TREND` se evalúa antes de `EXIT_ANCHOR` para reason determinista si ambos.
4. Sin condición de salida se emite `NO_INTENT/POL101_LONG_HOLD`.
5. Data faltante no inventa exit estratégico; el Gobernador decide protección.

### Cooldown advisory

| Evento confirmado | Parámetro advisory | Inicio | Fin |
|---|---|---|---|
| Setup timeout/fail | `P101_CD_SETUP_FAIL` | Invalidación registrada | N barras estratégicas FINAL |
| Entry rejected/cancelled/expired | `P101_CD_ENTRY_REJECT` | Outcome autoritativo | N barras FINAL |
| Exit filled estratégico | `P101_CD_EXIT` | Position FLAT reconciliada | N barras FINAL |
| Exit filled protector | `P101_CD_PROTECTIVE_EXIT` | Position FLAT reconciliada | N barras FINAL |

- N=0 significa no solicitar cooldown, no “deshabilitar” otra protección.
- La Máquina crea `COOLDOWN`; la Policy no muta EvaluationState directamente.
- Cambio de health/mandate durante cooldown puede extender/bloquear por regla
  sistémica, nunca acortarlo silenciosamente.

### Expiración e idempotencia

- Setup expira por timeout, versión, state/health, trend, pullback o source invalid.
- Entry intent expira en la próxima strategic boundary o antes si cambia una guarda.
- Mismo evaluation/setup/version produce el mismo intent ID.
- `ENTRY_EMITTED` impide segundo CandidateIntent hasta outcome/expiry autoritativo.
- Un intent expirado no revive si vuelven features favorables; se arma setup nuevo.

### Matriz de totalidad

| ID | Position | Policy state | Condición prioritaria | Output |
|---|---|---|---|---|
| P101-T01 | UNKNOWN | cualquiera | — | `NO_INTENT/POSITION_UNKNOWN` |
| P101-T02 | pending | cualquiera | — | `NO_INTENT/PENDING_FEEDBACK` |
| P101-T03 | FLAT | cualquiera | COOLDOWN | `NO_INTENT/COOLDOWN_ACTIVE` |
| P101-T04 | FLAT/LONG | cualquiera | Health no READY | `NO_INTENT/HEALTH_NOT_READY` |
| P101-T05 | LONG | IDLE | Time exit | `EXIT_CANDIDATE/EXIT_TIME` |
| P101-T06 | LONG | IDLE | Slope exit | `EXIT_CANDIDATE/EXIT_TREND` |
| P101-T07 | LONG | IDLE | Anchor exit | `EXIT_CANDIDATE/EXIT_ANCHOR` |
| P101-T08 | LONG | IDLE | Ninguna exit | `NO_INTENT/LONG_HOLD` |
| P101-T09 | FLAT | IDLE | Trend false | `NO_INTENT/TREND_CONTEXT_FALSE` |
| P101-T10 | FLAT | IDLE | Fuera de pullback band | `NO_INTENT/PULLBACK_NOT_IN_BAND` |
| P101-T11 | FLAT | IDLE | Trend + pullback | Armar; `NO_INTENT/PULLBACK_ARMED` |
| P101-T12 | FLAT | ARMED | Timeout | Invalidar + advisory |
| P101-T13 | FLAT | ARMED | Trend invalidada | Invalidar + advisory |
| P101-T14 | FLAT | ARMED | Pullback fail | Invalidar + advisory |
| P101-T15 | FLAT | ARMED | Cost unknown/cap | Invalidar/hold |
| P101-T16 | FLAT | ARMED | Sin resume | Mantener armado |
| P101-T17 | FLAT | ARMED | Resume sin volumen | Mantener armado |
| P101-T18 | FLAT | ARMED | Resume + volumen + gates | `ENTRY_CANDIDATE` una vez |
| P101-T19 | FLAT/pending | ENTRY_EMITTED | Sin outcome | `NO_INTENT/PENDING_FEEDBACK` |
| P101-T20 | cualquiera | cualquiera | Duplicate | `NO_INTENT/DUPLICATE` |
| P101-T21 | cualquiera | schema inválido | — | Reset + `NO_INTENT/SETUP_VERSION_INVALID` |

Eventos no listados siguen common Machine SM-030/SM-031; la Policy no oculta schema
desconocido.

### Prohibiciones T3.4

- No usar adjetivos como condición: cada guard referencia parámetro/campo.
- No entrar al armar pullback; se requiere cruce de resume posterior.
- No comprar una distancia más negativa sin stabilization/resume.
- No usar current forming bar.
- No continuar setup tras cambio de version/health/state.
- No emitir más de un entry intent por setup.
- No convertir cost unknown en cero.
- No generar exit protector desde Policy.
- No mutar cooldown, PositionState o RiskMandate.
- No usar L2 imbalance como reason primaria.

### Evidencia de cierre de T3.4

- La función cubre estados unknown, pending, flat, long, cooldown y health no ready.
- Guards tienen orden fijo; invalidación precede confirmación y entrada.
- Entry exige trend, pullback previo, resume, volumen, costo y estado válidos.
- Exit tiene precedencia determinista time→trend→anchor.
- Cooldown es advisory y sólo la Máquina lo aplica.
- 21 filas demuestran totalidad; duplicate/schema invalid tienen salida.
- No queda lenguaje operacional vago dentro de predicados.

## Registro y freeze de parámetros POL-101 — T3.5

### Contrato `ParameterSpecV1`

```text
ParameterSpecV1 = {
  param_id, unit, domain,
  provisional_value: SYMBOLIC,
  rationale,
  sensitivity: HIGH | MEDIUM | LOW,
  dependencies,
  calibration_method: TRAIN_ONLY,
  freeze_gate,
  neighbor_test_required
}
```

Ningún valor se selecciona mirando OOS. Cambiar dominio, unidad, dependencia o
método crea una nueva `parameter_version` e invalida experimentos dependientes.

| Parámetro | Unidad | Dominio estructural | Racional | Sens. | Dependencias | Calibración futura |
|---|---|---|---|---|---|---|
| `P101_N_SMA` | barras | entero ≥2 | Ventana del anchor | HIGH | D-002 | Grid discreto train-only |
| `P101_K_SLOPE` | barras | entero ≥1 | Lag de pendiente | MEDIUM | D-002, N_SMA | Rango train-only |
| `P101_THETA_SLOPE_ENTER` | ratio/barra | > EXIT | Contexto de entrada | HIGH | D-002 | Percentil train |
| `P101_THETA_SLOPE_EXIT` | ratio/barra | < ENTER | Histéresis de salida | HIGH | ENTER | Train-only |
| `P101_ATR_MIN` | ratio | 0≤MIN<MAX | Piso de vol | MEDIUM | D-002 | Cuantil train |
| `P101_ATR_MAX` | ratio | MIN<MAX | Techo de vol | MEDIUM | ATR_MIN | Cuantil train |
| `P101_PULLBACK_LOW` | ratio | FAIL<LOW≤HIGH | Banda inferior | HIGH | D-002 | Rango train |
| `P101_PULLBACK_HIGH` | ratio | LOW≤HIGH<RESUME | Banda superior | HIGH | LOW | Rango train |
| `P101_PULLBACK_FAIL` | ratio | <LOW | Invalida setup | HIGH | LOW | Rango train |
| `P101_RESUME_LEVEL` | ratio | >HIGH | Cruce de reanudación | HIGH | HIGH | Rango train |
| `P101_VOLUME_CONFIRM` | ratio | >0 | Confirmación F-004 | MEDIUM | D-002 | Cuantil train |
| `P101_COST_CAP_BPS` | bps | >0 | Gate F-010 | HIGH | D-006,D-009 | Derivado de costo, no retorno |
| `P101_ARM_TIMEOUT_BARS` | barras | entero ≥1 | Expiración setup | MEDIUM | D-002 | Rango train |
| `P101_EXIT_ATR_MULTIPLE` | ratio | >0 | Pérdida de anchor | HIGH | D-003 | Riesgo train-only |
| `P101_MAX_HOLDING_BARS` | barras | entero ≥1 | Time exit | MEDIUM | D-002 | Rango train |
| `P101_CD_SETUP_FAIL` | barras | entero ≥0 | Cooldown setup | LOW | — | Rango train |
| `P101_CD_ENTRY_REJECT` | barras | entero ≥0 | Cooldown rechazo | LOW | — | Rango train |
| `P101_CD_EXIT` | barras | entero ≥0 | Cooldown exit | LOW | — | Rango train |
| `P101_CD_PROTECTIVE_EXIT` | barras | entero ≥0 | Cooldown protector | LOW | D-003 | Rango train |

Reglas anti-overfit:

1. Rango/grid y search budget se pre-registran antes de train.
2. OOS nunca selecciona ni elimina parámetros.
3. Sensibilidad HIGH exige prueba de vecinos y estabilidad de signo.
4. Restricciones relacionales se validan antes de evaluar.
5. Search budget es comparable entre candidatas.

**Resultado T3.5: PASS.** 19/19 parámetros tienen unidad, dominio, racional,
sensibilidad, dependencia y método train-only; valores siguen `SYMBOLIC`.

## Precedencia final de acciones — T3.6

### Resolución de la contradicción stop/reconciliación

Un stop o circuit breaker no puede actuar sobre posición desconocida. Por tanto,
la precedencia segura es:

```text
reconciliación de estado (P0)
  → circuit breaker / stop / salida de riesgo (P1)
    → bloqueo sistémico (P2)
      → salida estratégica (P3)
        → entrada (P4)
          → hold (P5)
```

Dentro de P1, circuit breaker/stop tiene prioridad sobre otra salida de riesgo. La
redacción anterior “stop → reconciliación” queda reemplazada por esta regla.

| Rango | Clase | Subcaso | Acción única | Guarda mínima |
|---:|---|---|---|---|
| 0 | `P0_RECONCILIATION_BLOCK` | conflict/unknown/schema | `HOLD/STATE_UNKNOWN` | Position no reconciliada |
| 1a | `P1_PROTECTIVE_EXIT` | breaker/stop | `EXIT_LONG` | LONG reconciliado + trigger autoritativo |
| 1b | `P1_PROTECTIVE_EXIT` | risk breach/mandate revoked | `EXIT_LONG` | LONG reconciliado |
| 2 | `P2_SYSTEM_BLOCK` | data/cost/mandate insuficiente | `HOLD/BLOCKED` | Sin salida P1 válida |
| 3 | `P3_STRATEGIC_EXIT` | invalidación policy | `EXIT_LONG` | LONG conocido |
| 4 | `P4_ENTRY` | oportunidad aprobada | `ENTER_LONG` | FLAT/READY + todos los gates |
| 5 | `P5_NO_CHANGE` | no intent/cooldown | `HOLD` | — |

Empates usan estado/mandato más reciente y luego `decision_id` lexicográfico; nunca
arrival order. Si la guarda ganadora falla se reevalúa la siguiente clase, sin
emitir dos acciones.

El time stop es P3 por defecto; un `RiskMandate.time_stop_is_protective=true`
versionado puede elevarlo a P1. Ausencia de la bandera mantiene P3.

**Resultado T3.6: PASS.** Para cada combinación concurrente existe una única acción.

## Auditoría temporal y leakage — T3.7

| Condición | Inputs | Disponibilidad exigida | Veredicto |
|---|---|---|---|
| `trend_context` | slope, close, ATR | Barras FINAL; max input≤boundary | Permitido |
| `in_pullback_band` | distance_to_sma | Barra FINAL | Permitido |
| `resume_crossed` | distance actual/prior | Dos barras FINAL consecutivas | Permitido |
| `volume_confirmed` | volume_ratio | Barra FINAL; baseline excluye target | Permitido |
| `cost_admissible` | F-010 | BBO FRESH al decision_time | Permitido |
| `time_exit` | holding_bars | Conteo de barras FINAL | Permitido |
| trend/anchor exit | slope/distance/ATR | Barras FINAL | Permitido |
| Kline `x=false` como close | Barra FORMING | — | `PROHIBITED_LEAKAGE` |
| Ventana centrada/global scaling | Dataset completo | — | `PROHIBITED_LEAKAGE` |
| “MA60” visual sin timeframe | UI | — | Prohibido |
| L2 imbalance como trigger | F-011/F-012 | — | Prohibido D-007 |
| Late correction retroactiva | Evento tardío | — | Prohibido |
| As-of nearest de ambos lados | Cross-source | — | Prohibido; usar último ≤ as_of |
| Normalización OOS | Estadísticos OOS | — | Prohibido; train-only |

**Resultado T3.7: PASS.** Toda condición tiene disponibilidad y veredicto; ningún
input estratégico permitido usa futuro o barra abierta.

### Gate de Fase 3

T3.1–T3.7: **PASS_CONDITIONAL**. POL-101 queda totalmente especificada y
parametrizada simbólicamente; no está validada. D-001/D-002/D-003/D-009/D-014
deben congelarse antes de correr OOS.

# Fase 4 — Riesgo y ejecución teórica

## Sizing y exposición — T4.1

```text
stop_distance  = P101_EXIT_ATR_MULTIPLE · ATR_abs
adverse_buffer = slippage_buffer_abs + gap_buffer_abs
loss_per_unit  = stop_distance + adverse_buffer
risk_capital   = RiskMandate.risk_per_decision · capital

qty_risk = risk_capital / loss_per_unit
qty_expo = RiskMandate.max_exposure / reference_price
qty_cash = available_cash / (reference_price · (1 + cost_buffer_fraction))
qty_raw  = min(qty_risk, qty_expo, qty_cash)
qty      = quantize_down(qty_raw, step_size)
```

Guardas: loss_per_unit≤0/unknown, mandate ausente, qty=0, notional<minimum o filtros
inválidos ⇒ `HOLD/BLOCKED`. Nunca se redondea hacia arriba. Bajo CP-01 Spot sin
apalancamiento, pérdida absoluta máxima queda acotada por `max_exposure`; el gap
puede exceder el budget del stop, pero no el principal expuesto. Otro producto
reabre D-001 y este argumento.

**T4.1 PASS_CONDITIONAL:** ecuación acotada para vol cero/extrema/capital
insuficiente; valores dependen de D-003.

## Stops, trailing, time, cooldown y pérdidas agregadas — T4.2

| Control | Fórmula/trigger | Gap/fill parcial |
|---|---|---|
| Stop inicial | `entry_ref - stop_atr·ATR_abs` | Fill al primer precio realizable, no al stop teórico |
| Trailing | `max(prev_trail, high_since_entry-trail_atr·ATR_abs)` | Nunca baja; aplica al residual |
| Time stop | `holding_bars ≥ max_holding` | P3 salvo bandera protectora P1 |
| Cooldown | `P101_CD_*` barras FINAL | Bloquea entradas, nunca salida |
| Daily loss | `daily_loss ≥ daily_loss_max` | Bloquea entrada hasta reset UTC |
| Drawdown | `drawdown ≥ drawdown_max` | Breaker P1; puede ordenar salida |

Fill parcial conserva `EXIT_PENDING` y quantity residual; cancel/reject con residual
vuelve a `LONG/EXIT_CANDIDATE/DEGRADED`. Gap risk se registra como residual; jamás
se simula fill al stop.

**T4.2 PASS_CONDITIONAL:** semántica completa; números dependen de D-003.

## `RiskMandate` y Gobernador — T4.3

```text
RiskMandate = {
  version, authored_by: HUMAN, authored_at,
  capital, risk_per_decision, max_exposure,
  daily_loss_max, drawdown_max,
  allowed_directions,
  liquidity_gates, data_quality_gates,
  time_stop_is_protective,
  valid_from, valid_until, block_conditions
}
```

El Gobernador recibe CandidateIntent + mandate + PortfolioState + CostEstimate y
emite `RiskVerdict{APPROVED|REJECTED, approved_qty|null, binding_limits, reason,
mandate_version}`. Mandato ausente/expirado/incierto ⇒ REJECTED. Policy no puede
mutarlo. Mismos inputs/versiones ⇒ mismo verdict.

**T4.3 PASS:** autoridad humana versionada y rechazo fail-safe.

## Fallos y recuperación — T4.4

| Fallo | Detección | Estado seguro | Recuperación |
|---|---|---|---|
| Posición desconocida | POSITION_CONFLICT | UNKNOWN/IDLE/BLOCKED | POSITION_SYNC autoritativo |
| Restart | Estado no reconciliado | UNKNOWN; no entrada | Reconciliar antes de READY |
| Duplicado | event/decision ID visto | HOLD/DUPLICATE | Idempotente |
| Late | classification=LATE | No reescribe Decision | Contexto futuro |
| Entry reject/cancel | feedback autoritativo | FLAT/COOLDOWN | Nueva evaluación |
| Exit parcial | residual>0 | EXIT_PENDING | Continuar/reconciliar |
| Cancel exit con residual | residual>0 | LONG/EXIT_CANDIDATE/DEGRADED | Reevaluar protección |
| Desync exchange/local | sync inesperado | BLOCKED/DEGRADED | Custodio autoritativo |
| Gap L2 | sequence gap | Revocar view | Nueva generation LIVE |
| Feed stale | FreshnessPolicy | Invalidar dependencias | Recovery rule por fuente |

**T4.4 PASS:** cada fallo tiene detección, estado seguro y recuperación.

## Modelo futuro de paper fills — T4.5

**Market:** caminar asks/bids de una vista posterior al latency budget; precio
medio = VWAP de cantidad realmente visible; fill parcial si profundidad<qty; fee
taker; resto no se inventa. Nunca fill al mid.

**Limit pasiva:** requiere precio alcanzado, queue-ahead estimada conservadora y
traded-through volume superior a queue; fill probability<1; cancel/no-fill
permitidos; adverse-selection buffer obligatorio; fee maker sólo sobre fill.

| Escenario | Latencia | Slippage/impact | Partial/no-fill | Adverse selection |
|---|---|---|---|---|
| BASE | nominal pre-registrada | conservador | permitido | buffer base |
| ADVERSE | elevada | mayor | probable | buffer mayor |
| EXTREME | budget máximo | stress | frecuente | worst-case acotado |

Componente desconocido ⇒ `COST_UNKNOWN`, nunca cero.

**T4.5 PASS teórico:** no presume fill al mid/completo/gratuito; evidencia real de
fills sigue pendiente.

## Break-even — T4.6

```text
round_trip_cost_bps = fees_entry+fees_exit+cross_entry+cross_exit
                      +slippage_entry+slippage_exit+impact+other
break_even_move_bps = round_trip_cost_bps + uncertainty_buffer_bps
```

Ejemplo `EXAMPLE_ONLY` ya recalculado en T2.5:

```text
10 + 10 + 9.433962 + 9.433962 + 6.597550 + 3.777148 + 5
= 54.242622 bps
+ uncertainty_buffer 10 bps
= 64.242622 bps = 0.64242622 %
```

Si `expected_gross_move_bps ≤ break_even_move_bps` ⇒ `POLICY_FAIL-P2`/NO_GO para
esa hipótesis.

**T4.6 PASS:** cálculo reproducible, no valor real propuesto.

## Controles preventivos, detectivos y reactivos — T4.7

| Tipo | Control | Riesgo | Fallo crítico si falta |
|---|---|---|---|
| Preventivo | Mandato obligatorio | Entrada sin autoridad | Sí |
| Preventivo | Cost gate F-010 | Edge menor a costo | Sí |
| Preventivo | Sizing R/E/cash | Exposición excesiva | Sí |
| Preventivo | Freshness + cooldown | Dato stale/overtrading | Sí |
| Detectivo | Reconciliación | Estado falso | Sí |
| Detectivo | Gap/watermark/invariantes | Feed corrupto | Sí |
| Detectivo | Daily-loss/drawdown monitor | Pérdida agregada | Sí |
| Reactivo | Stop/trailing | Pérdida por decisión | Gap residual declarado |
| Reactivo | Circuit breaker | Drawdown/daily loss | Sí |
| Reactivo | EXIT_LONG protector | Deriva adversa | Sí |
| Reactivo | DEGRADED/BLOCKED | Sistema dañado | Sí |

Toda trayectoria tiene control o se declara residual. Para Spot long-only, la cota
última es max_exposure; para derivados D-001 debe reabrirse.

**Gate de Fase 4: PASS_CONDITIONAL.** Contratos y ecuaciones completos; D-001 y
D-003 deben resolverse antes de numerizar riesgo o ejecutar validación.

# Fase 6 — Arquitectura conceptual greenfield

## Contratos neutrales — T6.1

| Responsabilidad | Input/output normativo | Estado/fallo seguro |
|---|---|---|
| Sensor | RawMarketEvent | ABSENT/DATA_UNAVAILABLE |
| Guardia | QualifiedMarketFrame | FRESH…MISSING; DATA_BLOCKED |
| Custodio | PortfolioState | RECONCILED/CONFLICT; STATE_UNKNOWN |
| Modelo Temporal | MarketContext | SUFFICIENT/CONTEXT_INSUFFICIENT |
| Modelo Costos | CostEstimate | BOUNDED/COST_UNKNOWN |
| Política | CandidateIntent | NO_INTENT/ARMED/INVALIDATED |
| Gobernador | RiskVerdict | APPROVED/REJECTED |
| Máquina | Decision + next SystemState | HOLD/BLOCKED |
| Ledger | DecisionRecord inmutable | INCOMPLETE bloquea export |
| Validador | TestVerdict PASS/FAIL | FAIL explícito |

**T6.1 PASS:** datos, unidades, estados y fallos definidos sin bus/db/framework.

## Decision/replay — T6.2

El envelope normativo de T1.4 (23 campos) es el contrato T6.2. Idempotencia =
SHA256 de canonical JSON; expiración exige versions vigentes, no supersession,
ledger registrado y no consumo previo. Replay usa reloj explícito, decimales
normalizados, UTC, listas ordenadas, sin random/`now()`.

**T6.2 PASS.** No impone transporte/almacenamiento.

## Secuencias conceptuales — T6.3

```text
NORMAL:
Sensor→Guardia→{Temporal,Costos}; Custodio→State; Política→Intent;
Gobernador→Verdict; Máquina→Decision; Ledger RECORD_BEFORE_EXPORT.

STALE/RESYNC:
Gap→revoke source→invalidate context/intent/decision→HOLD/BLOCKED→new generation
LIVE→new evaluation (Decision vieja nunca revive).

DUPLICATE:
event/decision id seen→HOLD/DUPLICATE→no second export.

RESTART:
boot UNKNOWN/BLOCKED→authoritative POSITION_SYNC→QUALITY_READY→evaluation.

PROTECTIVE EXIT:
LONG + trigger P1→preempt strategy/entry→EXIT_LONG→Ledger→EXIT_PENDING.
```

**T6.3 PASS:** Política nunca ejecuta ni evade Gobernador.

## Evidencia mínima — T6.4

Conservar: MarketContext(features/units/windows/times/version), CandidateIntent
(policy/evidence/invalidation/expiry), RiskVerdict(limits/reason/mandate), Decision
completa, DecisionRecord hashes/transición y outcome autoritativo futuro. Registro
antes de export. Late data no reescribe historia.

**T6.4 PASS:** un tercero puede reconstruir por qué se decidió.

## Camino futuro — T6.5

```text
unit/property tests → deterministic replay → purged/embargo walk-forward OOS
→ shadow → paper fills → human review → [LIVE fuera de alcance]
```

Cada gate es secuencial y no compensatorio. Integración/plataforma sólo después del
veredicto.

**T6.5 PASS.** Live explícitamente fuera.

## Gate empírico futuro — T6.6

| Categoría | Métrica | Rechazo pre-registrado |
|---|---|---|
| Utility | DeltaU neta vs NULL | ≤ `margin_min` |
| Costos | gross edge vs cost+buffer | gross≤cost ⇒ fail |
| Downside | drawdown/tail/loss | > RiskMandate |
| Overfit | PBO | ≥ `pbo_max` |
| Estabilidad | folds/vecinos | cambio de signo/collapse |
| Muestra | episodios independientes | < `n_min` |
| Selectividad | coverage–utility | fuera de frontera |

Valores siguen `PENDING` bajo D-003/D-009/D-014 y se congelan antes de OOS; jamás
se mueven después de resultados.

**T6.6 PASS_CONDITIONAL:** schema/gobierno completo, números pendientes.

# Fase 7 — Revisión adversarial

## Hallazgos y respuestas — T7.1…T7.4

| ID | Perspectiva | Hallazgo | Respuesta/veredicto |
|---|---|---|---|
| Q-1 | Quant | Forming bar/leakage | BarLifecycle + auditoría T3.7: mitigado |
| Q-2 | Quant | POL-101 confundida con winner | D-015 sólo formalización: mitigado |
| Q-3 | Quant | Setup bars no independientes | Unidad=mismo setup episode: mitigado |
| Q-4 | Quant | Cost/turnover subestimado | F-010/T4.5/T4.6; valores pendientes |
| R-1 | Riesgo | Entry con state/data unknown | Hard block: mitigado |
| R-2 | Riesgo | Gap excede stop | Residual declarado; max exposure cota Spot |
| R-3 | Riesgo | Partial/cancel residual | SM-024/026: mitigado |
| A-1 | Arquitectura | Policy podría ejecutar | Transiciones/contratos lo prohíben: 0 paths |
| A-2 | Arquitectura | Restart/duplicate | reconciliation/idempotency: mitigado |
| P-1 | Producto | P0 siguen abiertas | Dueño/gate explícitos; no hidden default |
| P-2 | Producto | ENTER/HOLD/EXIT insuficientes | D-013 trigger de revisión; no evidencia actual |

**T7.1 PASS_CONDITIONAL; T7.2 PASS_CONDITIONAL; T7.3 PASS; T7.4 PASS.** Condición:
resolución humana antes de numerizar/ejecutar.

## Consistencia cruzada — T7.5

Correcciones integradas:

1. Precedencia armonizada: P0 reconciliación antes de P1 stop/breaker.
2. Time stop P3 por default, elevable a P1 por mandato versionado.
3. Gap risk: puede exceder stop budget, pero bajo CP-01 pérdida total queda acotada
   por max exposure; derivados reabren D-001.
4. T4.5 ya formalizado: la validación teórica no lo trata como ausente.
5. Terminología canónica preservada: observed_at; Decision≠Order≠Fill≠Position;
   BLOCKED=status; HOLD siempre con reason.

**T7.5 PASS:** contradicciones críticas abiertas = 0; decisiones humanas visibles.

# Fase 8 — Gate final y cierre

## Matriz de trazabilidad — T8.1

| Requisito | Diseño | Riesgo | Prueba/evidencia |
|---|---|---|---|
| Causalidad | BarLifecycle/T3.7 | ARCH_FAIL A2 | validation OB-03/SC-03/boundaries |
| Totalidad | SM-001…031/P101-T01…21 | Estado sin salida | OB-01 + 24 escenarios |
| Determinismo | canonical hashes | Duplicate order | OB-02/OB-04 |
| Riesgo no evadible | Gobernador/T3.6 | Bypass | OB-05 + FMEA |
| Staleness | FreshnessPolicy/L2 | Entrada stale | OB-06/SC-05/06 |
| Reconciliación | Custodio | Estado falso | OB-07/SC-11/12 |
| Costos | F-010/T4.5/4.6 | Edge no cosechable | OB-08 + 3 numéricos |
| Auditabilidad | Ledger/T6.4 | Historia irreproducible | OB-09 |
| Falsabilidad | ARCH/POLICY/NO_GO | Gate móvil | T5.6/5.7 |
| Arquitectura neutral | T6.1–6.5 | Herencia/bypass | T7.3 |

**T8.1 PASS:** no gap de trazabilidad crítico.

## Criterios North Star — T8.2

| Criterio | Evidencia | Estado |
|---|---|---|
| 3 artefactos finales | spec + validation + decision log | PASS |
| Contrato de datos completo | T2.1–T2.6 | PASS_CONDITIONAL budgets |
| Máquina/transiciones | T1.3/T3.6 | PASS |
| Entry/exit/sizing/stops | T1.4/T3.4/T4.1–4.3 | PASS_CONDITIONAL P0 |
| ≥3 policies sin edge claim | T3.2/T3.3 | PASS |
| Costos/break-even | T4.5/T4.6 | PASS teórico |
| Invariantes riesgo +/- | T4.3/T5 | PASS teórico |
| ≥15 escenarios + ≥3 numéricos | validation: 24 + 3 | PASS |
| Mapa greenfield | T0.2/T6.1 | PASS |
| Gate OOS | T6.6/D-009 | PASS_CONDITIONAL |
| P0/P1 visibles | decision log | PASS |
| Límites/no live | T8.4 | PASS |

## Veredicto exacto — T8.3

# `READY_FOR_OFFLINE_VALIDATION`

Justificación: la definición es completa, causal, determinista, falsable, auditable
y teóricamente probada; no quedan fallos lógicos críticos. “Ready” significa que
puede iniciarse **una fase separada de implementación del harness/replay**, no que
la policy tenga edge ni que el experimento OOS pueda correrse con defaults.

Precondiciones antes de **ejecutar** OOS: resolver/freeze D-001, D-002, D-003,
D-009 y D-014. Hasta entonces sólo puede prepararse el harness parametrizado.

## Permitido/prohibido — T8.4

Permitido: implementar unit/property tests y replay offline parametrizado; solicitar
P0; congelar gate; preparar dataset/splits. Prohibido: live, testnet/paper durante
este objetivo, credenciales, órdenes, claims de beneficio, bajar/mover gates,
tratar PASS teórico como edge o rellenar decisiones humanas.

## Pulido y consistencia — T8.5

Glosario, UTC, unidades, states, parameter IDs, reason codes y links auditados.
Artefactos finales:

- `docs/btc-decision-agent-spec.md`
- `docs/btc-decision-agent-theoretical-validation.md`
- `docs/btc-decision-agent-decision-log.md`

## Cierre — T8.6

Criterios T8.1–T8.5: cerrados. Registrar veredicto en tasks y crear STOPs. El cierre
no autoriza trading y preserva las precondiciones humanas/empíricas.

## Afirmaciones prohibidas a partir de estas capturas

- “El usuario opera Spot/Margin” sin confirmación adicional.
- “El usuario compra cuando el precio cruza MA60”.
- “67.75 % de bids implica subida o señal de compra”.
- “El spread será siempre 0.01 USDT”.
- “La estrategia 1h/15m es la que muestra la pantalla”.
- “La configuración observada es rentable o superior a otra política”.

## Decisiones abiertas detectadas (para T0.4)

| Prioridad | Decisión |
|---|---|
| P0 | Confirmar Spot frente a Margin/Futures y si el mandato es sólo `LONG/FLAT`. |
| P0 | Definir horizonte real y si la decisión ocurre únicamente al cierre de vela. |
| P0 | Definir presupuesto de riesgo, pérdida máxima y autoridad de aprobación. |
| P1 | Documentar la regla manual actual, si existe, y distinguirla de una nueva hipótesis. |
| P1 | Elegir familias de orden para el futuro modelo de paper fills. |
| P1 | Confirmar fees y supuestos de slippage para el break-even. |
| P2 | Elegir plataforma de implementación sólo después del veredicto conceptual. |
| P2 | Decidir qué contexto visual debe aparecer luego en observabilidad. |

## Evidencia de cierre de T0.1

- Los tres grupos exigidos (`OBSERVADO`, `AMBIGUO`, `NO MOSTRADO`) están completos.
- Cada observación tiene certeza e implicación limitada.
- Las ambigüedades se convierten en supuestos o decisiones, no en hechos.
- No se infiere ninguna regla de trading ni recomendación desde la UI.
