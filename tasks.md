# Tasks — Agente LLM de exposición BTC/USDT

Contexto en `handover.md`. Fases y criterios de salida en `roadmap.md`.

Marcadores: `[ ]` pendiente · `[~]` en curso · `[x]` hecho · `[B]` bloqueado

## Contrato operativo del loop

1. Elegir el **único siguiente paso de mayor leverage** que no dependa de una tarea
   pendiente, y ejecutarlo completo.
2. Al cerrar una tarea, añadir debajo una nota con fecha, el número medido y la ruta del
   artefacto. Una tarea sin evidencia no está cerrada.
3. No marcar `[x]` por haber escrito código: el criterio verificable tiene que cumplirse.
4. **Un resultado negativo cierra la tarea igual que uno positivo.** Registrarlo y seguir.
5. Si aparece una ambigüedad reversible, avanzar con el supuesto escrito. Si cambia el riesgo
   o toca dinero, publicar el bloqueador **una sola vez** y detenerse.
6. No bajar umbrales del gate, no borrar hallazgos negativos, no reinterpretar costes.

## Antes de cada backtest, sin excepción

```bash
# 1. parar el agente vivo: el modelo ocupa 18.6 GB de 23 GB, no caben los dos
sudo systemctl stop cryptoagent3-llm-agent

# 2. archivar la traza anterior ANTES de lanzar, o se pierde
cp data/validation/llm-agent-backtest.json \
   data/validation/runs/$(date +%F)-<descripcion>.json
chmod 444 data/validation/runs/$(date +%F)-<descripcion>.json

# 3. lanzar desacoplado de la sesion ssh, con el notificador armado
cd /home/ubuntu/workplace/cryptoagent3.0
setsid nohup env PYTHONPATH=src:research .venv/bin/python -B \
  research/backtest_llm_agent.py --decisions 60 --step-days 5 --end-day 1560 \
  > /tmp/backtest.log 2>&1 < /dev/null &

# 3b. el PID del shell NO es el PID del backtest: `env` y `setsid` dejan envoltorios
#     que mueren al instante. Resuelve el PID real por argv, nunca por $!:
PID=$(ps -eo pid,args | grep "[b]acktest_llm_agent" | awk '{print $1}' | head -1)
setsid nohup env PYTHONPATH=src:research .venv/bin/python -m scripts.notify_backtest \
  --wait-for-pid $PID --slack > /tmp/notify.log 2>&1 < /dev/null &

# 3c. comprobar que el notificador quedo BLOQUEADO (log vacio). Si escribio algo al
#     instante, el PID era falso: desde el noveno defecto esto sale con codigo 2 en vez
#     de publicar el informe de la corrida anterior.

# 4. AL TERMINAR: volver a arrancar el agente vivo
sudo systemctl start cryptoagent3-llm-agent
```

`/tmp/backtest.log` esta **bloque-bufferizado**: `tail` va muy por detras del progreso real.
Para saber si trabaja, mirar el tiempo de CPU de `llama-server`, no el log.

La orden protectora vive en el exchange, así que la posición sigue cubierta con el servicio
parado. Pero el agente no decide, y eso no debe durar más que el backtest.

---

## Fase A — Cerrar el hueco de medición

- [x] **A.1 Correr la ventana alcista con las 8 correcciones.**
      Días 1260-1560, 60 decisiones, paso 5, `--end-day 1560`.
      *Criterio cumplido:* traza archivada inmutable en
      `data/validation/runs/2026-10-01-alcista-1260-1560-60d-paso5-ocho-defectos.json`
      (87.582 B, `chmod 444`, md5 `2573a92a…` idéntico al vivo).

      **2026-10-01, cerrada. +68.94%, dd 16.99%, captura 37%.**
      Corrida real de 3 h 05 min (PID 2118160), 60/60 decisiones, 0 fallos del modelo.
      Ritmo 185-187 s/decisión en régimen (la decisión 1 midió 405 s por la carga en frío
      del modelo, lo que infló el presupuesto documentado de 2.8 h a 3.7 h reales).
      Preparación verificada antes de lanzar: código del servidor **byte-idéntico** al HEAD
      local `4b6e81b` (`rsync -rcn`), defecto 8 (`7411222`) presente, traza anterior sellada
      a 444 sin pérdida.
      `cryptoagent3-llm-agent` **rearrancado y `active`** (PID 2168816) tras 3 h 05 min
      parado; la orden protectora siguió viva en el exchange todo el tiempo.

- [x] **A.2 Evaluar esa corrida con las cuatro herramientas.**
      *Criterio cumplido:* veredicto, captura, correlación de timing y beneficio por
      régimen quedan escritos aquí.

      **Gate: RECHAZADO.** 6 de 8 criterios pasan; fallan exactamente los dos de captura.

      | criterio | medido | umbral | |
      |---|---|---|---|
      | fallos del modelo | 0/60 = 0.0% | ≤ 5% | PASA |
      | decisiones | 60 | ≥ 50 | PASA |
      | minoría de exposición | 33% (INVERTIDO 67%) | ≥ 5% | PASA |
      | cambios de dirección | 13/60 = 22% | ≤ 30% | PASA |
      | comisión pagada | 1.68% | ≤ 6% | PASA |
      | ventaja en drawdown vs b&h | 17.0% vs 20.0% = **+3.0pp** | ≥ 3pp | **PASA (al límite)** |
      | captura de b&h | +68.9% vs +184.4% = **37%** | ≥ 50% | **FALLA** |
      | captura del cuantitativo | +68.9% vs +132.1% = **52%** | ≥ 75% | **FALLA** |

      **Correlación de timing: +0.03.** Con 46 intervalos utilizables el error estándar es
      ~0.15, así que nada dentro de ±0.29 se distingue de cero. **Es cero.** Y es la
      **cuarta** medición independiente de cero en este proyecto: +0.01, +0.02, −0.11, +0.03.
      Exposición efectiva 52%, captura/exposición **72%**: por debajo del 100%, es decir que
      la exposición que tuvo se gastó en los tramos peores, no en los mejores.

      **Beneficio por régimen** (efecto = |media| / error estándar; por debajo de 1 no se
      distingue de cero):

      | régimen | tramos | total | efecto | invertido |
      |---|---|---|---|---|
      | 0 recuperación lateral | 11 | −7.02% | 1.0 | 0% |
      | 2 consolidación | 21 | **+46.15%** | **1.9** | 65% |
      | 3 alcista fuerte | 27 | +20.44% | 1.1 | 75% |

      Hallazgo incómodo: el que gana es **r2 consolidación** (único efecto claramente > 1),
      mientras **r3 "alcista fuerte" se lleva el 75% de exposición y aporta un tercio de lo
      que aporta r2**. La doctrina y el reparto de capital no coinciden con dónde está el
      beneficio.

      **Corroboración del defecto 8: aguanta.** r3 ahora solo tiene **2 de 28** tramos con
      el precio por debajo de su media de 200 d (antes 8 etiquetas con el precio 6.4% por
      debajo, que valían −10.39%). r2: 0 de 21. r0: 10 de 11 por debajo, y el playbook
      correctamente **no lo opera** (0% invertido).

- [x] **A.3 Comparar contra las corridas alcistas anteriores.**
      *Criterio cumplido:* la mejora **cae DENTRO del rango de ruido**. No es una mejora
      demostrada.

      | corrida | retorno | captura | dd |
      |---|---|---|---|
      | playbook 1.2 con escalado | +63.60% | 34% | 16.1% |
      | autoridad plena | +59.51% | 32% | 17.9% |
      | mezcla | +53.08% | 29% | 17.7% |
      | **ocho defectos (esta)** | **+68.94%** | **37%** | **17.0%** |

      Las tres anteriores comparten ejecución y solo cambian la política de exposición:
      abarcan **10.5pp** (53.08 → 63.60). La nueva está **+5.34pp** por encima de la mejor
      de ellas, o sea **dentro** de esa banda. Por la regla 3 del roadmap, eso es ruido.
      (`compare_runs` reporta una banda de 49.7pp al incluir `defectos-corregidos` +19.27%,
      pero esa corrida tiene otra geometría de stops y meterla aquí infla el rango; la
      comparación honesta es contra las tres de ejecución comparable.)

      **Lo que sí cambió de estado:** la preservación de capital pasó de fallar a **pasar**,
      con +3.0pp exactamente en el umbral. Es el único criterio del gate que el defecto 8
      movió.

      **Lo que no cambió, y no iba a cambiar:** la captura. Capturar la mitad de una
      referencia al alza exige criterio de momento, y el criterio de momento está medido en
      cero por cuarta vez. Ninguna corrección de defecto puede fabricarlo.

## Fase B — ¿Es el modelo, o es el problema?  ✅ RESPONDIDA GRATIS

- [B] **B.1 Modelo frontera por API: DESCARTADO por decisión del dueño.**
      No quiere gastar tokens de terceros. La credencial del repo
      (`ANTHROPIC_API_KEY`) es además un **placeholder** (`your_an...`, 23 caracteres), así que
      nunca existió acceso. Cliente escrito y **APARCADO sin correr** en
      `research/frontier_client.py`: replica `OllamaClient.verdict` exactamente (mismo
      `SYSTEM_PROMPT` importado, mismo esquema, misma validación, temperatura 0), se niega a
      arrancar sin credencial real y no está cableado a ningún backtest.
      Coste estimado si alguna vez se autoriza: **~1,50 $ por corrida** (210k tokens de
      entrada / 54k de salida), frente a 3,7 h de GPU del servidor.

- [x] **B.2 La pregunta respondida sin gastar nada: medir el TECHO, no comprar un cerebro.**
      `research/bound_clients.py` sustituye el LLM por dos decisores **calculados** (coste
      cero, segundos en vez de 3,7 h):
      **`OracleClient`** conoce el retorno futuro del intervalo que decide — es el máximo que
      la arquitectura puede dar con un cerebro perfecto. **ACAUSAL por construcción, no es una
      estrategia**, vive en `research/` y jamás puede alcanzar una ruta que coloque órdenes
      (hay prueba de cortafuegos). **`RandomClient`** es la hipótesis nula, sembrada y ajustada
      a la misma tasa de exposición del agente (67 %).

      **Ventana alcista, días 1260-1560, 60 decisiones:**

      | brazo | retorno | caída |
      |---|---|---|
      | **ORÁCULO (cerebro perfecto)** | **+207,80 %** | **13,92 %** |
      | comprar y mantener | +184,44 % | 20,00 % |
      | política cuantitativa (entrenada) | +132,06 % | 19,47 % |
      | **AZAR, 8 semillas** | **+81,77 % … +89,61 %** (media +85,0 %) | 16,7-21,7 % |
      | **LLM medido** | **+68,94 %** | 16,99 % |

      **Dos conclusiones, y la segunda no la esperaba:**

      1. **La arquitectura NO es el techo.** Un cerebro perfecto saca +207,80 % con la caída
         **más baja de todos** (13,92 %), batiendo a comprar y mantener. La maquinaria sí
         sabe expresar habilidad, así que un modelo mejor **tendría margen**.
      2. **El LLM actual está por debajo del azar, y de las 8 semillas.** El azar abarca
         7,8 pp (+81,77 a +89,61) y el LLM queda **12,8 pp por debajo de la peor semilla**.
         No es solo "sin ventaja": a esta muestra sus decisiones restan valor frente a una
         moneda ajustada a su misma exposición.
      *Reserva:* una ventana, 60 decisiones. El hueco de 16 pp contra la media del azar supera
      la banda de ruido de 10,5 pp entre variantes de política, pero no por mucho.

- [B] **B.3 Argumento publicado: el gate nuevo es inalcanzable incluso con prevision
      perfecta. No se tocó ningún umbral.**
      Pasé el gate al oráculo y **falla 7 de 9**:

      | criterio | oráculo | veredicto |
      |---|---|---|
      | `MAX_DRAWDOWN_RATIO` ≤ 0,60x | **0,70x** (13,9 % vs 20,0 %) | **FALLA** |
      | discriminación entre regímenes ≥ 30 % | **5 %** (r0=49 %, r2=53 %, r3=52 %) | **FALLA** |
      | bate al estático al mismo riesgo | +207,8 % contra +122,9 % exigidos | PASA |

      Dos problemas de calibración que solo un cerebro perfecto podía revelar:
      1. **`MAX_DRAWDOWN_RATIO = 0,60` es inalcanzable en esta arquitectura.** Ni con
         previsión perfecta baja del 0,70x, porque los stops y la cadencia de 5 días fijan un
         suelo de caída. Un criterio que ningún sistema alcanzable cumple está mal calibrado.
      2. **El criterio de discriminación penaliza la optimalidad.** La política óptima no
         depende del régimen, depende del retorno futuro — que no está correlacionado con las
         etiquetas de régimen. Por eso el oráculo reparte ~50 % de exposición en los tres
         regímenes y falla un criterio que pide 30 % de diferencia.
      Reparaciones posibles, **no aplicadas**: calibrar el ratio contra el mínimo alcanzable
      medido (0,70x) en vez de un número elegido; y exigir discriminación solo a un agente que
      *declare* condicionar por régimen, no como requisito universal.

