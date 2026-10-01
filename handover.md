# Handover: agente LLM de exposición BTC/USDT

Documento de entrega. Escrito para que quien lo recoja no repita las semanas que ya se
gastaron. Lo más valioso que hay aquí son los resultados **negativos**: están medidos, y
tres de ellos refutan hipótesis que parecían obvias.

Fecha de corte: 1 de octubre de 2026. Repo `SrCarlangas/cryptoagent3.0`, rama `main`,
37 commits, 480 pruebas en verde, ruff y mypy limpios.

---

## 1. Qué se está construyendo

Un agente que decide la **exposición** de una cuenta BTC/USDT en Binance DEMO: si el
capital debe estar en BTC (`INVERTIDO`) o en USDT (`EN LIQUIDEZ`), y con cuánto.

La autoridad de órdenes la tiene un LLM local (`qwen3:30b-a3b` vía Ollama) corriendo en un
servidor propio. Decide cada 30 minutos. No elige números: elige una **dirección** y una
**postura** cualitativa (DEFENSIVA / NEUTRAL / AGRESIVA), y todas las magnitudes (tamaño,
stop, arrastre, horizonte) se derivan de la volatilidad medida y de límites fijados de
antemano por régimen de mercado.

Esa separación es deliberada y viene de un fallo observado: en una decisión el modelo
declaró un movimiento esperado de **+35.31%** a pocos días. No sabe estimar magnitudes.

### Arquitectura, capas de decisión (la más estricta primero)

```
1. cortacircuitos (pérdida diaria, drawdown)     -> puede forzar SALIDA, nunca una entrada
2. stop protector en el exchange                 -> puede forzar SALIDA
3. calidad del dato                              -> se abstiene si la evidencia no es fiable
4. suficiencia de percepción                     -> se abstiene sin 200 cierres diarios
5. EL AGENTE LLM                                 -> decide la exposición
6. portero economico + cadencia                  -> actuar debe cubrir su coste
```

Si el LLM no responde, cae a una política numérica validada (`RegimeMixturePolicy`) que
**solo puede cerrar, nunca abrir**. Esa asimetría viene de un fallo real: el stop saltó a
las 11:23, el LLM deliberó y eligió liquidez con 0.70 de convicción, y 34 minutos después
un reinicio borró el veredicto en memoria y el fallback volvió a comprar. Una decisión
deliberada de estar en efectivo fue revertida por un reinicio.

### Ficheros que importan

| Fichero | Líneas | Qué hace |
|---|---|---|
| `src/.../realtime_demo.py` | 1860 | Motor protector, stops, estado persistente, runner que coloca órdenes |
| `src/.../llm_agent.py` | 1020 | Prompt, cliente Ollama, `LLMAgentEngine`, portero de coste |
| `src/.../regime_playbook.py` | 978 | Estrategia por régimen, `resolve_plan`, mezcla, corroboración |
| `src/.../llm_memory.py` | 492 | Registro de decisiones y resultados medidos (SQLite) |
| `research/backtest_llm_agent.py` | — | El backtest. **Una decisión = una llamada al LLM.** |
| `scripts/gate_llm_agent.py` | — | Criterios pre-registrados que deciden si opera |

---

## 2. La hipótesis inicial, y en qué quedó

**Hipótesis:** un LLM con contexto de mercado estructurado, análogos históricos y su propio
historial medido puede decidir *cuándo* estar expuesto a BTC mejor que una política
numérica o que comprar y mantener.

**En qué quedó: refutada en la parte de "cuándo".**

Medición directa, sobre tres corridas independientes de la ventana alcista. Correlación
entre la exposición que el agente **de verdad** tuvo y el movimiento del precio en ese
mismo intervalo:

```
  override (playbook 1.2)   +0.01
  autoridad plena           +0.02
  mezcla por tamaño         -0.11

  46 intervalos utilizables -> error estandar 0.15 -> nada dentro de +-0.29 se distingue de cero
```

Las tres están en cero. **El agente no tiene ventaja de momento.** Su exposición es
independiente de lo que el precio hizo después.

Esto no es una sorpresa aislada: confirma lo que este proyecto ya había establecido tres
veces antes de que existiera el agente LLM. De veinte pares de señal y horizonte medidos
en muestras no solapadas, ninguno alcanzó un error estándar. El LLM no se escapa de ese
hallazgo.

