# Validación teórica del agente de decisión BTC

**Estado:** FINAL — Fase 5 (T5.1–T5.8) cerrada teóricamente
**Alcance:** validación conceptual y determinista de la especificación congelada
en `docs/btc-decision-agent-spec.md`; no implementa, no ejecuta, no conecta cuentas
y no envía órdenes.
**Fecha:** 2026-09-15

## Supuestos declarados

1. Esta validación es **teórica**. "PASS" significa que la lógica es completa,
   determinista, causal, acotada por riesgo y falsable en el papel; **no** significa
   rentable, aprobada para producción ni validada estadísticamente.
2. ADR-0002 congeló por delegación explícita D-001/D-002/D-003 para el perfil
   de fixtures, D-011 para plataforma offline y D-009/D-014 como contratos de un
   experimento futuro. Esto no convierte los valores en evidencia empírica ni
   autoriza OOS ejecutado, paper, testnet o live.
3. Los ejemplos numéricos usan valores **sintéticos y didácticos**, etiquetados
   `EXAMPLE_ONLY`. Reutilizan la aritmética ya publicada en el ejemplo manual de
   T2.5 para que un tercero pueda recalcularlos sin datos de mercado reales.
4. No se afirma edge, retorno esperado ni superioridad de ninguna política. POL-101
   es `PRIMARY_FOR_THEORETICAL_FORMALIZATION`; POL-102/POL-103 son challengers; las
   tres siguen `CANDIDATE_UNVALIDATED`.
5. Este documento no contiene credenciales, no autoriza trading y no constituye
   asesoría financiera.

## Niveles de evidencia

Cada obligación, escenario y hallazgo declara su nivel de evidencia para no
confundir demostración conceptual con evidencia empírica.

| Nivel | Símbolo | Significado | Qué puede afirmar |
|---|---|---|---|
| Demostración lógica | `L` | Se deriva de contratos, tablas de transición, predicados puros o invariantes de la spec. | Totalidad, determinismo, prohibiciones, coherencia estructural. |
| Cálculo recalculable | `C` | Aritmética cerrada sobre datos sintéticos que un tercero reproduce a mano. | Dimensionalidad, break-even mecánico, ordenamiento de guards. |
| Argumento de diseño | `A` | Razonamiento sobre por qué la regla es segura, sin cálculo ni corrida. | Mitigaciones, elección de fail-safe, cobertura de casos. |
| Evidencia empírica | `E` | **Pendiente.** Requiere replay/backtest/OOS con datos reales y costos. | Utilidad neta, robustez, drawdown, edge. **No disponible en esta fase.** |

Regla: ninguna afirmación de nivel `E` se declara satisfecha en este documento.
Todo lo que dependa de `E` aparece en la lista de evidencia empírica pendiente
(T5.8) y arrastra un veredicto **condicional**.

---

## T5.1 — Matriz de obligaciones de prueba

Cada obligación declara método, evidencia disponible, nivel y veredicto honesto.
`PASS` sólo aplica a la propiedad teórica nombrada; nunca a utilidad económica.

| # | Obligación | Método de verificación | Evidencia en la spec | Nivel | Veredicto teórico |
|---|---|---|---|---|---|
| OB-01 | **Totalidad** — toda combinación relevante de estado/calidad termina en una decisión definida. | Recorrer las 10 configuraciones válidas × familias de evento; SM-030/SM-031 cierran el resto. | Tabla SM-001…SM-031; matriz de totalidad P101-T01…T21; NULL_HOLD por configuración. | `L` | PASS teórico |
| OB-02 | **Determinismo** — mismos inputs/estado/versión ⇒ misma salida. | Verificar `decision_id = SHA256(canonical_json(...))` sin `now()` ni aleatoriedad; predicados puros de POL-101. | Regla de identidad T1.4; serialización canónica; `NULL_HOLD.deterministic=true`. | `L` | PASS teórico |
| OB-03 | **Causalidad** — ninguna decisión usa información con timestamp posterior a `decision_time`. | Auditoría input→disponibilidad (T5.7); invariante `max_input_event_time ≤ as_of_time ≤ decision_time`; barra estratégica sólo `FINAL`. | FeatureValue invariantes; BarLifecycle; `required_features_valid` exige `as_of_time == boundary`. | `L` | PASS teórico |
| OB-04 | **Idempotencia** — una identidad no produce dos decisiones activables. | `DUPLICATE_IDENTITY`→SM-029; `POL101_DUPLICATE`; `ENTRY_EMITTED` impide segundo intent. | SM-029; preflight POL-101; contrato de consumo "decision_id no fue consumido". | `L` | PASS teórico |
| OB-05 | **Safety / riesgo no evadible** — ninguna entrada atraviesa un Gobernador ausente, incierto o bloqueado. | Guarda de `ENTER_LONG` exige `RISK_APPROVED`; prohibición "Política → RiskMandate"; precedencia P0/P1 sobre P4. | Contrato `ENTER_LONG`; transiciones prohibidas; precedencia de decisiones. | `L` | PASS teórico |
| OB-06 | **Staleness / abstención segura** — datos stale/incompletos ⇒ HOLD/bloqueo, nunca señal. | Estados FRESH/SUSPECT/STALE/MISSING; budget faltante ⇒ `BLOCKED`; `null + reason`, nunca cero/forward-fill. | FreshnessPolicy; política por fuente S-01…S-09; guards de features. | `L` | PASS teórico |
| OB-07 | **Reconciliación** — posición desconocida/contradictoria impide entrada. | `UNKNOWN`⇒health `BLOCKED`; SM-003 `POSITION_CONFLICT`; `POL101_POSITION_UNKNOWN`. | Dimensión PositionState; SM-003/SM-027/SM-028. | `L` | PASS teórico |
| OB-08 | **Costos** — edge bruto ≤ costo total ⇒ NO_GO de esa hipótesis; costo desconocido ≠ cero. | Fórmula `round_trip_cost_bps`; `POL101_COST_CAP_EXCEEDED`; `COST_UNKNOWN`; ejemplo numérico N-2. | F-010; `cost_admissible`; DeltaU vs NULL. | `C` | PASS teórico (umbral empírico pendiente `E`) |
| OB-09 | **Auditabilidad** — cada decisión conserva inputs, versiones, razones y transición reconstruibles. | `evidence_refs`, `reason_codes`, `state_before.version`, timestamps; `ledger_precondition=RECORD_BEFORE_EXPORT`. | Envelope `Decision`; taxonomía de razones. | `L` | PASS teórico |

