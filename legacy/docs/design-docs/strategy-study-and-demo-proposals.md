# Estudio de estrategia y propuestas para cuenta demo

**Fecha:** 2026-09-16  
**Alcance:** backtest offline sobre el dataset histórico congelado (BTC/USDT 1h, 2020→2026). Sin dinero real, sin órdenes, sin cuenta conectada. Reglas: parámetros elegidos solo en train; el test se lee una vez; todo trade paga costo round-trip conservador (74.24 bps con buffer).

## Qué se probó

- **Horizontes:** 1h, 4h y 1d (reamuestreo causal desde 1h).
- **Mecanismos:** tendencia (cruce de medias), ruptura (breakout con volatilidad), reversión (pullback profundo + rebote).
- **Gestión:** con y sin stop-loss, time stop.
- **Táctica del usuario "congelar y esperar":** no vender en pérdida y esperar recuperación.
- **Baseline:** buy & hold y no-operar.

## Resultados (split de prueba, no visto en calibración)

| Estrategia | Horizonte | Trades test | Retorno neto test | Buy&hold test | Veredicto |
|---|---|---:|---:|---:|---|
| Tendencia 24/168 | 1h | 112 | −35.5% | +67.9% | pierde |
| Tendencia 12/42 | 4h | 84 | −5.7% | +64.2% | pierde vs b&h |
| Tendencia 10/50 | 1d | 14 | −4.6% | +79.3% | pierde vs b&h |
| Tendencia 20/100 | 1d | 9 | −21.4% | +79.3% | pierde |
| Breakout 30 | 4h | 62 | −37.6% | +64.2% | pierde |
| Breakout 20 | 1d | 17 | −17.0% | +79.3% | pierde |
| Reversión 42 | 4h | 8 | −3.1% | +64.2% | pierde, muestra escasa |
| Reversión 20 | 1d | 3 | +11.95% | +79.3% | positiva pero 3 trades = no fiable |

Patrón dominante: **casi todo gana en entrenamiento y se degrada o pierde en prueba** (sobreajuste), y **ninguna estrategia supera a buy & hold** en el periodo de prueba, con drawdowns de 30–75%.

## La táctica "congelar y esperar" (medida)

| Variante | Trades cerrados | Win rate | Peor cerrado | Posición atrapada |
|---|---:|---:|---:|---|
| Freeze + take-profit 10% | 6 | 100% | +9.3% | **−36.2% sin realizar, sin cerrar** |
| Stop 15% + TP 10% | 23 | 65% | −22.1% | −3.6% |
| Stop 8% + TP 10% | 29 | 52% | −22.1% | −3.6% |

Lección: el "100% de aciertos" de congelar y esperar es una ilusión contable. No pierdes "porque no cierras", pero la pérdida existe: una posición quedó −36% atascada. Esa es exactamente la cola de riesgo que arruina cuentas. Usar stop reduce el atasco pero también recorta el resultado; ninguna variante batió a buy & hold.

## Conclusión honesta

Con datos reales, costos realistas y sin mirar el futuro, **no encontré una estrategia de trading activo con edge robusto que supere a comprar y mantener BTC**. Esto es coherente con el `NO_GO` previo de POL-101 y con la literatura: el trading intradía neto de costos rara vez supera al buy & hold en un activo tan volátil.

Esto **no** es un fracaso del proyecto: el sistema hizo su trabajo, que es impedir que llevemos a real algo que no funciona.

## Propuestas para cuenta demo (paper, sin capital real)

Ordenadas por lo que realmente aprenderías, no por promesa de ganancia. Ninguna es un pase a real; real requiere pasar el gate y tu autorización posterior.

### Propuesta 1 — Baseline buy & hold con reglas de riesgo (recomendada como referencia)
Comprar y mantener, con un circuit breaker de drawdown. Sirve como **vara de medir honesta**: cualquier estrategia activa que en demo no supere esto, no merece capital real. Es la que la evidencia respalda hoy.

### Propuesta 2 — Tendencia diaria 10/50 con stop y time stop (la "menos mala" activa)
Es la variante activa más estable en horizonte diario. En prueba quedó ligeramente negativa, así que se lleva a demo **para observar comportamiento en vivo y disciplina de salida**, no porque prometa ganar. Objetivo: ver si con ejecución real (slippage, latencia) se acerca o se aleja del backtest.

### Propuesta 3 — Reversión diaria, marcada como experimento de baja confianza
Fue la única con retorno positivo en prueba (+11.95%), pero con **solo 3 operaciones**: estadísticamente no concluyente. Se lleva a demo únicamente para **acumular más muestra en vivo** antes de creer nada. No se le asigna expectativa de edge.

## Cómo avanzar a demo de forma segura

Para operar en la testnet/demo de Binance hace falta implementar (hoy no existe, por diseño):
1. Un puerto de ejecución contra la **testnet** de Binance (`testnet.binance.vision`), aislado del dominio.
2. Manejo seguro de credenciales de testnet (variables de entorno, nunca en el repo).
3. Reconciliación de fills reales de la demo con el estado del agente.
4. Registro de cada decisión y fill en el ledger para comparar decisión vs ejecución.

Esto es una fase nueva con su propia autorización. Antes de escribir una línea de ejecución, mi recomendación es cerrar la calibración honesta y aceptar que, si nada supera a buy & hold en demo, lo correcto es no pasar a real.

## Reglas que no se rompen

- No se recalibra mirando el conjunto de prueba.
- No se presenta un backtest ganador como evidencia de edge futuro.
- "Congelar y esperar" no se implementa sin un límite de pérdida: su riesgo de cola es inaceptable sin control.
- Demo primero; real solo tras pasar el gate y con autorización explícita y montos mínimos.