**Lo que sí quedó en pie:** el agente preserva capital. Es el único efecto que ha
replicado en todos los estudios de este proyecto, y replica aquí también.

---

## 3. Estado actual, los dos números que definen el problema

```
VENTANA ALCISTA  (dias 1260-1560, 300 dias, 60 decisiones, paso 5d)
  agente               +53.08%   dd 17.7%   captura 29%
  cuantitativo        +132.06%   dd 19.5%
  comprar y mantener  +184.44%   dd 20.0%
  GATE: RECHAZADO  (falla captura vs b&h, captura vs cuantitativo, preservacion)

VENTANA BAJISTA  (dias 2150-2450, 300 dias, 60 decisiones, paso 5d)
  agente                -2.39%   dd  6.1%   expuesto solo 9% del tiempo
  cuantitativo         -12.50%
  comprar y mantener   -12.86%   dd 39.5%
  GATE: APROBADO 8/8
```

**El problema en una frase:** gana claramente cuando el mercado cae, porque se queda
fuera, y captura solo un tercio cuando sube, porque no sabe distinguir los tramos buenos
de los malos.

Y una advertencia sobre el gate que quien reciba esto debe entender: contra una referencia
**a la baja** el criterio es "no perder más", que es fácil. Contra una referencia **al
alza** exige capturar la mitad. Así que la ventana bajista es fácil de aprobar y la
alcista es difícil. El APROBADO de arriba no es simétrico al RECHAZADO.

---

## 4. Los ocho defectos estructurales encontrados

**Todos tienen la misma forma: un parámetro o una doctrina declara una intención y nada la
implementa.** Las 202 pruebas de entonces pasaban en verde durante toda la vida de cada
uno. Este patrón es el hallazgo metodológico más reutilizable del documento.

| # | Defecto | Efecto medido |
|---|---|---|
| 1 | `ExecutionPlan.apply()` no sustituía `break_even_*`. Toda posición 0.5% en verde se cerraba al primer retroceso de 0.25% | Ventana alcista −15.82% → +13.21%. Stops de 10 → 5 |
| 2 | El backtest llenaba al cierre de d+1 pero evaluaba el stop desde las barras de d: 48h de precios **anteriores a la entrada** | 11 de 12 salidas por stop eran fantasma |
| 3 | El arrastre se medía en volatilidad **diaria** mientras cada régimen declara un horizonte. 2.8σ no es lo mismo en 24h que en 168h | Stops 19 → 7. Horas con posición 50.6% → 81.0% |
| 4 | El riesgo era un tercer mando para dos grados de libertad. Techo fijo contra stop que escala con la volatilidad → recortaba la posición justo cuando la volatilidad se expandía | Pisó la asignación declarada en 11 de 60 decisiones. Día 1550: pedía 75%, daba 35% |
| 5 | `horizon_hours` decía en su docstring que gobernaba el plazo de evaluación. Nada lo leía: todo se juzgaba a 24h, incluidas decisiones de 168h | El agente leía ese historial en su prompt. Ruta directa de una medición mal hecha a la cautela sistemática |
| 6 | El escalado de posición existía en el backtest y **no** en producción | 22.5pp sobre la ventana alcista. Todo lo medido describía un sistema no desplegado |
| 7 | Un fallo del modelo no consumía la cadencia: bucle de reintentos | 30 decisiones de fallback en 5 minutos, martilleando un Ollama ya saturado |
| 8 | El régimen 3 se llama "tendencia alcista establecida" y se lleva el 90% del capital, concedido sobre una etiqueta sin corroborar | 8 etiquetas r3 con el precio **6.4% por debajo** de su media de 200d = −10.39% (efecto 1.3), tres cuartos de la pérdida bajista |

El #8 es el más instructivo y el último encontrado. La corrección no toca ninguna
asignación: exige que el precio esté del lado que la doctrina del régimen nombra, y si no,
usa la estrategia prudente del lado donde el precio realmente está. Ventana bajista
−13.90% → **−2.39%**.

### Cómo encontrar el noveno

El procedimiento que funcionó, y que recomiendo repetir:

1. Coger cada campo de `RegimeStrategy` y `RealtimeParams` y preguntar **quién lo lee**.
   `grep` el nombre. Si solo aparece en su propia definición, en el `to_dict` y en una
   prueba que lo construye, no hace nada.
