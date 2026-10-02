# Informe ejecutivo — 1 de octubre de 2026

Un día de medición sobre CryptoAgent 3.0. Nueve horas, dos líneas de trabajo, **ninguna orden
colocada** y ningún umbral relajado.

---

## 1. El titular

**El agente no tiene ventaja de momento, y ahora sabemos que su único logro aparente tampoco
era suyo.**

Dos resultados nuevos, los dos negativos y los dos sólidos:

1. La ventana alcista con las ocho correcciones midió **+68,94 %** con **correlación de timing
   +0,03**. Es la **cuarta** medición independiente de cero (+0,01, +0,02, −0,11, +0,03; error
   estándar 0,15). Ninguna corrección de defecto puede fabricar criterio de momento.
2. El resultado bajista que se celebraba (−2,39 % frente a −12,86 % de comprar y mantener)
   **lo reproduce tener el 15 % en BTC de forma estática y no decidir nada**. A su caída del
   6,1 %, un estático habría perdido −2,0 %; el agente perdió −2,4 %. El acto de decidir no
   añadió nada medible.

Y un veredicto cerrado en la investigación paralela: **en los cuatro regímenes de mercado,
fuera de muestra, nada supera a quedarse en USDT.**

---

## 2. Fase A — el número que faltaba

| | medido |
|---|---|
| retorno | **+68,94 %** |
| caída máxima | 16,99 % |
| captura de comprar y mantener | 37 % |
| correlación de timing | **+0,03** (= cero) |
| veredicto del gate | **RECHAZADO** |

**No es una mejora demostrada.** Es el mejor de los cinco intentos sobre esta ventana, pero
está **+5,34 pp** sobre la mejor anterior y las tres corridas comparables abarcan **10,5 pp**:
cae dentro del ruido.

Lo único que la corrección del octavo defecto movió de estado fue la preservación de capital,
de fallar a pasar, con +3,0 pp justo en el umbral.

**Coste operativo descubierto:** una corrida cuesta **3,7 h**, no las 2,8 h documentadas
(185-187 s por decisión, y la primera cuesta 405 s por la carga en frío del modelo de 18,6 GB).

---

## 3. El noveno defecto estructural, cobrado en vivo

Al lanzar la corrida capturé el PID equivocado, y eso destapó un defecto real: el notificador
envió a Slack un **`*Backtest terminado* · APROBADO`** con los números de la ventana bajista de
septiembre **mientras la corrida real iba por la decisión 1 de 60**.

*Mecanismo:* un PID ya muerto se trataba como "acaba de terminar", y luego se leía la traza del
path por defecto sin comprobar que perteneciera a la corrida vigilada. **Cero pruebas** cubrían
el fichero, igual que los ocho defectos anteriores. Es la **tercera** vez que un valor por
defecto silencioso fabrica un número falso en este proyecto.

Corregido: PID inexistente sale con código 2 y una traza anterior a la vigilancia se rechaza.

---

## 4. Estudio de regímenes — cerrado, con veredicto definitivo

**14 intentos registrados.** Encargo: hallar el mejor playbook para alcista, bajista, lateral y
alta volatilidad sin dirección, solo spot, techo de caída 25 %, comisiones reales.

### El resultado

**En los cuatro regímenes, fuera de muestra, nada supera a quedarse en USDT.** Las cuatro
formas de fallar son distintas y eso es lo informativo:

| régimen | cómo falla |
|---|---|
| **BAJISTA** | retornos **negativos**: 6 de 7 variantes pierden. 7 de 7 folds eligieron USDT. Test limpio 2018-2019: entre −27,4 % y −61,8 %. |
| **ALCISTA** | todas positivas (+66 % a +262 %) pero **un solo tramo las carga**: 5 de 13 tramos positivos, mediana **−3,3 %**, prueba de signo **p = 0,867**, y el jackknife lleva +126,0 % a **+19,5 %** quitando el rally post-COVID. |
| **LATERAL** | efecto 0,22 en el test limpio tras parecer 1,00 en selección. |
| **ALTA_VOL** | efecto entre 0,43 y 0,92 según el instrumento; nunca estable. |

### La señal de alarma que lo decidió

**El régimen "ganador" cambió tres veces** al corregir defectos de mi propio instrumento:
LATERAL → ALTA_VOL → BAJISTA/LATERAL, y los tres quedaron refutados al confirmarlos. Ningún
cambio tocó umbrales ni criterios: todos fueron arreglos de defectos. **Que la identidad del
ganador no sea estable es la firma del ruido siendo seleccionado**, no de un efecto.

### Defectos de instrumento que encontré y corregí en mi propio trabajo

| defecto | efecto |
|---|---|
| Objetivo escalar gameable | premiaba un detector que oscila cada 3 días: 366 transiciones, retardo −26,5 d, 96 % de falsas alarmas, y "ganaba" |
| Barrí el eje equivocado | retardo idéntico de 15,0 d en 12 celdas: lo gobierna la ventana, no los umbrales |
| **Exigía racha ininterrumpida en vez de cobertura** | **borró 723 días, el 38 % de la historia**: 2020 y 2021 enteros, incluidos el crash del COVID y el alcista de 2021 |
| Sin duración mínima de régimen | un dip de 4 días era un "régimen", y eso hizo pasar un playbook bajista que era dip-buying |
| Look-ahead propio, evitado en el acto | la duración mínima la implementé mirando toda la serie; sustituida por permanencia mínima causal |
| `persistence_days=5` adoptaba al 4.º día | un parámetro que no hacía lo que declaraba |