**Cobertura de OB frente a objetivos O1–O14:** OB-01→O3; OB-02→O4; OB-03→O1;
OB-04→O7; OB-05→O5; OB-06→O2; OB-07→O6; OB-08→O9/O13 (parte empírica pendiente);
OB-09→O8. Los objetivos O10–O12, O14 dependen de evidencia `E` y quedan listados en
T5.8; no se declaran PASS aquí.

---

## T5.2 — Escenarios deterministas

Se documentan **24 escenarios** (mínimo requerido: 15). Cada uno declara input,
estado inicial `(Position/Evaluation/Health)`, salida obligatoria y razón. Todos
son nivel `L` salvo indicación. Los 15 casos exigidos por la tarea están marcados
con `[REQ]`.

| ID | Escenario | Estado inicial | Input / evento | Acción obligatoria | Razón primaria | Regla |
|---|---|---|---|---|---|---|
| SC-01 `[REQ]` | Entrada válida | `FLAT/PULLBACK_ARMED/READY` | Resume cruzado + volumen + costo OK | `ENTER_LONG` (una vez) | `OPPORTUNITY_APPROVED` | SM-013; POL101-T18 |
| SC-02 `[REQ]` | Sin volumen | `FLAT/PULLBACK_ARMED/READY` | Resume cruzado, `volume_ratio < VOLUME_CONFIRM` | `HOLD` (mantiene armado) | `POL101_VOLUME_NOT_CONFIRMED` | POL101-T17 |
| SC-03 `[REQ]` | Vela abierta | `FLAT/IDLE/READY` | Barra `FORMING` (`x=false`) usada como trigger | `HOLD` bloqueado | `DATA_BLOCKED` / feature `null` | BarLifecycle; `required_features_valid` falla |
| SC-04 `[REQ]` | Spread alto | `FLAT/PULLBACK_ARMED/READY` | `round_trip_cost_bps > COST_CAP_BPS` | `HOLD`; invalida setup + cooldown | `POL101_COST_CAP_EXCEEDED` | POL101-T15 |
| SC-05 `[REQ]` | Feed stale | `FLAT/IDLE/READY` | Fuente requerida `STALE` (age > max_age) | `HOLD` bloqueado | `DATA_BLOCKED` | S-04/S-05 STALE ⇒ health `DEGRADED/BLOCKED` |
| SC-06 `[REQ]` | Gap de secuencia L2 | `FLAT/IDLE/READY` | Gap en sequence del libro | `HOLD` bloqueado | `DATA_BLOCKED` | `BookSyncState` revoca view; SM-006/008 |
| SC-07 `[REQ]` | Whipsaw | `FLAT/PULLBACK_ARMED/READY` | Trend context se vuelve falso tras armar | `HOLD`; invalida setup + cooldown | `POL101_TREND_INVALIDATED` | POL101-T13 |
| SC-08 `[REQ]` | Spoofing / imbalance aislado | `FLAT/IDLE/READY` | `depth_imbalance_B` extremo, sin trend+pullback | `HOLD` | `NO_INTENT` (L2 no es trigger) | D-007; F-011 filtro, no trigger |
| SC-09 `[REQ]` | Volatilidad extrema | `FLAT/IDLE/READY` | `atr_fraction` fuera de `[ATR_MIN, ATR_MAX]` | `HOLD` | `POL101_TREND_CONTEXT_FALSE` | `trend_context` falso |
| SC-10 `[REQ]` | Evento duplicado | `ENTRY_PENDING/IDLE/READY` | Mismo intent/identidad reenviado | `HOLD`; una sola exportación | `DUPLICATE` | SM-029; POL101-T20 |
| SC-11 `[REQ]` | Restart | `UNKNOWN/IDLE/BLOCKED` | Arranque sin posición reconciliada | `HOLD` bloqueado | `STATE_UNKNOWN` | SM-001/002; POL101-T01 |
| SC-12 `[REQ]` | Posición desconocida | `UNKNOWN/IDLE/BLOCKED` | `POSITION_CONFLICT` | `HOLD` bloqueado | `INVALID_STATE_COMBINATION`/`STATE_UNKNOWN` | SM-003 |
| SC-13 `[REQ]` | Risk blocked | `FLAT/ENTRY_CANDIDATE/READY` | `RISK_REJECTED` | `HOLD` | `RISK_REJECTED` | SM-011 |
| SC-14 `[REQ]` | Stop / salida protectora | `LONG/IDLE/READY` | `PROTECTIVE_TRIGGER` autoritativo | `EXIT_LONG` (P1) | `RISK_LIMIT_BREACH`/`PROTECTIVE_INVALIDATION` | SM-021→SM-023 |
| SC-15 `[REQ]` | Salida normal (estratégica) | `LONG/IDLE/READY` | `trend_exit` verdadero | `EXIT_LONG` (P3) | `POL101_EXIT_TREND` | POL101-T06 |
| SC-16 | Cost unknown | `FLAT/PULLBACK_ARMED/READY` | `round_trip_cost_bps = null` | `HOLD` | `COST_UNKNOWN` | POL101-T15; F-010 |
| SC-17 | Trigger protector con datos degradados | `LONG/IDLE/DEGRADED` | `PROTECTIVE_TRIGGER` + posición conocida | `EXIT_LONG` (P1) | `DATA_RISK_WITH_KNOWN_POSITION` | HealthState `DEGRADED` permite salida |
| SC-18 | Fill parcial de salida | `EXIT_PENDING/IDLE/READY` | `EXIT_PARTIAL` (residual > 0) | `HOLD` (sigue pending) | `PENDING_FEEDBACK` | SM-024 |
| SC-19 | Cancelación de salida con residual | `EXIT_PENDING/IDLE/READY` | Cancelación, residual > 0 | Reevaluar protección | reason exit protector | SM-026 ⇒ `LONG/EXIT_CANDIDATE/DEGRADED` |
| SC-20 | Cooldown activo | `FLAT/COOLDOWN/READY` | `STRATEGIC_TICK` durante cooldown | `HOLD` | `COOLDOWN` | SM-018; POL101-T03 |
| SC-21 | Schema desconocido | Cualquiera | `UNKNOWN_SCHEMA` | `HOLD` bloqueado | `UNKNOWN_SCHEMA` | SM-031; POL101-T21 |
| SC-22 | Mandato de riesgo expirado | `FLAT/IDLE/READY` | `MANDATE_EXPIRED` | `HOLD` bloqueado | `MANDATE_EXPIRED` | SM-008 |
| SC-23 | Arm timeout | `FLAT/PULLBACK_ARMED/READY` | `bars_since_arm > ARM_TIMEOUT_BARS` | `HOLD`; invalida + cooldown | `POL101_ARM_TIMEOUT` | POL101-T12 |
| SC-24 | Time exit | `LONG/IDLE/READY` | `holding_bars ≥ MAX_HOLDING_BARS` | `EXIT_LONG` (P3) | `POL101_EXIT_TIME` | POL101-T05 (precede a trend/anchor) |