2. Coger cada afirmación de un docstring que diga "esto gobierna X" y verificar que X
   lo lee.
3. Coger cada doctrina en prosa (`RegimeStrategy.doctrine`) y comprobar que la condición
   que describe se cumple cuando se concede la estrategia.

---

## 5. Las iteraciones que NO funcionaron

Esta sección existe para que no se vuelvan a intentar. Cada una costó entre 3 y 9 horas de
GPU.

### 5.1 Tres políticas de exposición, indistinguibles

```
  override del playbook (el regimen puede revertir al agente)   +63.60%   dd 16.1%
  autoridad plena (el agente decide y nada lo revierte)         +59.51%   dd 17.9%
  mezcla por tamano (el desacuerdo mueve el tamano)             +53.08%   dd 17.7%
```

10.5 puntos sobre 60 decisiones, una ventana, una pasada, contra una referencia que hizo
+184%. **Elegir la mejor de tres desde dentro de su propio rango es ajustar a la muestra.**

Y hay una trampa dentro: el override **costó** 39 puntos sobre un agente cauteloso y
**ganó** 30 sobre un agente confiado. El signo de la regla depende del comportamiento del
agente, no de la regla. Ninguna respuesta generaliza.

### 5.2 La herramienta de réplica engaña sobre reglas de decisión

`research/counterfactual.py` reejecuta decisiones grabadas contra reglas distintas en
segundos en vez de horas. Para reglas de **ejecución** acertó: los defectos 1, 3 y 4 se
encontraron ahí y se reprodujeron en corridas reales. Para **política de exposición** falló
dos veces por ~40 puntos:

```
  quitar el override      replica +99.70%   corrida real +59.51%
  mezclar el desacuerdo   replica +99.48%   corrida real +53.08%
```

La razón es estructural. Una regla de exposición cambia la posición que el agente tiene al
decidir → cambia lo que decide → cambia lo que se escribe en su memoria → cambia las
estadísticas que lee en el prompt siguiente. Congelar las decisiones elimina justo la
realimentación por la que actúa el cambio.

**Está documentado dentro del propio fichero.** Úsalo para ejecución, nunca para decisión.

### 5.3 Un cambio de prompt destruyó la discriminación

Se le dijo al agente *"el tamaño ya es la prudencia, tu trabajo es acertar la dirección,
no administrar el riesgo"*. Verdad del mecanismo, mala instrucción:

```
                   antes                    despues
  conviccion       9 valores distintos      3 valores (46/60 en 0.85)
  postura          DEF 15 / NEU 27 / AGR 18 AGR 46 de 60
```

La postura y la convicción son **lo único** que el playbook lee para dimensionar. Si las
dos se colapsan, el tamaño se vuelve constante y la modulación por régimen deja de
existir. Ya revertido.

**Lección:** cualquier cambio de prompt debe ir seguido de `research/agent_calibration.py`
para comprobar que el agente sigue usando el rango.

### 5.4 Hipótesis refutadas por medición

- **"El stop protector destruye el retorno."** Quitarlo empeora la ventana bajista
  (−10.05% contra −2.96%). Lo que movía el resultado era el **tamaño**.
- **"La histéresis de régimen causa los stops."** 7 de 10 salidas por stop ocurrieron sin
  ningún cambio de régimen.
- **"Los rangos globales de postura están mal calibrados."** La postura responde
  limpiamente: convicción 0.497/0.538/0.730 y precio 1.32x/1.48x/2.02x.
- **"La cadencia gruesa del backtest castiga al agente."** Reentrar 1h después de un stop
  en vez de esperar la siguiente decisión cambia +23.23% → +23.44%. Nada.

---

## 6. Mecanismos de prueba

### 6.1 El gate pre-registrado — `scripts/gate_llm_agent.py`

Los criterios se escriben y comitean **antes** de leer el resultado. Sale 0 solo si pasan
todos. Lo que deliberadamente **no** exige es batir a comprar y mantener.

```
  fallos del modelo             <= 5%
  decisiones                    >= 50
  minoria de exposicion         >= 5%     (un agente constante no necesita un LLM)
  cambios de DIRECCION          <= 30%
  comision pagada               <= 6% del capital
  ventaja en drawdown vs b&h    >= 3pp
  captura de un b&h al alza     >= 50%    (a la baja: basta no perder mas)
  captura del cuantitativo      >= 75%    (a la baja: basta no perder mas)
```

