# North Star — Agente de decisión BTC explicable y validable

## Supuestos declarados

1. Este ciclo define y prueba **teóricamente** la idea; no implementa código de
   producción, no conecta una cuenta y no envía órdenes reales ni simuladas.
2. El alcance provisional es BTC/USDT Spot, una sola posición, `LONG`/`FLAT`, sin
   apalancamiento. Cambiar a Margin, Futures o `SHORT` obliga a revisar todo el
   modelo de riesgo y no se hará por inferencia silenciosa.
3. Las capturas de Binance son evidencia de los datos observados por el usuario,
   no una especificación de su estrategia manual. La temporalidad y los
   disparadores exactos siguen abiertos.
4. La fuente objetivo son las interfaces oficiales de Binance (WebSocket/REST),
   nunca lectura visual de la aplicación ni automatización de clics.
5. La solución se diseña **greenfield y desde primeros principios**. No hereda
   estrategias, clases, eventos, límites ni decisiones arquitectónicas de otro
   CryptoAgent. Las hipótesis se generan y comparan bajo un contrato común.
6. “Validada teóricamente” significa lógica completa, causal, consistente,
   falsable, acotada por riesgo y sometida a casos normales/adversos. **No**
   significa rentable, aprobada para producción ni validada estadísticamente.
7. Código, resultados o restricciones de sistemas previos sólo pueden usarse
   después de congelar el concepto, como evidencia adversarial o insumo de una
   futura integración; nunca como punto de partida de la ideación.

## Problema que se quiere resolver

El operador observa precio, MA60, volumen, estadísticas de 24 horas, spread,
libro y profundidad de BTC/USDT, pero las capturas no expresan una regla
repetible de entrada/salida. Para convertir esa observación en un agente hacen
falta contratos temporales precisos, una función de decisión determinista,
gestión de riesgo, costos de ejecución, manejo de datos defectuosos y una
arquitectura conceptual que se sostenga por sí misma.

La ideación debe partir del objetivo —observar, comprender el estado de mercado y
decidir de forma segura—, no de cómo otro sistema resolvió el problema. Tampoco
debe fabricar un ganador: una solución greenfield puede terminar en `PIVOT` o
`NO_GO` si sus hipótesis no son coherentes o falsables.

## Visión final

Tener una **especificación lista para validación empírica offline** de un agente
que siga BTC/USDT en tiempo real, mantenga un estado de mercado confiable y emita
una de tres decisiones:

- `ENTER_LONG`: proponer pasar de `FLAT` a `LONG`.
- `HOLD`: conservar el estado; es la decisión por defecto.
- `EXIT_LONG`: proponer pasar de `LONG` a `FLAT`.

Cada decisión debe ser reproducible con los mismos datos, incluir las razones y
valores que la originaron, tener vigencia limitada y quedar subordinada a un
**Gobernador de Riesgo conceptual** independiente. La política propone; el
gobernador autoriza o bloquea; ninguna política puede evadir ese límite.

## Resultado observable esperado

Al terminar el ciclo, una persona nueva en el proyecto debe poder responder sin
interpretaciones libres:

1. Qué datos consume el agente, con qué frecuencia y cómo detecta datos viejos,
   duplicados, incompletos o fuera de secuencia.
2. En qué instante puede decidir y qué significa una vela “cerrada”.
3. Qué condiciones exactas producen `ENTER_LONG`, `HOLD` y `EXIT_LONG`.
4. Cómo se calcula el tamaño, stop, expiración y pérdida máxima permitida.
5. Qué sucede ante spread alto, slippage, desconexión, reinicio, orden duplicada,
   posición desconocida o circuit breaker activo.
6. Cómo se separan sensor, calidad, custodio de estado, modelo temporal,
   modelo de costos, política, gobernador, máquina, ledger y validador, sin
   imponer tecnología.
7. Qué afirmaciones fueron demostradas teóricamente, cuáles requieren backtest o
   paper trading y cuáles siguen siendo decisiones humanas.
8. Por qué el veredicto final es `READY_FOR_OFFLINE_VALIDATION`, `PIVOT` o
   `NO_GO`, sin confundir una definición prolija con rentabilidad.

