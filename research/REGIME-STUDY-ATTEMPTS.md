# Bitácora de intentos: playbooks por régimen

Un intento por sección, con su número medido. Los negativos cierran una línea igual que los
positivos. Diseño en `REGIME-STUDY-PREREGISTRATION.md`.

Dataset: `sha256:53938d3d…`, 58.769 barras horarias de Binance, 2020-01-01 → 2026-09-16,
agregadas a **2442 días completos**. Train 1269 d (→2023-06-30), validación 640 d
(→2025-03-31), prueba **533 d sin tocar**.

---

## Intento 1 — Taxonomía por ratio de eficiencia + percentil de volatilidad

**Hipótesis:** dos ejes ortogonales (rectitud del camino, volatilidad relativa) separan los
cuatro regímenes, y un detector causal los sigue con retardo aceptable.

**Resultado: la capa de detección se mide, y falla fuera de muestra.**

### 1a. Primer objetivo: degenerado, descartado

Objetivo inicial `retardo_mediano + 20 × tasa_falsas_alarmas`. El barrido encontró su
óptimo degenerado de inmediato:

| config | retardo | falsas | transiciones en 1269 d |
|---|---|---|---|
| `win=7 er=0.25 k=1` | **−26,5 d** | **96 %** | **366** |

Un detector que cambia de etiqueta cada tres días *anticipa* toda transición por
coincidencia, y una suma ponderada paga encantada 20 puntos de falsas alarmas por 26 de
adelanto ficticio. **El escalar medía la capacidad de oscilar, no de detectar.**

Sustituido por restricciones duras: retardo ≥ 0 (un detector causal no puede adelantar
legítimamente a un oráculo acausal), falsas ≤ 35 %, cobertura ≥ 70 %, y transiciones ≤ 3×
las del propio oráculo (14 en 1269 d, una cada 90 días). Cambio declarado por ser
corrección de un defecto de la métrica, no una reponderación para mejorar al ganador.

### 1b. Segundo defecto: barrí el eje que no importa

La primera pasada barrió umbrales con la ventana fija en 30 d y dio **retardo 15,0 d en las
12 celdas elegibles**. Un número idéntico entre variantes que deberían diferir es
evidencia: el retardo lo gobierna la **longitud de la ventana** (≈ ventana/2, cuando la
mitad del retrovisor ya es el régimen nuevo), y es casi independiente de los umbrales.

### 1c. Con la métrica arreglada: solo 1 de 84 configuraciones sobrevive

**Frontera del compromiso, en TRAIN:**

| techo de falsas alarmas | mejor retardo alcanzable | config |
|---|---|---|
| 10 % | **ninguna** | — |
| 20 % | **ninguna** | — |
| 30 % | 21,0 d | `win=30 er=0.45 k=8` |
| 50 % | 14,5 d | `win=21 er=0.45 k=8` |

**No existe "rápido y con pocas falsas alarmas" en estos datos a resolución diaria.** Por
debajo de un 20 % de falsas alarmas no hay ninguna configuración, a ningún retardo.

### 1d. Y la única supervivientes no aguanta fuera de muestra

`win=30 er=0.45 k=8`, congelada:

| segmento | retardo mediano | falsas alarmas | cobertura | transiciones |
|---|---|---|---|---|
| train | 21,0 d | 28 % | 81 % | 18 |
| **validación** | 21,0 d | **36 %** | 88 % | 11 |

**Veredicto: FALLA en validación** (36 % > 35 %). El retardo sí es estable (21 d en ambos),
lo cual dice que el retardo es estructural y la tasa de falsas alarmas es la frágil.

### 1e. Defecto estructural de la taxonomía: el régimen BAJISTA está vacío

| | detector | oráculo |
|---|---|---|
| reparto BAJISTA en train | **3 %** | **0 %** |

El bajista 2021-2022, donde comprar y mantener perdió **−73,3 %**, queda etiquetado como
LATERAL o ALTA_VOL_SIN_DIRECCION. No es un problema de umbral: un ratio de eficiencia a 30
días es **bajo** durante una caída en escalera con contrarrallies violentos, que es
exactamente la forma de un bajista de BTC. **Un eje de dirección basado en rectitud del
camino no puede ver un bajista entrecortado**, y es justo el régimen donde más dinero hay
en juego.

Consecuencia operativa: **no tiene sentido escribir el playbook bajista sobre esta
taxonomía**, porque no tendría datos sobre los que apoyarse. Hay que arreglar el eje de
dirección antes de pasar a estrategias.

**Siguiente paso derivado de esta medición:** sustituir el eje de dirección por caída desde
máximo móvil y posición frente a una media larga — que es como se define económicamente un
bajista — en vez de rectitud del camino. La volatilidad se queda como segundo eje.

---

## Pendiente, no medido todavía

- Reglas de entrada/salida/stop/tamaño por régimen: **no escritas**. Dependen de una
  taxonomía que aísle el bajista.
- Comparación contra comprar-y-mantener-con-techo-del-25 % y contra todo-en-USDT.
- Segmento de prueba 2025-04-01 → 2026-09-16: **intacto**.

---

## Intento 2 — Eje de dirección por caída desde máximo (sustituye al ratio de eficiencia)

**Resultado: el bajista aparece.** BAJISTA pasa de 3 % a **60 %** de los días de train.

**Defecto del oráculo descubierto al medir:** confirmaba la dirección con solo 15 días hacia
delante. En un bajista los tramos de 15 d suben constantemente por los contrarrallies, así que
el oráculo marcaba **0 %** de bajista. Sensibilidad del horizonte de confirmación:

| medio-ventana | bajista en el oráculo | días etiquetados | transiciones |
|---|---|---|---|
| 15 d | **0 %** | 1025 | 11 |
| 30 d | 12 % | 810 | 11 |
| **45 d (elegido)** | **16 %** | 682 | 10 |
| 60 d | 26 % | 574 | 8 |
| 90 d | 44 % | 459 | 5 |

---

## Intento 3 — Primer "éxito", RECHAZADO por mí mismo

BAJISTA comprado daba **+28,7 %, efecto 1,58, caída 5,2 %** en validación con comisiones
adversas, y cumplía los tres criterios. No se reportó: se interrogó.

| segmento | tramos BAJISTA | qué eran de verdad |
|---|---|---|
| train | 1 tramo de **275 d**: 39.942 → 19.930 (**−50,1 %**) | el bajista real. Comprado: **−48,5 %, caída 63,4 %** |
| validación | 5 tramos de 1, 4, 7, 9 y 14 d, **todos positivos** | dips breves en un alcista furioso |

**La misma etiqueta nombraba dos fenómenos distintos.** El "playbook bajista" era comprar el
dip en un mercado al alza, y no habría sobrevivido a un bajista real.

Tres defectos del instrumento, corregidos:

1. **Sin duración mínima** → un dip de 4 días era un "régimen". Añadida permanencia mínima
   de 30 días.
2. **Efecto sobre tramos de duración incomparable** → 275 d y 4 d pesaban igual. Ahora se
   calcula sobre el **retorno logarítmico diario**.
3. **Sin suelo de evaluabilidad** → ahora exige ≥ 4 tramos y ≥ 120 días, y un criterio no
   evaluable **FALLA** (regla del repo).

**Look-ahead evitado en el acto.** La duración mínima se implementó primero con
`enforce_min_segment`, que mira toda la serie para saber si un tramo fue bastante largo: en el
día *t* eso exige saber cuánto durará el tramo en curso. Sustituido por `apply_min_dwell`
(¿cuánto lleva ya la etiqueta vigente?), con una prueba que contrasta explícitamente que la
primera lee el futuro y la segunda no.

**Tras quitar el artefacto, ningún régimen cumplía el criterio.**

---

## Intento 4 — La causa raíz era el tamaño de muestra

640 días de validación entre 4 regímenes con permanencia de 30 d dan 3-5 tramos por régimen.
Con 4 muestras el error estándar impide alcanzar efecto 1,0 salvo por suerte: ALTA_VOL mostraba
efecto **1,77** con 3 tramos y 90 días, que precisamente por eso **no es evaluable y falla**.

Con los umbrales congelados a priori, se mancomuna la región de desarrollo 2020-01 → 2025-03
(1909 días). El holdout no se toca.

**Defecto adicional:** `persistence_days=5` adoptaba la etiqueta al **cuarto** día consecutivo,
no al quinto — un parámetro que no hacía lo que declaraba, la misma forma que los nueve
defectos anteriores. Corregirlo **empeoró** LATERAL: +84,5 % / efecto 2,72 → **+52,6 % /
efecto 1,51**. Sobrevivir a una corrección que te empeora es mejor evidencia que el número alto.

---

## Intento 5 — LATERAL cumple; los otros tres regímenes son USDT

Región de desarrollo, comisiones adversas 20 bps. Detalle y reservas en `tasks.md` R.5.

| régimen | veredicto | mejor medida |
|---|---|---|
| **LATERAL** | **CUMPLE** | exposición 100 %: +52,6 %, efecto **1,51**, caída 17,7 %, 8 tramos |
| ALCISTA | USDT | efecto 0,56 y caída **28,7 %**, que rompe el techo del 25 % |
| BAJISTA | USDT | 1 solo tramo de 262 d, no evaluable; comprado −46,1 % (−15,4 % con stop 15 %) |
| ALTA_VOL_SIN_DIRECCION | USDT | efecto 0,43 |

**Tres reservas que no se maquillan:** falla en validación aislada (efecto 0,33); los 8 tramos
son de 2023-2025 y el régimen **no ocurre en 2020-2022**; solo 2 de 6 variantes cumplen.

**LATERAL no es "mercado plano".** Un mercado plano en su máximo se etiqueta ALCISTA. LATERAL
es el cubo calmado en un retroceso moderado bajo el máximo. Funciona porque acumula la deriva
incondicional de BTC con volatilidad baja por construcción, **sin necesitar criterio de
momento** — que es lo único que este repo ha medido en cero cuatro veces.


---

## Intento 6 — Defecto que había borrado el 38 % de la historia

Diagnosticando la reserva 2 ("LATERAL no ocurre en 2020-2022") apareció que **no era una
propiedad del mercado**:

```
2020  n=362  SIN ETIQUETA=362
2021  n=361  SIN ETIQUETA=361
```

**723 días sin etiquetar**, el crash del COVID y el alcista entero de 2021, con los rasgos en
`n/a`. Causa: `causal_features` exigía una racha **ininterrumpida** de 181 barras diarias.
Los 15 huecos documentados del dataset son de 1 a 5 **horas** y están casi todos en 2020-2021;
cada uno reseteaba la racha, que por tanto nunca alcanzaba 181. El primer día etiquetable caía
en marzo de 2022.

