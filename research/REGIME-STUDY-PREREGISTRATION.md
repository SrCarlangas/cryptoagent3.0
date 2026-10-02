# Pre-registro: playbooks por régimen para BTC/USDT spot

Escrito **antes** de medir. Existe porque este proyecto ya demostró, en
`data/validation/exposure-diagnosis.md` sección G, que elegir una configuración
después de ver su retorno produce artefactos: 20 de 42 celdas batían a comprar y
mantener en muestra, y las elegidas devolvieron −86pp, −23pp y +16pp fuera de muestra.

Cualquier cosa que este estudio decida después de ver un resultado queda marcada como
tal en el informe.

## 1. La pregunta, y lo que ya está respondido

**Pregunta nueva:** ¿existe una asignación *condicionada al régimen* que, respetando un
techo de caída del 25 %, bata a sus alternativas simples fuera de muestra?

**Ya respondido por este repo, y no se reintenta:**

| Hipótesis | Veredicto medido | Fuente |
|---|---|---|
| Hay señal direccional explotable a horizontes asequibles | **Refutada.** 0 de 20 pares señal/horizonte alcanzan 1 SE | diagnosis §D2 |
| La dirección a 4 h es predecible | **Refutada.** P(subida) = 0.5054 | diagnosis §A |
| Barrer la longitud de la media encuentra un ganador | **Refutada.** Ninguna sobrevive a comisiones adversas | diagnosis §E |
| La selección longitud/banda generaliza en retorno | **Refutada.** 1 de 3 cortes OOS | diagnosis §G |
| Recortar exposición recorta la caída | **CONFIRMADA, 3 de 3 cortes OOS** (+17.9/+17.9/+23.8pp) | diagnosis §G |

El prior honesto es por tanto: **es improbable encontrar ventaja de retorno; es probable
confirmar control de caída.** Este estudio está diseñado para poder entregar ese negativo.

## 2. La restricción del 25 % reencuadra el benchmark

Comprar y mantener cayó **−73.3 %** en el bajista 2021-2022 (diagnosis §E). **Viola el
techo del 25 % por un factor de casi tres.** Así que no es un benchmark admisible: es una
cota de referencia que el sistema no tiene permiso de igualar en riesgo.

Se reportan por tanto tres referencias, y se dice explícitamente cuál es admisible:

1. **Comprar y mantener** — contexto. **Inadmisible** (caída > 25 %).
2. **Todo en USDT** — admisible trivialmente (0 % retorno, 0 % caída). Es la barra que hay
   que batir para justificar operar.
3. **Comprar y mantener con techo de caída** — comprar y mantener que liquida al tocar
   −25 % y vuelve bajo una regla declarada. Es el competidor *honesto*, porque respeta la
   misma restricción.

Un playbook que bate a (1) en retorno pero cae un 40 % **no cuenta como éxito** aquí.

## 3. Taxonomía de regímenes (congelada ahora)

Dos ejes ortogonales sobre **cierres diarios completos** (UTC), nunca sobre la barra en
curso:

- **Direccionalidad:** ratio de eficiencia de Kaufman a 30 d,
  `ER = |C_t − C_{t−30}| / Σ|C_i − C_{i−1}|`. Mide si el camino fue recto o de ida y
  vuelta. Es una descripción, no una predicción.
- **Volatilidad:** desviación típica de retornos logarítmicos diarios a 30 d, expresada
  como **percentil dentro de los 365 d previos** (escala-libre, se adapta de época).

| Régimen | Definición |
|---|---|
| ALCISTA | `ER ≥ θ_er` y retorno 30 d > 0 |
| BAJISTA | `ER ≥ θ_er` y retorno 30 d < 0 |
| LATERAL | `ER < θ_er` y percentil de vol `< θ_vol` |
| ALTA_VOL_SIN_DIRECCION | `ER < θ_er` y percentil de vol `≥ θ_vol` |

`θ_er` y `θ_vol` se eligen **solo en el segmento de entrenamiento** y se congelan.

**Persistencia:** una etiqueta nueva requiere `k` días consecutivos antes de sustituir a la
vigente. Esto no es un adorno: la columna de banda cero falló 7 de 7 veces en diagnosis §F,
y el clasificador actual del proyecto cambia de etiqueta en el 37 % de las transiciones.

## 4. Cómo se mide la calidad de detección, separada del dinero

Pediste detección rápida y con pocas falsas alarmas. Eso es medible **sin** hablar de
rentabilidad, y se reporta aparte.

Se construye un **etiquetador oráculo** que usa ventanas *centradas* (es decir, mira el
futuro) para definir los segmentos "verdaderos". Sobre esos segmentos se mide:

- **Retardo de detección:** días desde la transición del oráculo hasta que el detector
  causal cambia de etiqueta.
- **Tasa de falsas alarmas:** transiciones del detector sin ninguna transición del oráculo
  dentro de una tolerancia declarada.
- **Cobertura:** fracción de transiciones del oráculo detectadas.

**Cortafuegos, y es la parte que más fácilmente se corrompe:** el oráculo existe
únicamente para puntuar al detector. Ninguna regla de entrada, salida, stop o tamaño puede
leerlo. Hay una prueba que lo exige.

## 5. Protocolo contra el sobreajuste

- **Entrenamiento / selección:** 2020-01-01 → 2023-06-30.
- **Validación (iteración permitida):** 2023-07-01 → 2025-03-31.
- **Prueba final, se mira UNA vez:** 2025-04-01 → 2026-09-16. Si se mira para iterar, se
  destruye y no hay otra.
- Retardo de ejecución de **1 barra**: se decide sobre una barra cerrada y se rellena al
  cierre siguiente.
- Comisión **10 bps por lado** (la tuya) y además un escenario adverso de **20 bps** que
  absorbe deslizamiento. Un playbook que solo sobrevive a 10 bps no se reporta como válido.
- Los huecos documentados del dataset nunca se puentean; el calentamiento de indicadores
  se reinicia tras un hueco.
- Si una variante cae dentro del rango de las otras, **es ruido**, no una mejora.

## 6. Criterios de éxito, declarados antes de medir

Un playbook de régimen se declara útil solo si, **en el segmento de validación y con
comisiones adversas**, cumple las tres:

1. Caída máxima **≤ 25 %**.
2. Retorno neto **> 0** y por encima de quedarse en USDT por un margen superior a su propio
   error estándar.
3. No peor que comprar-y-mantener-con-techo en retorno **por más de su error estándar**.

Si un régimen no cumple (2), el informe dirá que **en ese régimen lo correcto es quedarse
en USDT**. Ese resultado es un cierre válido, no un fracaso del estudio.

## 7. Qué se reporta aunque falle

Todos los intentos, incluidos los que no funcionan, con su número medido. Un negativo
medido cierra una línea igual que un positivo.
