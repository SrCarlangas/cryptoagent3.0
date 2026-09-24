# Roadmap — De capturas de Binance a definición validable del agente BTC

## Estado final

Fases 0–8 cerradas el 2026-09-15. Veredicto: `READY_FOR_OFFLINE_VALIDATION`.
La siguiente fase permitida es continuar pruebas/replay fixture-first offline.
D-001/D-002/D-003/D-009/D-011/D-014 ya están congeladas por ADR-0002, pero OOS no
se ejecuta en esta entrega y no existe dataset histórico versionado. Red, paper,
testnet, live e integración de cuenta siguen fuera de alcance.

## Supuestos declarados

- Este roadmap gobierna una fase documental y de razonamiento; no autoriza
  implementación, despliegue, testnet, paper trading ni órdenes reales.
- Se parte de BTC/USDT Spot, `LONG`/`FLAT`, sin apalancamiento, como alcance
  reversible para definir el sistema. Toda ampliación se registra como decisión.
- La regla manual exacta del usuario no está documentada. Las políticas
  candidatas se generarán desde primeros principios y se compararán bajo un
  contrato común; ninguna arquitectura o estrategia previa será el default.
- “Éxito” de este roadmap es una especificación lista para validación empírica
  offline o un `PIVOT`/`NO_GO` fundamentado; nunca una promesa de rentabilidad.
- Los criterios de falsación y riesgo se pre-registran antes de evaluar las
  ideas y no se debilitan para hacer encajar una candidata.

## Reglas de avance

1. Trabajar una sola tarea de mayor leverage por iteración y actualizar
   `tasks.md` con evidencia concreta.
2. No avanzar de fase si su gate de salida tiene una contradicción crítica.
3. Toda ambigüedad se clasifica como supuesto reversible, decisión humana o
   bloqueador; no se resuelve en silencio.
4. Las conclusiones deben derivarse de supuestos explícitos, fuentes primarias o
   cálculos reproducibles. Una opinión sin evidencia no cierra una tarea.
5. Si una hipótesis falla, registrar el fallo y pivotar; no ajustar el gate.

## Fase 0 — Base de verdad y alcance real

**Objetivo:** separar lo observado, lo que ya existe y lo que aún es hipótesis.

- Releer el análisis de las capturas y registrar datos visibles, ilegibles y no
  inferibles: temporalidad seleccionada, orden usada, posición, balance y regla.
- Definir desde el objetivo la frontera greenfield: qué observa, qué transforma,
  qué decide, qué bloquea y qué explica el sistema.
- Formular principios de diseño, invariantes y preguntas humanas sin consultar
  clases, eventos o restricciones de una implementación previa.
- Construir una matriz `NECESIDAD / RESPONSABILIDAD / INPUT / OUTPUT / FALLO`.
- Abrir el decision log con supuestos, evidencia y preguntas humanas.

**Salida:** sección “Current state” y arquitectura conceptual en la especificación.

**Gate:** la solución puede explicarse sin mencionar componentes heredados; las
limitaciones de las capturas y los límites del sistema están explícitos.

## Fase 1 — Contrato de producto y lenguaje común

**Objetivo:** precisar qué decisión toma el agente y qué no controla.

- Definir actor, objetivo, horizonte, símbolo, mercado y estados permitidos.
- Crear glosario de precio, bid/ask, spread, vela cerrada, posición, señal,
  decisión, autorización de riesgo, orden y fill.
- Definir `ENTER_LONG`, `HOLD`, `EXIT_LONG`, vigencia, prioridad y razones.
- Formalizar la máquina de estados y las transiciones prohibidas.
- Separar decisión estratégica, autorización de riesgo y ejecución.
- Clasificar las decisiones abiertas P0/P1/P2 y asignar default sólo cuando sea
  seguro, reversible y visible.

**Salida:** contrato funcional y máquina de estados en
`docs/btc-decision-agent-spec.md`.

