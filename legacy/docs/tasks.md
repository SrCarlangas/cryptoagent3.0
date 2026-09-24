# Tasks — Definición y validación teórica del agente BTC

## Supuestos declarados

- El loop trabaja sólo en documentos y análisis. No implementa trading,
  configuración, infraestructura ni credenciales.
- No abre conexiones autenticadas, no envía órdenes y no inicia testnet, paper o
  live trading. Puede consultar fuentes primarias, teoría y datos conceptuales.
- Alcance provisional: BTC/USDT Spot, `LONG`/`FLAT`, una posición y cero leverage.
- La solución es greenfield: Sensor, Calidad, Custodio de Estado, Modelo
  Temporal, Modelo de Costos, Política, Gobernador, Máquina de Decisión, Ledger y
  Validador se derivan del objetivo, no de componentes o flujos existentes.
- Las políticas candidatas se generan desde primeros principios y ninguna se
  etiqueta como edge sin validación OOS futura.
- La integración con cualquier plataforma queda fuera hasta congelar y validar el
  concepto.
- La definición puede terminar en `READY_FOR_OFFLINE_VALIDATION`, `PIVOT` o
  `NO_GO`. Forzar aprobación constituye fallo del ciclo.

## Contrato operativo del loop

1. Elegir el **único siguiente paso de mayor leverage** que no dependa de una tarea
   pendiente y ejecutarlo por completo.
2. Usar `[ ]` pendiente, `[~]` en curso, `[x]` hecho y `[B]` bloqueado.
3. Al cerrar una tarea, añadir debajo una nota breve con fecha, evidencia y rutas.
4. No marcar `[x]` por haber escrito texto: debe cumplirse el criterio verificable.
5. Registrar una ambigüedad en el decision log. Si es reversible, avanzar con un
   supuesto explícito; si cambia riesgo/mercado, publicar el bloqueador una sola
   vez y detenerse.
6. No bajar umbrales, borrar hallazgos negativos ni reinterpretar costos para que
   la hipótesis apruebe.
7. No empezar implementación. Las propuestas de código pertenecen a una fase
   posterior y separada, tras aprobación humana.
8. Cuando se cumpla el gate final, registrar el veredicto, crear
   `.kiro/btc-agent-goal/STOP` y terminar; no inventar tareas adicionales.

## Fase 0 — Base de verdad

- [x] T0.0 Confirmar la ruta del repositorio y que los tres documentos de control
      pueden crearse sin sobrescribir el objetivo previo de visualización.
      → 2026-09-15: workspace conceptual confirmado en
        `/Users/carlosrojas/Oracle/cryptoagent3.0`; no se requiere código para la
        etapa de ideación y validación teórica.
- [x] T0.1 Releer las capturas/análisis y crear una tabla `OBSERVADO / AMBIGUO /
      NO MOSTRADO`; incluir temporalidad, MA60, volumen, spread, profundidad,
      orden, posición, balance y regla manual.
      **Verificación:** cada afirmación visual tiene nivel de certeza; no se
      infiere una regla de trading desde la UI.
      → 2026-09-15, ciclo 1: evidencia consolidada en
        `docs/btc-decision-agent-spec.md`. Se separaron tres tablas con certeza y
        tratamiento seguro; se excluyó la captura de KiroCrew y no se derivó una
        señal de entrada/salida. Las ambigüedades se convirtieron en decisiones
        explícitas para el diseño greenfield.
- [x] T0.2 Definir desde primeros principios la frontera y arquitectura
      conceptual: qué observa, valida, transforma, propone, bloquea, decide y
      explica el sistema.
      **Verificación:** cada responsabilidad tiene input, output y fallo seguro;
      la solución se entiende sin nombres ni restricciones heredadas.
      → 2026-09-15, corrección de alcance: arquitectura greenfield materializada en
        `docs/btc-decision-agent-spec.md` con responsabilidades, contratos
        neutrales, flujo conceptual e invariantes. No se inspeccionó código.
- [x] T0.3 Definir el objetivo medible del agente, sus principios de diseño y
      las condiciones que falsarían la propuesta antes de elegir políticas.
      **Verificación:** cada objetivo tiene métrica conceptual, dirección deseada,
      límite y evidencia futura requerida; no depende de resultados heredados.
      → 2026-09-15, ciclo 3: añadida a `docs/btc-decision-agent-spec.md` una
        jerarquía G0–G4, función conceptual de utilidad, scorecard O1–O14, tipos de
        gate, 12 principios y falsación separada `ARCH_FAIL` / `POLICY_FAIL` /
        `NO_GO`. Ninguna política concreta fue favorecida.