**Cobertura de los 15 casos requeridos:** entrada válida (SC-01), sin volumen
(SC-02), vela abierta (SC-03), spread alto (SC-04), feed stale (SC-05), gap de
secuencia (SC-06), whipsaw (SC-07), spoofing (SC-08), volatilidad extrema (SC-09),
duplicado (SC-10), restart (SC-11), posición desconocida (SC-12), risk blocked
(SC-13), stop (SC-14), salida normal (SC-15). Los 15 están presentes; SC-16…SC-24
son cobertura adicional.

**Determinismo de la precedencia (caso combinado):** en `FLAT/ENTRY_CANDIDATE/READY`
con `RISK_APPROVED` **y** `QUALITY_DEGRADED` concurrentes, la precedencia 3 (bloqueo
de calidad) supera a la 7 (entrada): la salida obligatoria es `HOLD`, nunca
`ENTER_LONG`. Un evento de menor prioridad no revierte otro mayor dentro del mismo
`decision_time`.

---

## T5.3 — Ejemplos numéricos recalculables

Tres ejemplos completos (`EXAMPLE_ONLY`, nivel `C`). Se reutilizan las cinco barras
sintéticas del ejemplo manual de T2.5 para que sean reproducibles a mano.

Barras FINAL (unidad genérica equivalente a USDT/BTC):

| Barra | High | Low | Close | Base volume |
|---|---:|---:|---:|---:|
| t-4 | 102 | 99 | 100 | 10 |
| t-3 | 103 | 100 | 102 | 12 |
| t-2 | 104 | 100 | 101 | 8 |
| t-1 | 105 | 101 | 104 | 15 |
| t | 107 | 103 | 106 | 20 |