Contradecía además la convención que el propio repo ya tenía: `multislot_sim` usa
`MIN_LOOKBACK_COVERAGE = 0.95` sobre ventana temporal. Corregido con `MIN_WINDOW_COVERAGE`
equivalente: **1098 → 1729 días etiquetados** de 1909, y lo único sin etiquetar pasa a ser el
calentamiento real de 180 días.

**La conclusión anterior era un enunciado sobre el instrumento, no sobre el mercado.**

## Intento 7 — El arreglo invierte el ganador

| régimen | antes (723 días borrados) | después (serie completa) |
|---|---|---|
| LATERAL | +52,6 %, efecto **1,51**, dd 17,7 % → cumplía | +79,4 %, efecto **0,56**, dd **45,8 %** → falla |
| ALTA_VOL_SIN_DIRECCION | efecto 0,43 → fallaba | +175,3 %, efecto **1,72**, dd 20,0 % → cumple |

LATERAL cumplía **por el artefacto**: con 2021 restaurado su caída se va al 45,8 %, muy por
encima del techo del 25 %.

ALTA_VOL con exposición 100 %, comisiones adversas:

| segmento | tramos / días | total | efecto | caída |
|---|---|---|---|---|
| train | 4 / 120 | +95,9 % | 1,18 | 20,0 % |
| validación | 3 / 90 | +38,0 % | 1,43 | 18,0 % (no evaluable, 3 tramos) |
| desarrollo | 7 / 214 | +175,3 % | **1,72** | 20,0 % |

Pasan **5 de 6** variantes. **Jackknife** (quitar un tramo cada vez): el efecto se mantiene
entre **1,24 y 2,43**; quitando el tramo de +67,3 % quedan 1,24 y +64,6 %. No lo carga un solo
tramo.

## Intento 8 — Confirmación limpia en el holdout: NO CONFIRMA

Declarado antes de medir y acatado. Holdout **2025-04-01 → 2026-09-16 (533 d), gastado una
sola vez**. El detector corre sobre la serie completa y solo se **evalúan** los días del
holdout, porque recortar la serie desperdiciaría 180 días de calentamiento; el día *t* sigue
viendo solo hasta *t*.

| régimen | tramos / días | total (20 bps) | caída | veredicto |
|---|---|---|---|---|
| ALTA_VOL (candidato) | **1 / 39** | +26,6 % | 11,6 % | **NO EVALUABLE → FALLA** |
| LATERAL | 3 / 102 | **−34,7 %** | **39,2 %** | no evaluable; además refuta su pase previo |
| ALCISTA | 2 / 145 | −4,6 % | 17,1 % | no evaluable |
| BAJISTA | 2 / 225 | +8,6 % | 35,7 % | no evaluable |

**Causa raíz: potencia estadística, no defecto de instrumento ni debilidad de la estrategia.**
Y es demostrable sin mirar el resultado:

| región | días | tramos totales | por régimen |
|---|---|---|---|
| desarrollo | 1909 | 36 | ALCI 13 · BAJI 3 · LATE 12 · ALTA 8 |
| holdout | 533 | **9** | ALCI 3 · BAJI 2 · LATE 3 · **ALTA 1** |

El suelo pre-declarado es ≥ 4 tramos y ≥ 120 días por régimen. El régimen menos frecuente dio
7 tramos en 1909 días, así que alcanzar 4 exige ~1090 días: **el holdout es la mitad de lo
necesario.** Ningún régimen podía confirmarse ahí, con cualquier estrategia.

**Lo único que el holdout sí establece:** LATERAL con −34,7 % y caída 39,2 % **confirma que su
pase anterior era el artefacto de los 723 días**. El arreglo del intento 6 queda validado por
evidencia fuera de muestra.

**BLOCKER.** El holdout está gastado y no se reutiliza. Confirmar un playbook condicionado a
régimen necesita más episodios independientes de los que dan 6,7 años de datos diarios. Vía
legítima, con datos NUEVOS y no con estos: BTCUSDT en Binance arranca en agosto de 2017, así
que extender el dataset hacia atrás añade ~2,5 años (~900 días) y permitiría un test
pre-registrado nuevo. Alternativa: esperar datos futuros. Lo que **no** es legítimo es volver a
medir sobre este holdout.


---

## Intento 9 — Serie extendida a la inception de Binance

`research/extend_history.py`, reutilizando el cliente público de backfill del repo (solo
lectura, sin endpoints privados). Escrito a un **directorio nuevo**: todos los resultados
previos citan `sha256:53938d3d…` y mutar ese dataset invalidaría su procedencia en silencio.

| | antes | después |
|---|---|---|
| dataset_id | `sha256:53938d3d…` | `sha256:c475ef34…` |
| barras horarias | 58.769 | **79.477** |
| rango | 2020-01-01 → 2026-09-16 | **2017-08-17 → 2026-09-16** (9,1 años) |
| días completos | 2442 | **3296** |
| huecos documentados | 15 | 28 (el mayor, 33 h, feb 2018) |

**Supuestos declarados antes de medir:** BTCUSDT en Binance arranca el 2017-08-17, así que
es un suelo duro, no una elección. La Binance temprana es un venue más fino: 2018 tiene 7
huecos / 62 horas ausentes, el peor año de la serie. Cero precios no positivos, cero
`high < low`, cero `open_time` duplicados.

**Integridad de ETIQUETADO verificada antes de mirar retornos** (era el encargo explícito
tras el defecto del 38 %): **3116 de 3296 días etiquetados (94,5 %)**, y los 180 sin etiquetar
son exactamente el calentamiento (135 de 2017 + 45 de 2018). **Cero agujeros.** La extensión
además sanea 2020, que ahora recibe su calentamiento de 2019 en vez de perder 180 días.

## Intento 10 — El ganador cambia por TERCERA vez, y eso es el hallazgo

Re-etiquetado todo el rango, la región de selección (2020-01 → 2025-03) da:

| versión del instrumento | régimen "ganador" | efecto |
|---|---|---|
| con 723 días borrados | LATERAL expo 100 % | 1,51 |
| tras arreglar la cobertura | ALTA_VOL expo 100 % | 1,72 |
| con la serie extendida | **BAJISTA expo 50 % stop 15 %** (1,14) y LATERAL expo 50 % (1,00) | — |

ALTA_VOL cae a 0,92 y deja de pasar. **La identidad del régimen ganador no es estable bajo
cambios del instrumento**, y ninguno de los cambios tocó umbrales ni criterios: fueron
correcciones de defectos. Eso es la firma del ruido siendo seleccionado, no de un efecto.

**Defecto adicional corregido:** el criterio 3 comparaba contra exposición 100 % como si fuera
"comprar y mantener con techo", pero en BAJISTA esa variante tiene caída del **61,3 %** y es
**inadmisible** bajo el techo del 25 %. No se puede exigir a un playbook seguir el ritmo de un
referente que la restricción de riesgo prohíbe. Ahora, cuando el referente incumple el techo,
el criterio 3 se satisface por defecto y el código lo dice explícitamente.

## Intento 11 — Test limpio 2018-2019: NINGÚN RÉGIMEN CONFIRMADO

Candidato primario pre-declarado por la regla de mayor efecto en selección: **BAJISTA,
exposición 50 % con stop del 15 %** (efecto 1,14). Secundario: LATERAL 50 % (1,00).
Región **2018-01-01 → 2019-12-31**, nunca vista, gastada una sola vez. Comisiones adversas:

| régimen | tramos / días | selección | **test limpio** | caída | veredicto |
|---|---|---|---|---|---|
| **BAJISTA** expo 50 % stop 15 % | **4 / 415** | +8,4 % ef 1,14 | **−27,4 %** ef 3,91 | **27,4 %** | **FALLA** (retorno negativo y caída > 25 %) |
| **LATERAL** expo 50 % | **4 / 161** | +49,5 % ef 1,00 | +15,9 % **ef 0,22** | 18,1 % | **FALLA** (no se distingue de cero) |
| ALCISTA | 1 / 63 | — | +19,4 % | 19,2 % | no evaluable |
| ALTA_VOL | 1 / 35 | — | +6,8 % | 10,7 % | no evaluable |

**Esta vez el fallo NO es falta de potencia.** BAJISTA y LATERAL superan el suelo de
evaluabilidad (4 tramos, 415 y 161 días) y fallan por mérito propio:

- **BAJISTA invierte el signo**: +8,4 % en selección → **−27,4 %** fuera de muestra. El efecto
  3,91 es alto porque la media diaria es consistentemente **negativa**; el criterio exige
  media > 0, así que lo rechaza correctamente. Estar comprado al 50 % en un bajista pierde
  dinero, y el stop del 15 % no lo salva.
- **LATERAL se desinfla**: efecto 1,00 → **0,22**. Positivo, pero indistinguible de cero.

Es la reproducción independiente de lo que `exposure-diagnosis.md` §G ya había establecido: la
selección en muestra no generaliza. Y la inestabilidad del intento 10 era el aviso.

## Cierre del estudio

**En los cuatro regímenes, fuera de muestra, nada supera a quedarse en USDT.** El pre-registro
declaró este desenlace como un cierre válido, no un fracaso: "Si un régimen no cumple (2), el
informe dirá que en ese régimen lo correcto es quedarse en USDT."

Lo que sí queda establecido, y es positivo más que una ausencia:

1. **En BAJISTA, quedarse en USDT está activamente respaldado**, no solo "sin confirmar":
   comprado pierde −27,4 % a −61,8 % según la variante, con caídas del 27 % al 62 %.
2. **El techo del 25 % es la restricción que manda.** Comprar y mantener cayó −73,3 % en
   2021-2022 y −61,8 % en el bajista de 2018 dentro de los tramos BAJISTA: inadmisible por un
   factor de 2,5.
3. **Recortar la caída sigue siendo el único efecto que replica**, consistente con 3 de 3
   cortes OOS en el estudio previo del repo.

No se registra blocker: el estudio llegó a una respuesta definitiva con dos regiones de prueba
limpias independientes, no se quedó atascado.


---

## Intento 12 — Búsqueda walk-forward de un playbook BAJISTA

**Por qué walk-forward y no otro holdout:** no queda región sin gastar. 2017-08→2019-12 se
gastó como test limpio, 2020-01→2025-03 es la región de selección, 2025-04→2026-09 se gastó
como primer holdout. Un cuarto "test limpio" sobre cualquiera de ellas sería medir sobre datos
ya vistos.

Walk-forward expansivo responde lo que sigue siendo respondible: **¿generaliza ELEGIR un
playbook con datos pasados al año siguiente?** Cada medición es OOS respecto a los datos que
produjeron la elección. Purga: un tramo que cruza la frontera del fold se **descarta**, no se
parte; partirlo dejaría al fold de selección ver parte del desenlace con el que se puntúa el
fold de prueba. Embargo de 30 días, igual a la permanencia mínima del detector.