- [x] T0.4 Crear `docs/btc-decision-agent-decision-log.md` con plantilla: ID,
      pregunta, opciones, supuesto actual, evidencia, impacto, dueño y estado.
      **Verificación:** toda ambigüedad de P0/P1 aparece allí.
      → 2026-09-15, ciclo 4: creado decision log con 12 registros (3 P0, 7 P1,
        2 P2), estados gobernados, historial, triggers y matriz de cobertura. Las
        decisiones humanas permanecen `OPEN_HUMAN`; no se convirtieron en defaults.
- [x] T0.5 Revisar y cerrar la matriz
      `NECESIDAD / RESPONSABILIDAD / INPUT / OUTPUT / FALLO` de la arquitectura.
      **Verificación:** cubre todo el objetivo sin tecnología, componente heredado
      ni responsabilidad huérfana.
      → 2026-09-15, ciclo 5: auditoría T0.5 encontró dos gaps críticos y añadió
        Custodio de Estado + Modelo de Costos independientes. Matriz: 11/11
        necesidades y 11/11 artefactos cubiertos, 0 huérfanos, 0 blockers. Fase 0
        cerrada `PASS_CONDITIONAL` con D-001–D-003 simbólicos y visibles.

## Fase 1 — Contrato funcional

- [x] T1.1 Definir objetivo, usuario, horizonte, símbolo, mercado y límites del
      agente; separar recomendación, autorización y ejecución.
      **Verificación:** el agente no puede autorizarse a sí mismo.
      → 2026-09-15, ciclo 6: contrato funcional añadido a
        `docs/btc-decision-agent-spec.md`: actor, inputs, triggers estratégico y
        protector, separación de cinco etapas, tres acciones, FR-001…FR-018 y ocho
        escenarios. D-001–D-003 siguen simbólicas; ejecución permanece fuera.
- [x] T1.2 Escribir glosario canónico con unidades y UTC para precio, bid/ask,
      spread, kline, feature, señal, decisión, posición, orden y fill.
      **Verificación:** cada término tiene una sola definición.
      → 2026-09-15, ciclo 7: glosario normativo añadido a
        `docs/btc-decision-agent-spec.md`: UTC/RFC3339, seis instantes/reglas de
        cierre, 16 magnitudes con unidad, 49 términos, 11 expresiones prohibidas e
        invariantes. `observed_at` queda canónico; `ingest_time` es alias prohibido.
- [x] T1.3 Formalizar estados `FLAT`, `ENTRY_CANDIDATE`, `LONG`,
      `EXIT_CANDIDATE`, `COOLDOWN`, más `DEGRADED/BLOCKED` si corresponde.
      **Verificación:** tabla completa de transición, guarda, acción y estado
      siguiente; transiciones prohibidas explícitas.
      → 2026-09-15, ciclo 8: máquina jerárquica añadida a la especificación con
        tres dimensiones (Position/Evaluation/Health), 10 configuraciones válidas,
        precedencia, SM-001…SM-031, 15 prohibiciones y siete casos de frontera.
- [x] T1.4 Definir contratos de `ENTER_LONG`, `HOLD`, `EXIT_LONG`: campos,
      prioridad, vigencia, razones y posición objetivo.
      **Verificación:** mismos inputs/estado/version producen idéntica decisión.
      → 2026-09-15, ciclo 9: envelope `Decision` con 23 campos, TargetPosition,
        seis clases de prioridad, taxonomía de reasons, guardas/vigencia por acción,
        invalidación, serialización canónica e identidad SHA-256 determinista.
- [x] T1.5 Clasificar decisiones abiertas P0/P1/P2: Spot vs derivados, long-only,
      horizonte, cierre de vela, tipos de orden, riesgo y objetivo de evaluación.
      **Verificación:** defaults provisionales están rotulados, no ocultos.
      → 2026-09-15, ciclo 10: decision log ampliado a D-001…D-013 y matriz de
        defaults/gates; 3 P0 abiertas, 8 P1 gobernadas y 2 P2 diferidas, todas con
        dueño y límite. CP-01 centraliza supuestos; Fase 1 `PASS_CONDITIONAL`.

## Fase 2 — Datos y features

- [x] T2.1 Documentar con fuente oficial los contratos de kline, `bookTicker`,
      aggregate trades, depth snapshot/diffs, 24h ticker y `exchangeInfo`.
      **Verificación:** tabla con fuente, campos usados, frecuencia, unidad,
      límites y requisito de autenticación; market data público no usa secretos.
      → 2026-09-15, ciclo 11: documentación oficial Binance Spot versionada en la
        especificación; S-01…S-09 cubren WS/REST, campos, unidades, update speed,
        weights, filtros, auth `NONE`, criticidad y fallos seguros. Sin conexiones.