Dos cosas que debes saber antes de tocarlo:

- Los dos últimos criterios **se cambiaron de forma después de ver un resultado**, por
  decisión del dueño. Antes eran déficits en puntos porcentuales absolutos, lo que hacía
  el mismo criterio trivial contra una referencia de −12.86% e imposible contra una de
  +184.44%. El cambio fue de la **forma** del instrumento, no del umbral, y está escrito
  en el fichero con las razones y con los valores retirados.
- Un criterio que no se puede evaluar **falla**, no pasa. Si un informe no mide la
  comisión, ese criterio sale en rojo. Este proyecto tuvo una métrica que decía
  `blocked_by_cost=79` cuando el valor real era 0, y la lección quedó.

### 6.2 El backtest — `research/backtest_llm_agent.py`

Una decisión = una llamada al LLM = 130-180 segundos. Una corrida de 60 decisiones cuesta
**~2.8 horas**. Esto domina todo el ritmo de trabajo.

Fidelidad conseguida, con sangre:

- Los stops se evalúan contra **mínimos horarios** reales, no cierres diarios. El dataset
  es horario (58.769 barras, 24/día, con high/low). Al cambiarlo, el drawdown de una
  prueba pasó de 1.01% a 3.07%.
- El marcado empieza en **d+2** porque la orden se llena al cierre de d+1 (defecto #2).
- Usa las **mismas funciones** que producción: `resolve_plan`, `plan_adjustment`,
  `clears_cost_static`, `ProtectiveDecisionEngine.active_stop`. Replicar con reglas
  distintas mide un sistema que no existe.
- Índice histórico con **purga y embargo**: un corte `before_day` ingenuo dejaba filas cuya
  ventana de 90 días hacia adelante cruzaba el día de la decisión. Fuga de futuro real,
  encontrada y corregida.

Sesgo que **queda** y no se puede netear: el agente decide cada 5 días en el backtest y
cada 30 minutos en producción, así que un stop temprano lo deja en liquidez el resto del
intervalo. Medido con reentrada forzada, vale ~2.7 puntos y el signo depende de la ventana.

### 6.3 Herramientas de diagnóstico

Todas en `research/`, todas sin GPU, todas sobre trazas archivadas.

| Herramienta | Para qué | Hallazgo que produjo |
|---|---|---|
| `capture_decomposition.py` | Despeja la exposición **real** del camino del equity y la correlaciona con el movimiento | **Timing = 0.** El hallazgo central |
| `counterfactual.py` | Reejecuta decisiones contra otras reglas de ejecución en segundos | Defectos 1, 3, 4 |
| `regime_corroboration.py` | ¿La etiqueta cuadra con la condición que su doctrina nombra? | Defecto 8 |
| `regime_attribution.py` | Beneficio y pérdida por régimen, con efecto en errores estándar | Localizó la pérdida bajista en r3 |
| `agent_calibration.py` | Distribución de convicción, movimiento esperado y postura | El colapso de discriminación (5.3) |
| `churn_source.py` | ¿Quién genera cada viaje de ida y vuelta, el agente o el playbook? | 9 de 15 cambios los imponía el playbook |
| `exposure_gap.py` | Dónde se pierde la exposición entre el plan y el libro | El tope de riesgo pisando la asignación |
| `show_trace.py` | Una línea por decisión: qué pidió, qué se ejecutó, por qué | Verificación de punta a punta |
| `compare_runs.py` | Corridas archivadas lado a lado, con el rango visible | Que las tres políticas son ruido |

**La herramienta más importante es `capture_decomposition.py`** y debí usarla el primer
día. Despeja la exposición efectiva invirtiendo el camino del equity:

```
f = (equity_ratio - 1) / (price_ratio - 1)
```

Eso es lo que el libro **hizo**, stops incluidos, en vez de la cuota registrada, que se
mide en la decisión y no dice nada del intervalo siguiente. La diferencia no es cosmética:
la cuota registrada decía 66-82% invertido y la exposición efectiva era 53-61%.

### 6.4 Protocolo anti-sobreajuste

- **Ventana de desarrollo:** días 1260-1560 (alcista, b&h +184%).
- **Ventana de control:** días 2150-2450 (bajista, b&h −12.86%).
- **Holdout declarado de antemano y NUNCA examinado: días 960-1260.** Sigue intacto.
  Úsalo una vez, para el veredicto, no para iterar.
- Las corridas se archivan inmutables en `data/validation/runs/` con `chmod 444`. Esto
  existe porque se **perdió** una traza de 100 decisiones al sobrescribirla con una prueba
  de humo.
- Iterar sobre **defectos**, no sobre parámetros. La distinción operativa que emergió:
  las correcciones justificadas por **coherencia interna** se reprodujeron en corridas
  reales; las elecciones de política optimizadas sobre una ventana no.

---

## 7. Los problemas que no se han resuelto

### 7.1 El central: no hay ventaja de momento

Medido en cero, tres veces. Y de ahí se sigue algo que conviene tener claro: **ninguna
política de exposición puede cerrar la brecha**, porque la política elige *cuándo* y
*cuándo* no lleva información. El único mando que sube la captura es subir la exposición, y
eso sube el drawdown.

Caminos que **no** se han explorado y que un modelo mejor preparado debería evaluar:

- **Horizonte.** Todo se ha medido a 5 días. Quizá la ventaja esté a 1 hora o a 30 días.
  El coste de una corrida ha impedido barrer horizontes.
- **Features.** El agente ve retornos, medias móviles y volatilidad. No ve libro de
  órdenes, flujo, financiación de perpetuos, ni nada on-chain. Si existe una ventaja, es
  más plausible que esté en un dato que el agente no tiene que en una política mejor sobre
  los datos que ya tiene.
- **La pregunta que se le hace.** Se le pide dirección. Quizá sepa responder mejor a
  "¿cuál es el riesgo de una caída del 20% en los próximos 7 días?", que es una pregunta
  sobre régimen y no sobre dirección, y donde los LLM suelen ser menos malos.
- **Un modelo mayor.** `qwen3:30b-a3b` es lo que cabe en 23 GB. No se ha probado si un
  modelo frontera tiene ventaja de momento donde este no la tiene. **Esta es la prueba
  más limpia y más baratamente decisiva que queda.**

### 7.2 Nunca se corrió la ventana alcista con las 8 correcciones

La mejor alcista (+53.08%) es **anterior** al defecto 8. Y el defecto 8 valía 11.5 puntos
en la bajista. Falta esa corrida y es lo primero que haría: 2.8 horas, sin escribir código.

### 7.3 El holdout sigue sin tocar

Deliberado. No se ha ganado el derecho a gastarlo.

### 7.4 El clasificador de régimen es inestable

La etiqueta cambia en el **37%** de las transiciones a paso de 5 días, y el 31% de las
transiciones invierte la exposición por defecto. Hay un `RegimeTracker` que exige
persistencia (el horizonte de la estrategia que se abandonaría) y la corroboración del
defecto 8, pero el clasificador de base sigue siendo ruidoso y nadie lo ha reentrenado ni
cuestionado en este ciclo.

### 7.5 r0 y r1 no aportan nada

Entre −2.9% y +4.8% con efecto ≤1.4. Son el 55-87% de los tramos. El propio playbook ya no
los opera por defecto, lo cual es correcto, pero significa que el sistema está inactivo la
mayor parte del tiempo.

### 7.6 Operativo

- El servidor tiene **23 GB** y el modelo ocupa 18.6 GB. **No caben el agente vivo y un
  backtest a la vez**: la máquina entra en swap y ambos se arrastran (prompt a 15 tokens/s).
  Hay que parar el agente para correr un backtest, y acordarse de volver a arrancarlo.
- El Mac del dueño tiene **17 GB libres de disco**, menos que el modelo. No es alternativa.
- Los avisos de Slack **funcionan** pero `SLACK_CHANNEL=U0BV2CJGM0E` es un **usuario**, no
  un canal, así que llegan como mensaje directo del bot `crybin` y aparecen en la sección
  **Apps** de Slack, no en Mensajes. El dueño no los encontraba. El token no tiene permiso
  (`missing_scope`) para listar ni unirse a canales, así que para usar un canal hay que
  invitar al bot manualmente y cambiar la variable.
- `chat.postMessage` devuelve **HTTP 200 incluso cuando falla**. Hay que parsear el cuerpo.
  Este proyecto creyó durante semanas que Slack funcionaba cuando nunca había entregado nada.

---

## 8. Trampas concretas que costaron tiempo

Cada una es una hora perdida o un número falso.

- **`pkill -f <patrón>` se auto-mata** por ssh. Usar el truco del corchete: `[b]acktest`.
- **Contar procesos con `pgrep` se cuenta a sí mismo.** `/proc/PID/exe` resuelve al python
  del sistema y es inútil; hay que comparar argv contra el intérprete del venv.
- **`LLM_AGENT_PAGE` es un string de Python.** Un `\n` dentro de un literal de JavaScript es
  un error de sintaxis que mata la página entera en silencio.
- **DDL de SQLite:** `CREATE TABLE IF NOT EXISTS` no hace nada sobre una tabla existente, así
  que una columna nueva necesita `ALTER TABLE`, y cualquier índice que la referencie debe ir
  **después**. Poner el índice en el DDL principal dejó al agente vivo en bucle de caídas con
  "no such column: posture", y ninguna prueba lo detectó porque todas construyen una base
  nueva.
- **Un script de handover con `sed`** casó dos barras invertidas donde el unit tenía una, y
  habría dejado al agente en dry-run con el cuantitativo desactivado. Nadie operando.
- **Valores por defecto silenciosos son la fuente número uno de números falsos.** Una
  herramienta rellenó campos ausentes con 95%/3%/2% y produjo cifras reales sobre una
  política que nunca corrió. Ahora falla de forma ruidosa. Pasó **dos veces** (planes y
  `agent_asked_for`).
- **Números idénticos entre variantes que deberían diferir son evidencia, no tranquilidad.**
  Así se descubrió que la mezcla no estaba conectada.

---

## 9. Infraestructura

```
servidor      ssh -i ~/llaves/ssh-key-2026-03-18.key ubuntu@157.137.231.201
produccion    /home/ubuntu/workplace/cryptoagent3.0   (NO es un repo git, se sincroniza por rsync)
modelo        qwen3:30b-a3b en Ollama (Docker), 18.6 GB
maquina       aarch64, 23 GB RAM, sin GPU

servicios     cryptoagent3-llm-agent        agente vivo, cadencia 30 min, autoridad de ordenes
              cryptoagent3-llm-dashboard    puerto 8787 (necesita ReadWritePaths=data/live por el WAL de SQLite)
              cryptoagent3-daily-summary    timer a las 23:55 UTC
              cryptoagent3-exposure-agent   inactivo y deshabilitado (politica numerica anterior)

datos         data/live/llm-agent-memory.sqlite3     decisiones y resultados
              data/live/llm-agent-state.json         estado del motor (version v5)
              data/live/llm-agent-intents.sqlite3    libro de intenciones, hace segura una reintentada
              data/validation/runs/                  corridas archivadas inmutables
```

**Solo una autoridad de órdenes puede estar activa a la vez.** Quitar `--dry-run` y añadir
`--i-understand-this-is-demo` es el interruptor.

---

## 10. Qué haría yo a continuación, en orden

1. **Correr la ventana alcista con las 8 correcciones.** No existe y el defecto 8 valía
   11.5 puntos en la bajista. 2.8 horas, cero código. Es el dato que falta para saber
   dónde estamos de verdad.
2. **Probar un modelo frontera contra el mismo backtest**, aunque sea por API y aunque
   cueste. La pregunta "¿tiene este modelo ventaja de momento donde `qwen3:30b-a3b` no la
   tiene?" es la más decisiva que queda y es barata de responder con 60 decisiones.
3. **Barrer horizontes.** Todo se ha medido a 5 días por coste de cómputo. Si la ventaja
   existe a otra escala, nada de lo hecho la habría visto.
4. **Añadir features que el agente no tiene** antes de seguir refinando políticas sobre los
   que ya tiene.
5. **No tocar el holdout** hasta que algo de lo anterior dé una ventaja medible.

Y una recomendación sobre el encuadre, que es quizá lo más útil: el sistema **ya** hace
bien una cosa medible y replicable, preservar capital en caídas (bajista −2.39% contra
−12.86%, drawdown 6.1% contra 39.5%). Puede que el producto correcto no sea "batir a
comprar y mantener" sino "comprar y mantener con la caída recortada", que es un objetivo
alcanzable con lo que ya está construido y medido. Perseguir la captura alcista exige una
ventaja de momento que, medida tres veces, no está ahí.