**Gate:** dos lectores distintos obtendrían la misma decisión ante el mismo caso;
no quedan verbos vagos ni responsabilidades superpuestas.

## Fase 2 — Contrato de datos en tiempo real

**Objetivo:** definir una fuente reproducible y una política de calidad segura.

- Documentar streams oficiales requeridos: kline, `bookTicker`, aggregate trades,
  depth; y REST para snapshot, 24h ticker y metadatos del símbolo.
- Especificar timestamps, UTC, intervalos, cierre de vela, secuencias, deduplicado,
  reconexión, backfill, heartbeats y límites de staleness.
- Definir esquema canónico, unidades, precisión, provenance y reglas de descarte.
- Definir features causales mínimas: SMA/pendiente, volumen relativo, ATR o
  volatilidad, spread, slippage estimado e imbalance persistente.
- Documentar por qué una captura instantánea o imbalance aislado no es señal.

**Salida:** contrato fuente → evento → feature → decisión, con ejemplos válidos e
inválidos.

**Gate:** todo dato tiene fuente, frecuencia, unidad, freshness y conducta de
fallo; ningún feature usa información futura.

## Fase 3 — Hipótesis y lógica de entrada/salida

**Objetivo:** convertir intuiciones en reglas deterministas y falsables.

- Definir una política nula (`HOLD`) como control de seguridad.
- Generar al menos tres políticas candidatas desde mecanismos distintos, por
  ejemplo tendencia, reversión y ruptura, sin elegir ganadora de antemano.
- Decidir para cada candidata si volumen, spread o depth son señal, filtro o dato
  excluido, con justificación causal.
- Escribir pseudocódigo completo de entrada, abstención, salida y cooldown.
- Crear registro de parámetros: unidad, dominio, valor provisional, racional,
  sensibilidad y método futuro de calibración.
- Establecer prioridad entre salida por riesgo, stop, reversión y expiración.
- Auditar look-ahead, data snooping y dependencia de vela abierta.

**Salida:** tabla de decisión y comparación `CONTROL / CANDIDATA / DESCARTADA`.

**Gate:** para cualquier estado e inputs definidos existe exactamente una salida;
los umbrales pueden variar sin cambiar la semántica de la regla.

## Fase 4 — Riesgo y ejecución teórica

**Objetivo:** demostrar que una señal no puede convertirse en exposición no
acotada.

- Formalizar sizing, exposición máxima, stop inicial, trailing opcional, pérdida
  diaria, drawdown, cooldown y circuit breakers.
- Definir el contrato conceptual del Gobernador de Riesgo y límites humanos
  requeridos, sin adoptar defaults de otra implementación.
- Especificar conducta ante feed viejo, posición desconocida, restart, eventos
  duplicados, fill parcial, rechazo y estado desincronizado.
- Definir modelo futuro de paper fills para Market/Limit sin elegir aún ejecución
  real: comisión, spread, slippage, latencia y probabilidad de fill.
- Derivar ecuación de costo round-trip y movimiento mínimo de break-even.
- Modelar stops protectores del exchange sólo como requisito de una futura fase
  live, nunca como acción de este ciclo.

**Salida:** sección de riesgo, tabla de invariantes y modelo de costos.

**Gate:** toda trayectoria tiene exposición y pérdida teóricas acotadas, o se
clasifica explícitamente como no acotable/`NO_GO`.

## Fase 5 — Prueba teórica y falsación

**Objetivo:** intentar romper la definición antes de escribir código.

- Crear obligaciones de prueba para totalidad, determinismo, causalidad,
  idempotencia, seguridad, freshness y reconciliación.
- Construir al menos 15 escenarios: entrada válida, falta de volumen, vela
  abierta, spread alto, feed viejo, gap, whipsaw, spoofing, volatilidad extrema,
  duplicado, restart, posición desconocida, circuit breaker, stop y salida normal.