Features base (N=3, K=1), idénticas a T2.5:

```text
SMA_3(t)        = (101 + 104 + 106)/3 = 103.666667
SMA_3(t-1)      = (102 + 101 + 104)/3 = 102.333333
distance_to_sma = 106/103.666667 - 1  = 0.022508      (2.2508 %)
sma_slope_3_1   = 103.666667/102.333333 - 1 = 0.013029 (1.3029 % por barra)
volume_ratio_3  = 20 / ((12+8+15)/3) = 20/11.666667 = 1.714286
ATR_3           = 4      atr_fraction_3 = 4/106 = 0.037736 (3.7736 %)
```

Parámetros **sintéticos** para los ejemplos (no propuestos):

```text
THETA_SLOPE_ENTER = 0.010    ATR_MIN = 0.010   ATR_MAX = 0.060
PULLBACK_LOW = 0.005  PULLBACK_HIGH = 0.030  PULLBACK_FAIL = 0.002
RESUME_LEVEL = 0.020  VOLUME_CONFIRM = 1.50   COST_CAP_BPS = 40
EXIT_ATR_MULTIPLE = 1.5      MAX_HOLDING_BARS = 8
fees = 10 bps/lado    impact_buffer = 5 bps
```

### Ejemplo N-1 — Entrada aceptada

Setup ya `PULLBACK_ARMED` en t-1 con `prior.distance_to_sma = 0.018`. En t:

```text
trend_context: slope 0.013029 ≥ 0.010          → true
               close 106 > SMA 103.666667       → true
               ATR_MIN 0.010 ≤ 0.037736 ≤ 0.060 → true
resume_crossed: prior 0.018 ≤ 0.020 AND now 0.022508 > 0.020 → true
volume_confirmed: 1.714286 ≥ 1.50              → true
cost_admissible: round_trip_cost ≤ COST_CAP_BPS (ver N-2 base) → true
```

Todos los predicados verdaderos ⇒ `entry_intent` una vez ⇒ tras `RISK_APPROVED`
`ENTER_LONG` (P4). Recalculable: cambiar `prior.distance_to_sma` a 0.021 rompe
`resume_crossed` (0.021 > 0.020) y la salida pasa a `HOLD/POL101_RESUME_NOT_CROSSED`.

### Ejemplo N-2 — Entrada rechazada por costo

Costo round-trip base (idéntico a T2.5), con BBO `bid=105.90 / ask=106.10`,
`mid=106.00`, y depth para Q=1 BTC:

```text
spread_bps        = 10_000·0.20/106      = 18.867925
buy_cross_bps     = sell_cross_bps       = 9.433962
buy_depth_slippage(1)  = 10_000·(106.17-106.10)/106.10 = 6.597550
sell_depth_slippage(1) = 10_000·(105.90-105.86)/105.90 = 3.777148

round_trip_cost = 10 + 10 + 9.433962 + 9.433962
                  + 6.597550 + 3.777148 + 5
                = 54.242622 bps
```

Comparación de gate: `54.242622 bps > COST_CAP_BPS 40 bps` ⇒ `cost_admissible` es
false ⇒ salida obligatoria `HOLD/POL101_COST_CAP_EXCEEDED` + cooldown; **nunca**
`ENTER_LONG`. Este es el mismo mecanismo que fuerza `NO_GO` de una hipótesis cuyo
edge bruto no supera el costo total.

Break-even mecánico: para que una entrada sea admisible, el movimiento bruto
esperado debe superar `54.242622 bps ≈ 0.5424 %` **más** el buffer de incertidumbre
pre-registrado. Con la banda de distancia observada (2.2508 % sobre SMA), el costo
consume ~24 % de ese margen bruto; la utilidad neta sólo se decide con evidencia
empírica `E` (pendiente), no aquí.

### Ejemplo N-3 — Salida prioritaria (anchor exit)

Posición `LONG`. Supóngase que en una barra posterior el precio cae bajo la SMA:
`distance_to_sma = -0.060`, `atr_fraction = 0.037736`.

```text
anchor_exit: distance ≤ -EXIT_ATR_MULTIPLE · atr_fraction
             -0.060 ≤ -1.5 · 0.037736 = -0.056604   → true (-0.060 < -0.056604)
```

Orden normativo de salida LONG: `TIME_EXIT` (falso, holding_bars < 8) → `EXIT_TREND`
(evaluar `slope ≤ THETA_SLOPE_EXIT`) → `EXIT_ANCHOR` (verdadero). Salida obligatoria
`EXIT_LONG/POL101_EXIT_ANCHOR` (P3 estratégico). Recalculable: con
`distance_to_sma = -0.050`, `-0.050 ≤ -0.056604` es false ⇒ `anchor_exit` false; si
tampoco hay trend/time exit, salida `HOLD/POL101_LONG_HOLD`.

---

## T5.4 — Pruebas de frontera de umbrales