*Reserva que viaja con cada número:* ya había visto la mayor parte de esta historia en
iteraciones anteriores, así que estos folds son evidencia más débil que una región intacta. No
la sustituyen; son lo que queda.

### Resultado: en los 7 folds la selección eligió USDT

| fold | train hasta | test hasta | elegido | tramos test |
|---|---|---|---|---|
| 1-4 | 2019-02 … 2022-02 | 2020-02 … 2023-02 | **USDT** | 1 |
| 5-7 | 2023-02 … 2025-02 | 2024-02 … 2026-02 | **USDT** | 0 |

**Ningún candidato superó nunca el suelo pre-declarado en los datos de entrenamiento**, así
que la búsqueda no llegó siquiera a proponer algo que operar. USDT es el defecto y no tiene
que ganarse su puesto; un playbook largo debe pasar el techo de caída, ser positivo y alcanzar
efecto ≥ 1,0 para desplazarlo.

### Contraste: cada playbook aplicado a ciegas a todos los folds, OOS con embargo

| playbook | tramos | total | caída | efecto |
|---|---|---|---|---|
| **USDT (control)** | 4 | **0,0 %** | **0,0 %** | — |
| expo 100 % stop 10 % | 4 | +3,5 % | 19,7 % | **0,58** |
| expo 50 % | 4 | −3,5 % | 31,5 % | 0,83 |
| expo 50 % stop 15 % | 4 | −4,1 % | 14,8 % | 0,46 |
| expo 100 % trail 15 % | 4 | −6,9 % | 23,5 % | 0,46 |
| expo 100 % stop 15 % | 4 | −12,9 % | 28,4 % | 0,40 |
| expo 100 % | 4 | −18,8 % | 61,3 % | 0,73 |

**6 de 7 negativos.** El único positivo tiene efecto 0,58, por debajo del suelo de 1,0, o sea
indistinguible de cero — y 1 de 7 variantes positiva es lo que produce el ruido.

### Veredicto: en BAJISTA nada supera a quedarse en USDT

Medido por tres vías independientes:

1. **Test limpio 2018-2019** (4 tramos, 415 días, evaluable): todas las variantes entre
   −27,4 % y −61,8 %; USDT 0 %.
2. **Selección walk-forward:** 7 de 7 folds eligieron USDT.
3. **Aplicación ciega walk-forward:** 6 de 7 variantes negativas, la positiva con efecto 0,58.

**Y es explicable estructuralmente, no es un fallo de búsqueda.** Solo spot, comprado o en
USDT: en un declive sostenido, batir a estar fuera exige acertar el momento de los
contrarrallies, que es exactamente la ventaja de momento que este proyecto ha medido en cero
**cuatro** veces (+0,01, +0,02, −0,11, +0,03; error estándar 0,15).

### Por qué se detiene aquí y no se añaden más variantes

**El régimen BAJISTA aporta solo 4-5 episodios independientes en 9,1 años.** Mi propio suelo
de evaluabilidad exige 4 tramos, así que cualquier playbook nuevo nacería en el límite de lo
medible: con 4 muestras el efecto no alcanza 1,0 salvo por suerte. Es un techo de **potencia
estadística**, no de imaginación. Seguir proponiendo variantes sobre 4 episodios es el
procedimiento que fabrica ganadores que no sobreviven, y este estudio ya lo hizo tres veces
(LATERAL → ALTA_VOL → BAJISTA, todos invertidos al confirmar).

### Retroalimentación concreta al agente, derivada de la medición

En BAJISTA la exposición correcta es **0 %, no el 12 % que tuvo**. Medido con el gate nuevo:

| exposición en bajista | veredicto del criterio de riesgo igualado |
|---|---|
| 0 % estricto | **PASA** (a caída 0 % el estático equivalente también da 0 %) |
| ~2 % residual | PASA (−0,5 % contra un límite de −0,8 %) |
| **12 %, lo que hizo** | **FALLA** (−2,4 % contra un límite de −2,3 %) |

Ese 12 % residual le costó ~0,4pp, y esos 0,4pp son exactamente la diferencia entre pasar y
fallar. La prescripción es medible: **en BAJISTA, ir a cero.**

### Argumento publicado sobre el gate, para decisión humana

Siguiendo la regla "si un criterio parece mal construido, se publica el argumento y se espera
decisión humana", sin tocar ningún umbral:

**El criterio de discriminación castiga la respuesta correcta en una ventana de un solo
régimen.** Exige minoría de exposición ≥ 5 %. Sobre una ventana íntegramente bajista, la
respuesta que toda la evidencia respalda es exposición 0 %, que da minoría 0 % y **FALLA**:

| exposición | minoría | discriminación | riesgo igualado |
|---|---|---|---|
| 0 % | 0 % | **FALLA** | PASA |
| 12 % | 12 % | PASA | **FALLA** |

Ninguna exposición constante puede pasar los dos a la vez en una ventana de un solo régimen.
El criterio tiene sentido sobre una ventana que contiene varios regímenes, donde un agente
constante sí es sospechoso. Posible reparación, **no aplicada**: evaluar la discriminación solo
sobre ventanas que contengan más de un régimen, o medirla entre regímenes en vez de dentro de
la ventana. Queda a tu decisión.


---

## Intento 13 — Prescripción "0 % en BAJISTA" al agente vivo: NO APLICADA

Pedida, investigada y **rechazada con la medición**, no por cautela.

**Primero el mapeo**, porque confundir taxonomías habría prescrito sobre el régimen
equivocado: mi BAJISTA viene de mi eje de caída desde máximo; el agente vivo usa su propia
mezcla aprendida r0-r3. Su bajista es `r1 "bajista profundo"`, con
`allocation_at_neutral = 0.20` y `default_exposure = CASH`.

**Hecho 1: en r1 el agente ya estaba a cero.** Exposición observada **0,0 % en 16 decisiones**
de la ventana bajista. Bajar el 0.20 a 0 es un **no-op** sobre la evidencia medida.

**Hecho 2: la pérdida no vino de r1 sino de r2**, con 3 decisiones al 78 % de exposición
(−3,6 %, efecto 0,6).

**Hecho 3: esas decisiones estaban CORRECTAMENTE corroboradas.**

| régimen | decisiones | precio vs media 200d | retorno 90d | por debajo de la media |
|---|---|---|---|---|
| r2 | 3 | **+14,2 %** | +19,1 % | **0 de 3** |
| r3 | 1 | **+10,3 %** | +19,8 % | **0 de 1** |

Ocurrieron en los días 2430-2445, el final de la ventana, con el mercado ya por encima de su
tendencia y subiendo un 19 % a 90 días. La etiqueta y la doctrina coincidían. **No es un
defecto: es la ausencia de ventaja de momento.** La evidencia decía "sobre tendencia y
subiendo", el agente se expuso, y perdió.

**Por qué no se aplica:** sería afinar un parámetro justificado por el retorno de una ventana,
que es lo que la regla 2 del roadmap prohíbe y lo que ya falló repetidamente en este proyecto.
No hay defecto de coherencia interna que lo respalde: la doctrina de r1 dice "preservar capital
manda" y una asignación del 20 % con `default_exposure = CASH` y `risk_per_trade = 0.013` no la
contradice.

---

## Intento 14 — Playbook ALCISTA: tampoco supera a USDT, y por una razón distinta

Mismo código que BAJISTA (`research/regime_walkforward.py --regime ALCISTA`), que además
reproduce BAJISTA idéntico, así que no hay deriva entre las dos respuestas.

**Selección: 7 de 7 folds eligieron USDT.** Nada superó el suelo pre-declarado en entrenamiento.

**Aplicación ciega, OOS con embargo, 13 tramos** (muestra mucho mejor que los 4 de BAJISTA):

| playbook | tramos | total | caída | efecto |
|---|---|---|---|---|
| **USDT (control)** | 13 | **0,0 %** | **0,0 %** | — |
| expo 100 % | 13 | +262,5 % | **29,9 %** (rompe el techo) | 0,16 |
| expo 50 % | 13 | **+126,0 %** | 22,5 % | **0,37** |
| expo 100 % stop 15 % | 13 | +211,8 % | 29,9 % | 0,15 |
| expo 100 % stop 10 % | 13 | +118,5 % | 28,8 % | 0,48 |
| expo 100 % trail 15 % | 13 | +65,6 % | 31,7 % | 0,65 |
| expo 50 % stop 15 % | 13 | +110,7 % | 22,5 % | 0,10 |

**Aquí TODAS las variantes son fuertemente positivas**, al contrario que en BAJISTA donde 6 de
7 eran negativas. Eso invita a leerlo como un hallazgo. No lo es:

| ALCISTA expo 50 % | |
|---|---|
| tramos positivos | **5 de 13** |
| prueba de signo | **p = 0,867** (consistente con una moneda, o peor) |
| **mediana del tramo** | **−3,3 %** |
| tramos | +19 % −3 % −4 % **+89 %** −2 % −5 % −7 % +16 % −3 % −4 % +19 % +3 % −5 % |

**Jackknife:** quitando **un solo tramo de 13** (2020-10-15, el rally post-COVID), el total cae
de **+126,0 % a +19,5 %**. En expo 100 %, de +262,5 % a +30,2 %.

**El tramo típico de ALCISTA PIERDE dinero** al 50 % de exposición con comisiones adversas. El
total positivo es un valor extremo, no un comportamiento. Leer el +126 % como playbook habría
sido exactamente el error que este estudio ya cometió tres veces.

### Veredicto conjunto de los cuatro regímenes

**En los cuatro, fuera de muestra, nada supera a quedarse en USDT.** Y las dos formas de
fallar son instructivamente distintas:

| régimen | cómo falla |
|---|---|
| BAJISTA | retornos **negativos**: 6 de 7 variantes pierden. USDT gana por evitar pérdidas. |
| ALCISTA | retornos positivos pero **un solo tramo los carga**; mediana −3,3 %, signo p=0,867. |
| LATERAL | efecto 0,22 en el test limpio, tras parecer 1,00 en selección. |
| ALTA_VOL | efecto 0,43-0,92 según el instrumento; nunca estable. |

Coherente con lo único que este repo ha medido de forma estable: **no hay ventaja de momento**
(+0,01, +0,02, −0,11, +0,03; error estándar 0,15), y sin ella la elección de *cuándo* estar
expuesto no lleva información.


---

## Intento 15 — Challenge a la conclusión: ¿por qué hay firmas de cripto rentables?

La objeción es correcta y obliga a precisar qué se midió. **Lo medido responde una pregunta
estrecha:** ¿puede una decisión direccional long/flat sobre BTC spot, un solo venue, sin
apalancamiento, a cadencia de 5 días, batir a tener BTC? No. **Y casi ninguna firma rentable
hace eso.**

