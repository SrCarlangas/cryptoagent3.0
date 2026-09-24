# Agente ML local BUY/HOLD/SELL

## Alcance y seguridad

El runtime usa un clasificador softmax lineal local como **fuente final de intención direccional**. El modelo sólo elige `BUY`, `HOLD` o `SELL`; no elige cantidad ni envía órdenes. Los breakers diarios/drawdown, stop inicial/break-even/trailing, calidad/frescura de datos, cooldown, minimum hold, reconciliación de posición, sizing por efectivo/riesgo, filtros del venue, SQLite write-ahead e idempotencia continúan siendo vetos posteriores o de mayor prioridad.

Si el JSON del modelo no existe o es inválido, el CLI aborta. Si se construye el engine sin modelo, toda dirección no protectora produce `MODEL_UNAVAILABLE` y `HOLD`. Los stops y breakers siguen pudiendo producir una salida protectora sin modelo.

No usa servicios ni APIs ML externos y no añade dependencias. El modelo, normalizador Welford, entrenamiento SGD, persistencia y métricas usan Python local. Sigue siendo DEMO-only para ejecución.

## Entrenamiento reproducible

```bash
.venv/bin/python -m scripts.train_local_model \
  --dataset data/history/btcusdt-1h \
  --model-path data/models/local-softmax-v1.json \
  --report-json data/reports/local-softmax-v1-training.json \
  --report-md data/reports/local-softmax-v1-training.md
```

El entrenador verifica el manifest/hash del dataset y selecciona exactamente los cinco años calendario que terminan en el último cierre disponible. No mezcla datos: conserva orden temporal, no cruza gaps y separa el 20% final como holdout. Cada label mira cuatro barras hacia delante dentro del mismo segmento continuo:

- `BUY`: retorno 4h menos 20 bps de costo round-trip >= 10 bps.
- `SELL`: retorno inverso 4h menos 20 bps >= 10 bps.
- `HOLD`: ninguna oportunidad neta supera el umbral.

La normalización se ajusta online sólo con observaciones de entrenamiento. El holdout no actualiza pesos ni normalizador, y se purgan del train los ejemplos cuyo target 4h toca o cruza el inicio del holdout. El JSON de reporte contiene ventana, dataset/hash, split, purga, distribución de clases, matriz de confusión, accuracy, macro-F1, log-loss y baselines mayoritario/uniforme. El artefacto sólo queda `PROMOTED` si supera accuracy del baseline mayoritario y log-loss del baseline uniforme; el runtime rechaza modelos no promovidos salvo opt-in explícito restringido a dry-run.

## Features multi-fuente

El schema fijo `evidence-multisource/1.0.0` proyecta `EvidenceSnapshot` y contexto local de cartera/riesgo:

- retornos de horizontes 5m, 30m, 4h, 1d, 7d y 30d;
- confianza y retorno structural/tactical;
- edge neto, flow imbalance, spread/missing flag, cobertura y edad;
- posición LONG, PnL no realizado, drawdown, PnL diario, distancia al stop y riesgo por trade.

Esto es evidencia tabular **multi-fuente**, no aprendizaje visual ni “multimodal visual”.

### Limitación histórica importante

El dataset congelado 1h sólo contiene OHLCV y conteo de trades. No contiene BBO/spread, aggTrades/order flow, velas 5m/30m ni historia de posición/PnL/stops/breakers. Para entrenamiento, el spread queda marcado ausente, flow usa un proxy de vela firmada, 5m/30m usan el retorno de la vela 1h cerrada y los campos de cartera usan valores neutrales. Por ello hay diferencia de modalidad entre entrenamiento y runtime; las métricas del holdout no demuestran rentabilidad live ni paridad microestructural.

## Runtime y aprendizaje online

```bash
.venv/bin/python -m scripts.run_realtime_demo \
  --dry-run \
  --model-path data/models/local-softmax-v1.json \
  --no-online-learning \
  --allow-unpromoted-model
```

Para activar aprendizaje delayed-label local y persistente en investigación dry-run (elimina `--allow-unpromoted-model` cuando un entrenamiento futuro obtenga `PROMOTED`):

```bash
.venv/bin/python -m scripts.run_realtime_demo \
  --dry-run \
  --model-path data/models/local-softmax-v1.json \
  --online-learning \
  --allow-unpromoted-model
```

El entrenamiento generado en este workspace quedó `REJECTED`: accuracy `0.399001` frente a baseline mayoritario `0.402568`, aunque macro-F1 fue `0.339868` y log-loss `1.096240` mejoró ligeramente el uniforme `1.098612`. Por eso sólo se permite investigarlo con `--allow-unpromoted-model` en dry-run; no puede autorizar órdenes DEMO.

Como máximo se encola una experiencia por hora. Alrededor del target exacto de cuatro horas se admite una tolerancia máxima de cinco minutos; si no aparece un precio causal en esa ventana, el target se registra como expirado y no se entrena con un horizonte distinto. La resolución corre incluso cuando breakers, stops o calidad vetan la predicción direccional. Cada actualización escribe primero una experiencia write-ahead idempotente con `update_id`, feature schema y vector exacto; después actualiza SGD y guarda atómicamente modelo/normalizador/cola. Un reinicio reaplica una fila aún pendiente sin duplicar el log.

El activity journal y dashboard exponen por separado `strategy_version`, `directional_model_version`, dirección, confianza/probabilidades y si el aprendizaje online estaba activo.