## Frontera funcional objetivo

```text
Mercado → Sensor → Guardia ─┬→ Modelo Temporal
                              └→ Modelo de Costos
Cuenta/posición → Custodio de Estado
Mandato humano → ProductMandate + RiskMandate

Contexto + estado + costo
        ↓
Política de Oportunidad → Gobernador de Riesgo
        ↓
Máquina de Decisión ENTER_LONG / HOLD / EXIT_LONG
        ↓
Ledger explicable → Validador Teórico
```

La especificación termina antes de implementar el adaptador, la estrategia o el
Paper Executor.

## Invariantes no negociables

- **Causalidad:** una decisión sólo usa información disponible en su timestamp;
  no hay look-ahead ni velas aún abiertas para disparadores estratégicos.
- **Abstención segura:** datos insuficientes, obsoletos o incoherentes producen
  `HOLD`/bloqueo de entradas, nunca una señal inventada.
- **Riesgo primero:** ninguna entrada atraviesa un Gobernador de Riesgo ausente,
  incierto o bloqueado. La política no puede aumentar límites por sí misma.
- **Idempotencia:** el mismo evento/`trace_id` no puede originar dos órdenes.
- **Estado reconciliado:** una posición desconocida impide nuevas entradas.
- **Costos completos:** comisión, spread, slippage y fills parciales forman parte
  de toda hipótesis; un edge bruto menor al costo total es `NO_GO`.
- **Libro prudente:** imbalance/depth instantáneos no equivalen a intención real;
  deben tratarse como datos manipulables y efímeros.
- **Auditabilidad:** cada decisión conserva versión de estrategia, inputs,
  razones, timestamps, calidad de datos y regla aplicada.
- **Secretos fuera del diseño:** no se escriben claves, tokens ni credenciales.
- **Promoción manual:** ningún resultado de este ciclo habilita trading real.

## Artefactos finales del ciclo

Además de mantener coherentes `north_star.md`, `roadmap.md` y `tasks.md`, el ciclo
debe producir:

1. `docs/btc-decision-agent-spec.md`: contrato funcional y técnico completo.
2. `docs/btc-decision-agent-theoretical-validation.md`: obligaciones de prueba,
   casos, cálculos, contraejemplos y veredicto.
3. `docs/btc-decision-agent-decision-log.md`: supuestos, decisiones, alternativas,
   evidencia y asuntos que requieren al usuario.

## Qué significa “definición prolija”

- Glosario único; términos, unidades y zonas horarias no se contradicen.
- Reglas expresadas como tablas, fórmulas o pseudocódigo determinista; no quedan
  frases como “volumen alto”, “tendencia fuerte” o “spread razonable” sin método.
- Todo parámetro tiene unidad, dominio, valor provisional, fuente y mecanismo de
  calibración sin contaminar el conjunto de prueba.
- Hay trazabilidad requisito → regla → riesgo → caso teórico → componente.
- Se separan claramente hechos existentes, hipótesis, decisiones humanas y
  trabajo empírico futuro.
- Los tres documentos de control y los tres artefactos finales no se contradicen.

## Qué significa “probada teóricamente”

La definición sólo supera esta etapa si cumple todas estas obligaciones:

1. **Totalidad:** cada combinación relevante de estado y calidad de datos termina
   en una decisión definida.
2. **Determinismo:** mismos inputs, estado y versión producen la misma salida.
3. **Consistencia temporal:** timestamps, cierre de velas y ventanas no permiten
   usar futuro ni mezclar muestras desalineadas.
4. **Seguridad acotada:** exposición y pérdida teórica tienen cotas explícitas;
   stops y circuit breakers no dependen de una interpretación humana.
5. **Viabilidad de costos:** existe ecuación de break-even y cualquier hipótesis
   incompatible con costos se descarta.
6. **Casos reproducibles:** ejemplos numéricos y tabla de escenarios cubren
   entrada, abstención, salida, desconexión, duplicados y extremos.