Para cada comparación se prueban: igual (`=`), epsilon inferior/superior, cero,
máximo, `null`, `NaN` y timestamp fuera de orden. Convención de spec: bandas usan
`≤`/`≥` inclusivos; `resume_crossed` exige **estrictamente** `>` para el cruce.
Nivel `L` salvo cálculo marcado `C`.

| BT | Umbral / comparación | Caso frontera | Resultado obligatorio |
|---|---|---|---|
| BT-01 | `slope ≥ THETA_SLOPE_ENTER` | slope `=` θ | `trend_context` true (inclusivo) |
| BT-02 | `slope ≥ THETA_SLOPE_ENTER` | slope = θ − ε | false ⇒ `TREND_CONTEXT_FALSE` |
| BT-03 | `ATR_MIN ≤ atr ≤ ATR_MAX` | atr `=` ATR_MIN o `=` ATR_MAX | true en ambos extremos (inclusivos) |
| BT-04 | `ATR_MIN ≤ atr ≤ ATR_MAX` | atr = ATR_MAX + ε | false ⇒ `TREND_CONTEXT_FALSE` |
| BT-05 | `PULLBACK_LOW ≤ dist ≤ PULLBACK_HIGH` | dist `=` LOW y `=` HIGH | armar (inclusivo en ambos) |
| BT-06 | `resume_crossed` (`prior ≤ R` y `now > R`) | now `=` RESUME_LEVEL | **no** cruza (requiere `>` estricto) ⇒ mantiene armado |
| BT-07 | `resume_crossed` | now = R + ε, prior = R | cruza ⇒ evaluar volumen/costo |
| BT-08 | `volume_ratio ≥ VOLUME_CONFIRM` | ratio `=` VOLUME_CONFIRM | confirmado (inclusivo) |
| BT-09 | `round_trip_cost ≤ COST_CAP_BPS` | costo `=` cap | admisible (inclusivo); costo = cap + ε ⇒ `COST_CAP_EXCEEDED` |
| BT-10 | `atr_fraction` denominador | `Close(t) = 0` | `null_reason` (división indefinida evitada); nunca 0 |
| BT-11 | `volume_ratio` denominador | `mean_prev_volume = 0` | `null_reason=ZERO_VOLUME_BASELINE`; nunca ∞ ni 0 |
| BT-12 | `distance_to_sma` denominador | `SMA_N = 0` | requiere `SMA_N > 0`; si no, `null` |
| BT-13 | `depth_imbalance` denominador | `bid_notional + ask_notional = 0` | `null` (dominio `[-1,1]` no forzado a 0) |
| BT-14 | Cualquier feature required | `value = null` | `required_features_valid` false ⇒ `FEATURE_MISSING`/bloqueo |
| BT-15 | Cualquier feature required | `value = NaN` | tratado como no `QUALIFIED` ⇒ `BLOCKED`; nunca comparado numéricamente |
| BT-16 | Máximo de dominio | `holding_bars = MAX_HOLDING_BARS` | `time_exit` true (inclusivo `≥`) ⇒ `EXIT_TIME` |
| BT-17 | `event_age` / lateness | edad negativa > `clock_skew_budget` | `CLOCK_FAULT` ⇒ bloquea |
| BT-18 | Timestamp fuera de orden | `event_time > as_of_time` | viola invariante `max_input_event_time ≤ as_of_time` ⇒ feature `null`/bloqueo |
| BT-19 | Timestamp fuera de orden | evento late tras `FINAL` | `LATE_CORRECTION`: no reescribe Decision pasada; incidente |
| BT-20 | `arm_timeout` | `bars_since_arm = ARM_TIMEOUT_BARS` vs `>` | `> ARM_TIMEOUT_BARS` invalida; en `=` aún vigente (estricto `>`) |

**Cálculo de frontera `C` (BT-06):** con `RESUME_LEVEL = 0.020` y `now = 0.020000`,
`now > R` es `0.020 > 0.020 = false` ⇒ no cruza. Con `now = 0.020001` ⇒ true. La
asimetría (`≤` en prior, `>` en now) impide doble conteo del mismo nivel y elimina
la comparación ambigua en el punto exacto.

**Ausencia de comparación ambigua / división indefinida:** BT-10…BT-13 demuestran
que todo denominador con posible cero retorna `null + reason`, nunca 0, ∞ ni
forward-fill. BT-15 aísla `NaN` fuera del dominio numérico. Nivel de conjunto: `L`
+ `C` puntual.

---

## T5.5 — FMEA (Failure Mode and Effects Analysis)

Escalas 1–5 (S = severidad, O = ocurrencia conceptual, D = dificultad de detección;
mayor D = más difícil de detectar). `RPN = S·O·D` es orientativo, no un gate.
Nivel de mitigación `L`/`A`.