- [x] T2.2 Diseñar esquema canónico de eventos con `event_time`, `observed_at`,
      secuencia, símbolo, precision, provenance y schema version.
      **Verificación:** incluye ejemplo válido, duplicado, tardío y fuera de orden.
      → 2026-09-15, ciclo 12: `MarketEventV1` añadido con envelope, ocho event
        types, identidad SHA-256, sequence/watermark, pipeline de 12 pasos y casos
        V-01/D-01/L-01/O-01. Late/out-of-order no reescriben Decisions pasadas.
- [x] T2.3 Especificar sincronización de depth: snapshot, sequence IDs, gaps,
      resync, reconexión y heartbeat.
      **Verificación:** cualquier gap lleva a estado degradado; nunca a entrada.
      → 2026-09-15, ciclo 13: máquina `BookSyncState` con ocho estados,
        generación atómica, algoritmo bootstrap/incremental, L2-001…L2-023,
        revocación por gap, reconnect/heartbeat/backoff y seis ejemplos.
- [x] T2.4 Definir política de cierre de vela y staleness por tipo de dato.
      **Verificación:** ninguna regla estratégica lee una vela abierta como si
      estuviera cerrada y `null`/stale tiene salida definida.
      → 2026-09-15, ciclo 14: `FreshnessPolicy`, estados FRESH/SUSPECT/STALE/
        MISSING/NOT_REQUIRED, reglas S-01…S-09, BarLifecycle, watermarks, null/zero,
        recuperación y FRSH-01…FRSH-12. D-014 registra budgets pendientes.
- [x] T2.5 Formalizar features mínimas con fórmula y unidad: SMA/pendiente,
      volumen relativo, ATR/volatilidad, spread bps, costo/slippage estimado e
      imbalance persistente.
      **Verificación:** cálculo manual de cada feature sobre un ejemplo pequeño.
      → 2026-09-15, ciclo 15: registro F-001…F-012 con `FeatureValue`, fórmulas,
        unidades, guards/nulls y parámetros pendientes. Ejemplo sintético calcula
        SMA/slope/volumen/ATR/volatilidad/spread/VWAP/costo/imbalance/persistencia.
- [x] T2.6 Justificar features excluidas y el rol limitado del libro.
      **Verificación:** documenta spoofing, fugacidad, costos y contraejemplos
      independientes posteriores al freeze; un imbalance aislado no dispara
      `ENTER_LONG`.
      → 2026-09-15, ciclo 16: AG-001…AG-010, catálogo de admisión/exclusión,
        10 mecanismos + CE-L2-01…10 y ruta de reapertura. D-007 `DECIDED`: L2 es
        filtro de costo/liquidez y diagnóstico, nunca trigger autónomo.

## Fase 3 — Hipótesis de decisión

- [x] T3.1 Definir la política nula `HOLD` como control de seguridad y costo de
      oportunidad explícito.
      **Verificación:** produce una salida válida para todo estado sin inventar
      oportunidad ni exposición.
      → 2026-09-15, ciclo 17: `POL-000-NULL-HOLD` formalizada con output único
        `NO_INTENT`, tabla total de estados, invariantes, baselines cash/long,
        DeltaU, regret pareado, NULL-01…12 y siete condiciones de fallo.
- [x] T3.2 Generar al menos tres políticas candidatas desde mecanismos distintos
      —tendencia, reversión y ruptura u otras justificadas— bajo el mismo contrato.
      **Verificación:** cada una declara mecanismo causal, inputs, invalidación y
      condiciones de fallo sin afirmar superioridad.
      → 2026-09-15, ciclo 18: `POL-101` trend-pullback, `POL-102` reversion
        escalada por ATR y `POL-103` breakout tras compresión; contrato común,
        setup states, predicates simbólicos, invalidaciones, fallos y PC-01…12.
- [x] T3.3 Comparar políticas en tabla: datos, horizonte, turnover, costos, régimen
      favorable, failure modes, complejidad y evidencia futura requerida.
      **Verificación:** shortlist conceptual o `PIVOT` con criterio pre-registrado.
      → 2026-09-15, ciclo 19: rúbrica lexicográfica G0–G4/AG-001…10, matrices de
        datos/costo/régimen/muestra y D-015. POL-101 primary sólo para formalización;
        POL-102/103 challengers, 0 winner y 0 evidencia empírica usada.
- [x] T3.4 Escribir pseudocódigo total de entrada/abstención/salida/cooldown.
      **Verificación:** no contiene “alto”, “fuerte”, “suficiente” ni otra palabra
      sin definición operativa.
      → 2026-09-15, ciclo 20: `evaluate_POL101` total con setup state, inputs/output,
        19 parámetros simbólicos, reasons exhaustivos, predicados puros, entry/exit,
        cooldown advisory, expiración e idempotencia; P101-T01…T21.