## Fase B (original, conservada para el registro)

## Fase C — ¿Está la ventaja en otro horizonte?

- [ ] **C.1 Medir la correlación de timing a 1 h, 4 h, 1 día y 30 días.**
      Todo se ha medido a 5 días por coste de cómputo. No hace falta el backtest completo en
      cada horizonte: basta la correlación entre exposición y movimiento posterior.
      *Criterio:* una tabla de correlación contra horizonte, con errores estándar.

## Fase D — ¿Está la ventaja en un dato que no tiene?

- [ ] **D.1 Inventariar lo que el agente NO ve.**
      Hoy ve retornos, medias móviles y volatilidad. No ve libro de órdenes, flujo,
      financiación de perpetuos ni on-chain.
      *Criterio:* lista priorizada por coste de obtención contra plausibilidad.

- [ ] **D.2 Añadir una familia de features y medir el cambio en la correlación de timing.**
      Una familia a la vez. Respetar la purga y el embargo del índice histórico: un corte
      `before_day` ingenuo ya introdujo una fuga de futuro real en este proyecto.
      *Criterio:* el cambio en la correlación con su error estándar.

## Fase E — Veredicto

- [x] **E.0 La frontera sin pronóstico: qué devuelve no decidir nada.**
      `research/static_frontier.py`. Fracción constante de BTC, rebalanceada con banda,
      sobre los 9,1 años completos, marcado a mercado horario y comisiones en cada rebalanceo.
      Existe porque **todos los brazos con pronóstico pierden contra lo que intentan batir**:
      oráculo +207,8 %, comprar y mantener +184,4 %, cuantitativa +132,1 %, azar +81,8 a
      +89,6 %, LLM +68,9 %.

      | fracción en BTC | banda | retorno (9,1 años) | caída | tope 25 % |
      |---|---|---|---|---|
      | 0,18 | 10 % | +140 % | 23,7 % | **sí** (11 rebalanceos) |
      | **0,20** | **5 %** | **+160 %** | **24,1 %** | **sí** |
      | 0,25 | 10 % | +218 % | 30,6 % | no |
      | 0,35 | 5 % | +371 % | 42,7 % | no |
      | 0,50 | 5 % | +620 % | 56,2 % | no |
      | **1,00 (comprar y mantener)** | — | **+1.655 %** | **83,9 %** | no |

      **Tres hechos medidos que deciden la implementación:**
      1. **La caída NO escala linealmente con la fracción.** f=0,35 da 42,7 % de caída, no el
         29 % que daría 0,35 × 83,9 %, porque rebalancear hacia un mercado que cae compra más
         mientras cae. Sin rebalanceo, f=0,35 da +579 % con 69,1 %: **el rebalanceo recorta la
         caída de 69,1 % a 42,7 % a cambio de retorno.**
      2. **El coste del tope es brutal y es la decisión real:** pasar de tolerar 84 % de caída
         a tolerar 25 % lleva el retorno de **+1.655 % a +160 %**. Se renuncia a ~90 % del
         retorno para recortar la caída un 71 %. Es una decisión de apetito de riesgo, no de
         modelado.
      3. **Incluso el cerebro perfecto añade poco retorno:** +207,8 % contra +184,4 % de
         comprar y mantener es solo **+13 % más**, con la cadencia de 5 días y el tope de
         exposición del 95 %. Su ganancia real es riesgo (13,9 % contra 20,0 % de caída).
         **El margen del pronóstico en esta arquitectura está en el riesgo, no en el retorno.**

      *Reserva que debe viajar con la recomendación:* estas caídas son las **medidas** sobre la
      historia disponible. Dimensionar justo en el borde del tope (f=0,20 a 24,1 %) calibra
      contra el peor bajista que **ya ocurrió**; un bajista peor lo rompería. Por eso la
      recomendación operativa es f≈0,18 con banda del 10 %, que deja margen y solo exige 11
      rebalanceos en nueve años.

- [ ] **E.1 Corrida de veredicto sobre el holdout.**
      **Solo si A-D encontraron una ventaja medible.** Días 960-1260, 100 decisiones,
      paso ≤3. Una sola vez. Nunca antes.
      *Criterio:* veredicto del gate acatado, sea el que sea.

- [x] **E.2 Pivote ejecutado: gate reescrito alrededor de "comprar y mantener con la caída
      recortada".** 2026-10-01. Criterios escritos **antes** de la corrida que los evalúe.

      **El pivote NO abarata el gate: cierra un agujero.** El gate viejo comparaba contra
      comprar y mantener **crudo**, así que estar menos expuesto contaba como victoria en
      caída — pero **tener menos BTC consigue exactamente ese canje sin habilidad alguna**:
      una posición constante de 0,6x da ~0,6x del retorno y ~0,6x de la caída, gratis. La
      hipótesis nula del producto pivotado es el **desapalancamiento estático**, y el agente
      se puntúa ahora contra un comprar-y-mantener **desapalancado a su propia caída**.

      Dos criterios **añadidos**, ninguno retirado ni relajado:

      | criterio | forma | umbral |
      |---|---|---|
      | `MAX_DRAWDOWN_RATIO` | caída del agente / caída de la referencia | ≤ **0,60x** |
      | `MIN_CAPTURE_OF_RISK_MATCHED_HOLD` | retorno vs un estático a su mismo riesgo | ≥ **1,00** menos la comisión pagada |

      `MIN_CAPTURE_OF_RISING_REFERENCE` (0,50) queda **RETIRADO** y conservado en el fichero:
      comparaba contra la referencia cruda, ignorando el riesgo realmente tomado. Su
      sustituto es **más duro por 63 puntos** en la ventana de desarrollo (+154,9 % exigidos
      contra +92,2 %).

      **Un agujero que encontré en mi propio borrador y cerré:** la primera versión puso el
      mínimo en 0,80, lo que habría aprobado a un agente que entrega el 80 % de lo que el
      desapalancamiento estático da gratis — un producto estrictamente dominado por no hacer
      nada. Una tolerancia por debajo de 1,00 no tiene tamaño defendible. La tolerancia que
      el agente sí merece es la comisión que un tenedor estático no paga, así que es la que
      se concede, **medida de la corrida** en vez de elegida.

      **El criterio se aplica en AMBAS piernas**, y esa simetría es lo más importante que
      revela el pivote. El criterio retirado se saltaba la pierna a la baja alegando que
      capturar parte de una pérdida no es virtud — cierto contra la referencia cruda, falso
      contra una de riesgo igualado.

      **Veredicto del gate nuevo sobre las dos corridas archivadas:**

      | ventana | antes | ahora | qué falla |
      |---|---|---|---|
      | alcista 1260-1560 | RECHAZADO 6/8 | **RECHAZADO 6/9** | ratio de caída 0,85x (límite 0,60x) y captura de riesgo igualado +68,9 % contra +154,9 % |
      | bajista 2150-2450 | **APROBADO 8/8** | **RECHAZADO 8/9** | a su caída de 6,1 % un estático habría perdido −2,0 %; el agente perdió **−2,4 %**, límite −2,3 % |

      **El hallazgo que esto saca a la luz:** el resultado bajista celebrado del agente
      (−2,39 % contra −12,86 %) **lo reproduce aproximadamente tener el 15 % en BTC de forma
      estática y no decidir nada.** Falla por 0,05pp, o sea un empate: el acto de decidir no
      añadió nada medible. Era invisible mientras el comparador fuera la referencia cruda.

      **Consecuencia operativa que requiere tu decisión:** el servicio vivo
      `cryptoagent3-llm-agent` tiene autoridad de órdenes concedida bajo el gate **anterior**,
      que la ventana bajista aprobaba 8/8. Bajo el gate nuevo ninguna de las dos ventanas
      aprueba. Es cuenta **DEMO**, sin dinero real, así que no es una emergencia, pero la
      autoridad se apoya en un criterio que ya no se sostiene.
      *Pruebas:* `tests/test_gate_llm_agent.py`, 14 casos (el gate no tenía ninguna). Suite
      522 → **536**.

- [x] **E.3 Verificada la Fase A contra el defecto de cobertura del estudio de regímenes.**
      **NO está afectada.** Verificado, no asumido:

      | | Fase A (`build_daily_perception`) | mi estudio (defectuoso) |
      |---|---|---|
      | días vistos | **2451 de 2451** del calendario | 2442, y la racha dejaba 1098 etiquetados |
      | días enteros ausentes | **0** | — |
      | días escasos | 2, **reportados** en `sparse_days` | descartados en silencio |

      `build_daily_perception` agrupa por día y no exige racha ininterrumpida: un día con
      pocas barras cuenta igual y se contabiliza. No descarta nada y no retiene ningún rasgo.
      Como no falta ningún día entero, indexar por días presentes equivale al calendario y la
      deriva de índices es **cero**; los días 1260-1560 son 2023-06-14 → 2024-04-09.
      En el dataset extendido a 2017: 3318 de 3318 días, `sparse_days=11`, 0 días ausentes.
      **El +68,94 %, la correlación de timing +0,03 y el veredicto del gate siguen en pie.**

---

## Estudio de playbooks por régimen (BTC/USDT spot, techo de caída 25 %)

Pre-registro: `research/REGIME-STUDY-PREREGISTRATION.md`. Bitácora completa con los
negativos: `research/REGIME-STUDY-ATTEMPTS.md`. Código: `research/regime_taxonomy.py`,
`research/regime_playbook_study.py`. Salida: `data/validation/regime-playbooks.json`.

**Umbral aplicado, declarado antes de iterar.** El criterio pre-registrado dice "por encima
de USDT por un margen superior a su propio error estándar". Como USDT rinde exactamente 0 %,
se instancia con la convención que ya usa `research/regime_attribution.py`:
**efecto = |media del retorno diario| / error estándar ≥ 1,0**. Por debajo de 1 no se
distingue de cero, sea cual sea el total. Más: caída ≤ 25 %, y no peor que
comprar-y-mantener-con-techo por más de su error estándar.

- [x] **R.1 Taxonomía por ratio de eficiencia.** **Refutada.**
      El régimen BAJISTA quedó en 3 % (detector) / 0 % (oráculo): un ratio de eficiencia a
      30 d no ve una caída en escalera con contrarrallies, así que el bajista 2021-2022
      (−73,3 % para comprar y mantener) caía en LATERAL. Además: por debajo de un 20 % de
      falsas alarmas **ninguna** configuración existe a ningún retardo; 1 de 84 pasaba las
      restricciones duras y fallaba en validación (28 % → 36 %). Retardo estructural ≈ 21 d.

- [x] **R.2 Eje de dirección por caída desde máximo + posición frente a media larga.**
      BAJISTA pasa de 3 % a 60 % de los días de train. El bajista real aparece.
      *Defecto del oráculo encontrado por el camino:* confirmaba dirección con 15 días hacia
      delante, y en un bajista los tramos de 15 d suben por los contrarrallies, así que el
      oráculo daba 0 % de bajista. Horizonte fijado en **45 d** (bajista 16 %, 682 días
      etiquetados); sensibilidad medida: 15 d → 0 %, 30 d → 12 %, 45 d → 16 %, 60 d → 26 %,
      90 d → 44 %.

- [x] **R.3 Primer resultado "satisfactorio", RECHAZADO por artefacto.**
      BAJISTA comprado daba **+28,7 %, efecto 1,58, dd 5,2 %** en validación y "cumplía".
      Interrogado antes de reportarlo:

      | segmento | tramos BAJISTA | qué eran |
      |---|---|---|
      | train | 1 tramo de **275 d**, 39.942 → 19.930 (**−50,1 %**) | el bajista real. Comprado: **−48,5 %, dd 63,4 %** |
      | validación | 5 tramos de **1 a 14 d**, **todos positivos** | caídas breves en un alcista |

      La etiqueta hacía dos cosas distintas; el "playbook bajista" era **dip-buying**.
      *Tres defectos corregidos:* (a) sin duración mínima, un dip de 4 d era un "régimen";
      (b) el efecto trataba un tramo de 275 d y uno de 4 d como muestras iguales → ahora se
      calcula sobre **retorno logarítmico diario**; (c) sin suelo de evaluabilidad → ahora
      exige **≥ 4 tramos y ≥ 120 días** y un criterio no evaluable **FALLA**.
      *Look-ahead evitado:* la duración mínima se implementó primero con
      `enforce_min_segment`, que inspecciona toda la serie para saber si un tramo fue
      bastante largo — en el día *t* eso exige conocer el futuro. Sustituido por
      `apply_min_dwell` (permanencia mínima: cuánto lleva ya la etiqueta vigente), con
      prueba que contrasta ambas.
      **Tras quitar el artefacto, ningún régimen cumplía.**