| FM | Componente | Modo de fallo | Efecto | S | O | D | Mitigación en la spec | Riesgo residual |
|---|---|---|---|---:|---:|---:|---|---|
| FM-01 | Sensor/Feed | BBO stale sin marca | Costo subestimado, entrada indebida | 5 | 3 | 3 | `observed_age` budget; S-04 STALE ⇒ `CostEstimate` bloqueado | Bajo si budget congelado; **budget `E` pendiente** |
| FM-02 | Feed | Gap de secuencia L2 no detectado | Imbalance/costo falso | 5 | 2 | 3 | `BookSyncState` revoca generation; gap ⇒ view no LIVE | Bajo (lógica), depende de heartbeat `E` |
| FM-03 | Features | Barra `FORMING` leída como `FINAL` | Look-ahead | 5 | 2 | 4 | BarLifecycle; `as_of_time == boundary`; solo `FINAL` | Bajo (invariante dura) |
| FM-04 | Features | Denominador 0 ⇒ 0 en vez de null | Señal fantasma | 4 | 2 | 3 | Guards F-002/F-004/F-006/F-011 ⇒ `null + reason` | Bajo |
| FM-05 | Decisión | Dos decisiones para una identidad | Doble entrada | 5 | 2 | 3 | `decision_id` determinista; SM-029; `ENTRY_EMITTED` | Bajo |
| FM-06 | Decisión | Reason vago oculta bloqueo | Auditoría falsa | 4 | 2 | 4 | Taxonomía cerrada; `BLOCKED ⇒ HOLD` con reason | Bajo |
| FM-07 | Bus/orden de eventos | "Último en llegar gana" | Reversión de prioridad | 5 | 3 | 4 | Precedencia P0…P5; menor ordinal no reemplazado | Bajo (lógica); concurrencia real `E` |
| FM-08 | Riesgo | Entrada sin RiskMandate | Exposición no acotada | 5 | 2 | 3 | `ENTER_LONG` exige `RISK_APPROVED`; mandato null ⇒ solo hold/exit | Bajo (invariante dura) |
| FM-09 | Riesgo | Política eleva su propio límite | Bypass del Gobernador | 5 | 1 | 3 | Prohibición "Política → RiskMandate"; separación de poderes | Bajo |
| FM-10 | Persistencia/Estado | Restart con posición desconocida | Entrada sobre estado falso | 5 | 3 | 3 | `UNKNOWN`⇒`BLOCKED`; SM-001/002 reconciliación | Bajo |
| FM-11 | Persistencia | Late correction reescribe historia | Decisión no reproducible | 4 | 2 | 4 | `LATE_CORRECTION` no retroactivo; feature pasada intacta | Bajo |
| FM-12 | Costos | Costo desconocido tratado como 0 | Break-even falso | 5 | 2 | 3 | `COST_UNKNOWN`; término desconocido nunca 0 | Bajo |
| FM-13 | Ejecución futura | Fill parcial ignorado | Posición mal contada | 5 | 3 | 3 | SM-024/026 residual reconciliado; no fingir flat | Medio: **modelo de fills es Fase 4/`E`** |
| FM-14 | Ejecución futura | Rechazo/cancelación no reevaluado | Protección omitida | 5 | 2 | 3 | SM-026 ⇒ `LONG/EXIT_CANDIDATE/DEGRADED` | Medio: depende de feedback autoritativo `E` |

**Fallos críticos abiertos:** 0 a nivel lógico. FM-13/FM-14 tienen riesgo residual
**medio** porque el modelo de fills (T4.5) y el feedback de ejecución todavía no
están formalizados; se arrastran como bloqueadores parciales a T5.8 (evidencia `E`).

---

## T5.6 — Red-team adversarial

Cada ataque intenta forzar una entrada indebida, evadir el riesgo o romper el
determinismo. Un ataque "resistido" significa que la regla o el veredicto no cambia;
donde la defensa depende de un budget/gate pendiente, se marca `E`.

| RT | Ataque | Vector | Defensa en la spec | Resultado |
|---|---|---|---|---|
| RT-01 | Cambio de régimen | Trend se invierte tras armar | `POL101_TREND_INVALIDATED` invalida setup antes de confirmar | Resistido (`L`) |
| RT-02 | Gap de precio | Salto entre barras | `true_range` captura gap; barra `FINAL` sólo con watermark | Resistido (`L`); magnitud tolerable `E` |
| RT-03 | Flash move | Pico y reversión intra-ventana | Trigger sólo en barra `FINAL`; forming no dispara | Resistido (`L`) |
| RT-04 | Spoofing | Imbalance L2 masivo y efímero | D-007: L2 es filtro/veto, nunca trigger; `persistent_imbalance` con coverage | Resistido (`L`) |
| RT-05 | Baja liquidez | Depth insuficiente para Q | `INSUFFICIENT_VISIBLE_DEPTH` ⇒ costo `null` ⇒ bloqueo | Resistido (`L`) |
| RT-06 | Fee tier peor | Costo real > escenario base | `round_trip_cost` con escenarios `BASE/ADVERSE/EXTREME`; cap | Resistido en estructura (`C`); tier real `E` |
| RT-07 | Slippage adverso | Barrido peor que VWAP snapshot | `impact_buffer_bps`; slippage medido más allá del best quote | Parcial: buffer es simbólico, calibración `E` |
| RT-08 | Replay/duplicado | Reinyectar evento consumido | `decision_id` consumido una vez; `DUPLICATE` | Resistido (`L`) |
| RT-09 | Clock skew | Timestamps manipulados | `CLOCK_FAULT` si edad negativa > budget | Resistido (`L`); budget `E` |
| RT-10 | Forzar aprobación | Bajar umbral para que pase | Gobierno: no bajar umbrales, no borrar hallazgos negativos; pre-registro | Resistido por proceso (`A`) |