- [x] T3.5 Crear registro de parámetros: nombre, unidad, dominio, provisional,
      racional, sensibilidad y calibración futura train-only.
      **Verificación:** ningún parámetro se elige mirando resultados OOS.
- [x] T3.6 Definir precedencia: reconciliación → circuit breaker/stop/salida de
      riesgo → bloqueo sistémico → salida estratégica → entrada → hold.
      **Verificación:** no hay dos acciones incompatibles para un mismo evento.
- [x] T3.7 Ejecutar auditoría temporal y de leakage sobre cada condición.
      **Verificación:** tabla input → disponibilidad temporal → permitido/prohibido.

## Fase 4 — Riesgo y ejecución teórica

- [x] T4.1 Formalizar tamaño de posición y exposición máxima con ecuaciones,
      unidades y límites; separar capital, risk budget y notional.
      **Verificación:** resultado está acotado para volatilidad cero/extrema y
      capital insuficiente.
- [x] T4.2 Definir stop inicial, trailing opcional, time stop, cooldown, pérdida
      diaria y drawdown sin asumir que una orden siempre llena.
      **Verificación:** prioridad y comportamiento ante gap/fill parcial definidos.
- [x] T4.3 Formalizar el contrato del `RiskMandate` y del Gobernador de Riesgo.
      **Verificación:** límites provienen de autoridad humana versionada; mandato
      ausente, incierto o bloqueado impide entrada.
- [x] T4.4 Especificar invariantes ante posición desconocida, restart, duplicado,
      retraso, rechazo, cancelación y desincronización exchange/local.
      **Verificación:** cada fallo tiene detección, estado seguro y recuperación.
- [x] T4.5 Definir modelo futuro de paper fills para Market y Limit: fee, spread,
      slippage, latencia, fill parcial, cancelación y adverse selection.
      **Verificación:** no presupone fill al mid ni fill completo gratuito.
- [x] T4.6 Derivar costo round-trip y movimiento de break-even con margen de
      seguridad.
      **Verificación:** ejemplo numérico recalculable; si edge bruto ≤ costo total,
      el veredicto de esa hipótesis es `NO_GO`.
- [x] T4.7 Crear tabla de controles preventivos, detectivos y reactivos.
      **Verificación:** toda pérdida no acotada queda como fallo crítico.

## Fase 5 — Obligaciones de prueba teórica

- [x] T5.1 Crear `docs/btc-decision-agent-theoretical-validation.md` con matriz de
      obligaciones: totalidad, determinismo, causalidad, idempotencia, safety,
      staleness, reconciliación, costos y auditabilidad.
      **Verificación:** cada obligación tiene método, evidencia y PASS/FAIL.
- [x] T5.2 Construir mínimo 15 escenarios deterministas: entrada válida, sin
      volumen, vela abierta, spread alto, feed stale, gap de secuencia, whipsaw,
      spoofing, volatilidad extrema, duplicado, restart, posición desconocida,
      risk blocked, stop y salida normal.
      **Verificación:** input completo, estado inicial, salida y razón esperada.
- [x] T5.3 Resolver mínimo 3 ejemplos numéricos completos: entrada aceptada,
      entrada rechazada por costo/riesgo y salida prioritaria.
      **Verificación:** un tercero puede reproducir cada resultado a mano.
- [x] T5.4 Probar fronteras para cada umbral: igual, epsilon inferior/superior,
      cero, máximo, `null`, NaN y timestamp fuera de orden.
      **Verificación:** no hay comparación ambigua ni división no definida.
- [x] T5.5 Ejecutar FMEA de feed, features, decisión, bus, riesgo, persistencia y
      ejecución futura.
      **Verificación:** severidad, ocurrencia, detección, mitigación y residual.
- [x] T5.6 Red-team de hipótesis con cambio de régimen, gaps, flash move, spoofing,
      baja liquidez, fee tier peor y slippage adverso.
      **Verificación:** hallazgos cambian regla/veredicto o tienen mitigación.
- [x] T5.7 Congelar las hipótesis y luego contrastarlas con evidencia externa,
      priors de mercado y resultados adversos disponibles.
      **Verificación:** la evidencia puede refutar o degradar la candidata, pero no
      reescribir retroactivamente su mecanismo o gate.
- [x] T5.8 Emitir resumen PASS/FAIL y lista de evidencia empírica pendiente.
      **Verificación:** PASS teórico no se describe como edge ni como live-ready.

## Fase 6 — Arquitectura conceptual greenfield