| lo que hacen las firmas | por qué este montaje no puede |
|---|---|
| **Creación de mercado** (Wintermute, GSR, Cumberland, Jump): capturan el spread miles de veces al día más rebajas de maker | ventaja de latencia e inventario, no de pronóstico. Aquí somos taker a 5 días |
| **Base / cash-and-carry**: largo spot + corto perpetuo, cobran financiación, delta neutral | **exige cortos y derivados: prohibidos por el mandato** |
| **Arbitraje entre exchanges y triangular** | exige varios venues con capital en cada uno |
| **Stat-arb transversal** sobre cientos de tokens | la ventaja vive en el CORTE TRANSVERSAL; medimos un solo activo |
| **Microestructura a segundos** | el propio diagnóstico halló reversión a 4h con **2,08 ee** — el mayor efecto jamás medido aquí — y lo descartó porque el churn costaba 137 %/año **como taker**. Como maker con rebajas ese coste cae un orden de magnitud |
| **Beta disfrazada de alfa + supervivencia** | muchas "firmas exitosas" estuvieron largas en 2020-2021. Y los muertos no se ven: 3AC, Alameda, Celsius, BlockFi, Genesis |
| **Ingresos no direccionales**: exchanges, custodia, listados, spread OTC | no es trading |

**La contradicción se disuelve: ambas cosas son ciertas porque describen negocios distintos.**
El nuestro es pronóstico direccional en un solo activo spot a horizonte de días — el rincón más
duro y concurrido, y el único donde comprar y mantener es el competidor más fuerte.

Y hay un número nuevo que acota el mandato: **incluso un cerebro perfecto a cadencia de 5 días
solo añade +13 % de retorno** sobre comprar y mantener (+207,8 % contra +184,4 %). **El techo lo
fija el mandato, no el modelo.**

### Hipótesis "inputs equivocados": comprobada, y el resultado está partido

Hallazgo que la motiva: `market_features` consume **solo cierres diarios y el precio**. El
dataset lleva `base_volume`, `quote_volume`, `trade_count`, `high`, `low`, `open` desde el
principio y **ninguno se había medido nunca**.

`research/flow_diagnosis.py`, método idéntico al del diagnóstico original (Spearman sobre
muestras no solapadas, todos los desplazamientos, horizontes de churn asequible):

| feature | horizonte | rho medio | rho/ee | signo estable |
|---|---|---|---|---|
| ticket medio (z30) | 168h | +0,0546 | **+1,18** | sí |
| nº operaciones (z30) | 48h | +0,0287 | **+1,16** | sí |
| ticket medio (z30) | 48h | +0,0268 | **+1,08** | sí |
| ticket medio (z30) | 96h | +0,0378 | **+1,08** | sí |
| volumen (z30) | 48h | +0,0251 | **+1,01** | sí |

**5 de 24 pares alcanzan 1 error estándar, todos positivos y con signo estable, frente a 0 de 20
del estudio solo-cierres.** Es lo primero que este proyecto mide por encima de 1 ee a horizonte
asequible. El patrón más coherente es el **ticket medio** (proxy de composición de los
participantes): positivo a 48h, 96h y 168h.

**Pero 0 de 24 alcanzan 2 errores estándar**, y la prueba económica lo mata:
`research/flow_strategy.py`, walk-forward con selección dentro del fold, 1 día de retardo,
comisiones adversas, contra comprar-y-mantener **al mismo riesgo**:

| | |
|---|---|
| folds que baten al estático al mismo riesgo | **0 de 7** |
| retorno compuesto OOS de la estrategia | **−40,7 %** |
| comprar y mantener en el mismo tramo | **+675,0 %** |
| comprar y mantener al mismo riesgo | +580,9 % |

**Veredicto: la hipótesis de los inputs está respaldada estadísticamente y refutada
económicamente.** Un rho de +0,03 es real y es demasiado pequeño para pagar 20 bps de ida y
vuelta. Construir un LLM sobre estos inputs repetiría el error central del proyecto.

### El carry: la ventaja real de cripto, medida — y decayendo

Financiación histórica del perpetuo BTCUSDT, dato público gratuito, **7.737 pagos de 8h sobre
7,1 años** (`data/history/btcusdt-funding.json`):

- media por pago **+0,0105 %**, positiva en **85,8 %** de los pagos
- suma **+81,5 %** sobre 7,1 años = **11,5 % anual** cobrado por el lado corto
- cash-and-carry (largo spot + corto perpetuo) es **delta neutral**: no pronostica nada

**Pero se está comprimiendo, y eso cambia la recomendación:**

| año | anualizado | % pagos positivos |
|---|---|---|
| 2021 | **30,6 %** | 93 % |
| 2022 | 4,2 % | 78 % |
| 2024 | 11,9 % | 92 % |
| 2025 | 5,1 % | 87 % |
| **2026** | **3,0 %** | 74 % |

A 3,0 % bruto, menos comisiones en ambas patas, menos coste de margen y menos riesgo operativo
(liquidación del corto, riesgo de exchange), **hoy es marginal**. Era una ventaja real y está
decayendo, que es lo que les pasa a las ventajas cuando se descubren.

### Por qué NO se construye el LLM que "copia" a los traders exitosos

Honestamente, y con los números arriba:

1. **Creación de mercado y arbitraje son juegos de latencia e infraestructura.** Un LLM que
   decide cada 30 minutos no compite con un motor a microsegundos. No es cuestión de prompt.
2. **El carry no necesita juicio:** "si la financiación supera X, monta la base" es un `if`. Un
   LLM no añade nada sobre una condición mecánica, y el premio está a 3 %.
3. **El stat-arb transversal es un problema de ranking y covarianzas** sobre cientos de activos,
   donde los métodos numéricos son mejores que un LLM por construcción.
4. **El techo del mandato está medido en +13 %** incluso con previsión perfecta. Ningún trabajo
   de inputs o de modelo dentro del mandato vale mucho.

**Dónde un LLM sí estaría diferenciado**, y es la única reformulación honesta: leer **texto no
estructurado** que los números no capturan — anuncios de exchange, gobernanza de protocolos,
cambios regulatorios, divulgaciones de hackeos. Ese es otro trabajo: no "cuándo estar largo"
sino "acaba de ocurrir algo que invalida la posición".

**No lo construyo porque no es comprobable con lo que hay:** no tengo texto con marca temporal
y los archivos de noticias filtran futuro de forma notoria (fechas de publicación revisadas,
artículos editados). Construirlo sin poder validarlo fuera de muestra sería exactamente el
error que este proyecto ha documentado quince veces. Si se consigue un corpus con marca temporal
auditable, la hipótesis queda formulada y es medible: **¿reduce la caída alrededor de fechas de
evento conocidas, fuera de muestra?**


---

## Intento 16 — Fuera de la caja: el mandato nunca dijo UN activo

El reencuadre que faltaba. Todo el proyecto ha medido **TIMING** —cuándo estar expuesto a BTC—
y no ha hallado nada en cuatro mediciones, con un techo medido de +13 % incluso con previsión
perfecta. Eso es una propiedad de la pregunta, no de los modelos.

El mandato es "solo spot, comprado o en USDT, sin apalancamiento, sin cortos". **No dice un solo
activo.** Una rotación long-only entre pares spot cabe entera dentro de él, y es un mecanismo
distinto: no necesita la dirección de ningún activo, solo el **orden relativo** de varios —
problema estadístico más fácil, y donde vive la ventaja transversal más replicada de la
literatura. El proyecto nunca lo había mirado.

**Universo:** 30 pares USDT diarios 2019-2026 descargados de Binance (`data/history/
cross-section-1d.json`), elegidos por **longevidad, no por rendimiento**, e incluyendo a
propósito activos que colapsaron (LUNA, FTT) y dos que dejan de cotizar dentro de la muestra
(EOS 2025-05, MATIC 2024-09). Disponibilidad **punto-en-el-tiempo estricta**: un activo entra en
el ranking solo si de verdad tenía la historia necesaria antes de esa fecha. Un deslistado se
liquida a su último cierre observado, no desaparece.

**Walk-forward, 5 folds anuales, selección de lookback/cesta/signo dentro del fold, comisiones
adversas, contra BTC comprar-y-mantener al mismo riesgo:**

| fold | OOS hasta | elegido | rotación | BTC | BTC@riesgo | caída | gana |
|---|---|---|---|---|---|---|---|
| 1 | 2021-12-31 | momento 30d top8 | **+2.024,1 %** | +62,3 % | +62,3 % | 59,5 % | sí |
| 2 | 2022-12-31 | momento 30d top3 | −80,4 % | −64,2 % | −64,2 % | 82,7 % | no |
| 3 | 2023-12-31 | momento 90d top3 | +210,2 % | +153,7 % | +153,7 % | 40,1 % | sí |
| 4 | 2024-12-30 | momento 30d top8 | +10,0 % | +120,8 % | +120,8 % | 54,3 % | no |
| 5 | 2025-12-30 | momento 90d top3 | −8,1 % | −6,4 % | −6,4 % | 52,5 % | no |

Compuesto OOS **+1.205,1 %** contra **+192,5 %** de BTC al mismo riesgo. Titular espectacular.

### Y es un solo fold. Jackknife:

| se quita | compuesto resultante |
|---|---|
| **fold 1 (+2.024,1 %)** | **−38,6 %** |
| fold 2 (−80,4 %) | +6.562,0 % |
| fold 3 (+210,2 %) | +320,7 % |
| fold 4 (+10,0 %) | +1.086,3 % |
| fold 5 (−8,1 %) | +1.320,0 % |

Quitar **un fold de cinco** lleva el resultado de +1.205 % a **−38,6 %**, y el rango del
jackknife va de −38,6 % a +6.562 %. **Eso no es una estrategia, es un billete de lotería.** El
fold 1 es 2021: la manía de las alts. Un top-8 por momento a 30 días en 2021 captura la beta de
esa burbuja, no alfa.

Y **la caída compuesta es 80,4 %**, que viola el tope del 25 % por un factor de 3,2.

### Veredicto, con un matiz que importa

**Refutado en su forma actual**, pero **no de la misma manera** que los demás:

| | BAJISTA | ALCISTA | rotación transversal |
|---|---|---|---|
| retornos | **negativos** | positivos, un tramo los carga | positivos, **3 de 5 folds**, mediana **+10,0 %** |
| cómo falla | USDT gana por evitar pérdidas | jackknife +126 % → +19,5 % | jackknife +1.205 % → −38,6 % **y caída 80,4 %** |

La rotación transversal es **el mecanismo más prometedor medido hoy** y simultáneamente **no
certificable con 5 folds anuales** e **inadmisible bajo el tope del 25 %**. Con 5 observaciones
independientes no se establece nada, exactamente el techo de potencia que ya cerró BAJISTA.

### Dónde encaja de verdad un LLM, y qué falta para probarlo