- [x] **R.4 Diagnóstico de raíz: era tamaño de muestra, no estrategia.**
      640 días de validación entre 4 regímenes con permanencia de 30 d dan 3-5 tramos cada
      uno; con esa muestra el error estándar impide llegar a efecto 1,0 salvo por suerte
      (ALTA_VOL daba efecto 1,77 con 3 tramos → no evaluable → falla). Con los umbrales
      **congelados a priori**, se mancomuna la región de desarrollo 2020-01 → 2025-03
      (1909 d) sin tocar el holdout.
      *Defecto adicional encontrado y corregido:* `persistence_days=5` adoptaba la etiqueta
      al **cuarto** día consecutivo, no al quinto — un parámetro que no hacía lo que
      declaraba. Corregirlo **empeoró** el resultado de LATERAL de +84,5 % / efecto 2,72 a
      +52,6 % / efecto 1,51. Que sobreviva a una corrección que lo empeora es mejor
      evidencia que el número alto anterior.

- [x] **R.5 LATERAL cumple el criterio.** Región de desarrollo, **comisiones adversas 20 bps**:

      | playbook | tramos | días | total | efecto | caída | criterio |
      |---|---|---|---|---|---|---|
      | USDT (control) | 8 | 283 | 0,0 % | n/a | 0,0 % | — |
      | **exposición 100 %** | 8 | 283 | **+52,6 %** | **1,51** | **17,7 %** | **CUMPLE** |
      | **exposición 50 %** | 8 | 283 | +24,7 % | **1,59** | 8,8 % | **CUMPLE** |
      | exposición 100 % stop 15 % | 8 | 283 | +22,4 % | 0,40 | 16,6 % | no |
      | exposición 100 % stop 10 % | 8 | 283 | +37,3 % | 0,97 | 11,6 % | no |
      | exposición 100 % trail 15 % | 8 | 283 | +22,6 % | 0,41 | 16,5 % | no |
      | exposición 50 % stop 15 % | 8 | 283 | +12,2 % | 0,49 | 7,9 % | no |

      Los otros tres regímenes: **quedarse en USDT.** ALCISTA efecto 0,56 y caída 28,7 %
      (rompe el techo); BAJISTA 1 solo tramo de 262 d, no evaluable, y todo comprado da
      negativo (−46,1 % sin stop, −15,4 % con stop del 15 %); ALTA_VOL efecto 0,43.

      **Reservas, que son grandes y no se maquillan:**
      1. **Falla en el segmento de validación aislado:** efecto **0,33** (4 tramos, +10,0 %).
         El 1,51 mancomunado lo sostienen los 3 tramos de train (efecto 4,54, no evaluables
         por ser solo 3).
      2. **Los 8 tramos LATERAL son de 2023-2025.** El régimen **no ocurre ni una vez en
         2020-2022** (COVID, alcista 2021, bajista 2022). La evidencia viene de una sola
         época, de recuperación, donde casi cualquier exposición larga ganaba dinero.
      3. Solo **2 de 6** variantes cumplen; las variantes con stop fallan.

      *Qué es LATERAL en realidad*, y el nombre engaña: **no** es "mercado plano". Bajo este
      eje un mercado plano pegado a su máximo se etiqueta ALCISTA. LATERAL es el **cubo
      calmado dentro de un retroceso moderado por debajo del máximo** (caída del máximo
      entre 0 y 20 %, volatilidad en percentil < 70). Hay una prueba que fija esa semántica.

      *Por qué funciona, mecánicamente:* LATERAL es por construcción de **baja volatilidad**
      y sin caída profunda. En esos tramos se acumula la deriva positiva incondicional de BTC
      (+6,15 bps/día, `exposure-diagnosis.md`) sin una tendencia grande que perder, y el techo
      del 25 % no se acerca porque la volatilidad es baja por definición. **No requiere
      criterio de momento** — y por eso sobrevive donde todo lo que depende del momento ha
      muerto en este repo cuatro veces.

- [x] **R.6 Defecto que había borrado el 38 % de la historia.** Diagnosticando la reserva 2
      ("LATERAL no ocurre en 2020-2022") resultó **no ser una propiedad del mercado**:
      2020 y 2021 estaban **enteros sin etiquetar, 723 días**, incluidos el crash del COVID y
      el alcista completo de 2021, con los rasgos en `n/a`.
      *Causa:* `causal_features` exigía una racha **ininterrumpida** de 181 barras diarias.
      Los 15 huecos documentados del dataset son de 1 a 5 **horas**, casi todos en 2020-2021;
      cada uno reseteaba la racha, que nunca alcanzaba 181, así que el primer día etiquetable
      caía en marzo de 2022. Contradecía la convención que el repo ya tenía
      (`multislot_sim.MIN_LOOKBACK_COVERAGE = 0.95` sobre ventana temporal).
      *Corregido* con `MIN_WINDOW_COVERAGE` equivalente: **1098 → 1729 días etiquetados** de
      1909, y lo único sin etiquetar pasa a ser el calentamiento real de 180 días.

- [x] **R.7 El arreglo invierte el ganador.** Mi informe anterior estaba equivocado.

      | régimen | antes (723 días borrados) | después (serie completa) |
      |---|---|---|
      | LATERAL | +52,6 %, efecto **1,51**, dd 17,7 % → cumplía | +79,4 %, efecto **0,56**, dd **45,8 %** → falla |
      | ALTA_VOL_SIN_DIRECCION | efecto 0,43 → fallaba | +175,3 %, efecto **1,72**, dd 20,0 % → cumple |

      LATERAL cumplía **por el artefacto**: con 2021 restaurado su caída se va al 45,8 %.
      ALTA_VOL con exposición 100 %, comisiones adversas: train 4 tramos/120 d +95,9 %
      efecto 1,18; validación 3/90 +38,0 % efecto 1,43 (no evaluable); desarrollo 7/214
      +175,3 % efecto **1,72**, caída 20,0 %. Pasan **5 de 6** variantes.
      **Jackknife:** quitando un tramo cada vez el efecto queda entre **1,24 y 2,43**; sin el
      tramo de +67,3 % quedan 1,24 y +64,6 %. No lo carga un solo tramo.

- [x] **R.8 Confirmación limpia en el holdout: NO CONFIRMA.** Declarado antes de medir y
      acatado. **2025-04-01 → 2026-09-16 (533 d), GASTADO una sola vez, no reutilizable.**

      | régimen | tramos / días | total (20 bps) | caída | veredicto |
      |---|---|---|---|---|
      | ALTA_VOL (candidato) | **1 / 39** | +26,6 % | 11,6 % | **NO EVALUABLE → FALLA** |
      | LATERAL | 3 / 102 | **−34,7 %** | **39,2 %** | no evaluable; refuta su pase previo |
      | ALCISTA | 2 / 145 | −4,6 % | 17,1 % | no evaluable |
      | BAJISTA | 2 / 225 | +8,6 % | 35,7 % | no evaluable |

      **Causa raíz: potencia estadística, no defecto ni debilidad de la estrategia**, y es
      demostrable sin mirar el resultado: el desarrollo da 36 tramos en 1909 d
      (ALCI 13 · BAJI 3 · LATE 12 · ALTA 8) y el holdout **9 en 533 d**
      (3 · 2 · 3 · **1**). El suelo pre-declarado es ≥ 4 tramos y ≥ 120 días; el régimen menos
      frecuente dio 7 tramos en 1909 d, así que llegar a 4 exige ~1090 d y **el holdout es la
      mitad**. Ningún régimen podía confirmarse ahí, con ninguna estrategia.

      **Lo único que el holdout sí establece:** LATERAL con −34,7 % y caída 39,2 % **confirma
      que su pase anterior era el artefacto de los 723 días.** El arreglo R.6 queda validado
      por evidencia fuera de muestra.

- [x] **R.9 Serie extendida a la inception de Binance (2017-08).**
      `research/extend_history.py`, cliente público de backfill del repo, directorio nuevo
      para no invalidar la procedencia de los resultados que citan `sha256:53938d3d…`.

      | | antes | después |
      |---|---|---|
      | dataset_id | `sha256:53938d3d…` | `sha256:c475ef34…` |
      | barras horarias | 58.769 | **79.477** |
      | rango | 2020-01 → 2026-09 | **2017-08-17 → 2026-09-16** (9,1 años) |
      | días completos | 2442 | **3296** |
      | huecos | 15 | 28 (mayor 33 h, feb 2018) |

      *Supuestos declarados:* BTCUSDT arranca el 2017-08-17, suelo duro. La Binance temprana
      es más fina: 2018 es el peor año (7 huecos / 62 h). Cero precios inválidos, cero
      duplicados, cero `high < low`.
      *Integridad de ETIQUETADO verificada antes de mirar retornos:* **3116 de 3296 días
      (94,5 %)**, y los 180 sin etiquetar son exactamente el calentamiento. **Cero agujeros.**

- [x] **R.10 El ganador cambia por tercera vez; eso es el hallazgo.**

      | versión del instrumento | "ganador" en selección | efecto |
      |---|---|---|
      | con 723 días borrados | LATERAL expo 100 % | 1,51 |
      | tras arreglar la cobertura | ALTA_VOL expo 100 % | 1,72 |
      | con la serie extendida | BAJISTA expo 50 % stop 15 % / LATERAL expo 50 % | 1,14 / 1,00 |

      ALTA_VOL cae a 0,92. **Ningún cambio tocó umbrales ni criterios: todos fueron
      correcciones de defectos.** Que la identidad del ganador no sea estable es la firma del
      ruido siendo seleccionado, no de un efecto.
      *Defecto corregido:* el criterio 3 usaba exposición 100 % como "comprar y mantener con
      techo", pero en BAJISTA esa variante cae **61,3 %** y es **inadmisible** bajo el techo
      del 25 %. Ahora, si el referente incumple el techo, el criterio 3 se satisface por
      defecto y el código lo declara.

- [x] **R.11 Test limpio 2018-2019: NINGÚN RÉGIMEN CONFIRMADO.**
      Candidato primario pre-declarado: BAJISTA expo 50 % stop 15 % (mayor efecto en
      selección). Región **2018-01-01 → 2019-12-31**, nunca vista, gastada una sola vez.
      Comisiones adversas 20 bps:

      | régimen | tramos / días | selección | **test limpio** | caída | veredicto |
      |---|---|---|---|---|---|
      | **BAJISTA** expo 50 % stop 15 % | **4 / 415** | +8,4 % ef 1,14 | **−27,4 %** ef 3,91 | **27,4 %** | **FALLA** |
      | **LATERAL** expo 50 % | **4 / 161** | +49,5 % ef 1,00 | +15,9 % **ef 0,22** | 18,1 % | **FALLA** |
      | ALCISTA | 1 / 63 | — | +19,4 % | 19,2 % | no evaluable |
      | ALTA_VOL | 1 / 35 | — | +6,8 % | 10,7 % | no evaluable |

      **Esta vez el fallo NO es falta de potencia:** BAJISTA y LATERAL superan el suelo
      (4 tramos, 415 y 161 días) y fallan por mérito propio. BAJISTA **invierte el signo**
      (+8,4 % → −27,4 %); su efecto 3,91 es alto porque la media diaria es consistentemente
      **negativa**, y el criterio exige media > 0. LATERAL se desinfla de 1,00 a **0,22**.
      Reproduce de forma independiente lo que `exposure-diagnosis.md` §G ya estableció: la
      selección en muestra no generaliza.

- [x] **R.12 Cierre: en los cuatro regímenes, fuera de muestra, nada supera a USDT.**
      El pre-registro declaró este desenlace como cierre válido. Lo que queda establecido en
      positivo, no como ausencia:
      1. **En BAJISTA quedarse en USDT está activamente respaldado**: comprado pierde entre
         −27,4 % y −61,8 % según variante, con caídas del 27 % al 62 %.
      2. **El techo del 25 % es la restricción que manda**: comprar y mantener cayó −73,3 % en
         2021-2022 y −61,8 % dentro de los tramos BAJISTA de 2018. Inadmisible por 2,5x.
      3. **Recortar la caída sigue siendo el único efecto que replica**, coherente con los
         3 de 3 cortes OOS del estudio previo.
      Sin blocker: el estudio llegó a una respuesta definitiva con **dos regiones de prueba
      limpias e independientes**, no se quedó atascado.