- [x] T6.1 Completar contratos tecnológicos neutrales para Sensor, Guardia,
      Custodio, Modelo Temporal, Modelo de Costos, Política, Gobernador, Máquina,
      Ledger y Validador.
      **Verificación:** cada contrato define datos, unidades, estados y errores.
- [x] T6.2 Diseñar `Decision` versionada: identidad, symbol, event/data time,
      expiración, transición, acción, razones, evidencia, calidad, política y
      mandato de riesgo.
      **Verificación:** soporta idempotencia, expiración y replay determinista sin
      imponer transporte o almacenamiento.
- [x] T6.3 Crear diagramas conceptuales: normal, stale/resync, duplicado, restart y
      salida protectora.
      **Verificación:** la Política nunca ejecuta ni evade al Gobernador.
- [x] T6.4 Definir evidencia mínima de MarketContext, intent, risk verdict,
      decisión y outcome para auditoría, sin elegir persistencia.
      **Verificación:** un tercero puede reconstruir por qué se decidió.
- [x] T6.5 Diseñar el camino futuro por gates: pruebas → replay → walk-forward con
      purga/embargo → shadow → paper → revisión humana.
      **Verificación:** live está fuera y cualquier integración es posterior.
- [x] T6.6 Pre-registrar el gate empírico futuro: métricas OOS, costos, drawdown,
      PBO, estabilidad, tamaño de muestra y reglas de rechazo.
      **Verificación:** ningún umbral puede moverse después de ver resultados.

## Fase 7 — Revisión adversarial

- [x] T7.1 Revisión cuantitativa independiente del texto: leakage, snooping,
      sample size, turnover, costos y falsabilidad.
      **Verificación:** hallazgos y respuesta registrados, no sólo “reviewed”.
- [x] T7.2 Revisión de riesgo: exposición, gaps, stops, circuito, recovery y peor
      caso.
      **Verificación:** cero pérdidas no acotadas aceptadas silenciosamente.
- [x] T7.3 Revisión arquitectónica: ownership de estado, idempotencia, contratos,
      resiliencia y observabilidad.
      **Verificación:** cero caminos que permitan a una Política ejecutar o evadir
      al Gobernador de Riesgo.
- [x] T7.4 Revisión de producto: utilidad de `ENTER/HOLD/EXIT`, explicabilidad y
      decisiones que aún pertenecen al usuario.
      **Verificación:** P0/P1 tienen resolución o bloqueador/dueño explícito.
- [x] T7.5 Resolver contradicciones cruzadas entre los seis documentos.
      **Verificación:** búsqueda terminológica y matriz de trazabilidad sin gaps.

## Fase 8 — Gate final y cierre

- [x] T8.1 Completar matriz requisito → diseño → riesgo → prueba → evidencia.
- [x] T8.2 Verificar uno por uno los criterios de aceptación de `north_star.md` y
      enlazar evidencia; no marcar por intuición.
- [x] T8.3 Emitir exactamente un veredicto con justificación:
      `READY_FOR_OFFLINE_VALIDATION`, `PIVOT` o `NO_GO`.
- [x] T8.4 Enumerar qué puede hacerse después y qué sigue prohibido; incluir que
      no hay promesa de beneficio ni autorización live.
- [x] T8.5 Releer y pulir glosario, unidades, timestamps, estados, parámetros y
      enlaces en todos los documentos.
- [x] T8.6 Registrar aquí el veredicto final y crear `.kiro/btc-agent-goal/STOP`.
      **Verificación:** el archivo existe sólo después de cerrar T8.1–T8.5.

## Checklist inequívoco de “definición prolija y probada teóricamente”

- [x] Reglas completas y deterministas, sin lenguaje operacional vago.
- [x] Datos causales, sincronizados, versionados y con política de staleness.
- [x] Riesgo, sizing, costos y estados de fallo formalizados y acotados.
- [x] ≥15 escenarios, ≥3 cálculos numéricos y pruebas de frontera completos.
- [x] Contraejemplos y FMEA sin fallos críticos abiertos.
- [x] Arquitectura greenfield completa, neutral y sin bypass de riesgo.
- [x] Plan empírico futuro conserva gate, costos, purga y embargo.
- [x] Supuestos y decisiones humanas visibles; cero credenciales.
- [x] Veredicto honesto; no confunde teoría, backtest, paper y live.
- [x] Consistencia cruzada de los seis documentos demostrada.

## Bloqueadores

_Ninguno activo._

### B-001 — Cerrado por corrección de alcance (2026-09-15)

- El blocker surgió al intentar exigir código e integración durante una ideación.
- El usuario aclaró que busca una solución conceptual nueva desde el objetivo.
- Resolución: el workspace documental es suficiente; T0.2 se redefinió y cerró
  como arquitectura greenfield. No queda decisión humana pendiente por B-001.