### Datos

El dataset se extendió a la inception de Binance: **79.477 barras horarias, 2017-08-17 →
2026-09-16, 9,1 años**, con integridad verificada (0 precios inválidos, 0 duplicados, 94,5 % de
días etiquetados y los 180 restantes son el calentamiento). Se escribió a un directorio nuevo
para no invalidar la procedencia de los resultados anteriores.

### Por qué converge

**BAJISTA aporta solo 4-5 episodios independientes en 9,1 años.** Es un techo de potencia
estadística, no de imaginación. Y es explicable estructuralmente: solo spot, sin cortos, así que
batir a estar fuera en un declive exige acertar los contrarrallies — la ventaja de momento
medida en cero cuatro veces.

---

## 5. El gate, reescrito alrededor del pivote

Se ejecutó el pivote declarado de antemano: el producto ya no es "batir a comprar y mantener"
sino **"comprar y mantener con la caída recortada"**.

**Y el pivote no abarató el gate: cerró un agujero.** El gate viejo comparaba contra comprar y
mantener **crudo**, así que estar menos expuesto contaba como victoria — pero **tener menos BTC
consigue exactamente ese canje sin habilidad alguna**. La hipótesis nula correcta es el
desapalancamiento estático, así que el agente se puntúa ahora contra un comprar-y-mantener
**desapalancado a su propia caída realizada**.

Dos criterios **añadidos**, ninguno relajado. El sustituto del criterio retirado es **más duro
por 63 puntos** (+154,9 % exigidos donde el viejo pedía +92,2 %).

También se reparó el criterio de discriminación: se mide **entre regímenes**, no como minoría
dentro de la ventana. Esa minoría contaba decisiones y no condicionamiento — en la ventana
bajista el 12 % lo producían **4 decisiones** en regímenes apenas vistos, mientras en los dos que
el agente sí vio su exposición difería un **2,9 %**.

### Veredicto del gate reparado

| ventana | antes | ahora |
|---|---|---|
| alcista | RECHAZADO 6/8 | **RECHAZADO 6/9** |
| bajista | **APROBADO 8/8** | **RECHAZADO 7/9** |

---

## 6. Lo que requiere tu decisión

**El servicio vivo `cryptoagent3-llm-agent` tiene autoridad de órdenes concedida bajo el gate
anterior**, que la ventana bajista aprobaba 8/8. Bajo el gate nuevo ninguna ventana aprueba.

Es cuenta **DEMO**, sin dinero real, así que no es una emergencia. Pero su autoridad se apoya en
un criterio que ya no se sostiene.

---

## 7. Una prescripción que no apliqué

Se pidió poner la exposición a 0 % en el régimen bajista del agente vivo. **No lo hice, y la
medición es la razón:**

1. En `r1 "bajista profundo"` el agente **ya estaba a cero**: 0,0 % observado en 16 decisiones.
   Bajar su parámetro es un **no-op** sobre la evidencia.
2. La pérdida vino de **r2**, con 3 decisiones al 78 % de exposición.
3. Esas decisiones estaban **correctamente corroboradas**: precio **+14,2 %** sobre su media de
   200 días, 0 de 3 por debajo, mercado subiendo 19 % a 90 días.

**No es un defecto, es la ausencia de ventaja de momento.** Aplicarlo sería afinar un parámetro
justificado por el retorno de una ventana, que es exactamente lo que ha fallado repetidamente
aquí.

---

## 8. Calidad del trabajo

| | |
|---|---|
| pruebas | **480 → 544** |
| `ruff` y `mypy` | limpios |
| órdenes colocadas | **0** |
| umbrales del gate relajados | **0** |
| regiones de prueba limpias gastadas | 2, ambas registradas como gastadas |

---

## 9. Dónde está cada cosa

| entregable | ruta |
|---|---|
| Bitácora del estudio, 14 intentos con los negativos | `research/REGIME-STUDY-ATTEMPTS.md` |
| Diseño pre-registrado antes de medir | `research/REGIME-STUDY-PREREGISTRATION.md` |
| Estado por tarea con todos los números | `tasks.md` (A.1-A.3, E.2-E.3, R.1-R.18) |
| Fases y reglas de avance | `roadmap.md` |
| Gate reescrito | `scripts/gate_llm_agent.py` |
| Taxonomía y detector de regímenes | `research/regime_taxonomy.py` |
| Walk-forward por régimen | `research/regime_walkforward.py` |
| Extensión del dataset a 2017 | `research/extend_history.py` |
| Traza de la corrida alcista (servidor, inmutable) | `data/validation/runs/2026-10-01-alcista-1260-1560-60d-paso5-ocho-defectos.json` |

---

## 10. Lo que yo haría ahora

El sistema hace bien **una** cosa medible: recortar la caída. Pero el gate simétrico acaba de
mostrar que **esa parte la consigue el desapalancamiento estático sin modelo**. Así que la
pregunta honesta ya no es cómo mejorar el agente, sino **si hay algún producto que justifique
operarlo**.

Lo único barato y decisivo que queda sin probar es la Fase B del roadmap: **el mismo backtest
con un modelo frontera por API**, cambiando solo el cliente del modelo. Si un modelo mejor tiene
ventaja de momento donde `qwen3:30b-a3b` no la tiene, todo lo construido sirve y solo había que
cambiar el cerebro. Si tampoco la tiene, la ventaja no está en el modelo y la conclusión honesta
es que el producto correcto es comprar y mantener con un tope de riesgo estático — sin LLM.