**Efecto sobre reglas/veredicto:** ningún ataque conceptual produce una entrada
indebida a nivel lógico. RT-07 (calibración de slippage/impacto) y los marcados `E`
no pueden declararse cerrados sin evidencia empírica; se arrastran a T5.8. Ningún
hallazgo motivó reescribir un mecanismo ni relajar un gate (respeta T5.7).

---

## T5.7 — Hipótesis congeladas frente a priors externos

Se congela el mecanismo de cada hipótesis y luego se contrasta con priors de mercado
y evidencia adversa **sin** reescribir el mecanismo ni mover su gate. La evidencia
externa puede **refutar o degradar** una candidata, nunca alterar retroactivamente
su definición o su umbral.

**Hipótesis congeladas (mecanismo, no parámetros):**

- **POL-101 `TREND_PULLBACK_RESUME`** (primary para formalización): en contexto de
  tendencia positiva confirmada, un retroceso acotado hacia la media seguido de una
  reanudación con volumen es una oportunidad long; se invalida si la tendencia se
  rompe o el pullback falla.
- **POL-102 `VOLATILITY_SCALED_REVERSION`** (challenger): desviaciones extremas
  escaladas por ATR tienden a revertir.
- **POL-103 `VOLATILITY_BREAKOUT`** (challenger): rupturas tras compresión de
  volatilidad continúan.
- **POL-000 `NULL_HOLD`** (control): no existe oportunidad suficientemente demostrada.

| Prior externo / evidencia adversa | Predicción sobre la hipótesis | Efecto permitido | Efecto prohibido |
|---|---|---|---|
| Momentum/trend-following documentado en cripto con costos altos | POL-101 plausible pero sensible a costos y whipsaw | Degradar a `NO_GO` si `DeltaU ≤ 0` en OOS | Redefinir "pullback" tras ver resultados |
| Mean-reversion frágil en tendencias fuertes | POL-102 con tail risk estructural (falling knife) | Retener como challenger; rechazar si tail > mandato | Cambiar `EXIT_ATR_MULTIPLE` post-OOS |
| Breakouts con alta tasa de falsos positivos y sensibilidad de ejecución | POL-103 sensible a slippage/latencia | Retener; degradar por costos | Relajar confirmación de ruptura |
| Costos de round-trip observables (spread+fees+slippage) suelen dominar edge intradía bruto | Riesgo de que edge bruto ≤ costo total | `NO_GO` de la hipótesis afectada | Reinterpretar costos para aprobar |
| Microestructura: imbalance L2 manipulable | Confirma D-007 (L2 no trigger) | Mantener L2 como filtro | Promover L2 a señal de entrada |

**Regla de integridad (nivel `A`):** el contraste con priors se registra como
diagnóstico. Ninguna candidata puede "aprobar" moviendo un gate; cualquier cambio de
mecanismo exige **nueva policy/version** y reabre sus pruebas (gobierno del decision
log). La evidencia empírica real (`E`) que permitiría refutar o promover queda
pendiente en T5.8.

---

## T5.8 — Resumen PASS/FAIL y evidencia empírica pendiente

### Veredicto por obligación (teórico)

| Obligación | Nivel | Veredicto |
|---|---|---|
| OB-01 Totalidad | `L` | **PASS teórico** |
| OB-02 Determinismo | `L` | **PASS teórico** |
| OB-03 Causalidad | `L` | **PASS teórico** |
| OB-04 Idempotencia | `L` | **PASS teórico** |
| OB-05 Safety/riesgo | `L` | **PASS teórico** |
| OB-06 Staleness | `L` | **PASS teórico** (budgets numéricos `E` pendientes) |
| OB-07 Reconciliación | `L` | **PASS teórico** |
| OB-08 Costos | `C` | **PASS teórico** (umbral económico `E` pendiente) |
| OB-09 Auditabilidad | `L` | **PASS teórico** |

**Fallos críticos abiertos a nivel lógico: 0.** No se declara PASS de utilidad,
edge, robustez ni drawdown: esas propiedades son de nivel `E` y no se evalúan aquí.

### Veredicto agregado

**PASS TEÓRICO CONDICIONAL.** La definición es completa, determinista, causal,
idempotente, acotada por riesgo, con abstención segura, reconciliación y
auditabilidad demostrables a nivel lógico (`L`) y con aritmética recalculable (`C`)
para costos y fronteras. **No es** una afirmación de rentabilidad ni de aptitud para
producción. El veredicto es **condicional** porque depende de decisiones humanas P0
abiertas y de evidencia empírica pendiente.

### Evidencia empírica pendiente (nivel `E` — no disponible en esta fase)