## Bitácora del loop

### 2026-09-15 — Inicialización

- Creados `north_star.md`, `roadmap.md` y `tasks.md` en la raíz del repositorio.
- Alcance fijado a definición y validación teórica; implementación y trading fuera.
- Primera tarea pendiente de mayor leverage: **T0.1**.

### 2026-09-15 — Ciclo 1

- Cerrada **T0.1** con evidencia visual clasificada y límites de inferencia.
- Sin blocker: las decisiones desconocidas quedaron explícitas, no asumidas.
- La dirección originalmente propuesta para T0.2 quedó supersedida por la
  corrección greenfield del usuario.

### 2026-09-15 — Ciclo 2

- T0.2 se bloqueó bajo el supuesto equivocado de que la ideación debía copiar un
  flujo implementado; B-001 quedó registrado y posteriormente cerrado.
- La corrección del usuario redefine el trabajo como solución conceptual nueva.

### 2026-09-15 — Corrección greenfield del usuario

- Mandato explícito: no contaminar la solución con el flujo real o arquitectura
  heredada; diseñar desde el objetivo y primeros principios.
- Actualizados North Star, roadmap, especificación y cola; **B-001 cerrado**.
- **T0.2 cerrada** con arquitectura conceptual y contratos neutrales en
  `docs/btc-decision-agent-spec.md`.
- Siguiente paso de mayor leverage: **T0.3**, definir objetivos medibles,
  principios y condiciones de falsación antes de elegir políticas.

### 2026-09-15 — Ciclo 3

- Cerrada **T0.3**: el éxito ya no significa “predecir siempre”, sino decidir de
  forma causal, segura, única, explicable y neta de costos, con `HOLD` como control.
- Congelados hard gates de tolerancia cero; límites humanos y gates empíricos
  permanecen explícitamente pendientes de pre-registro.
- Sin blocker. Siguiente paso: **T0.4**, crear el decision log y trasladar allí
  todas las decisiones P0/P1 sin resolverlas por inferencia.

### 2026-09-15 — Ciclo 4

- Cerrada **T0.4** con `docs/btc-decision-agent-decision-log.md`.
- Toda ambigüedad P0/P1 tiene ID, opciones, supuesto, evidencia, impacto, dueño,
  estado, límite temporal y trigger de revisión.
- D-004 preserva el mandato greenfield como decisión explícita; D-001–D-003 siguen
  abiertos al usuario sin bloquear la arquitectura simbólica.
- Sin blocker. Siguiente paso: **T0.5**, revisar la matriz de responsabilidades y
  cerrar formalmente la Fase 0.

### 2026-09-15 — Ciclo 5

- Cerrada **T0.5** mediante auditoría de cobertura; no fue una autoaprobación.
- Resueltos F0-01 (estado sin dueño) y F0-02 (costos controlados por la Política)
  añadiendo Custodio de Estado y Modelo de Costos independientes.
- Fase 0: **`PASS_CONDITIONAL`** — 11/11 necesidades, 11/11 artefactos, cero
  huérfanos, cero dependencias heredadas y cero blockers activos.
- Siguiente paso: **T1.1**, definir el contrato funcional de objetivo, actor,
  horizonte simbólico, mercado provisional y separación decisión/riesgo/ejecución.

### 2026-09-15 — Ciclo 6

- Cerrada **T1.1** con contrato funcional greenfield y verificable.
- Recomendación (`CandidateIntent`), autorización (`RiskVerdict`), decisión
  (`Decision`), evidencia (`DecisionRecord`) y ejecución futura son artefactos y
  responsabilidades diferentes.
- `BLOCKED` queda como status de `HOLD`, no como cuarta acción; protección puede
  preemptar estrategia pero nunca abrir posición.
- Sin blocker. Siguiente paso: **T1.2**, glosario canónico, unidades y UTC.

### 2026-09-15 — Ciclo 7

- Cerrada **T1.2** con glosario, unidades, tiempo UTC e invariantes semánticos.
- Separados inequívocamente Feature → CandidateIntent → RiskVerdict → Decision →
  Order → Fill → Position; “entrada/salida” sin etapa queda prohibido.
- `event_time`, `observed_at`, `decision_time` y `expires_at` ya no son aliases.
- Sin blocker. Siguiente paso: **T1.3**, máquina de estados y transiciones.

### 2026-09-15 — Ciclo 8

- Cerrada **T1.3** con máquina de estados jerárquica y determinista.
- Candidate, Decision, pending y posición confirmada quedan separados: una
  Decision nunca convierte por sí sola `FLAT↔LONG`.
