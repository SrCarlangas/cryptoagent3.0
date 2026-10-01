# Roadmap — Agente LLM de exposición BTC/USDT

El contexto completo está en `handover.md`. Este documento dice qué fase toca y cuándo se
puede pasar a la siguiente. Las tareas concretas viven en `tasks.md`.

## Dónde estamos

```
VENTANA ALCISTA  (dias 1260-1560, desarrollo)
  agente  +53.08%  dd 17.7%  captura 29%   <- ANTERIOR al defecto 8, hay que repetirla
  cuant  +132.06%
  b&h    +184.44%  dd 20.0%
  GATE: RECHAZADO

VENTANA BAJISTA  (dias 2150-2450, control)
  agente   -2.39%  dd  6.1%  expuesto 9% del tiempo
  cuant   -12.50%
  b&h     -12.86%  dd 39.5%
  GATE: APROBADO 8/8
```

El agente preserva capital y no captura tendencia. La causa está medida: **no tiene ventaja
de momento**. Correlación entre su exposición real y el movimiento del precio: +0.01, +0.02,
−0.11 en tres corridas, con error estándar 0.15.

## El objetivo, y su alternativa legítima

**Objetivo declarado:** que el agente pase el gate pre-registrado en una ventana no
examinada, y por tanto obtenga autoridad de órdenes con evidencia.

**Pivote declarado de antemano:** si tres de las fases de abajo cierran sin encontrar
ventaja de momento, el veredicto honesto es que el producto correcto no es "batir a comprar
y mantener" sino **"comprar y mantener con la caída recortada"**, que ya está construido y
medido (bajista −2.39% contra −12.86%, drawdown 6.1% contra 39.5%). Ese pivote **no es un
fracaso**: es el único efecto que ha replicado en todos los estudios de este proyecto.

Declarar el pivote aquí, antes de medir, es lo que impide que más tarde se reinterprete un
resultado flojo como un éxito.

## Supuestos declarados

- Cuenta Binance **DEMO**. Ninguna fase autoriza dinero real.
- Una sola autoridad de órdenes activa a la vez. Hoy la tiene el agente LLM.
- El agente elige **dirección y postura**, nunca magnitudes. Declaró un movimiento esperado
  de +35.31% una vez; no sabe estimar números.
- Una decisión del backtest = una llamada al LLM = 130-180 s. Una corrida de 60 decisiones
  cuesta **~2.8 horas**. Esto gobierna el ritmo de todo.
- El servidor tiene 23 GB y el modelo ocupa 18.6 GB: **no caben el agente vivo y un backtest
  a la vez**. Hay que parar el servicio y volver a arrancarlo después.

## Reglas de avance

Estas reglas son el resumen operativo de una semana de errores. Romperlas es repetirla.

1. **Una sola tarea de mayor leverage por iteración**, ejecutada completa, con `tasks.md`
   actualizado con evidencia concreta y rutas.
2. **Corregir defectos, no afinar parámetros.** La distinción que emergió midiendo: las
   correcciones justificadas por **coherencia interna** (un parámetro que nada lee, una
   doctrina que el mecanismo contradice, un error de unidades) se reprodujeron en corridas
   reales. Las elecciones de política optimizadas sobre el retorno de una ventana no.
3. **Si una variante cae dentro del rango de las otras, es ruido.** Tres políticas de
   exposición dieron +63.60%, +59.51% y +53.08% sobre la misma ventana. Elegir la mejor de
   un grupo que cabe en 10 puntos es ajustar a la muestra.
4. **`research/counterfactual.py` sirve para reglas de EJECUCIÓN, no de DECISIÓN.** Acertó
   en los defectos de stops y tamaño. Falló dos veces por ~40 puntos al predecir políticas
   de exposición, porque congelar las decisiones elimina la realimentación por la que actúa
   el cambio. Está escrito dentro del fichero.
5. **El holdout son los días 960-1260 y no se mira.** Se gasta una vez, para el veredicto.
   Mirarlo para iterar lo destruye y no hay otro.
6. **No se debilita el gate.** Si un criterio parece mal construido, se publica el argumento
   y se espera decisión humana. Un criterio que no se puede evaluar **falla**, no pasa.