1. **Utilidad neta (O9/O13):** `DeltaU(policy) > 0` frente a `NULL_HOLD` con costos
   conservadores en OOS. Requiere el gate D-009 pre-registrado.
2. **Downside (O10):** drawdown, pérdida de cola y pérdida por decisión ≤ mandato
   humano D-003 (aún `OPEN_HUMAN`).
3. **Robustez (O11):** estabilidad y ausencia de cambio de signo entre regímenes con
   purga/embargo y control de PBO.
4. **Selectividad (O12):** curvas coverage–precision–utility.
5. **Oportunidad temporal (O14):** cero decisiones emitidas tras expirar su horizonte,
   medido end-to-end (depende de D-002).
6. **Budgets de frescura (D-014):** `BBO_CAP_MS`, `DEPTH_CAP_MS`, `β_bbo`, `β_depth`,
   `CLOCK_SKEW_MS`, etc., y su validación con latencia observada.
7. **Modelo de fills y feedback de ejecución (T4.5 / FM-13 / FM-14):** fee, spread,
   slippage, latencia, fill parcial, cancelación, adverse selection.
8. **Calibración de `impact_buffer_bps` y escenarios de costo (RT-07 / D-006):**
   fee tier real, tamaño Q y profundidad histórica L2.
9. **Parámetros estratégicos (T3.5, aún `[ ]`):** dominios/rangos congelados
   train-only para POL-101 y challengers.

Ninguno de estos ítems puede cerrarse dentro del alcance documental actual; todos
requieren una fase separada de replay/backtest/OOS con datos reales y aprobación
humana. Un PASS teórico **no** habilita trading, testnet ni paper durante este ciclo.

---

## Contradicciones y bloqueadores detectados

- **BL-01 (bloqueador parcial, arrastrado):** el modelo de paper fills (T4.5) y el
  feedback de ejecución no están formalizados; FM-13/FM-14 conservan riesgo residual
  medio. La spec ya tiene la máquina de estados que los consumirá (SM-015/024/026),
  pero la validación de esos caminos es de nivel `E`. No es contradicción interna;
  es trabajo de Fase 4 aún abierto (T4.1–T4.7 marcados `[ ]`).
- **BL-02 (dependencia, no contradicción):** OB-06 y varios escenarios (SC-05,
  BT-17) dependen de budgets `D-014` que siguen `PRE_REGISTER_PENDING`. La lógica
  fail-safe es completa (budget ausente ⇒ `BLOCKED`), pero los valores numéricos y
  su idoneidad son `E`.
- **BL-03 (dependencia P0):** los ejemplos numéricos N-1…N-3 usan parámetros
  sintéticos porque D-001/D-002/D-003 siguen `OPEN_HUMAN`. El veredicto de utilidad
  permanece condicional hasta que el usuario cierre esas decisiones.
- **Sin contradicciones cruzadas detectadas** entre este documento y la
  especificación, el decision log, el roadmap y el north star a nivel de estados,
  razones, prioridades, fórmulas y taxonomía. La resolución formal cruzada de los
  seis documentos corresponde a T7.5 (Fase 7), aún pendiente.

## Trazabilidad

| Sección | Origen en la spec |
|---|---|
| T5.1 obligaciones | T0.3 (O1–O14); T1.3; T1.4; T2.4; T2.5; T3.1 |
| T5.2 escenarios | T1.3 (SM-001…031); T3.4 (P101-T01…T21) |
| T5.3 numéricos | T2.5 (ejemplo manual); T3.4 (predicados) |
| T5.4 fronteras | T2.5 (guards/null); T2.4 (clock); T3.4 (predicados) |
| T5.5 FMEA | T1.3; T1.4; T2.3; T2.4; T4 (pendiente) |
| T5.6 red-team | T2.6/D-007; T2.3; T2.4; F-010 |
| T5.7 priors | T3.2; T3.3; D-009; D-015 |
| T5.8 veredicto | T0.3; D-003; D-009; D-014; T3.5; T4.5 |

## Cierre normativo integrado de Fase 5

Esta sección **supersede** cualquier referencia histórica anterior que describa
T3.5 o T4.1–T4.7 como “pendiente/no formalizada”. Esas tareas ya están integradas
en `docs/btc-decision-agent-spec.md`. FM-13/FM-14 conservan calibración empírica
pendiente (`E`), pero no un gap de definición.

- Obligaciones teóricas PASS: **9/9**.
- Escenarios deterministas: **24**; ejemplos numéricos: **3**; fronteras: **20**.
- FMEA: **14** modos; fallos críticos lógicos abiertos: **0**.
- Red-team: **10** ataques; ninguno evade un hard gate a nivel lógico.
- Evidencia empírica (`E`) continúa pendiente y no se presenta como PASS.

**Veredicto de Fase 5: `PASS_TEORICO_CONDICIONAL`.** Es evidencia suficiente para
`READY_FOR_OFFLINE_VALIDATION`, sujeto a congelar D-001/D-002/D-003/D-009/D-014
antes de ejecutar OOS. No prueba edge, rentabilidad, fills reales ni aptitud live.