- Eventos concurrentes siguen precedencia; schema desconocido bloquea en vez de
  ocultarse como self-loop; `DEGRADED/BLOCKED` nunca permite entrada.
- Sin blocker. Siguiente paso: **T1.4**, contrato de `ENTER_LONG`, `HOLD` y
  `EXIT_LONG` con campos, prioridad, vigencia, razones y posición objetivo.

### 2026-09-15 — Ciclo 9

- Cerrada **T1.4** con contratos normativos de las tres acciones.
- `target_position` expresa objetivo económico, no posición confirmada ni orden.
- Prioridad, vigencia, supersession, razones e identidad son deterministas; una
  Decision obsoleta o duplicada nunca es consumible.
- Sin blocker. Siguiente paso: **T1.5**, revisar y clasificar decisiones abiertas
  P0/P1/P2, sus defaults provisionales y gates de resolución.

### 2026-09-15 — Ciclo 10

- Cerrada **T1.5** y, con ella, la Fase 1 en `PASS_CONDITIONAL`.
- Las 13 decisiones tienen prioridad, estado, dueño, etiqueta y gate temporal;
  defaults ocultos = 0. D-013 fija G0–G4 + `HOLD` antes de evaluar políticas.
- CP-01 permite ejemplos estructurales, pero no es configuración aprobada.
- Sin blocker. Siguiente paso: **T2.1**, contratos conceptuales de fuentes de
  mercado usando documentación primaria, sin implementar conexiones.

### 2026-09-15 — Ciclo 11

- Cerrada **T2.1** con contratos oficiales de nueve fuentes públicas Binance Spot.
- Registradas limitaciones decisivas: bookTicker sin event_time, ticker de ventana
  móvil (no día UTC), depth snapshot máximo 5000 y filtros/rate limits dinámicos.
- Todas las fuentes son `NONE`; no se usaron ni almacenaron credenciales.
- Sin blocker. Siguiente paso: **T2.2**, schema canónico con ejemplos válido,
  duplicado, tardío y fuera de orden.

### 2026-09-15 — Ciclo 12

- Cerrada **T2.2** con schema canónico inmutable y provider-neutral.
- `event_time` representa el hecho; `provider_emitted_at` la emisión y
  `observed_at` la recepción. observed_at no participa en identidad.
- Duplicate, late, out-of-order, collision, gap y schema desconocido tienen
  semántica y fallo seguro distintos.
- Sin blocker. Siguiente paso: **T2.3**, sincronización de depth snapshot/diffs,
  estados de resync y ejemplos de secuencia.

### 2026-09-15 — Ciclo 13

- Cerrada **T2.3** con sincronización L2 completa y fail-safe.
- Snapshot+diffs se publican sólo mediante generation swap atómico; qty=0 elimina
  nivel y cada update reemplaza cantidad absoluta.
- Un gap revoca la vista, invalida dependencias y nunca usa imbalance viejo como
  fallback ni dispara entrada.
- Sin blocker. Siguiente paso: **T2.4**, política de cierre de vela, freshness,
  staleness, lateness y heartbeat por tipo de dato.

### 2026-09-15 — Ciclo 14

- Cerrada **T2.4** con política de freshness por fuente y uso.
- Barra estratégica sólo es usable en `FINAL`; `FORMING`, stale, null y silencio
  sin continuidad nunca se reinterpretan como evidencia válida.
- D-014 evita inventar budgets mientras D-002 siga abierta; budget ausente bloquea.
- Sin blocker. Siguiente paso: **T2.5**, fórmulas/unidades de features mínimas y
  cálculo manual reproducible.

### 2026-09-15 — Ciclo 15

- Cerrada **T2.5** con doce features descriptivas, no señales.
- Cada feature declara fórmula, unidad, ventana, fuentes, quality y null_reason;
  costo desconocido, depth insuficiente y denominador cero nunca se vuelven 0.
- El ejemplo es `EXAMPLE_ONLY`; no fija parámetros ni recomienda una acción.
- Sin blocker. Siguiente paso: **T2.6**, justificar features excluidas y cerrar el
  rol del order book antes del gate de Fase 2.

### 2026-09-15 — Ciclo 16

- Cerrada **T2.6** y la Fase 2 en **`PASS_CONDITIONAL`**.
- AG-001…10 gobierna admisión; forming bars/leakage/indicator zoo no entran por
  popularidad. D-007 fija L2 como costo/veto/diagnóstico, no dirección.
- Contratos: 9 fuentes, 8 event types, 12 features, 0 triggers L2 autónomos.
- D-002, D-008 y D-014 siguen visibles antes del freeze/OOS; no bloquean ideación.
- Sin blocker. Siguiente paso: **T3.1**, política nula `HOLD` y costo de oportunidad.

