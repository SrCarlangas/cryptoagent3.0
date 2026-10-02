# Backtest del agente LLM

- modelo: `qwen3:30b-a3b` (razonamiento desactivado)
- dataset: `sha256:53938d3dccb146703a6491ba28a2f601ae74bdd3305305904d0b808c2ff3ee73`
- ventana: 300 dias, decision cada 5 dias
- comision: 10 bps por lado
- tiempo de computo: 0 minutos

| | retorno neto | drawdown max | cambios |
|---|---|---|---|
| **agente LLM** | +207.80% | 13.92% | 46 |
| modelo cuantitativo | +132.06% | 19.47% | 25 |
| buy and hold | +184.44% | 20.00% | 2 |

## Comportamiento del agente

- decisiones tomadas: 60 (fallos del modelo: 0)
- eligio INVERTIDO en el 55% de las decisiones
- actuo en el 65% (el resto no requeria cambio o no cubria costo)
- cambios de exposicion que el costo bloqueo: 0 (de ellos salidas: 0, debe ser 0)
- veces que el regimen impuso su exposicion sobre la del agente: 0 por diseño. La direccion es del agente y no se revierte; el regimen fija el tamano, el stop y el horizonte. Quitar ese override valia +39pp y la mitad de los viajes de ida y vuelta sobre las mismas decisiones grabadas.
- salidas por stop protector: 7
- cambios de DIRECCION: 15 · ajustes de TAMANO: 31 · comision pagada: 5.46% del capital
  El umbral de rotacion se fijo contra el coste de dar vueltas al capital, que es un viaje de ida y vuelta. Un ajuste de tamano es un solo lado, asi que contarlos juntos hace parecer churner a un agente que escala dentro de una tendencia. La comision pagada es la cantidad que de verdad importa y aqui esta medida, no inferida.
- aperturas: 10  cierres: 0  ampliaciones: 11  reducciones: 18

## Estrategia por regimen

| regimen | decisiones | invertido | postura dominante | asignacion media | stop medio |
|---|---|---|---|---|---|
| 0 | 11 | 7 (64%) | AGRESIVA | 67% | 3.7% |
| 2 | 15 | 8 (53%) | AGRESIVA | 75% | 5.7% |
| 3 | 34 | 18 (53%) | AGRESIVA | 82% | 8.6% |

## Advertencia sobre la simulacion

Los stops se evaluan contra MINIMOS HORARIOS reales, no contra cierres diarios, asi que una mecha que habria tocado el stop si cuenta. El marcado empieza en d+2 porque la orden se llena al cierre de d+1: antes se recorrian las barras de d y d+1, anteriores a la propia entrada, y 11 de 12 salidas por stop las disparaban precios que ya habian pasado cuando la posicion se abrio.

Queda un sesgo real que CASTIGA al agente y que no se puede netear: solo decide cada 5 dias por coste de computo, asi que si el stop salta el primer dia se queda en liquidez el resto del intervalo, mientras en produccion volveria a decidir en 30 minutos. Medido con reentrada forzada, ese sesgo vale varios puntos.
- coincidio con el modelo cuantitativo en el 52%


## Advertencia sobre la evidencia

Una sola ventana, una sola pasada, comisiones honestas. El modelo cuantitativo se valido con 3 cortes x 16 configuraciones x 5 semillas mas comisiones adversas porque cada corrida cuesta milisegundos; una decision del LLM cuesta 45-100 s. Esto sirve para detectar un agente roto o patologico. NO alcanza para establecer una ventaja.