7. **Contraejemplos:** se intenta falsar cada regla con whipsaw, gap, spoofing,
   baja liquidez, volatilidad extrema y cambio de régimen.
8. **Independencia arquitectónica:** cada responsabilidad tiene límites y
   contratos conceptuales propios; ninguna depende de una implementación previa.
9. **Falsabilidad empírica:** queda definido el protocolo futuro de replay,
   walk-forward con purga/embargo y costos, sin ejecutarlo ni rebajar el gate.
10. **Veredicto honesto:** las contradicciones críticas causan `PIVOT` o `NO_GO`;
    no se ajusta el criterio para aprobar la idea.

## Criterios de aceptación

- [x] Los tres artefactos finales existen, están enlazados y pasaron revisión de
      consistencia terminológica y temporal.
- [x] El contrato de datos cubre klines, `bookTicker`, trades, depth, estadísticas
      24h, metadatos del símbolo, reconexión, secuencias y staleness.
- [x] La máquina de estados y la tabla de decisión definen todas las transiciones,
      guardas, prioridades y expiraciones.
- [x] Entrada, salida, sizing y stops están formalizados sin umbrales vagos.
- [x] La arquitectura admite y compara al menos tres políticas conceptuales
      bajo el mismo contrato; ninguna se presenta como edge probado.
- [x] El modelo de costos y ejecución incluye comisión, spread, slippage, fill
      parcial y latencia; contiene cálculo de break-even.
- [x] Los invariantes de riesgo tienen al menos un caso positivo y uno negativo.
- [x] Hay una matriz de mínimo 15 escenarios y mínimo 3 ejemplos numéricos
      trazables que cualquiera puede recalcular.
- [x] El mapa conceptual separa responsabilidades, entradas, salidas y fallos
      sin nombres ni restricciones de una implementación heredada.
- [x] El plan empírico futuro pre-registra antes de medir sus umbrales OOS,
      costos, drawdown, PBO, estabilidad y tamaño de muestra; no permite moverlos
      después de observar resultados.
- [x] No quedan contradicciones críticas ni decisiones P0/P1 ocultas.
- [x] El veredicto final declara límites: no asegura beneficio y no autoriza live.

## Fuera de alcance

- Implementar feeds, estrategia, base de datos, UI o executor.
- Adaptar el concepto a clases, eventos o infraestructura de un sistema previo.
- Modificar límites de riesgo o configuración de producción.
- Crear, almacenar o probar credenciales.
- Enviar órdenes, incluso en testnet o paper, durante este ciclo documental.
- Optimizar parámetros contra un periodo conocido o rebajar el acceptance gate.
- Diseñar market making de baja latencia, Futures, Margin, short o apalancamiento.

## Definición de terminado

El ciclo termina cuando todos los criterios de aceptación tienen evidencia en los
artefactos finales y se emite uno de estos veredictos:

- `READY_FOR_OFFLINE_VALIDATION`: definición coherente y teóricamente validada;
  puede comenzar una fase separada de implementación/replay offline.
- `PIVOT`: la idea contiene valor, pero debe cambiar estrategia, datos o alcance.
- `NO_GO`: contradice el objetivo, costos, riesgo o coherencia interna.

Un `PIVOT` o `NO_GO` bien demostrado también es éxito. Al terminar, el loop debe
registrar el veredicto en `tasks.md` y crear `.kiro/btc-agent-goal/STOP`; no debe
seguir generando trabajo para consumir ciclos.

## Estado final del objetivo

**Veredicto: `READY_FOR_OFFLINE_VALIDATION` (2026-09-15).**

La definición greenfield y la validación teórica están completas. Esto autoriza
únicamente implementación y replay fixture-first offline. D-001, D-002, D-003,
D-009, D-011 y D-014 están congeladas por ADR-0002; esto no autoriza OOS ejecutado
y no existe dataset histórico versionado. No hay claim de edge, rentabilidad,
paper/testnet/live readiness ni autorización de órdenes.

Evidencia principal:

- `docs/btc-decision-agent-spec.md`
- `docs/btc-decision-agent-theoretical-validation.md`
- `docs/btc-decision-agent-decision-log.md`