### 2026-09-15 — Ciclo 17

- Cerrada **T3.1** con control nulo determinista y sin parámetros.
- `NULL_HOLD` nunca crea intent/exposición, pero tampoco impide exits protectores
  del sistema; cash y keep-position se comparan desde el mismo estado inicial.
- Opportunity regret es diagnóstico ex post y jamás feature o label retroactivo.
- Sin blocker. Siguiente paso: **T3.2**, generar al menos tres policies candidatas
  de mecanismos distintos bajo el mismo contrato y sin elegir ganadora.

### 2026-09-15 — Ciclo 18

- Cerrada **T3.2** con tres candidatas `CANDIDATE_UNVALIDATED`.
- Trend, reversion y breakout parten de mecanismos, setups, invalidaciones y
  failure modes diferentes; ninguna se rankeó ni recibió parámetros numéricos.
- D-010 queda `DECIDED` para la shortlist, no para un ganador.
- Sin blocker. Siguiente paso: **T3.3**, comparación conceptual bajo criterios
  predefinidos de datos, turnover, costos, régimen, complejidad y falsabilidad.

### 2026-09-15 — Ciclo 19

- Cerrada **T3.3** con comparación conceptual pre-empírica.
- POL-101 avanza como `PRIMARY_FOR_THEORETICAL_FORMALIZATION`; no se declara edge
  ni winner. POL-102/POL-103 siguen como challengers bajo igualdad experimental.
- D-015 registra criterios y triggers; un cambio después de OOS exige ronda nueva.
- Sin blocker. Siguiente paso: **T3.4**, pseudocódigo total de POL-101 para
  entrada, abstención, salida, cooldown, expiración y fallos.

### 2026-09-15 — Ciclo 20

- Cerrada **T3.4** con pseudocódigo total de POL-101.
- Invalidación precede confirmación; entry exige pullback armado en barra anterior,
  resume, volumen, costo y estado sanos. Exit sigue time→trend→anchor.
- Policy sólo aconseja cooldown; Máquina conserva ownership de estados/prioridades.
- Sin blocker. Siguiente paso: **T3.5**, registro de parámetros con dominio,
  racional, sensibilidad, dependencias y calibración train-only.

## Cierre integrado — todas las fases

| Tareas | Evidencia | Resultado |
|---|---|---|
| T3.5–T3.7 | Registro de 19 parámetros, precedencia P0→P5 y auditoría temporal en spec | PASS_CONDITIONAL |
| T4.1–T4.7 | Sizing, stops, RiskMandate, fallos, fills, break-even y controles en spec | PASS_CONDITIONAL |
| T5.1–T5.8 | `docs/btc-decision-agent-theoretical-validation.md`: 9 obligaciones, 24 escenarios, 3 numéricos, 20 fronteras, 14 FMEA, 10 red-team | PASS_TEORICO_CONDICIONAL |
| T6.1–T6.6 | Contratos neutrales, replay, diagramas, evidencia y gate OOS en spec | PASS_CONDITIONAL |
| T7.1–T7.5 | Revisiones quant/risk/arquitectura/producto y contradicciones resueltas | PASS |
| T8.1–T8.6 | Trazabilidad, aceptación, veredicto, límites, pulido y STOPs | PASS |

### Veredicto final

**`READY_FOR_OFFLINE_VALIDATION`**

Significa: la definición y validación teórica habilitaron la implementación
fixture-first offline. ADR-0002 congeló D-001/D-002/D-003/D-009/D-011/D-014, pero
no autoriza OOS ejecutado y no existe dataset histórico versionado. No significa
edge, rentabilidad, paper/testnet/live readiness ni autorización de órdenes.

### Artefactos

- `/Users/carlosrojas/Oracle/cryptoagent3.0/docs/btc-decision-agent-spec.md`
- `/Users/carlosrojas/Oracle/cryptoagent3.0/docs/btc-decision-agent-theoretical-validation.md`
- `/Users/carlosrojas/Oracle/cryptoagent3.0/docs/btc-decision-agent-decision-log.md`

### STOPs creados

- `/Users/carlosrojas/Oracle/cryptoagent3.0/.kiro/btc-agent-goal/STOP`
- `/Users/carlosrojas/.kiro/crew/workspace/.stop-chat-4-1789498603`

### 2026-09-15 — Cierre final

- Fases 0–8 cerradas; tareas pendientes: 0; blockers críticos: 0.
- Precedencia corregida: reconciliación P0 antes de stop/breaker P1.
- Gap risk declarado; bajo CP-01 Spot long-only la exposición total queda acotada
  por `max_exposure`; otros productos reabren D-001.
- Auto-nudge detenido deliberadamente; no se generará trabajo de relleno.