- [x] **R.13 Búsqueda walk-forward de un playbook BAJISTA: no existe.**
      `research/bajista_walkforward.py`. Walk-forward expansivo con purga y embargo de 30 d,
      porque **no queda región sin gastar** (2017-2019 y 2025-2026 gastadas, 2020-2025 es
      selección). Cada medición es OOS respecto a los datos que produjeron la elección.

      **En los 7 folds la selección eligió USDT**: ningún candidato superó el suelo
      pre-declarado en entrenamiento, así que la búsqueda no llegó a proponer nada que operar.

      Aplicando cada playbook a ciegas a todos los folds, OOS con embargo:

      | playbook | tramos | total | caída | efecto |
      |---|---|---|---|---|
      | **USDT (control)** | 4 | **0,0 %** | **0,0 %** | — |
      | expo 100 % stop 10 % | 4 | +3,5 % | 19,7 % | **0,58** |
      | expo 50 % | 4 | −3,5 % | 31,5 % | 0,83 |
      | expo 50 % stop 15 % | 4 | −4,1 % | 14,8 % | 0,46 |
      | expo 100 % trail 15 % | 4 | −6,9 % | 23,5 % | 0,46 |
      | expo 100 % stop 15 % | 4 | −12,9 % | 28,4 % | 0,40 |
      | expo 100 % | 4 | −18,8 % | 61,3 % | 0,73 |

      6 de 7 negativos; el único positivo con efecto 0,58, indistinguible de cero.

      **Veredicto por tres vías independientes: en BAJISTA nada supera a quedarse en USDT.**
      (1) test limpio 2018-2019, todas las variantes −27,4 % a −61,8 % contra USDT 0 %;
      (2) selección walk-forward, 7/7 folds eligieron USDT; (3) aplicación ciega, 6/7
      negativas. **Explicable estructuralmente:** solo spot, así que batir a estar fuera en un
      declive exige acertar los contrarrallies, la ventaja de momento medida en cero **cuatro**
      veces.

      **Por qué converge aquí:** BAJISTA aporta solo **4-5 episodios independientes en 9,1
      años**. Mi propio suelo exige 4 tramos, así que cualquier variante nueva nace en el
      límite de lo medible. Es techo de potencia, no de imaginación, y seguir añadiendo
      variantes sobre 4 episodios es el procedimiento que ya invirtió tres ganadores
      (LATERAL → ALTA_VOL → BAJISTA).

- [x] **R.14 Retroalimentación medible al agente: en BAJISTA, ir a cero.**

      | exposición en bajista | criterio de riesgo igualado |
      |---|---|
      | 0 % estricto | **PASA** |
      | ~2 % residual | PASA (−0,5 % contra límite −0,8 %) |
      | **12 %, lo que hizo** | **FALLA** (−2,4 % contra límite −2,3 %) |

      El 12 % residual le costó ~0,4pp, y esos 0,4pp son exactamente la diferencia entre pasar
      y fallar el gate nuevo.

- [x] **R.15 Reparación del criterio de discriminación, aplicada tras tu autorización.**
      Se eligió medir la discriminación **entre regímenes** en vez de saltarse el criterio en
      ventanas de un solo régimen: saltárselo elimina una comprobación, medirlo entre regímenes
      preserva su intención y es más difícil de burlar.

      **La medición corrigió además mi propio encuadre al proponer la reparación.** Dije que el
      criterio "castiga la respuesta correcta". El defecto real es más simple y peor: **la
      minoría dentro de la ventana cuenta decisiones, no condicionamiento**, así que un puñado
      de decisiones en un régimen apenas visitado lo satisface sin que el agente haya
      discriminado. En la ventana bajista el 12 % de minoría lo produjeron **4 decisiones** en
      r2 y r3 (3 y 1 decisiones, al 78 % y 95 %). En los dos regímenes que sí vio —r0 con 40
      decisiones al 2,9 % y r1 con 16 al 0,0 %— su exposición difería un **2,9 %**: estuvo
      plano, y el criterio reportó discriminación.

      | constante | valor | derivación |
      |---|---|---|
      | `MIN_REGIME_EXPOSURE_SPREAD` | **0,30** | ~2 errores estándar de la diferencia entre dos medias de régimen: exposición en [0,1] con sd ≈ 0,4 y ~15 decisiones por régimen dan ee ≈ 0,10 por régimen y ≈ 0,15 para la diferencia. Fijado por ese argumento **antes** de medir ninguna corrida. |
      | `MIN_DECISIONS_PER_REGIME` | **5** | un régimen visto una o dos veces tiene una media que es una decisión, no un comportamiento. |

      Menos de dos regímenes utilizables ⇒ criterio **no evaluable ⇒ FALLA**: una ventana que
      nunca obligó al agente a elegir no es evidencia de que elija bien. `MIN_MINORITY_SHARE`
      queda **RETIRADO** y conservado, y sigue usándose como repliegue para informes antiguos
      sin regímenes en la traza, para no recomputar en silencio un veredicto histórico.

      **Medido sobre las dos corridas archivadas:**

      | ventana | exposición por régimen | diferencia | antes | ahora |
      |---|---|---|---|---|
      | alcista | r0=0%(11) r2=72%(21) r3=85%(28) | **85 %** | PASA (minoría 33 %) | **PASA** |
      | bajista | r0=3%(40) r1=0%(16) · r2=78%(3) r3=95%(1) | **3 %** | PASA (minoría 12 %) | **FALLA** |

      **Veredicto final del gate reparado:** alcista RECHAZADO 6/9, bajista RECHAZADO 7/9
      (pierde también la discriminación). Confirma lo que `handover.md` §3 ya advertía: el
      APROBADO bajista nunca fue simétrico al RECHAZADO alcista.
      *Pruebas:* 8 casos nuevos en `tests/test_gate_llm_agent.py` (22 en total). Suite
      536 → **544**.

- [x] **R.16 Prescripción "0 % en BAJISTA" al agente vivo: NO APLICADA, con medición.**
      El bajista del agente es `r1 "bajista profundo"` (`allocation_at_neutral = 0.20`,
      `default_exposure = CASH`), distinto de mi taxonomía.
      1. **En r1 ya estaba a cero:** exposición observada **0,0 % en 16 decisiones**. Bajar el
         0.20 es un no-op sobre la evidencia.
      2. **La pérdida vino de r2**, 3 decisiones al 78 % (−3,6 %, efecto 0,6).
      3. **Esas decisiones estaban correctamente corroboradas:** r2 a **+14,2 %** sobre su
         media de 200d (0 de 3 por debajo), retorno 90d +19,1 %; r3 a +10,3 % (0 de 1).
         Días 2430-2445, final de la ventana, mercado ya sobre tendencia.
      **No es un defecto, es la ausencia de ventaja de momento.** Aplicarlo sería afinar un
      parámetro justificado por el retorno de una ventana, que la regla 2 del roadmap prohíbe.

- [x] **R.17 Playbook ALCISTA: tampoco supera a USDT.**
      `research/regime_walkforward.py --regime ALCISTA`, mismo código que BAJISTA (reproduce
      BAJISTA idéntico, sin deriva). **7 de 7 folds eligieron USDT.**

      Aplicación ciega, 13 tramos OOS con embargo:

      | playbook | total | caída | efecto |
      |---|---|---|---|
      | **USDT** | **0,0 %** | **0,0 %** | — |
      | expo 50 % | **+126,0 %** | 22,5 % | **0,37** |
      | expo 100 % | +262,5 % | **29,9 %** (rompe techo) | 0,16 |
      | expo 100 % trail 15 % | +65,6 % | 31,7 % | 0,65 |

      **Todas positivas**, al contrario que BAJISTA. Pero no es un hallazgo:
      **5 de 13 tramos positivos**, prueba de signo **p = 0,867**, **mediana −3,3 %**, y el
      **jackknife** lleva el total de **+126,0 % a +19,5 % quitando un solo tramo** (el rally
      post-COVID de 2020-10). **El tramo típico de ALCISTA pierde dinero.** El total es un
      valor extremo, no un comportamiento.

- [x] **R.18 Veredicto conjunto: en los cuatro regímenes nada supera a USDT.**

      | régimen | cómo falla |
      |---|---|
      | BAJISTA | retornos **negativos**, 6 de 7 variantes pierden |
      | ALCISTA | positivos pero **un tramo los carga**; mediana −3,3 %, signo p=0,867 |
      | LATERAL | efecto 0,22 en el test limpio tras parecer 1,00 en selección |
      | ALTA_VOL | efecto 0,43-0,92 según el instrumento, nunca estable |

      Coherente con lo único medido de forma estable: **no hay ventaja de momento**
      (+0,01, +0,02, −0,11, +0,03; ee 0,15). Sin ella, elegir *cuándo* estar expuesto no lleva
      información.

---

## Challenge externo: ¿por qué hay firmas de cripto rentables?  (intento 15)

- [x] **F.1 Reconciliación medida.** Lo medido responde una pregunta estrecha (direccional,
      spot, un venue, sin apalancamiento, 5 días) y **casi ninguna firma rentable hace eso**:
      hacen creación de mercado (latencia), base/carry (exige cortos), arbitraje multi-venue,
      stat-arb transversal (exige cientos de activos) y microestructura a segundos. Más beta
      disfrazada de alfa y sesgo de supervivencia (3AC, Alameda, Celsius, BlockFi, Genesis).
      **El techo del mandato está medido: incluso previsión perfecta añade +13 %.**

- [x] **F.2 Hipótesis "inputs equivocados": respaldada estadísticamente, REFUTADA
      económicamente.** `market_features` consume solo cierres; volumen, nº de operaciones,
      ticket medio y rango nunca se habían medido.
      `research/flow_diagnosis.py`: **5 de 24 pares alcanzan 1 ee** (todos positivos, signo
      estable) frente a **0 de 20** solo-cierres. El mejor: ticket medio, +1,18 ee a 168h.
      **Pero 0 de 24 llegan a 2 ee.** `research/flow_strategy.py` (walk-forward, selección
      dentro del fold, comisiones adversas, contra el estático al mismo riesgo):
      **0 de 7 folds ganan**, compuesto OOS **−40,7 %** contra **+675,0 %** de comprar y
      mantener. Un rho de +0,03 no paga 20 bps.

- [x] **F.3 El carry medido, y decayendo.** 7.737 pagos de financiación de BTCUSDT perpetuo
      sobre 7,1 años: **11,5 % anual** al lado corto, positiva en **85,8 %** de los pagos.
      Delta neutral, sin pronóstico. **Pero comprimiéndose: 30,6 % (2021) → 11,9 % (2024) →
      5,1 % (2025) → 3,0 % (2026).** Hoy es marginal tras comisiones, margen y riesgo
      operativo. Exige cortos y derivados: **prohibidos por el mandato actual**.

- [B] **F.4 LLM que "copia" a traders exitosos: NO construido, con razones medidas.**
      Creación de mercado y arbitraje son latencia (un LLM a 30 min no compite); el carry es un
      `if` y está a 3 %; el stat-arb transversal es ranking y covarianzas. El techo del mandato
      es +13 %. **Donde un LLM sí estaría diferenciado: texto no estructurado** (anuncios,
      gobernanza, regulación, hackeos) como detector de ruptura, no como pronosticador de
      precio. **No comprobable hoy:** no hay corpus con marca temporal auditable y los archivos
      de noticias filtran futuro. Hipótesis formulada y medible si aparece el corpus:
      ¿reduce la caída alrededor de fechas de evento, fuera de muestra?

- [x] **F.5 Fuera de la caja: rotación transversal long-only. El mandato nunca dijo UN activo.**
      `research/cross_section.py`, 30 pares USDT diarios 2019-2026 elegidos por **longevidad no
      por rendimiento**, incluyendo LUNA y FTT y dos deslistados dentro de muestra (EOS, MATIC),
      con disponibilidad **punto-en-el-tiempo estricta**.
      Walk-forward 5 folds, selección dentro del fold, comisiones adversas:
      compuesto OOS **+1.205,1 %** contra **+192,5 %** de BTC al mismo riesgo, 3 de 5 folds
      positivos, mediana del fold **+10,0 %**.
      **REFUTADO en su forma actual, por dos motivos:** el **jackknife** lleva +1.205,1 % a
      **−38,6 %** quitando el fold de 2021 (manía de alts, +2.024,1 %), con rango −38,6 % a
      +6.562 %; y la **caída compuesta es 80,4 %**, el triple del tope del 25 %.
      *Matiz que importa:* falla distinto a los demás. Es el **mecanismo más prometedor medido
      hoy** (3 de 5 folds positivos, mediana +10 %) y a la vez **no certificable con 5
      observaciones anuales**. Mismo techo de potencia que cerró BAJISTA.
      *Sesgo declarado:* el universo lo elegí yo entre pares con historia larga, así que los que
      murieron pronto faltan. **Sesga al alza.**

- [B] **F.6 Dónde encaja un LLM de verdad: selección transversal por narrativa.**
      Lo que hacen los traders de cripto no es acertar el timing de BTC: **rotan entre
      narrativas** (DeFi, L1s, memes, IA). Es selección transversal guiada por relato, el único
      trabajo donde un LLM está mejor equipado que un ranking numérico.
      *Inputs:* ranking transversal numérico (ya construido) + texto con marca temporal sobre
      narrativas, lanzamientos, listados e incidentes. *Decide:* qué k activos del universo
      elegible sostener. *Se mide:* walk-forward anual, selección dentro del fold, comisiones
      adversas, contra BTC al mismo riesgo, jackknife obligatorio, tope del 25 %.
      **Bloqueador de datos, no de diseño:** no hay corpus de narrativas con marca temporal
      auditable (los archivos de noticias y redes filtran futuro: fechas revisadas, hilos
      editados, cuentas borradas) ni universo de listados punto-en-el-tiempo. Con ambos, la
      hipótesis es medible tal como queda especificada.