Esto sí responde "copiar a los traders exitosos". Lo que los traders de cripto realmente hacen
no es acertar el timing de BTC: **rotan entre narrativas** (verano DeFi, L1s, memes, tokens de
IA). Es una decisión de **selección transversal guiada por relato**, y es el único trabajo de
esta lista donde un LLM está estructuralmente mejor equipado que un ranking numérico: leer de
qué se habla, qué sector recibe capital, qué lanzamiento viene.

**Inputs que consumiría:** el ranking numérico transversal (ya construido) **más** texto con
marca temporal sobre narrativas, lanzamientos, listados e incidentes.
**Qué decidiría:** qué k activos del universo elegible sostener el próximo periodo. No dirección,
no tamaño: **selección**.
**Cómo se mide:** idéntico a este intento — walk-forward anual, selección dentro del fold,
comisiones adversas, contra BTC al mismo riesgo, con jackknife obligatorio y el tope del 25 %.

**No se construye hoy, y la razón es de datos, no de ganas:** no existe corpus de narrativas con
marca temporal auditable, y los archivos de noticias y de redes filtran futuro de forma notoria
(fechas revisadas, hilos editados, cuentas borradas). Sin eso, cualquier resultado sería
in-sample disfrazado, que es el error que este proyecto ha documentado dieciséis veces.
**Bloqueador declarado:** conseguir un feed de texto con marca temporal verificable y un
universo de listados punto-en-el-tiempo. Con ambos, la hipótesis es medible tal como está
especificada arriba.


---

## Intento 17 — La unidad de observación estaba mal, y al arreglarla aparece el hallazgo real

El intento 16 hizo jackknife sobre folds **anuales**. Esa conclusión es válida para lo que
probó, pero el test tenía un defecto que conviene nombrar porque es la imagen espejo del que
infló resultados anteriores: **un fold anual es la unidad equivocada para una estrategia que
rebalancea cada mes.** Agrupar doce decisiones en una observación tira once doceavos de la
información y hace que un año bueno parezca una sola suerte.

`research/cross_section_monthly.py` mide el mismo mecanismo con la unidad correcta: el
**periodo de rebalanceo**. Mismos parámetros elegidos solo con folds pasados y congelados, así
que **los 60 periodos puntuados son todos fuera de muestra**. No se baja ningún umbral: se sube
la muestra de 5 a 60 y se añaden dos estadísticos resistentes a valores extremos.

| | |
|---|---|
| periodos fuera de muestra | **60** (antes tratados como 5) |
| diferencia **media** (rotación − BTC) | **+5,21 %** por periodo |
| diferencia **mediana** | **−3,54 %** |
| error estándar | 3,76 % → **efecto 1,38** (suelo 1,0) |
| periodos en que la rotación gana | **29 de 60 = 48 %** |
| prueba de signo, una cola | **p = 0,6506** |
| media por periodo | rotación +8,90 % · BTC +3,68 % |
| **sin el mejor periodo de 60** | media +3,08 %, **efecto 0,98** |

### El hallazgo: media positiva, mediana NEGATIVA

La media supera a la mediana en **8,7 puntos**. La rotación **pierde algo más a menudo de lo que
gana** (48 % de acierto, indistinguible de una moneda) y **cuando gana, gana mucho**.

Eso no es "sin ventaja". Es un **perfil de convexidad**: una distribución de pagos asimétrica a
la derecha. Es exactamente lo que es una cesta de alts — sangra la mayor parte del tiempo y
ocasionalmente multiplica.

**Veredicto honesto frente al criterio pre-declarado:** el titular (media > 0, efecto ≥ 1,0)
**pasa** con 1,38. Las dos comprobaciones de robustez que añadí **en este módulo antes de
correrlo** fallan: la prueba de signo dice moneda (p=0,65) y quitar **un** periodo de 60 deja el
efecto en **0,98**, justo por debajo del suelo. Un resultado que solo sobrevive en la media, con
mediana negativa y que se cae al retirar 1 de 60 observaciones, **no está establecido**. Se
declara como lo que es: el hallazgo más cercano a real de todo el proyecto, y no certificable.

### Por qué esto reconcilia de verdad la pregunta original

**Lo que cobran los traders de cripto rentables no es exactitud, es CONVEXIDAD.** Pierden en la
mayoría de sus posiciones y ganan mucho en unas pocas. Por eso parecen exitosos y por eso todas
mis mediciones no encontraban nada: **he estado midiendo tasa de acierto y correlación de
timing durante todo el proyecto**, cuando el negocio va de asimetría y de dimensionar hacia
pagos asimétricos.

Las cuatro mediciones de correlación de timing en cero (+0,01, +0,02, −0,11, +0,03) son
correctas **y miden lo irrelevante**. Un operador con 48 % de acierto y mediana negativa puede
ser muy rentable si la cola derecha paga lo suficiente — y la correlación de timing de ese
operador saldría cero.

### Lo que esto implica para el LLM, y ahora sí es específico

El trabajo del LLM **no es acertar más veces** — cuatro medidas dicen que no puede. Es
**identificar configuraciones asimétricas**: donde la pérdida está acotada por construcción y la
ganancia queda abierta. Eso es un juicio cualitativo sobre estructura de pagos, no una
predicción de dirección, y es el único trabajo de toda esta investigación donde un LLM está
plausiblemente mejor equipado que un ranking numérico.

- **Inputs:** el universo transversal elegible (construido) + estructura de la posición (cuánto
  se puede perder si falla) + texto con marca temporal sobre catalizadores.
- **Decide:** qué k candidatos tienen cola derecha abierta con pérdida acotada. Selección y
  acotación, no dirección.
- **Se mide:** y aquí está el cambio metodológico que se deriva de este intento, **la métrica
  deja de ser tasa de acierto o correlación de timing**. Se mide por **asimetría de los
  resultados**: media contra mediana, ratio cola-derecha/cola-izquierda, y el criterio
  pre-declarado aplicado al **spread mensual** con prueba de signo y recorte del mejor periodo.

**Bloqueador que se mantiene:** sin corpus con marca temporal auditable ni universo de listados
punto-en-el-tiempo, el brazo de texto no es validable. Pero el brazo **numérico** de esta
hipótesis ya es medible y acaba de medirse: efecto 1,38 en la media, 0,98 recortado, 48 % de
acierto. El siguiente paso con datos que ya existen es **ampliar la muestra**, no añadir
cerebro: con 60 periodos la pregunta no se cierra, con 150-200 sí.


---

## Intento 18 — HALLAZGO: hay señal, y es transversal, y es la contraria a la que buscaba

Cada test anterior tiraba la mayor parte de sus propios datos. `cross_section_monthly.py` midió
el **spread de la cartera**: 60 observaciones. Pero la cartera es una forma concreta de expresar
una señal, y su pago lo dominan el dimensionamiento y qué pocos activos cayeron en la cesta. **La
información de la señal vive un nivel más abajo**, en el ranking transversal: ¿ordena la señal
los activos en el orden en que van a resultar sus retornos?

Eso es el **coeficiente de información**, se calcula DENTRO de cada periodo entre activos y se
promedia entre periodos. Con 30 activos y 88 periodos usa **2.396 observaciones activo-periodo**
en vez de 60, y su error estándar sale de la variación del IC entre periodos.

`research/cross_section_ic.py`, periodos de 30 d no solapados, señales causales:

| señal | IC medio | IC mediana | t | periodos+ |
|---|---|---|---|---|
| **volatilidad 30d** | **−0,1609** | −0,1806 | **−5,23** | 25/88 |
| **volumen medio 30d** | **+0,0728** | +0,0600 | **+2,74** | 51/88 |
| crecimiento de volumen | −0,0330 | −0,0355 | −1,29 | 43/88 |
| momento 30d | −0,0335 | −0,0107 | −1,21 | 42/88 |
| momento 30d ajustado por vol | −0,0302 | −0,0172 | −1,08 | 40/88 |
| momento 180d | +0,0162 | +0,0099 | +0,58 | 46/88 |
| momento 90d | +0,0101 | +0,0417 | +0,34 | 46/88 |

**Dos señales a |t| >= 2. Es la primera vez que este proyecto mide algo a dos sigmas.** Y el
**momento no es significativo** en ningún horizonte — justo la familia sobre la que construí la
rotación del intento 16, lo que explica por qué su resultado era un fold afortunado.

### Los dos confundidores obvios, probados y descartados

| | universo completo | **solo sobrevivientes** | **sin periodos catastróficos** |
|---|---|---|---|
| volatilidad 30d | t = −5,23 | **t = −5,29** | **t = −4,65** |
| volumen medio 30d | t = +2,74 | **t = +3,08** | **t = +2,59** |

1. **Supervivencia.** Restringido a los 28 pares que siguen cotizando, el efecto es **más
   fuerte** (−5,29), no más débil. Si la supervivencia lo explicara, quitar a los muertos lo
   mataría. No lo hace.
2. **Catástrofes.** Eliminando los 5 periodos en que algún activo cayó más del 50 %, queda
   t = −4,65, muy por encima de dos sigmas.

### Qué es esto, en términos reconocibles

Es la **anomalía de baja volatilidad**: dentro del corte transversal, los activos de menor
volatilidad rinden más por unidad de riesgo. Es uno de los efectos más replicados de todas las
finanzas — acciones, bonos, materias primas — y aquí aparece en cripto a t ≈ −5. Más un efecto
de **tamaño/liquidez** (t = +2,74): los nombres más grandes y líquidos del universo rinden más.

### La reconciliación, por fin completa

**Los inputs SÍ estaban equivocados, pero no como yo supuse.** No era que faltara volumen como
señal temporal — eso lo medí y falló (0 de 7 folds). Estaban equivocados en **DIMENSIÓN**:

> todo el proyecto midió la dimensión **temporal** (¿cuándo estar expuesto a BTC?) cuando la
> señal vive en la dimensión **transversal** (¿qué activo, entre varios?).

Y eso reconcilia la pregunta original de forma limpia: las firmas rentables cosechan **primas
factoriales documentadas** —baja volatilidad, tamaño, liquidez, carry— no aciertos
direccionales. Mis cuatro mediciones de correlación de timing en cero son **correctas**, y
miden una dimensión en la que no hay nada que medir.

### Lo que esto implica para el LLM, honestamente

**Esta señal no necesita un LLM.** Un factor de baja volatilidad es una **ordenación**: se
calcula con una desviación típica y un `sort`. Meter un LLM ahí añade coste y latencia sin
añadir información.

El LLM solo tendría sitio en la capa que queda por encima —selección por narrativa y
configuraciones asimétricas (intentos 16-17)— y esa capa sigue **no validable** sin corpus con
marca temporal auditable.

### Lo que FALTA antes de poder operar esto, y no está hecho