7. **Todo cambio de prompt se sigue de `research/agent_calibration.py`.** Un cambio de
   prompt colapsó la convicción de 9 valores a 3 y la postura a 77% AGRESIVA, y como la
   postura y la convicción son lo único que dimensiona, el tamaño se volvió constante.
8. **Archivar la traza antes de lanzar la siguiente corrida.** Se perdió una de 100
   decisiones por sobrescribirla con una prueba de humo. `data/validation/runs/`, `chmod 444`.
9. **Un resultado negativo medido cierra una tarea igual que uno positivo.** No se reintenta
   una hipótesis ya refutada: hay cuatro en `handover.md` sección 5.4.

---

## Fase A — Cerrar el hueco de medición

**Por qué primero:** la mejor ventana alcista (+53.08%) es anterior al octavo defecto, y ese
defecto valía 11.5 puntos en la bajista. Ahora mismo **no sabemos dónde estamos**. Cuesta
2.8 horas y cero líneas de código.

- Correr la ventana alcista (días 1260-1560, 60 decisiones, paso 5) con las 8 correcciones.
- Archivar, pasar el gate, la atribución por régimen y la descomposición de captura.

**Gate de salida:** existe una corrida alcista con el código actual, archivada e inmutable,
con su veredicto del gate y su correlación de timing registrados en `tasks.md`.

## Fase B — ¿Es el modelo, o es el problema?

**Por qué es la prueba más decisiva que queda:** `qwen3:30b-a3b` es lo que cabe en 23 GB. No
se ha probado si un modelo mejor tiene ventaja de momento donde este no la tiene. Si la
tiene, todo lo construido sirve y solo había que cambiar el cerebro. Si no la tiene, la
ventaja no está en el modelo y las fases C y D son las únicas esperanzas.

- Correr el mismo backtest, misma ventana, mismas 60 decisiones, con un modelo frontera por
  API. Cambiar **solo** el cliente del modelo; ninguna otra cosa.
- Comparar la correlación de timing, que es la medida que decide. El retorno es secundario:
  un retorno mejor con timing cero sigue siendo suerte.

**Gate de salida:** correlación de timing del modelo nuevo, con su error estándar, contra la
de `qwen3:30b-a3b` sobre la misma ventana.

## Fase C — ¿Está la ventaja en otro horizonte?

Todo se ha medido a 5 días, por coste de cómputo. Si la ventaja existe a otra escala, nada
de lo hecho la habría visto.

- Barrer horizontes de decisión: 1 h, 4 h, 1 día, 30 días.
- Medir la correlación de timing en cada uno. No hace falta que el backtest completo corra
  en todos: basta la correlación.

**Gate de salida:** una curva de correlación de timing contra horizonte, con errores
estándar, que diga si hay algún plazo donde el agente discrimine.

## Fase D — ¿Está la ventaja en un dato que no tiene?

El agente ve retornos, medias móviles y volatilidad. No ve libro de órdenes, flujo,
financiación de perpetuos ni nada on-chain. Si existe una ventaja, es más plausible que esté
en un dato que le falta que en una política mejor sobre los datos que ya tiene.

- Añadir una familia de features a la vez, y medir la correlación de timing antes y después.
- Respetar la purga y el embargo del índice histórico: un corte `before_day` ingenuo ya metió
  una fuga de futuro real en este proyecto.

**Gate de salida:** por cada familia de features, el cambio en la correlación de timing con
su error estándar.

## Fase E — Veredicto

Solo se entra aquí si A-D produjeron una ventaja medible, o si se agotaron.

- **Con ventaja:** una corrida de veredicto sobre el holdout (días 960-1260), 100 decisiones,
  paso ≤3. Una sola vez. Se acata el resultado.
- **Sin ventaja:** ejecutar el pivote declarado arriba. Reescribir el gate alrededor de
  "comprar y mantener con la caída recortada", con los criterios pre-registrados **antes** de
  volver a medir, y presentarlo como lo que es.

**Gate de salida:** veredicto registrado, con su evidencia, y `.kiro/` marcado como cerrado.
No se inventan fases adicionales para evitar escribir un `NO_GO`.