- Resolver al menos 3 ejemplos numéricos completos y recalculables.
- Ejecutar análisis dimensional y de fronteras (`=`, justo por debajo/encima,
  cero, máximo, `null`, timestamp fuera de orden).
- Calcular break-even teórico y descartar hipótesis cuyo movimiento esperado no
  pueda superar costos con margen conservador.
- Hacer FMEA: severidad, probabilidad, detectabilidad, mitigación y riesgo residual.
- Intentar falsar cada conclusión con cambios de régimen, costos, ruido y
  evidencia externa sólo después de congelar la hipótesis conceptual.

**Salida:** `docs/btc-decision-agent-theoretical-validation.md` con evidencia y
resultado PASS/FAIL por obligación.

**Gate:** cero fallos críticos abiertos; toda obligación tiene evidencia o causa
un `PIVOT`/`NO_GO`. “Parece razonable” no cuenta como PASS.

## Fase 6 — Arquitectura conceptual greenfield

**Objetivo:** cerrar una arquitectura tecnológica y organizacionalmente neutral.

- Definir responsabilidades y contratos de Sensor, Guardia de Calidad, Custodio
  de Estado, Modelo Temporal, Modelo de Costos, Política, Gobernador, Máquina de
  Decisión, Ledger y Validador.
- Definir un contrato versionado de decisión con identidad, timestamps, vigencia,
  transición, razones, inputs, calidad y versión de política.
- Precisar qué evidencia debe conservarse para replay y auditoría, sin elegir base
  de datos, bus o framework.
- Demostrar que la Política no puede saltarse el Gobernador de Riesgo ni mutar sus
  propios límites.
- Diseñar una secuencia futura separada: pruebas → replay → walk-forward → shadow
  → paper → revisión humana. Live queda fuera.
- Dejar cualquier adaptación a CryptoAgent u otra plataforma como fase posterior
  al veredicto conceptual.

**Salida:** diagramas conceptuales, matriz responsabilidad-contrato y protocolo de
implementación futuro dentro de la especificación.

**Gate:** cada responsabilidad tiene dueño, inputs, outputs y fallos sin depender
de componentes, nombres o decisiones heredadas.

## Fase 7 — Revisión adversarial y decisión

**Objetivo:** someter el paquete completo a crítica cuantitativa, de riesgo y de
arquitectura.

- Revisión cuantitativa: falsabilidad, leakage, overfitting, costos y gate OOS.
- Revisión de riesgo: gaps, stops, sizing, fallos operativos y pérdidas no acotadas.
- Revisión de arquitectura: contratos, estados, resiliencia y observabilidad.
- Revisión de producto: decisión útil, explicación comprensible y asuntos humanos.
- Resolver contradicciones o degradar el veredicto; no ocultarlas como “futuro”.
- Emitir `READY_FOR_OFFLINE_VALIDATION`, `PIVOT` o `NO_GO` con razones.

**Salida:** decision log cerrado y veredicto trazable.

**Gate:** no quedan P0/P1 sin dueño, ni afirmaciones de rentabilidad o autorización
live.

## Fase 8 — Pulido, trazabilidad y cierre del loop

**Objetivo:** dejar una definición prolija que otro equipo pueda implementar sin
reinterpretarla.

- Uniformar glosario, símbolos, unidades, estados, nombres y enlaces.
- Crear matriz requisito → diseño → riesgo → prueba → evidencia.
- Releer los seis documentos de principio a fin y eliminar contradicciones.
- Marcar uno por uno los criterios de `north_star.md` con evidencia.
- Registrar veredicto y próximos pasos permitidos/prohibidos en `tasks.md`.
- Crear `.kiro/btc-agent-goal/STOP` cuando el gate final esté satisfecho.

**Salida:** paquete documental final y loop detenido deliberadamente.

**Gate final:** se cumple la definición de terminado de `north_star.md`; si sólo
queda una decisión humana bloqueante, se publica una vez y se detiene el loop, sin
relleno ni ciclos artificiales.