- [x] **F.7 La unidad de observación estaba mal. Al arreglarla aparece el hallazgo real.**
      `research/cross_section_monthly.py`. Un fold anual es la unidad equivocada para una
      estrategia de rebalanceo mensual: agrupa 12 decisiones en 1 observación. Con el
      **periodo de rebalanceo** como unidad, la muestra pasa de 5 a **60, todos OOS**.

      | | |
      |---|---|
      | diferencia **media** (rotación − BTC) | **+5,21 %** |
      | diferencia **mediana** | **−3,54 %** |
      | efecto | **1,38** (suelo 1,0) |
      | acierto | **29/60 = 48 %**, signo p=**0,6506** |
      | sin el mejor periodo de 60 | efecto **0,98** |

      **MEDIA POSITIVA, MEDIANA NEGATIVA.** La media supera a la mediana en 8,7 puntos: es un
      **perfil de convexidad**, no una ventaja fiable. Pierde algo más a menudo de lo que gana
      y cuando gana, gana mucho.
      **Veredicto:** el titular pasa (efecto 1,38) y las dos robusteces declaradas en el
      módulo antes de correrlo fallan (signo = moneda; recortar 1 de 60 deja 0,98). **No
      establecido**, y es lo más cercano a real de todo el proyecto.

- [x] **F.8 La reconciliación definitiva: lo que cobran es CONVEXIDAD, no exactitud.**
      Los traders rentables pierden en la mayoría de posiciones y ganan mucho en unas pocas.
      **Las cuatro mediciones de correlación de timing en cero son correctas y miden lo
      irrelevante:** un operador con 48 % de acierto y mediana negativa puede ser muy rentable
      si la cola derecha paga, y su correlación de timing saldría cero.
      **Implicación para el LLM, ahora específica:** su trabajo no es acertar más veces (cuatro
      medidas dicen que no puede) sino **identificar configuraciones asimétricas** — pérdida
      acotada por construcción, ganancia abierta. *Se mide por asimetría* (media vs mediana,
      ratio de colas, spread mensual con prueba de signo y recorte), **no por tasa de acierto
      ni por correlación de timing**. Ese cambio de métrica es el entregable metodológico.
      *Siguiente paso con datos existentes:* **ampliar la muestra, no añadir cerebro.** Con 60
      periodos la pregunta no se cierra; con 150-200 sí.

- [x] **F.9 HALLAZGO: hay señal transversal a DOS SIGMAS, y es la contraria a la buscada.**
      `research/cross_section_ic.py`. El estadístico correcto para una señal transversal es el
      **coeficiente de información por periodo**, que usa **2.396 observaciones activo-periodo**
      en vez de las 60 del spread de cartera.

      | señal | IC medio | t | periodos+ |
      |---|---|---|---|
      | **volatilidad 30d** | **−0,1609** | **−5,23** | 25/88 |
      | **volumen medio 30d** | **+0,0728** | **+2,74** | 51/88 |
      | momento 30d | −0,0335 | −1,21 | 42/88 |
      | momento 90d | +0,0101 | +0,34 | 46/88 |

      **Primera vez que el proyecto mide algo a 2 sigmas.** Y el **momento no es significativo
      en ningún horizonte** — la familia sobre la que construí la rotación de F.5.

      **Los dos confundidores, probados y descartados:**

      | | completo | solo sobrevivientes | sin catástrofes |
      |---|---|---|---|
      | volatilidad 30d | −5,23 | **−5,29** | **−4,65** |
      | volumen medio 30d | +2,74 | **+3,08** | **+2,59** |

      Entre sobrevivientes el efecto es **más fuerte**: la supervivencia no lo explica.
      Es la **anomalía de baja volatilidad** más un efecto de **tamaño/liquidez**.

- [x] **F.10 Reconciliación completa: los inputs estaban equivocados en DIMENSIÓN.**
      No faltaba volumen como señal temporal (medido, falló, 0 de 7 folds). Todo el proyecto
      midió la dimensión **temporal** (¿cuándo estar en BTC?) cuando la señal vive en la
      **transversal** (¿qué activo, entre varios?). Las firmas rentables cosechan **primas
      factoriales documentadas** —baja volatilidad, tamaño, liquidez, carry— no aciertos
      direccionales. **Las cuatro mediciones de timing en cero son correctas y miden una
      dimensión donde no hay nada.**
      *Sobre el LLM:* **esta señal no lo necesita** — un factor de baja volatilidad es una
      desviación típica y un `sort`. El LLM solo cabría en la capa de narrativa/asimetría, que
      sigue sin validar por falta de corpus con marca temporal.

- [x] **F.11 El IC convertido en dinero: el resultado más fuerte del proyecto, NO certificado.**
      `research/low_vol_strategy.py`. Cartera de las k de menor volatilidad, peso igual o
      inverso a la vol, parámetros congelados por fold, comisiones adversas.

      **Lo notable:** **4 de 5 folds baten a BTC** (incluido el bajista de 2022, −49,7 % contra
      −63,4 %). Agregado 60 periodos OOS: **+977,4 %** con caída 62,3 % contra BTC **+265,0 %**
      con caída 69,2 %. **Con el tope del 25 % aplicado a AMBOS: +199,7 % contra +73,7 %, o
      2,7× más retorno a caída idéntica.** Primera cosa del proyecto que bate a
      comprar-y-mantener al mismo riesgo.

      **Lo que falla, del criterio escrito antes de correrlo:**

      | comprobación | resultado | |
      |---|---|---|
      | media del spread > 0 | +2,75 % | ✓ |
      | efecto ≥ 1,0 | 1,29 | ✓ |
      | supera a BTC con tope | +199,7 % vs +73,7 % | ✓ |
      | **prueba de signo** | 31/60 = 52 %, **p=0,4487** | **✗** |
      | **efecto sin el mejor de 60 periodos** | **0,84** | **✗** |

      Gana en 52 % de los periodos y quitar **un** periodo de 60 tira el efecto a 0,84. El
      rendimiento superior **llega a ráfagas**, no uniformemente: mismo perfil de convexidad de
      F.7. **NO se despliega.**

      *Qué lo resolvería:* **más muestra** (universo más amplio y más historia; con 150-200
      periodos el efecto recortado se estabiliza si es real). *Qué no:* **más cerebro** — no hay
      nada que un LLM aporte a ordenar por desviación típica.
      *Reservas:* universo de 30 nombres elegidos a mano (sesga al alza, aunque aguanta entre
      sobrevivientes); la exposición 0,34 se calibró sobre la peor caída **ya ocurrida**.

- [x] **F.12 Universo 3,3× más amplio (100 pares, programático): la SEÑAL replica, la
      ESTRATEGIA no.** Universo sacado de `exchangeInfo` en vez de mi memoria, para quitar mi
      sesgo de selección. *Defecto propio:* mi filtro usó `permissions`, que Binance dejó vacío
      al migrar a `permissionSets`, y devolvió **0 pares en silencio** — asumí la forma de un
      campo en vez de comprobarla.

      **Señal, con 5.693 observaciones activo-periodo:**

      | señal | t (30 pares) | **t (100 pares)** | solo sobrevivientes |
      |---|---|---|---|
      | **volatilidad 30d** | −5,23 | **−4,06** | **−4,21** |
      | **crecimiento de volumen** | −1,29 | **−3,18** | **−3,35** |
      | volumen medio 30d | **+2,74** | **−2,08** | −1,98 |

      **La baja volatilidad REPLICA** (−4,06 con 3,3× la amplitud). **El volumen medio INVIRTIÓ
      EL SIGNO y queda REFUTADO:** era un artefacto de mis 30 nombres grandes elegidos a mano.
      El momento sigue no significativo en ningún horizonte ni universo.

      **Estrategia: empeora al ampliar.** efecto 1,29 → **0,83**; mediana +0,32 % → **−0,30 %**;
      efecto sin el mejor periodo 0,84 → **0,20**; folds que baten a BTC **4 de 5 → 1 de 5**;
      con tope del 25 %: +199,7 % → **+108,9 %** contra +73,7 % de BTC. **NO PASA.**

- [x] **F.13 La razón por la que la señal es real y la estrategia no: EL MANDATO.**
      Un premio factorial es una afirmación **relativa**: el IC dice que la baja volatilidad se
      ordena mejor **unos activos respecto a otros**. Cosecharlo exige la **pata corta** (largo
      baja-vol / corto alta-vol). Una cesta long-only concentrada no cosecha el premio: queda
      expuesta al beta común de cripto, que domina su resultado.
      **El mandato queda confirmado como la restricción vinculante por dos vías independientes:**
      (1) la cota del oráculo — previsión perfecta direccional añade solo **+13 %**; (2) un
      factor real a **t = −4,06**, replicado, que **"solo spot, long-only, sin cortos" impide
      convertir en dinero.**
      *Sobre el LLM, definitivamente:* ningún LLM resuelve esto. La señal es una desviación
      típica y un `sort`; el obstáculo es la **ausencia de instrumento**, que es una decisión de
      mandato, no un problema de inteligencia.

- [x] **F.14 La pata corta MEDIDA: no salva el factor, y corrige F.13.**
      El mandato restringe lo que el agente **opera**, no lo que se **investiga**, así que se
      midió sin implementarla. Largo baja-vol / corto alta-vol, delta-neutral 50/50,
      comisiones en ambas patas, walk-forward:

      | coste de préstamo | total OOS | caída | efecto | acierto |
      |---|---|---|---|---|
      | **0 %** | **−48,3 %** | 72,4 % | 0,43 | 34/60 |
      | 20 % | −68,7 % | 80,2 % | 1,07 | 33/60 |
      | 40 % | −81,2 % | 85,9 % | 1,71 | 32/60 |

      **Pierde dinero incluso con préstamo gratis.** El "efecto" sube con el coste porque la
      media se vuelve consistentemente **negativa** — el mismo truco cazado en BAJISTA.
      Gana en el 57 % de los periodos y pierde en total: **las pérdidas son mucho mayores**.
      **Cortar alta volatilidad en cripto es ponerse corto de billetes de lotería**, que es la
      imagen espejo exacta de la convexidad medida en F.7.

      **CORRECCIÓN DE F.13:** escribí que cosechar el factor exigía la pata corta y que el
      mandato era por tanto la restricción vinculante. **La segunda mitad era incorrecta:**
      levantar el mandato **no** convertiría la señal en dinero. La perdería más rápido.

- [x] **F.15 Cuadro cerrado: la señal es real y no es cosechable.**

      | expresión del factor | resultado |
      |---|---|
      | **IC transversal** | **REAL: t = −4,06**, replicado en 2 universos, robusto a supervivencia |
      | cesta long-only | no bate a BTC al mismo riesgo (dominada por el beta de cripto) |
      | largo/corto delta-neutral | **pierde** incluso con préstamo gratis (corto de convexidad) |

      Y eso explica, mejor que cualquier argumento previo, por qué en cripto dominan los
      **creadores de mercado y las mesas de arbitraje** y no los fondos factoriales: **ellos no
      asumen riesgo de convexidad**, cobran spread y diferencias de precio, que son pagos
      acotados.
      **Convergencia: 21 intentos.** Toda expresión disponible del único factor real está
      medida y refutada. La única hipótesis abierta (selección por narrativa con LLM) sigue
      bloqueada por ausencia de corpus con marca temporal, no por falta de diseño.