**Un IC no es un P&L.** Un IC de −0,16 es fuerte para estándares cuantitativos (los factores de
renta variable corren a 0,02-0,05), pero convertirlo en dinero exige construcción de cartera,
comisiones y el **tope de caída del 25 %** — y "baja volatilidad" en cripto sigue siendo
volatilidad altísima en absoluto. **No se ha medido.** El siguiente paso es exactamente ese, y
debe pasar el mismo gate: walk-forward, comisiones adversas, contra BTC al mismo riesgo,
jackknife, tope del 25 %.

**Reserva que se mantiene:** el universo son 30 nombres elegidos a mano por longevidad. El efecto
aguanta entre sobrevivientes, lo que descarta el confundidor principal, pero un universo
punto-en-el-tiempo más amplio sigue siendo la validación pendiente.


---

## Intento 19 — El factor convertido en dinero: el resultado más fuerte, y no certificado

`research/low_vol_strategy.py`. La señal del intento 18 (volatilidad 30d ascendente, t = −5,23)
expresada como cartera: las k de menor volatilidad, peso igual o inverso a la volatilidad,
rebalanceo mensual, parámetros elegidos en folds pasados y congelados, comisiones adversas.

### Lo que es notable

| fold hasta | elegido | estrategia | BTC | ¿gana? |
|---|---|---|---|---|
| 2021-12-31 | top5 igual | **+325,0 %** (dd 34,6 %) | +75,6 % (dd 39,3 %) | sí |
| 2022-12-31 | top3 inversa-vol | −49,7 % (dd 53,1 %) | **−63,4 %** (dd 64,4 %) | sí |
| 2023-12-31 | top3 inversa-vol | +116,6 % (dd 11,7 %) | +157,0 % (dd 14,2 %) | no |
| 2024-12-30 | top5 inversa-vol | +146,2 % (dd 17,2 %) | +135,1 % (dd 14,6 %) | sí |
| 2025-12-30 | top3 igual | −5,4 % (dd 25,8 %) | −6,0 % (dd 26,1 %) | sí |

**4 de 5 folds baten a BTC**, incluido el bajista de 2022. Agregado sobre 60 periodos OOS:
estrategia **+977,4 %** con caída 62,3 % contra BTC **+265,0 %** con caída 69,2 %. Más retorno
**y** menos caída.

**Con el tope del 25 % aplicado a AMBOS brazos** (la comparación que de verdad importa bajo el
mandato):

| | exposición | retorno | caída |
|---|---|---|---|
| **factor de baja volatilidad** | 0,34 | **+199,7 %** | 25,0 % |
| **BTC** | 0,28 | **+73,7 %** | 25,0 % |

**2,7× más retorno a caída idéntica.** Es lo primero en todo el proyecto que supera a
comprar-y-mantener al mismo riesgo.

### Y no pasa el criterio completo

| comprobación pre-declarada | resultado | |
|---|---|---|
| diferencia media del spread > 0 | +2,75 % | ✓ |
| efecto ≥ 1,0 | **1,29** | ✓ |
| mediana del spread > 0 | +0,32 % | ✓ |
| supera a BTC con el tope aplicado | +199,7 % vs +73,7 % | ✓ |
| **prueba de signo** | 31/60 = 52 %, **p = 0,4487** | **✗** |
| **efecto quitando el mejor de 60 periodos** | **0,84** | **✗** |

Gana en **52 %** de los periodos —indistinguible de una moneda— y quitar **un** periodo de 60
deja el efecto en 0,84, por debajo del suelo. **El rendimiento superior es real en la media y
llega a ráfagas**, no de forma uniforme. Es el mismo perfil de convexidad del intento 17, y es
exactamente lo que la comprobación de recorte existe para detectar.

**Veredicto: NO CERTIFICADO.** Escribí el recorte y la prueba de signo en el módulo antes de
correrlo, y se acatan. No se despliega nada con esto.

### Qué lo resolvería, y qué no

**Lo resolvería más muestra.** 60 periodos mensuales sobre 5 folds es poco para un premio
factorial que llega a ráfagas; si el efecto es real, con 150-200 periodos el efecto recortado se
estabiliza por encima del suelo. Vías: universo más amplio (reduce el ruido transversal por
periodo) y más historia.

**No lo resolvería más cerebro.** No hay nada que un LLM aporte a ordenar activos por desviación
típica. El factor es un `sort`; la incertidumbre es de tamaño de muestra, no de capacidad de
decisión.

### Reservas que viajan con el número

1. **Universo de 30 nombres elegidos a mano** por longevidad. El efecto aguanta entre
   sobrevivientes (t = −5,29, más fuerte), lo que descarta el confundidor principal, pero un
   universo punto-en-el-tiempo más amplio sigue pendiente. **Sesga al alza.**
2. **La exposición del 0,34 se calibró sobre la caída medida**, es decir sobre el peor tramo que
   ya ocurrió. Un tramo peor rompería el tope, igual que advertí para el 18 % estático.
3. **Cuatro de cinco folds** es alentador y son cinco observaciones.


---

## Intento 20 — Universo 3,3x mas amplio: la SEÑAL replica, la ESTRATEGIA no

El paso que yo mismo identifique: mas muestra. Y se hizo eliminando tambien mi sesgo de
seleccion — el universo sale **programaticamente** de `exchangeInfo` de Binance, no de mi
memoria. **100 pares USDT** con >= 900 dias (mediana 2047 d), frente a los 30 elegidos a mano.

*Defecto propio por el camino, de la misma familia que todo lo de hoy:* mi primer filtro uso
`permissions`, que Binance dejo vacio al migrar a `permissionSets`, y devolvio **0 pares en
silencio**. Asumi la forma de un campo en vez de comprobarla. El campo correcto es
`isSpotTradingAllowed`: **503 pares**.

### La señal: REPLICA, con 5.693 observaciones activo-periodo

| señal | t (30 pares) | **t (100 pares)** | t (solo sobrevivientes) |
|---|---|---|---|
| **volatilidad 30d** | −5,23 | **−4,06** | **−4,21** |
| **crecimiento de volumen** | −1,29 | **−3,18** | **−3,35** |
| volumen medio 30d | **+2,74** | **−2,08** | −1,98 |
| momento 30d / 90d / 180d | −1,21 / +0,34 / +0,58 | −1,69 / −0,86 / −1,50 | −1,87 / −0,99 / −1,65 |

1. **La anomalia de baja volatilidad replica** en un universo independiente y 3,3x mayor:
   t = −4,06 (−4,21 entre sobrevivientes). Se debilita desde −5,23 pero sigue muy por encima de
   dos sigmas con 5.693 observaciones. Un artefacto suele colapsar, no aguantar en −4.
2. **El volumen medio INVIRTIO EL SIGNO: +2,74 → −2,08. REFUTADO.** Mi hallazgo del intento 18
   era un artefacto de los 30 nombres grandes y liquidos que elegi a mano. Esto es exactamente
   para lo que sirve ampliar la muestra, y es la razon por la que el sesgo de seleccion se
   declaro desde el principio.
3. **El crecimiento de volumen se fortalece a −3,18:** los activos cuyo volumen se dispara
   rinden MENOS despues. Señal nueva que solo aparecio al ampliar.
4. **El momento sigue sin ser significativo en ningun horizonte ni universo.**

### La estrategia: EMPEORA al ampliar, y falla el criterio por mas margen

| | 30 pares | **100 pares** |
|---|---|---|
| estrategia OOS | +977,4 % (dd 62,3 %) | **+281,1 %** (dd 80,1 %) |
| BTC | +265,0 % (dd 69,2 %) | +265,0 % (dd 69,2 %) |
| spread medio | +2,75 % | +3,13 % |
| **mediana del spread** | +0,32 % | **−0,30 %** |
| efecto | 1,29 | **0,83** |
| acierto | 31/60 = 52 % | **28/60 = 47 %** |
| **efecto sin el mejor periodo** | 0,84 | **0,20** |
| folds que baten a BTC | **4 de 5** | **1 de 5** |
| con tope 25 % en ambos | +199,7 % vs +73,7 % | **+108,9 % vs +73,7 %** |

**Veredicto: NO PASA, y por mas margen que antes.** El efecto recortado se desploma a 0,20.

### Por que la señal es real y la estrategia no: la razon es el mandato

Esto no es una contradiccion, es la consecuencia de que un **premio factorial es una afirmacion
RELATIVA**. El IC dice que los activos de baja volatilidad se ordenan mejor **unos respecto a
otros**. Cosechar eso requiere la pata corta: **largo baja-vol / corto alta-vol**. Una cesta
long-only concentrada en los k de menor volatilidad no cosecha el premio — queda expuesta al
beta comun de todo el mercado cripto, que es lo que domina su resultado, y ademas concentra
riesgo idiosincratico.

Y la seleccion walk-forward eligio `crecimiento de volumen` en los 5 folds porque ganaba en
muestra, para despues fallar en 4 de 5 fuera de muestra. El patron de siempre.

**El mandato queda confirmado como la restriccion vinculante, ahora por dos vias independientes:**

1. **La cota del oraculo:** incluso prevision perfecta direccional añade solo +13 % sobre
   comprar y mantener a cadencia de 5 dias.
2. **Un factor real que no se puede cosechar:** existe señal transversal a t = −4,06, replicada,
   y **"solo spot, long-only, sin cortos" impide convertirla en dinero.**

Eso es, por fin, la respuesta completa y medida a la pregunta original. Las firmas rentables
cosechan primas factoriales **con la pata corta** y con derivados. El mandato de este proyecto
excluye precisamente el instrumento que convierte la señal en retorno.

### Lo que esto implica para el LLM, definitivamente

Ningun LLM resuelve esto. La señal es una desviacion tipica y un `sort`; el obstaculo es la
**ausencia de la pata corta**, que es una decision de mandato, no un problema de inteligencia.
Añadir un LLM a una cesta long-only de baja volatilidad no cambia que le falte el instrumento.

### Hipotesis medible que queda formulada

**Largo baja-volatilidad / corto alta-volatilidad, delta-neutral, sobre los 100 pares**, con el
mismo gate: walk-forward, comisiones adversas, tope del 25 %, efecto con prueba de signo y
recorte. Requiere **levantar el mandato** para permitir cortos (perpetuos o margen). Con los
datos ya descargados es medible de inmediato; sin el cambio de mandato no es implementable.


---

## Intento 21 — La pata corta medida: NO salva el factor, y corrige mi conclusion del intento 20

El mandato restringe lo que el AGENTE puede operar, no lo que se puede investigar. Asi que la
pata corta se **midio** sin implementarla, porque ese era el numero que decidia si levantar el
mandato valia la pena.

Largo las k de MENOR volatilidad / corto las k de MAYOR volatilidad, delta-neutral 50/50,
comisiones en AMBAS patas, walk-forward con k elegida por fold, y sensibilidad al coste de
prestamo de la corta:

