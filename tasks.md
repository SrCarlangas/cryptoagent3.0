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
setsid nohup env PYTHONPATH=src:research .venv/bin/python -m scripts.notify_backtest \
  --wait-for-pid <PID> --slack > /tmp/notify.log 2>&1 < /dev/null &

# 4. AL TERMINAR: volver a arrancar el agente vivo
sudo systemctl start cryptoagent3-llm-agent
```

La orden protectora vive en el exchange, así que la posición sigue cubierta con el servicio
parado. Pero el agente no decide, y eso no debe durar más que el backtest.

---

## Fase A — Cerrar el hueco de medición

- [ ] **A.1 Correr la ventana alcista con las 8 correcciones.**
      Días 1260-1560, 60 decisiones, paso 5, `--end-day 1560`. ~2.8 h.
      La mejor alcista que existe (+53.08%) es anterior al defecto 8, que valió 11.5 puntos
      en la bajista. Sin esto no sabemos dónde estamos.
      *Criterio:* traza archivada inmutable en `data/validation/runs/`.

- [ ] **A.2 Evaluar esa corrida con las cuatro herramientas.**
      ```bash
      PYTHONPATH=src:research .venv/bin/python -m scripts.gate_llm_agent --report <ruta>
      PYTHONPATH=src:research .venv/bin/python -m research.regime_attribution <ruta>
      PYTHONPATH=src:research .venv/bin/python -m research.capture_decomposition <ruta>
      PYTHONPATH=src:research .venv/bin/python -m research.regime_corroboration <ruta>
      ```
      *Criterio:* en `tasks.md` quedan escritos el veredicto del gate, la captura, la
      **correlación de timing** y el beneficio por régimen con su efecto.

- [ ] **A.3 Comparar contra las cuatro corridas alcistas anteriores.**
      `python -m research.compare_runs "*alcista-1260-1560*"`
      *Criterio:* queda dicho si la mejora del defecto 8 sale del rango de ruido de las
      otras tres (10.5pp) o cae dentro. Si cae dentro, **no** es una mejora.

## Fase B — ¿Es el modelo, o es el problema?

- [ ] **B.1 Correr el backtest con un modelo frontera por API.**
      Misma ventana, mismas 60 decisiones, mismo paso. Cambiar **solo** `OllamaClient` por un
      cliente equivalente. Nada más: ni prompt, ni playbook, ni stops.
      *Criterio:* traza archivada, y el coste en dólares anotado.

- [ ] **B.2 Comparar la correlación de timing entre los dos modelos.**
      Es la medida que decide, no el retorno. Un retorno mejor con timing cero es suerte.
      *Criterio:* las dos correlaciones con su error estándar, y una frase que diga si la
      diferencia supera dos errores estándar.

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

- [ ] **E.1 Corrida de veredicto sobre el holdout.**
      **Solo si A-D encontraron una ventaja medible.** Días 960-1260, 100 decisiones,
      paso ≤3. Una sola vez. Nunca antes.
      *Criterio:* veredicto del gate acatado, sea el que sea.

- [ ] **E.2 Si no hay ventaja, ejecutar el pivote declarado.**
      Reescribir el gate alrededor de "comprar y mantener con la caída recortada", con los
      criterios pre-registrados **antes** de volver a medir. La evidencia que lo sostiene ya
      existe: bajista −2.39% contra −12.86%, drawdown 6.1% contra 39.5%.
      *Criterio:* gate nuevo comiteado antes de la corrida que lo evalúa.

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
- [x] La herramienta de réplica predice el efecto de un cambio de política.
      **Refutado dos veces:** predijo +99.70% y salió +59.51%; predijo +99.48% y salió
      +53.08%.

## Trabajo cerrado

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