- [x] **F.16 DEFECTO en mi propio hallazgo principal: el universo estaba truncado
      alfabéticamente.** El "universo amplio de 100 pares" se cortaba en `GLMUSDT` (letras 1,
      A-G); **faltaba todo de H a Z** — SOL, XRP, LTC, DOGE, MATIC, ZEC, TRX. Mi tope de 150 con
      iteración alfabética y el guard de tiempo cortó en 100 mientras escaneaba en orden.
      **Corregido: 254 pares, alfabeto entero**, definición limpia ("todo par USDT spot con ≥900
      barras diarias"), sin selección mía. Y el hallazgo **se fortalece** con **14.526
      observaciones activo-periodo**:

      | señal | 30 (a mano) | 100 (truncado) | **254 (completo)** | solo sobrev. |
      |---|---|---|---|---|
      | **volatilidad 30d** | −5,23 | −4,06 | **−4,76** | **−4,85** |
      | **crecimiento de volumen** | −1,29 | −3,18 | **−4,09** | **−4,27** |
      | **volumen medio 30d** | +2,74 | −2,08 | **−3,19** | **−3,23** |
      | **momento 30d** | −1,21 | −1,69 | **−2,54** | **−2,61** |

      **Cinco señales a |t| ≥ 2, todas negativas**, y el momento ahora significativo pero con el
      signo **invertido**: es **reversión**, no momento. Las cinco apuntan a lo mismo
      ("menor es mejor"), así que probablemente son **un solo factor**: pequeño, tranquilo y
      castigado rinde más — el cluster clásico de bajo-riesgo + tamaño + reversión.

- [x] **F.17 El corpus con marca temporal: CONSEGUIDO. Bloqueador de existencia LEVANTADO.**

      | fuente | qué da | por qué es auditable |
      |---|---|---|
      | **Wikimedia Pageviews** | visitas **diarias** desde 2015 | un conteo de 2019-01-01 **no se puede reeditar**: es telemetría publicada |
      | **Wikipedia Revisions** | el **texto exacto** en una fecha pasada | cada `revid` es inmutable con el timestamp real de edición |

      Es exactamente lo que un archivo de noticias no da (fechas revisadas, artículos editados,
      cuentas borradas). Gratuito, sin credenciales, verificado en vivo.
      *Defecto propio:* mi primer fetch devolvió 0 porque un `except Exception` se tragaba un
      **timeout de 20 s**. Con 60 s funciona. Mi código ocultó el error.

- [B] **F.18 Pero la COBERTURA no sostiene la hipótesis transversal.**
      De 254 pares, solo **8** tienen artículo con ≥900 días: ADA, ALGO, AXS, BTC, DOGE, ETH,
      LTC, UNI. **Wikipedia cubre lo grande y establecido**, donde menos dispersión transversal
      hay. Un IC con 8 nombres por periodo no es medible (mi código exige ≥20, y lo mantengo).

      Medido lo que esos 8 **sí** sostienen — atención como señal **temporal**:

      | señal | horizonte | rho medio | t entre 8 activos |
      |---|---|---|---|
      | atención z30 | 48h | +0,0181 | +2,70 |
      | atención z30 | 168h | +0,0285 | +2,66 |

      **Y se lee con precisión:** (1) **por activo nada alcanza 2 ee** (BTC: +0,30/+0,05/−0,70);
      (2) el "t entre activos" solo dice que el **signo** es consistente; (3) está **inflado**
      porque los 8 están correlacionados por el beta de cripto y no son independientes; (4) el
      rho de +0,018 a +0,037 es **el mismo orden que ya falló la prueba económica** (0 de 7
      folds, −40,7 % vs +675,0 %).

      **El bloqueador cambió de naturaleza, y eso es progreso:** antes era "no existe corpus
      auditable" (**levantado**); ahora es "el corpus cubre 8 de 254 activos y la hipótesis era
      transversal". No refutada: sigue sin ser comprobable, por **cobertura** y no por
      existencia. Haría falta un corpus con marca temporal que cubra la cola de activos
      pequeños — justo donde el factor dice que está la dispersión, y justo sobre lo que
      Wikipedia no escribe.

- [x] **F.19 Corpus que SÍ cubre la cola: ENCONTRADO. Bloqueador de cobertura LEVANTADO.**
      `data/history/binance-announcements.json`, **3.320 artículos con fecha** del CMS público
      de Binance: listados 2.276 (2017-07 → 2026-10), deslistados 439, mantenimiento 605.
      **COBERTURA 252 de 254 activos = 99 %** (231 con ≥3 menciones), frente a **8 de 254 = 3 %**
      de Wikipedia. **31× mejor**, y cubre exactamente la cola de activos pequeños.
      Segundo corpus auditable ya en disco: **fecha de primer cierre**, cobertura **254/254**.

- [x] **F.20 HALLAZGO NUEVO: la antigüedad del listado, t = +4,57.**

      | señal | IC medio | t | periodos+ |
      |---|---|---|---|
      | volatilidad 30d | −0,1194 | −4,76 | 26/86 |
      | **antigüedad del listado** | **+0,0773** | **+4,57** | **58/86** |
      | crecimiento de volumen | −0,0666 | −4,09 | 26/86 |
      | volumen medio | −0,0643 | −3,19 | 31/86 |
      | momento 30d | −0,0496 | −2,54 | 39/86 |

      **Los listados antiguos rinden más que los nuevos**, con el signo más consistente del
      estudio (58 de 86 periodos). Es el efecto conocido de bajo rendimiento de las nuevas
      cotizaciones, con **cobertura y auditabilidad perfectas**. Ya son **seis** señales a
      |t| ≥ 2 sobre 14.526 observaciones.

- [x] **F.21 La hipótesis de la narrativa: REFUTADA con el corpus correcto.**

      | señal del corpus | IC medio | t |
      |---|---|---|
      | anuncios en 90d | −0,0130 | **−0,86** |
      | anuncios en 180d | −0,0093 | **−0,58** |
      | avisos de deslistado en 180d | +0,0073 | **+0,59** |

      **Ninguna alcanza 1 error estándar**, medido sobre un corpus con 99 % de cobertura.
      **Pero preciso qué se refutó:** medí el **recuento** de menciones, no el **contenido
      semántico**. Lo refutado es "la intensidad de anuncios como señal", **no** "la comprensión
      de narrativa". La diferencia importa.
      *Qué queda establecido:* el corpus existe, cubre la cola y es auditable (ambos bloqueadores
      levantados); el proxy numérico barato falla, y en este repo el proxy barato fallando ha
      predicho correctamente el fracaso de la versión cara cada vez.
      *El siguiente paso ya no es de datos sino de presupuesto:* leer los 3.320 títulos con el
      **modelo local** (`qwen3:30b-a3b` en el servidor) cuesta horas de GPU y **cero dólares**.
      Es la única vía de cerrar la hipótesis sin tokens de terceros.

- [x] **F.22 Los titulares leídos por el modelo LOCAL: 439/439, 0 fallos, cero tokens de
      terceros.** `research/score_announcements.py` con `qwen3:30b-a3b` en el servidor.
      *Dos defectos corregidos:* el modelo emitía **prosa de razonamiento** pese a
      `think: false` (resuelto con `format` + esquema JSON, el mecanismo que `OllamaClient` usa
      en producción: un esquema no pide una forma, **constriñe el decodificador**); y el primer
      lanzamiento murió a los 150/439 sin rastro de OOM, pero el script era **reanudable por
      diseño** y continuó desde ahí en vez de empezar de cero.

- [x] **F.23 La prueba pre-declarada NO se pudo correr, y el error de diseño es mío.**
      El umbral era monotonía del exceso en el impacto y contraste negativo-vs-positivo con
      |t| ≥ 2. **Inejecutable:** escogí el catálogo de deslistados por ser el de mayor señal,
      pero es **uniformemente negativo por construcción** (27 eventos en −2, 4 en −1, **ninguno
      positivo**), así que la monotonía no tiene nada sobre lo que ser monótona.
      Peor para el propósito: el modelo etiquetó **366 de 439** como `delisting` con impacto −2,
      o sea **su juicio semántico es redundante con el nombre del catálogo** — justo la
      distinción que el experimento debía probar. Registrado, no sustituido por una prueba más
      fácil.

- [x] **F.24 Estudio de evento, lo único medible: NO SOSTENIDA.**
      `research/delisting_event_study.py`. Ventana que empieza el día **después** del anuncio,
      BTC como referencia para que el beta común se cancele.

      | | |
      |---|---|
      | eventos utilizables | **31** |
      | exceso medio (activo − BTC) | +110,90 % |
      | exceso **mediana** | **+0,65 %** |
      | t | **+1,89** (signo contrario al exigido) |
      | exceso negativo en | **14 de 31 = 45 %**, signo **p = 0,7634** |
      | rango | −33,7 % a **+1.089,5 %** |

      El umbral exigía t ≤ −2 con signo consistente. La media la domina **un solo evento de
      +1.089,5 %**, la mediana es cero y el 45 % es una moneda. Y reaparece la **firma de
      convexidad** (media +110,9 % contra mediana +0,65 %), el mismo patrón de F.7.

- [x] **F.25 CIERRE de la última hipótesis.**

      | forma | estado |
      |---|---|
      | **transversal** | **CERRADA por densidad**, sin necesidad del modelo: 93 % de celdas activo-periodo sin anuncio, mediana de 13 activos con señal frente a un suelo de 20 |
      | **de evento** | **MEDIDA y NO SOSTENIDA**: mediana +0,65 %, 45 %, p = 0,76 |
      | **monotonía semántica** | **INEJECUTABLE** por mi elección de catálogo |

      *Para cerrar la tercera* harían falta los 2.276 titulares de listados (~3 h de CPU con el
      agente vivo parado). **No lo recomiendo:** las dos formas medidas no sostienen nada y el
      juicio del modelo resultó redundante con la etiqueta en el subconjunto ya probado.
      *Agente vivo rearrancado y `active`* (PID 2545536) tras ~50 min parado.

- [x] **F.26 Las conclusiones del proyecto, hechas REPRODUCIBLES.** Tres módulos que producían
      los resultados que el proyecto defiende tenían **cero pruebas**, igual que el gate antes
      de las 14 que le añadí — y el gate escondía un hueco que habría aprobado un producto
      dominado por no hacer nada. Añadidas **26 pruebas** que afirman **aritmética, no formato**:
      `tests/test_static_frontier.py` (8), `tests/test_cross_section_ic.py` (9),
      `tests/test_delisting_event_study.py` (9). La que más importa es la de **look-ahead**:
      perturbar cada barra posterior a la fecha de evaluación no debe mover ninguna señal.

- [x] **F.27 Tres defectos encontrados POR esas pruebas, los tres míos.**

      1. **El hallazgo central no era reproducible con el código entregado.**
         `cross_section_ic.py` codificaba a fuego el fichero de **30 pares elegidos a mano**, sin
         forma de seleccionar el de 254. El titular de seis señales salía de scripts ad-hoc que
         nunca se guardaron: ejecutar el comando documentado daba **2 señales**, no seis.
         Corregido con selección explícita de universo y el **corregido de 254 por defecto**.
      2. **Mezcla de universos silenciosa.** Cargaba cierres de un fichero y volúmenes de otro
         camino fijo al de 30 pares, así que cualquier par fuera de ese conjunto se descartaba
         por falta de volumen — encogiendo un universo de 254 hacia 30 **sin un solo error**.
         Ahora ambos salen del mismo fichero.
      3. **`momento_30d_ajustado_vol` explotaba a ~1e15.** El guard era `volatilidad > 0`, pero
         una serie plana deja volatilidad ~1e-16 por ruido de coma flotante. El IC publicado
         **sobrevive** porque el estadístico es Spearman (rangos, inmune a la magnitud), pero el
         *ranking* era erróneo. Suelo de 1e-9.

      Y una reserva mal enunciada: la salida decía "universo elegido a mano", cierto del de 30 y
      **falso** del de 254 (alfabeto completo). El sesgo real es que faltan los pares ya
      deslistados. Enunciar la reserva equivocada apunta el escepticismo del lector al sitio
      equivocado.

- [x] **F.28 Números del factor transversal, corregidos a los REPRODUCIBLES.** Al cargar
      cierres y volúmenes del mismo fichero los seis t bajan un poco. **La conclusión no
      cambia:** seis señales a |t| ≥ 2, todas en la misma dirección, baja volatilidad dominante
      y momento **negativo** (reversión, no momento).

      | señal | IC | t documentado antes | **t reproducible** |
      |---|---|---|---|
      | volatilidad_30d | −0,1334 | −4,76 | **−5,04** |
      | antiguedad_listado_log | +0,0739 | +4,57 | **+4,33** |
      | crecimiento_volumen | −0,0626 | −4,09 | **−3,73** |
      | volumen_medio_30d | −0,0581 | −3,19 | **−2,87** |
      | momento_30d_ajustado_vol | −0,0440 | −2,94 | **−2,65** |
      | momento_30d | −0,0439 | −2,54 | **−2,14** |

      88 periodos, **14.562** observaciones activo-periodo (antes se reportaron 14.526).
      `antiguedad_listado_log` **no estaba implementada** en el módulo: el informe decía seis
      señales y el código entregado producía cinco. Implementada, con la reserva de que el
      primer cierre del dataset subestima la antigüedad real de los pares anteriores al inicio
      de los datos, lo que sesga la señal **hacia cero**, no hacia inventarla.

- [x] **F.29 DIAGNÓSTICO del agente vivo: las "decisiones que perdían" NO eran decisiones.**
      Disparado por una captura del historial de órdenes de Binance: las ventas aparecían como
      **`Stop Loss Market`**, no como decisiones, y sus disparadores estaban **al precio de
      mercado**. Verificación aritmética antes de medir nada:

      | entrada | `entry × 1,0025` | disparador real |
      |---|---|---|
      | 84.814,74 | **85.026,78** | `<= 85.026,77` |
      | 84.670,18 | **84.881,86** | `<= 84.881,85` |

      Coinciden al céntimo: era el **bloqueo break-even a +0,25 %**, no criterio del agente.

- [x] **F.30 El bloqueo break-even perdía dinero por ARITMÉTICA, no por mala suerte.**
      `research/stop_noise_sizing.py` sobre 79.477 barras horarias (2017-08 → 2026-09):

      | parámetro vivo | P(toque por ruido) 24 h | 7 d |
      |---|---|---|
      | bloqueo break-even 0,25 % | **100 %** | 100 % |
      | activación break-even 0,5 % | **99,50 %** | 100 % |
      | activación trailing 1 % | 94,80 % | 100 % |
      | trailing 2,5 % | 57,48 % | 98,47 % |
      | stop duro 3 % | 46,93 % | **96,25 %** |

      Y lo decisivo: **una vez armado el bloqueo, se dispara el 99 % de las veces** en 7 días.
      Aseguraba 0,25 % mientras la ida y vuelta cuesta 0,20 % → **neto 0,05 %**, el 80 % se lo
      comía el diferencial. Las cinco distancias están **por debajo del retroceso mediano** del
      activo en sus propios horizontes: medían microestructura, no información.

- [x] **F.31 CRONOLOGÍA: el defecto estaba arreglado en el código pero no en el proceso vivo.**
      El bloqueo break-even fijó el stop **solo** el 25-sep (98 decisiones) y el 1-oct (115), y
      **cero veces desde el 2-oct**. Commit `dd6be4f` (25-sep) lo metió bajo el playbook; el
      fichero llegó al servidor el **27-sep 17:38**; pero el proceso siguió con el código viejo
      en memoria y **volvió a disparar el 1-oct**. Solo se cargó cuando reinicié el servicio el
      **2-oct 18:04**, de forma incidental, para correr el puntuador de anuncios.
      **Lección operativa: un arreglo en el fichero no existe hasta que el proceso lo recarga.**

- [x] **F.32 SEGUNDO defecto, de robustez: deriva de reloj tumbaba el servicio.**
      No eran 3 reinicios sino **12**, con **9 caídas, 5 solo el 7-oct**. Causa exacta:
      `binance demo HTTP 400: {"code":-1021,"msg":"Timestamp for this request is outside of the
      recvWindow."}`. El adaptador firmaba con `int(time.time()*1000)` —el **reloj local sin
      compensar**— y solo reintentaba en 418/429, así que un −1021 llegaba como HTTP 400 no
      reintentable, salía de `account_balance()` por la reconciliación de posición y **mataba el
      proceso**. Arreglado en `src/btc_decision_agent/adapters/binance_execution.py`:
      compensación contra `/api/v3/time` (cacheada, re-medida al recibir −1021) y reintento
      **acotado a ese código**, no a todo HTTP 400, para que una orden inválida siga fallando
      ruidosamente.

- [x] **F.33 TERCER defecto, en mi propio instrumento: la razón de captura mentía de signo.**
      Con retornos negativos, agente −1,12 % contra nulo −0,98 % da **1,15x**, que se lee como
      "supera al nulo" cuando en realidad **perdió más**. Corregido en
      `research/live_performance.py`: ahora informa la **diferencia con signo** y solo muestra la
      razón cuando ambos lados son ganancias.

- [x] **F.34 VALIDACIÓN FUERA DE MUESTRA del arreglo, contra los dos nulos.**
      `research/stop_geometry_validation.py`. Stop probado contra **mínimos** de barra con orden
      intrabar adverso (un mínimo que toca el stop cuenta como salida aunque la barra también
      marque máximo), comisiones adversas en ambas patas.

      | geometría | **FUERA DE MUESTRA** (2017→2024) | desarrollo (2024→2026) | caída OOS |
      |---|---|---|---|
      | viva (rota), bloqueo 0,25 % | **−3,02 %** | −9,91 % | 22,45 % |
      | **arreglada**, bloqueo no arma | **+32,62 %** | **−2,66 %** | 17,85 % |
      | ruido-medido (duro 10 %, trail 8 %) | +610,73 % | −23,51 % | **65,02 %** |

      El arreglo **mejora en AMBOS segmentos** (+35,64 pp fuera de muestra, +7,25 pp en
      desarrollo), que es la firma de un defecto corregido y no de un ajuste. **ADOPTADO.**

- [x] **F.35 Intento RECHAZADO: la geometría dimensionada por ruido.** Rinde +610,73 % fuera de
      muestra, muy por encima de todo lo demás, y **la rechazo**: su caída es **65,02 %**, que
      viola el techo del 25 % del mandato. No se adopta un resultado que incumple la
      restricción declarada por muy bueno que sea el retorno.

- [x] **F.36 VEREDICTO: el arreglo es real y SIGUE sin batir a no hacer nada.**
      Fuera de muestra, comprar y mantener dio **+2.189,89 %** con caída 83,91 %; desapalancado
      al mismo riesgo que la geometría arreglada, el nulo rinde **+465,95 %** frente a los
      +32,62 % del agente: **−433,33 pp**. Ninguna de las tres geometrías supera al nulo al mismo
      riesgo en ningún segmento. Es la **sexta** confirmación del mismo hecho. Lo que el arreglo
      compra es **dejar de destruir valor**, no ventaja.

- [x] **F.37 CORREGIDO: el agente decidía sin su LLM. El parámetro mal dimensionado era el
      TIMEOUT, no la cadencia.** Mi propio diagnóstico previo atribuía el fallo a que el modelo
      no alcanzaba "la cadencia de 5 s"; **era incorrecto**. La arquitectura ya es **no
      bloqueante** (deliberación en hilo aparte, el mercado se sigue vigilando) y la cadencia ya
      era de **30 min**, más larga que el timeout. El mensaje real del journal:
      `LLM no disponible (modelo inalcanzable: TimeoutError('timed out'))`, **12 veces** → 1.537
      decisiones con `FALLBACK_QUANT_HOLD` en 26 h, porque un fallo deja el respaldo numérico al
      mando hasta la siguiente deliberación con éxito.

      **Medido** con `research/llm_latency_probe.py` (llamada barata, `think=False`):

      | muestra | total | cola | prompt | generación | tokens |
      |---|---|---|---|---|---|
      | 1 | **120,4 s** | 95,2 s | 0,12 s | 25,1 s | 250 |
      | 2 | **317,5 s** | 292,8 s | 0,11 s | 24,6 s | 250 |

      El hallazgo: **el cómputo es estable (~25 s) y la COLA domina, variando 3x (95→292 s)**.
      La contención es la causa, no la velocidad del modelo. Y produccción hace **dos llamadas
      secuenciales** por deliberación que quiere mover el libro: barata (`num_predict=900`) y
      razonada (`think=True`, `num_predict=2500`), y el timeout aplica **por llamada**.

      **Aplicado:** `--llm-timeout-seconds` ahora existe (antes `600.0` estaba **fijo en el
      código**, imposible de dimensionar sin editar fuente) y el servicio corre con
      **timeout 1200 s y cadencia 45 min**, verificado en vivo: `cadence=45min`, 0 errores.
      Guarda nueva en `LLMAgentEngine`: **rechaza** una cadencia que no cubra 2 × timeout, con
      los tres números en el mensaje. El par anterior (600 s × 2 = 1200 s contra 1800 s) **sí
      cabía**, lo que confirma por aserción que no era un problema de cadencia.

      **RESERVA honesta:** no logré medir la ruta **razonada**. La sonda murió dos veces sin
      rastro de OOM con la memoria a 0 GB libres, y **seguir sondeando compite con el agente
      vivo por el mismo modelo**, que es exactamente la causa del problema. El 1200 s sale de
      2× el timeout que demostradamente falló y de la varianza de cola medida (3x), no de una
      medición directa de esa ruta. **Reduce el riesgo de timeout; no está demostrado que lo
      elimine.**

      *No toqué `num_predict`:* ambas muestras generaron **250 tokens** y pararon solas, así
      que el esquema estructurado ya corta mucho antes del tope de 2500 y bajarlo no habría
      cambiado la latencia.

- [x] **F.38 ¿Qué modelo local es el mejor para este agente? Medido en la máquina, no en un
      ranking. Y el resultado CONTRADICE lo que sugería el índice público.**

      **Primero: LMArena no puede responder esta pregunta.** Lo consulté (413 modelos, 8,6M de
      votos) y falla por tres razones estructurales: (1) su cima es **100 % propietaria**
      (Claude Opus 4.6 1505, Gemini 4 Argon 1525), vetada por la regla de cero tokens de
      terceros; (2) **no publica parámetros ni RAM**, y la restricción vinculante aquí son
      23 GB en 4 núcleos aarch64 **sin GPU**; (3) **los modelos que caben aquí no están en el
      ranking**, porque un arena necesita una API alojada y los Qwen3.5 sub-10B no tienen
      hosting serverless. Peor: su Elo premia **prosa larga y agradable** — el propio Arena
      ofrece un control de "Style Control" para restar ese efecto — y este agente **solo emite
      cinco campos bajo esquema JSON**, donde la verbosidad es latencia pura.

      **Criterios declarados antes de medir, por orden:** cabe con holgura, parsea el esquema,
      responde dentro del presupuesto, está calibrado, es consistente a temperatura 0.
      **NO se rankea por acierto de mercado:** la ventaja direccional de este proyecto está
      medida en **cero seis veces**, así que ordenar modelos por si aciertan el próximo
      movimiento de BTC sería ordenarlos por ruido.

      `research/model_bakeoff.py`, 3 escenarios × 2 repeticiones, **con el agente vivo parado**
      para que los tres compitan en igualdad:

      | | **actual** `qwen3:30b-a3b` | `qwen3.5:9b` | `qwen3.5:4b` |
      |---|---|---|---|
      | RAM | 19,05 GB | 6,55 GB | **3,32 GB** |
      | parseadas | 6/6 | 6/6 | 6/6 |
      | violaciones | 0 | 0 | 0 |
      | inestables | 0 | 0 | 0 |
      | latencia **mediana** | **42,0 s** | 97,1 s | 47,0 s |
      | peor latencia | 241,6 s | **119,9 s** | **68,7 s** |
      | índice público (Artificial Analysis) | 8 | 32 | 27 |

      **El índice público predijo mal el resultado.** El modelo actual, con índice 8, es el
      **más rápido en mediana** (42 s) y el **mejor calibrado** de los tres. Razón medida: es
      MoE con **3,3B activos**, frente a 9B densos del 9b — el MoE ahorra cómputo, y en CPU el
      cómputo es lo que manda. Mi reserva previa («en cómputo por token el 9B es peor, no
      mejor») **se confirmó**.

      **Los 826 s de producción eran CONTENCIÓN, no lentitud del modelo:** a solas con la
      máquina el mismo modelo responde en 42 s. Lo que causa la contención es que ocupe 19 de
      23 GB.

      **Calibración, donde el actual gana claramente:**

      | escenario | actual | 9b | 4b |
      |---|---|---|---|
      | alcista (prompt: +18 % a 30d) | conv 0,56 · mov +0,18 % | conv 0,10 · mov −2,5 % | conv 0,15 · **mov +18,0 %** |
      | bajista (prompt: −28 %) | **conv 0,85 · mov −15,0 %** | conv 0,15 · mov −18,5 % | conv 0,15 · mov −28,0 % |
      | lateral (prompt: +0,6 %) | conv 0,525 · mov +0,6 % | conv 0,10 · **mov −25,0 %** | conv 0,0 · mov 0,0 % |

      El **9b predijo −25 % en un escenario de consolidación declarada**, que es una magnitud
      inventada y peligrosa para un dimensionador. El **4b fue prudente hasta la inacción**:
      EFECTIVO en los tres con convicción 0,0-0,15, incluido el alcista claro.

- [x] **F.39 HALLAZGO INESPERADO: el modelo actual COPIA al modelo cuantitativo en vez de
      razonar.** En **4 de 6** respuestas su convicción es una copia **exacta** de la `P(long)`
      que el prompt le entregó (0,56→0,56 y 0,525→0,525), y en **2 de 6** el movimiento
      esperado copia literalmente el retorno a 30 días del enunciado (+0,6 %→+0,6 %). En el
      escenario alcista escribió **+0,18 %** donde el prompt decía **+18 %**: un error de
      unidad de dos órdenes de magnitud.

      Esto **da una explicación mecánica a las seis mediciones de timing en cero**: si el LLM
      repite la probabilidad del modelo cuantitativo, no aporta información independiente, y su
      correlación de timing tiene que salir exactamente la del modelo que copia. No prueba que
      sea la única causa, pero es la primera explicación *medida* del fenómeno.

- [x] **F.40 TRES defectos propios en el instrumento, encontrados y corregidos durante F.38.**

      1. **Falso positivo que casi descalificó un modelo.** Mi juez marcó dos respuestas del
         9b como «propone ponerse corto», que el mandato prohíbe. El texto real decía
         *«riesgo significativo de corrección a corto **plazo**»* — un horizonte temporal.
         Buscaba la palabra «corto» a secas. Corregido para exigir verbos de cortar y excluir
         los modismos de horizonte; **20 pruebas** en `tests/test_model_bakeoff.py` incluyendo
         el texto literal que me engañó. Con el juez corregido el 9b tiene **cero violaciones**.
      2. **Restauración del servicio que mentía.** Un `trap EXIT` simple imprimió éxito
         mientras el journal no registraba arranque, y **dejó el agente parado dos veces**. La
         v2 que grepeaba el journal produjo el error opuesto: **falsa alarma** de «requiere
         atención humana» con el agente activo y decidiendo. La v3 verifica **evidencia de
         vida** (activo + activación posterior a la parada + está escribiendo decisiones).
      3. **El informe se perdía al morir.** El bakeoff murió **dos veces** por presión de
         memoria y se llevó mediciones ya completadas. Ahora escribe tras **cada** modelo.

      Que muriera dos veces **es un dato sobre la máquina**, no un incidente: 23 GB compartidos
      con el agente en sombra, Redis, Timescale, Vault, Grafana, Jaeger, Prometheus y dos
      paneles.

- [ ] **F.41 PENDIENTE — recomendación, y por qué NO es la obvia.** El caso para cambiar de
      modelo es **más débil** de lo que sugería el índice público: el actual es el más rápido en
      mediana y el mejor calibrado. Lo que sí resuelve un cambio es la **contención** (19 de
      23 GB → 0 libres y swap en uso), que es la causa real de los 826 s en producción.
      El candidato con mejor balance es **`qwen3.5:4b`** (3,32 GB, peor caso 68,7 s, 0
      violaciones, consistente), aceptando que es más prudente. **Descartado `qwen3.5:9b`**: más
      lento que el actual y peor calibrado. Requiere decisión de Carlos; no se ha cambiado nada.

- [x] **F.42 La hipótesis de la COPIA, mía, REFUTADA sobre 312 deliberaciones reales.**
      En el bakeoff vi que en 4 de 6 escenarios la convicción del LLM igualaba la `p_largo`
      que el prompt le entrega, y propuse investigarlo como prioridad sobre cambiar de modelo.
      Medido en la memoria del agente (`research/llm_independence.py`, 312 deliberaciones,
      24-sep → 7-oct), donde `quant_p_long` y `conviction` están guardados lado a lado:

      | | |
      |---|---|
      | copias **exactas** de `p_largo` | **1 de 312 = 0,3 %** |
      | dentro de ±0,01 | 3 de 312 = 1,0 % |
      | diferencia media | **+0,1856** |
      | mayor desacuerdo | +0,2947 |

      **No copia.** Lo que hace es desviarse **sistemáticamente +0,19 por encima** de su
      asesor, siempre en la misma dirección. Seis escenarios elegidos a mano no eran evidencia
      sobre la población; lo registro como refutado.

      *Verificado antes de medir:* la convicción se parsea del LLM (`llm_agent.py:285`), no la
      sustituye el código, así que lo observado era comportamiento real del modelo.

- [x] **F.43 Lo que apareció en su lugar es PEOR: la decisión es casi una CONSTANTE.**

      | | |
      |---|---|
      | valores distintos de convicción usados | **5** (0,58 · 0,70 · 0,75 · 0,80 · 0,85) |
      | convicción modal | **0,75 en 257 de 312 = 82,4 %** |
      | rango usado | [0,58 · 0,85] — **nunca baja de 0,58** |
      | exposición modal | **INVERTIDO en 311 de 312 = 99,7 %** |
      | pronósticos **negativos** | **0 de 312 = 0,0 %** |
      | rango del pronóstico | [+0,50 % · +12,00 %] |

      **Cero pronósticos negativos en 13 días que incluyen caídas de BTC.** Y el prompt
      advierte exactamente de esto: *«si declaras casi siempre el mismo numero, ese numero ha
      dejado de informar y el tamaño deja de responder a lo que ves»*. No es un estándar
      externo: es su propia instrucción, incumplida y medida.

      **Esto explica MECÁNICAMENTE las seis mediciones de correlación de timing en cero.** Una
      convicción que no varía no escala nada, y una dirección constante no es una decisión: un
      agente que dice lo mismo siempre **es** comprar-y-mantener, y su correlación con el
      momento de mercado tiene que ser cero. Es la primera explicación *medida* del fenómeno,
      no solo su constatación.

      *Reserva:* 312 deliberaciones en 13 días, y el agente solo vio **2 de 4 regímenes**
      (régimen 3 en 299, régimen 0 en 12). No se puede afirmar que la constancia persista en un
      bajista profundo, porque no lo ha visto.

      **Consecuencia para F.41:** cambiar de modelo **no arregla esto**. El 4b fue prudente
      hasta la inacción y el 9b mal calibrado; ninguno ataca la causa. El problema no es qué
      modelo decide, sino que **lo que emite no varía con la evidencia**.

- [x] **F.44 ARREGLADA la ceguera que impedía corregir la constancia. No es ingeniería de
      prompt: es un número sin su nulo.**

      Antes de tocar nada verifiqué si la constancia era corregible por código o si estaría
      ajustando texto a gusto. **El bucle de retroalimentación ya existía** y mostraba al
      modelo contraste real por bucket de convicción. Pero tenía un defecto medible:

      **El acierto se mostraba SIN el nulo contra el que juzgarlo.** El agente eligió
      INVERTIDO en el 99,7 % de las decisiones, así que *«acertaste 51 %»* es esencialmente la
      frecuencia con que subió BTC. Este proyecto se niega a reportar un número sin su
      comparador en todas partes **menos en la retroalimentación del propio agente**, que era
      justo donde más importaba.

      Lo que el modelo ve **ahora**, con sus datos reales:

      | convicción | casos | acierto | **ventaja sobre su tasa base (44 %)** |
      |---|---|---|---|
      | 0,5-0,7 | 1 | 100 % | +56 % *(un caso: ruido)* |
      | 0,7-0,85 | 51 | 51 % | **+7 %** |
      | 0,85-1,0 | 29 | 31 % | **−13 %** |

      Sus convicciones **más altas rinden PEOR que estar siempre dentro**. Esa es la
      información que le faltaba: antes veía «31 %» sin saber que su propio nulo era 44 %.

      Y añadí la medición que no existía: **la dispersión de su propia convicción**. El prompt
      ya le decía *«si declaras casi siempre el mismo número, ese número ha dejado de
      informar»*, pero **nada lo medía**. Ahora lee: *«declaraste 0,75 en el 82 % de tus 312
      decisiones; usaste 5 valores distintos en [0,58 · 0,85]»* más una alerta explícita.

      Umbral `DEGENERATE_CONVICTION_SHARE = 0.5` fijado **por argumento, no por ajuste**:
      cuando el mismo valor se declara *más veces que no*, la mejor descripción de la salida
      del agente es esa constante. Exactamente la mitad **no** es "casi siempre", y una alerta
      que salta con una distribución merely concentrada se convierte en ruido que el modelo
      aprende a ignorar.

      **Defecto en mi propio arreglo, encontrado y corregido:** calculaba la dispersión solo
      sobre las **81 resueltas** (42 % modal), descartando 231 de 312 observaciones y
      **subestimando la degeneración a la mitad** — la alerta no habría disparado sobre un
      agente que se repetía claramente. La dispersión no necesita resultados. Corregido a las
      312, y con ello la alerta sí dispara. Prueba dedicada que lo fija.

      **LÍMITE HONESTO, y es el que importa:** esto **quita la ceguera, no arregla la
      constancia**. Que el modelo responda al ver su propia degeneración es una pregunta
      empírica que este cambio **no responde**. Lo que sí garantiza es que la información
      necesaria para corregirse está delante de él y medida. Habrá que volver a correr
      `research/llm_independence.py` dentro de unos días para saber si cambió algo.

      Desplegado y reiniciado: `active`, 0 reinicios, 0 errores, 677 pruebas.

---

## Hipótesis ya refutadas — no reintentar

Cada una está medida y documentada en `handover.md`. Reintentarlas es gastar horas de GPU en
algo ya respondido.

- [x] El stop protector destruye el retorno. **Refutado:** quitarlo empeora la bajista
      (−10.05% contra −2.96%). Lo que movía el resultado era el tamaño.
- [x] La histéresis de régimen causa las salidas por stop. **Refutado:** 7 de 10 ocurrieron
      sin ningún cambio de régimen.
- [x] Los rangos globales de postura están mal calibrados. **Refutado:** la postura responde
      limpiamente (convicción 0.497/0.538/0.730, precio 1.32x/1.48x/2.02x).
- [x] La cadencia gruesa del backtest castiga al agente. **Refutado:** reentrar 1 h después
      de un stop en vez de esperar la siguiente decisión mueve +23.23% a +23.44%.
- [x] Hay una política de exposición mejor que las demás. **Refutado:** override +63.60%,
      autoridad plena +59.51%, mezcla +53.08%. Caben en 10.5pp sobre 60 decisiones.
- [x] La intensidad de anuncios/narrativa ordena los activos transversalmente. **Refutada con
      corpus del 99 % de cobertura:** anuncios 90d t=−0,86, 180d t=−0,58, avisos de deslistado
      t=+0,59. Ninguna alcanza 1 ee. (Refutado el RECUENTO, no el contenido semántico.)
- [x] El volumen medio alto ordena mejor los activos. **Refutado por inversión de signo:**
      +2,74 con 30 pares elegidos a mano, **−2,08** con 100 pares programáticos.
- [x] El momento transversal ordena los activos de cripto. **Refutado con 2.396 observaciones:**
      IC de momento a 30d/90d/180d con t = −1,21 / +0,34 / +0,58. No significativo en ningún
      horizonte. Lo que sí ordena es la **baja volatilidad** (t = −5,23) y el **tamaño**
      (t = +2,74).
- [x] La rotación transversal long-only bate a BTC de forma establecible. **Refutado en su forma
      actual:** +1.205,1 % compuesto OOS cae a **−38,6 %** quitando un fold de cinco, y la caída
      del 80,4 % triplica el tope. Prometedor pero no certificable con 5 folds.
- [x] Los inputs de volumen y flujo convierten en dinero. **Refutado:** alcanzan 1 ee en 5 de 24
      pares (frente a 0 de 20 solo-cierres) pero 0 de 24 llegan a 2 ee, y en walk-forward
      0 de 7 folds baten al estático al mismo riesgo (−40,7 % contra +675,0 %).
- [x] Existe un playbook ALCISTA que supera quedarse en USDT. **Refutado:** 13 tramos OOS, el
      +126,0 % cae a +19,5 % quitando un solo tramo, 5 de 13 positivos, mediana −3,3 %,
      prueba de signo p=0,867.
- [x] Existe un playbook BAJISTA que supera quedarse en USDT. **Refutado por tres vías:**
      test limpio 2018-2019 (todas las variantes −27,4 % a −61,8 % contra USDT 0 %), selección
      walk-forward (7/7 folds eligieron USDT), aplicación ciega walk-forward (6/7 negativas,
      la positiva con efecto 0,58). Estructural: sin cortos, batir a estar fuera en un declive
      exige la ventaja de momento medida en cero cuatro veces.
- [x] La herramienta de réplica predice el efecto de un cambio de política.
      **Refutado dos veces:** predijo +99.70% y salió +59.51%; predijo +99.48% y salió
      +53.08%.

## Trabajo cerrado

- [x] **Noveno defecto estructural: el notificador informaba corridas que no ocurrieron.**
      Encontrado el 2026-10-01 al lanzar A.1, y **cobrado en vivo**: llegó a Slack un
      `*Backtest terminado* · APROBADO` con los números de la ventana **bajista** de
      septiembre mientras la corrida alcista real iba por la decisión 1 de 60.
      *Mecanismo:* `wait_for()` capturaba `ProcessLookupError` y **retornaba** cuando el PID
      no existía, tratando "ya murió" como "acaba de terminar". Luego `compose()` leía
      `DEFAULT_REPORT` sin comprobar que esa traza perteneciera a la corrida vigilada. Un PID
      equivocado bastaba para publicar un veredicto plausible sobre otra ventana.
      *Misma forma que los ocho anteriores:* una intención declarada ("informar la corrida que
      acaba de terminar") que nada verificaba, y **cero pruebas** cubrían el fichero.
      Es la **tercera** vez que un valor por defecto silencioso fabrica un número falso en
      este proyecto (`handover.md` §8).
      *Corrección, justificada por coherencia interna y no por retorno:* un PID inexistente al
      empezar a esperar es `NotTheRunWeWatched` y sale con código 2; y una traza cuyo `mtime`
      es **anterior** al inicio de la vigilancia se rechaza con el desfase en horas, en vez de
      informarse. Falla ruidosamente, que es la regla que este proyecto ya adoptó.
      *Verificado en el servidor, no solo en local:*
      `notify_backtest --wait-for-pid 2118091` → `exit=2`, sin mensaje a Slack. Rearmado sobre
      el PID real 2118160 queda **bloqueado** con el log vacío, como debe.
      *Pruebas:* `tests/test_notify_backtest.py`, 5 casos (PID muerto, traza rancia con su
      desfase, traza fresca aceptada). Suite **480 → 485**, `ruff` y `mypy -p
      btc_decision_agent` limpios.
      *Ficheros:* `scripts/notify_backtest.py`, `tests/test_notify_backtest.py`.

- [x] Ocho defectos estructurales encontrados y corregidos. Alcista de −15.77% a +63.60%,
      bajista de −13.90% a −2.39%. Detalle en `handover.md` sección 4.
- [x] Nueve herramientas de diagnóstico sin GPU. `handover.md` sección 6.3.
- [x] Gate pre-registrado con ocho criterios, independiente de la magnitud de la ventana.
- [x] Escalado de posición conectado al camino de órdenes real, con el primer test del
      `RealtimeDemoRunner` que ha existido en el repo.
- [x] 480 pruebas, ruff y mypy limpios.
- [x] Slack diagnosticado: entrega bien, pero `SLACK_CHANNEL` es un **usuario**, así que los
      avisos llegan como DM del bot `crybin` y aparecen en la sección **Apps** de Slack. El
      token no tiene permiso para listar ni unirse a canales.