| coste de prestamo | total OOS | caida | efecto | acierto | recortado | con tope 25 % |
|---|---|---|---|---|---|---|
| **0 %** | **−48,3 %** | 72,4 % | 0,43 | 34/60 | 0,78 | −10,1 % |
| 10 % | −59,8 % | 76,6 % | 0,75 | 33/60 | 1,12 | −13,8 % |
| 20 % | −68,7 % | 80,2 % | 1,07 | 33/60 | 1,45 | −16,5 % |
| 40 % | −81,2 % | 85,9 % | 1,71 | 32/60 | 2,12 | −20,4 % |

**Pierde dinero incluso con prestamo GRATIS.** Y el "efecto" sube con el coste (0,43 → 1,71)
precisamente porque la media se vuelve mas consistentemente **negativa**: el efecto es
|media|/ee, asi que una media fiablemente negativa da efecto alto. Es el mismo truco que ya
se cazo en BAJISTA (efecto 3,91 con media negativa), y el criterio lo rechaza porque exige
media > 0.

### Por que pierde, y por que era predecible desde el intento 17

Gana en el **57 % de los periodos** y pierde en total: **las perdidas son mucho mayores que las
ganancias**. Eso es asimetria negativa, y es la imagen espejo exacta del hallazgo del intento 17.

**Cortar alta volatilidad en cripto es ponerse corto de billetes de loteria.** Ganas poco la
mayoria de los meses y te destruyen cuando uno multiplica. El premio de convexidad que el
intento 17 midio en la cola derecha (media positiva, mediana negativa) es precisamente lo que
hace inviable la pata corta: quien se la vende cobra una prima pequeña y asume la cola.

### Correccion de mi propia conclusion del intento 20

En F.13 escribi que **el mandato era la restriccion vinculante** y que cosechar el factor
**exigia la pata corta**. La primera mitad sigue en pie para la cota del oraculo; **la segunda
mitad era incorrecta y ahora esta medida**: levantar el mandato para permitir cortos **no**
convertiria la señal en dinero. La habria perdido mas rapido.

### El cuadro completo y cerrado

| expresion del factor | resultado |
|---|---|
| **IC transversal** (la señal) | **REAL: t = −4,06**, replicado en 2 universos, robusto a supervivencia |
| **cesta long-only** | no bate a BTC al mismo riesgo (dominada por el beta comun de cripto) |
| **largo/corto delta-neutral** | **pierde dinero** incluso con prestamo gratis (corta de convexidad) |

**La señal es estadisticamente real y no es cosechable con estos instrumentos, en ninguna
direccion.** Y eso explica, mejor que cualquier argumento anterior, por que en cripto dominan
los creadores de mercado y las mesas de arbitraje y no los fondos factoriales: **ellos no
asumen riesgo de convexidad.** Cobran spread y diferencias de precio, que son pagos acotados.

### Convergencia

21 intentos. Toda expresion disponible del unico factor real hallado esta medida y refutada, y
la unica hipotesis que queda abierta (seleccion por narrativa con un LLM) sigue bloqueada por
ausencia de corpus con marca temporal auditable — no por falta de diseño, que esta especificado
en F.6 y F.8. **Seguir iterando añadiria intentos sin añadir informacion.**


---

## Intento 22 — Captura de spread / rejilla: ya estaba medida y refutada

Era la unica estructura que habia descartado **por argumento** ("es un juego de latencia") y no
por medicion. Verificado en vez de asumido: `data/validation/multislot-study.json` (24-sep-2026,
barrido de **192 configuraciones**, comisiones adversas, sensibilidad a vecinos) ya la midio.

Y con una **ventaja injusta a su favor** — eligiendo la mejor configuracion *despues* de ver
cada ventana:

| ventana | comprar y mantener | mejor rejilla | caida | bate? |
|---|---|---|---|---|
| bajista 2021-11 a 2022-11 | −73,3 % | −4,6 % | 5,7 % | si, pero todo-liquidez da **0 %** y tambien lo bate |
| alcista 2020-2021 | +752,4 % | +46,5 % | 29,7 % | no |
| **completo 2020-2026** | **+953,6 %** | **+73,8 %** | 29,7 % | no |
| ultimos 5 anos | +57,9 % | +22,6 % | 23,5 % | no |
| medio-bajista a 2022-06 | +179,8 % | +24,0 % | 29,7 % | no |
| recuperacion 2023-2024 | +460,2 % | +30,2 % | 5,8 % | no |

**1 de 6 ventanas**, y la unica que gana la gana tambien quedarse quieto en USDT. El propio
estudio declara su clase de evidencia como `BAR_PROXY_1H_APPROXIMATION` y lista que sin spread
BBO historico ni flujo de ordenes **puede rechazar un diseño pero no probar rentabilidad**.

Eso cierra el argumento sobre creacion de mercado para una cuenta minorista: la version
accesible sin latencia ni rebajas de maker —una rejilla— esta medida y pierde contra tener el
activo por un factor de **13x** en el periodo completo.

---

# CONVERGENCIA — 22 intentos, todas las estructuras del mandato medidas

| estructura | veredicto medido |
|---|---|
| Timing direccional sobre BTC | **nada**: 4 mediciones de correlacion en cero; techo del oraculo **+13 %** |
| Inputs de flujo como señal temporal | 5 de 24 pares a 1 ee, pero **0 de 7 folds** baten al estatico |
| Carry (largo spot / corto perpetuo) | real: **11,5 % anual** historico, pero **3,0 % en 2026**; exige cortos |
| Momento transversal | **no significativo** en ningun horizonte ni universo |
| **Baja volatilidad transversal** | **SEÑAL REAL: t = −4,06**, replicada en 2 universos, robusta a supervivencia |
| → cesta long-only | no bate a BTC al mismo riesgo (la domina el beta de cripto) |
| → largo/corto delta-neutral | **pierde** incluso con prestamo gratis (corto de convexidad) |
| Rejilla / captura de spread | **1 de 6 ventanas** con seleccion post-hoc; 13x peor en el periodo completo |

**La conclusion que sobrevive a 22 intentos:** existe una señal transversal estadisticamente
real y **no es cosechable con los instrumentos de este mandato en ninguna direccion**. Lo que
cobran las firmas rentables son **pagos acotados** —spread, diferencias de precio entre venues,
financiacion— y ninguno de ellos es accesible a una cuenta minorista spot de un solo venue.

**Recomendacion operativa, sin cambios desde que se midio:** fraccion constante de **~18 % en
BTC con banda de rebalanceo del 10 %**. +140 % en 9,1 anos, caida 23,7 %, **11 rebalanceos en
total**. Sin LLM, sin factor, sin pata corta, sin rejilla.

**La unica hipotesis que queda abierta** es la seleccion transversal por narrativa con un LLM
(especificada en F.6 y F.8), bloqueada por **ausencia de corpus con marca temporal auditable**.
No esta refutada: no es comprobable. Esa distincion se mantiene.


---

## Intento 23 — El corpus con marca temporal: CONSEGUIDO y auditable. Y un defecto propio grave.

### 23a. DEFECTO EN MI PROPIO HALLAZGO PRINCIPAL, encontrado y corregido

Al mapear activos a Wikipedia descubri que el "universo amplio de 100 pares" del intento 20
estaba **truncado alfabeticamente**:

```
distribucion por primera letra: {1:2, A:34, B:14, C:17, D:11, E:10, F:8, G:4}
```

Se cortaba en `GLMUSDT`. **Todo de H a Z faltaba** — SOL, XRP, LTC, DOGE, MATIC, ZEC, TRX, XMR.
Mi tope de 150 combinado con iteracion alfabetica y el guard de tiempo corto en 100 aceptados
mientras escaneaba en orden. Asi que cuando escribi "replica en un universo independiente y
3,3x mayor" era un **corte alfabetico**, no una muestra representativa.

Universo completado: **254 pares, alfabeto entero 1-Z**, definicion limpia y declarable ("todo
par USDT spot con >= 900 barras diarias"), sin seleccion por mi parte. Y al corregirlo **el
hallazgo se FORTALECE**, con **14.526 observaciones activo-periodo**:

| señal | 30 (a mano) | 100 (truncado) | **254 (completo)** | solo sobrevivientes |
|---|---|---|---|---|
| **volatilidad 30d** | −5,23 | −4,06 | **−4,76** | **−4,85** |
| **crecimiento de volumen** | −1,29 | −3,18 | **−4,09** | **−4,27** |
| **volumen medio 30d** | +2,74 | −2,08 | **−3,19** | **−3,23** |
| **momento 30d** | −1,21 | −1,69 | **−2,54** | **−2,61** |
| momento 30d ajustado vol | −1,08 | −1,82 | **−2,94** | **−3,11** |

**Cinco señales a |t| >= 2 (seis entre sobrevivientes), todas NEGATIVAS.** Y el momento ahora
si es significativo pero **con el signo invertido: es REVERSION a corto plazo, no momento.**

Las cinco apuntan al mismo sitio —"menor es mejor"— asi que probablemente son **un solo factor**
y no cinco: pequeño, tranquilo y castigado rinde mas. Es el cluster clasico de bajo-riesgo +
tamaño + reversion, medido aqui sobre el universo completo y robusto a supervivencia.

### 23b. El corpus auditable: CONSEGUIDO, y por que si lo es

Dos fuentes verificadas en vivo, gratuitas y sin credenciales:

| fuente | que da | por que es auditable |
|---|---|---|
| **Wikimedia Pageviews API** | conteos de visitas **diarios** desde 2015 | un conteo de 2019-01-01 **no se puede reeditar despues**: es telemetria publicada, no un artefacto editorial |
| **Wikipedia Revisions API** | el **texto exacto** que un articulo tenia en una fecha pasada | cada `revid` es inmutable y su timestamp es el momento real de la edicion |

Eso es precisamente lo que un archivo de noticias NO da: ahi las fechas de publicacion se
revisan, los articulos se editan y las cuentas se borran. **El bloqueador declarado en F.6/F.8
queda levantado: el corpus existe.**

*Defecto propio por el camino, misma familia que todo lo anterior:* mi primer fetch devolvio 0
activos porque un `except Exception: return []` se tragaba un **timeout de 20 s** en los rangos
de 7 años. Con 60 s funciona. Mi propio codigo oculto el error.

### 23c. Y la cobertura del corpus NO sostiene la hipotesis transversal

De los 254 pares del universo, solo **8** tienen articulo con >= 900 dias de pageviews:
ADA, ALGO, AXS, BTC, DOGE, ETH, LTC, UNI.

**Wikipedia cubre lo grande y establecido**, que es exactamente donde hay menos dispersion
transversal. Un IC transversal con 8 nombres por periodo no es medible: mi propio codigo exige
>= 20 por periodo, y lo mantengo.

Asi que se midio lo que esos 8 activos SI sostienen: la atencion como señal **temporal**, con
el mismo metodo no solapado de `flow_diagnosis.py`.

| señal | horizonte | rho medio | t entre 8 activos |
|---|---|---|---|
| atencion z30 | 48h | +0,0181 | +2,70 |
| atencion z30 | 168h | +0,0285 | +2,66 |
| crecimiento de atencion 7v30 | 168h | +0,0370 | +2,47 |

**Y hay que leerlo con precision, porque invita a confundirse:**

1. **Por activo, NADA alcanza 2 errores estandar.** BTC da +0,30 / +0,05 / −0,70 / −0,44. ETH y
   DOGE igual.
2. El "t entre activos" solo dice que **el signo es consistente** entre los 8, no que el efecto
   sea grande.
3. **Ese t esta inflado:** los 8 activos estan fuertemente correlacionados por el beta comun de
   cripto, asi que no son 8 observaciones independientes. Tratarlos como si lo fueran sobreestima
   la significancia.
4. **El rho es +0,018 a +0,037**, el mismo orden de magnitud que las señales de flujo del intento
   15 que ya fallaron la prueba economica: 0 de 7 folds, −40,7 % contra +675,0 %. Un rho de 0,03
   no paga 20 bps de ida y vuelta.

### Veredicto sobre la ultima hipotesis

**El bloqueador cambio de naturaleza, y eso es progreso real:**

- **Antes:** "no existe corpus con marca temporal auditable". **Levantado:** existe, verificado,
  gratuito, y con texto punto-en-el-tiempo ademas de atencion.
- **Ahora:** el corpus **cubre 8 de 254 activos**, y la hipotesis que habia que probar era
  **transversal** (seleccion por narrativa entre muchos activos). 8 nombres no la sostienen.

No esta refutada: sigue sin ser comprobable, pero por una razon distinta y mas concreta —
**cobertura**, no existencia. Lo que haria falta es un corpus con marca temporal que cubra la
cola de activos pequeños, que es justo donde el factor medido (pequeño, tranquilo, castigado)
dice que esta la dispersion. Wikipedia, por construccion, no escribe sobre ellos.


---

## Intento 24 — Corpus que SI cubre la cola: anuncios de Binance. Atencion refutada, antiguedad hallada.

El bloqueador del intento 23 era **cobertura**: Wikipedia solo cubria 8 de 254 activos (3 %).
Buscado un corpus que llegue a la cola, y encontrado.

### El corpus

`data/history/binance-announcements.json`, **3.320 articulos con fecha de publicacion**, bajados
del CMS publico de Binance:

| catalogo | articulos | rango |
|---|---|---|
| New Cryptocurrency Listing | **2.276** | 2017-07-21 .. 2026-10-01 |
| Delisting | **439** | 2022-02-17 .. 2026-10-01 |
| Maintenance Updates | **605** | 2022-02-15 .. 2026-10-02 |

**COBERTURA: 252 de 254 activos (99 %)**, 231 con >= 3 menciones (91 %), frente a **8 de 254
(3 %)** de Wikipedia. Es **31x mejor** y cubre exactamente la cola de activos pequeños. Los 2
que faltan son tickers de una sola letra (T, W) que mi tokenizador no desambigua: limitacion de
tokenizacion, no de cobertura.

Y un segundo corpus auditable **que ya estaba en disco**: la **fecha de primer cierre** de cada
par. Cobertura **254/254 = 100 %**, y es auditable de la forma mas simple posible — la primera
barra existe o no existe, no se puede reeditar.

### HALLAZGO NUEVO: la antiguedad del listado, t = +4,57

| señal | IC medio | t | periodos+ |
|---|---|---|---|
| volatilidad 30d | −0,1194 | −4,76 | 26/86 |
| **antiguedad del listado (log)** | **+0,0773** | **+4,57** | **58/86** |
| crecimiento de volumen | −0,0666 | −4,09 | 26/86 |
| volumen medio 30d | −0,0643 | −3,19 | 31/86 |
| momento 30d ajustado vol | −0,0482 | −2,94 | 32/86 |
| momento 30d | −0,0496 | −2,54 | 39/86 |

**Los listados ANTIGUOS rinden mas que los nuevos**, con el signo positivo mas consistente de
todo el estudio (58 de 86 periodos). Es el efecto conocido de bajo rendimiento de las nuevas
cotizaciones, medido aqui con **cobertura perfecta y auditabilidad perfecta**. Ya son **seis**
señales a |t| >= 2 sobre 14.526 observaciones activo-periodo.

### Y la hipotesis de la narrativa: REFUTADA con el corpus correcto

| señal derivada del corpus | IC medio | t |
|---|---|---|
| anuncios en 90d | −0,0130 | **−0,86** |
| anuncios en 180d | −0,0093 | **−0,58** |
| avisos de deslistado en 180d | +0,0073 | **+0,59** |

**Ninguna alcanza 1 error estandar.** La intensidad de anuncios no lleva informacion
transversal, medido sobre un corpus que cubre el 99 % del universo. Esa era la pregunta que
quedaba, y ahora tiene respuesta en vez de un bloqueador.

### Pero hay que ser preciso sobre QUE se ha refutado

Medi el **recuento** de menciones, no el **contenido semantico**. Un LLM leeria el texto y
juzgaria de que habla; yo conte cuantas veces aparece el ticker. Asi que lo refutado es
**"la intensidad de anuncios como señal"**, no **"la comprension de narrativa"**.

La diferencia importa y no la disimulo. Lo que si queda establecido:

1. **El corpus existe, cubre la cola y es auditable.** Los dos bloqueadores anteriores
   (existencia y cobertura) estan levantados.
2. **El proxy numerico barato falla.** Y en este proyecto el proxy barato fallando ha predicho
   correctamente el fracaso de la version cara en cada ocasion previa.
3. **La version semantica es ahora comprobable**: 3.320 titulos con fecha, un LLM que los lee y
   puntua, medido con el mismo gate (IC transversal, luego prueba economica con jackknife y tope
   del 25 %). Requiere llamadas a un modelo, que es la via que esta vetada por coste.

El siguiente paso ya no es de datos, es de presupuesto: **leer 3.320 titulos con un modelo
local** (el servidor tiene `qwen3:30b-a3b`) costaria horas de GPU pero cero dolares. Esa es la
unica forma de cerrar la hipotesis sin gastar tokens de terceros.

---

## Intento 25 — Los titulares leidos por el modelo LOCAL. Hipotesis cerrada, con un error de diseno mio.

Ejecutado con `qwen3:30b-a3b` en el servidor via Ollama en loopback: **cero tokens de terceros**,
que es la restriccion permanente del dueno. `research/score_announcements.py`,
**439 de 439 titulares puntuados, 0 lotes con fallo**, salida en
`data/validation/announcement-scores-delisting.json`.

### Dos defectos de instrumento corregidos antes de medir

1. El modelo emitia **prosa de razonamiento** ("Okay, let's tackle this problem...") pese a
   `think: false`. Resuelto con el parametro `format` y un esquema JSON, el mismo mecanismo que
   `OllamaClient` usa en produccion: un esquema no pide una forma, **constriñe el decodificador**
   a ella.
2. El primer lanzamiento murio a los 150/439 sin rastro de OOM. El script era **reanudable por
   diseno** (escribe tras cada lote y salta los ya puntuados), asi que relanzarlo continuo desde
   150 en vez de empezar de cero. Esa decision de diseno salvo 20 minutos de CPU.

### LA PRUEBA PRE-DECLARADA NO SE PUDO CORRER, y el culpable soy yo

El umbral declarado era: exceso **monotono** en el impacto del modelo, y contraste
negativo-vs-positivo con **|t| >= 2**.

**Inejecutable sobre este corpus.** Escogi el catalogo de deslistados por ser el de mayor señal,
pero es **uniformemente negativo por construccion**: de los 31 eventos utilizables, 27 puntuaron
-2 y 4 puntuaron -1. **No hay grupo positivo contra el que contrastar**, asi que la monotonia no
tiene nada sobre lo que ser monotona. Es un error de diseno mio, no un resultado del mercado, y
se registra en vez de sustituirse por una prueba mas facil.

Peor aun para el proposito del experimento: el modelo etiqueto **366 de 439** titulares como
`delisting` con impacto -2. En este subconjunto **su juicio semantico es REDUNDANTE con el
nombre del catalogo** — justo la distincion que el experimento debia probar. Gaste ~50 minutos
de CPU para confirmar que un aviso de deslistado es mala noticia, cosa que la etiqueta ya decia.

### Lo unico medible: estudio de evento de una muestra

`research/delisting_event_study.py`. Tras un aviso de deslistado, ¿rinde el activo PEOR que BTC
a 30 dias? Ventana que empieza el dia DESPUES del anuncio, BTC como referencia para que el beta
comun de cripto se cancele.

| | |
|---|---|
| eventos utilizables | **31** |
| exceso **medio** (activo - BTC) | +110,90 % |
| exceso **mediana** | **+0,65 %** |
| error estandar 58,65 % | **t = +1,89** |
| eventos con exceso negativo | **14 de 31 = 45 %** |
| prueba de signo | **p = 0,7634** |
| rango | -33,7 % a **+1.089,5 %** |

**VEREDICTO: NO SOSTENIDA.** El umbral exigia t <= -2 con signo consistente; sale **+1,89**, con
el signo contrario al de la hipotesis. La media la domina **un unico evento de +1.089,5 %**, la
mediana es +0,65 % —o sea cero— y el 45 % de eventos negativos es una moneda.

Y aparece **otra vez la firma de convexidad**: media +110,9 % contra mediana +0,65 %. El mismo
patron del intento 17, ahora en los eventos de deslistado.

### Cierre de la ultima hipotesis

| forma de la hipotesis | estado |
|---|---|
| **transversal** (seleccion por narrativa entre muchos activos) | **CERRADA por densidad**, sin necesidad del modelo: el **93 %** de las celdas activo-periodo no tiene ningun anuncio, mediana de **13** activos con señal por periodo frente a un suelo de 20. Ningun modelo ordena 254 activos con informacion sobre 13 |
| **de evento** (¿predice el anuncio el retorno posterior?) | **MEDIDA y NO SOSTENIDA**: mediana +0,65 %, 45 % de aciertos, p = 0,76 |
| **monotonia del impacto semantico** | **INEJECUTABLE** por mi eleccion de catalogo: sin variacion de signo |

Lo que haria falta para cerrar la tercera: puntuar tambien los **2.276 titulares de listados**
para tener grupo positivo, otras ~3 horas de CPU del servidor con el agente vivo parado. Dado
que las dos formas que si se midieron no sostienen nada y que el juicio del modelo resulto
redundante con la etiqueta en el subconjunto ya probado, **no lo recomiendo**: seria gastar tres
horas para completar una prueba cuyas dos hermanas ya fallaron.
