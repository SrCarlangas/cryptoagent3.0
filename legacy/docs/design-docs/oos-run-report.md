# Reporte OOS ejecutado — dataset histórico congelado

**Fecha:** 2026-09-16  
**Alcance:** backtest/replay offline sobre dataset histórico público congelado. Sin red durante la evaluación, sin órdenes, cuenta, paper ni live.

## Dataset

- Símbolo/intervalo: BTC/USDT, 1h.
- Rango: `2020-01-01T00:00:00Z` → `2026-09-16T00:59:59Z`.
- Barras: 58,769; gaps documentados: 15 (32 barras faltantes por paradas de mercado).
- `dataset_id`: `sha256:53938d3dccb146703a6491ba28a2f601ae74bdd3305305904d0b808c2ff3ee73`.
- Fuente: `GET https://data-api.binance.vision/api/v3/klines` (market data público, solo lectura).

## Protocolo

- Parámetros de POL-101 (`p101/1`) **congelados antes** de abrir el dataset; son los valores `EXAMPLE_ONLY` de la spec, no calibrados.
- Barras FINAL reconstruidas por tramos contiguos; no se cruza ningún gap.
- Evaluación causal al cierre de cada barra 1h; features estrictamente pasadas.
- Costo round-trip ADVERSE aplicado a cada episodio: `54.242622 + 10 = 64.242622 bps`.
- Comparación pareada contra `NULL_HOLD` (utilidad neta cero por barra sin exposición).
- Gate `D-009/1.0.0` aplicado sin modificar umbrales.

## Resultado POL-101

| Métrica | Valor |
|---|---|
| Barras evaluadas | 58,705 |
| Episodios (setups completados) | 6 |
| Coverage | 0.000102 |
| Edge bruto medio/episodio | 24.84 bps |
| Costo round-trip + buffer | 64.24 bps |
| Utilidad neta agregada (ΔU vs NULL) | -0.023643 |
| Folds positivos | 0.60 |
| PBO | 0.4667 |
| Max drawdown | 0.0824 |
| Turnover | 6 |
| Win rate | 0.50 |

## Gate D-009

`FAIL`. Motivos:

- `INSUFFICIENT_EFFECTIVE_SAMPLE` (6 < 100);
- `DELTA_UTILITY_BELOW_MARGIN` (neta negativa < 0.01);
- `FOLD_STABILITY_FAIL` (0.60 < 0.70);
- `PBO_FAIL` (0.4667 ≥ 0.20);
- `PARAMETER_NEIGHBOR_INSTABILITY`;
- `COVERAGE_OUTSIDE_GATE` (0.000102 < 0.01);
- `GROSS_DOES_NOT_CLEAR_COST` (24.84 ≤ 64.24 bps).

## Diagnóstico

El edge bruto medio no supera el costo round-trip, y los parámetros congelados quedan fuera de la distribución real de BTC 1h: la ATR-fraction mediana es ~0.0054 frente a `atr_min=0.010`, y la pendiente mediana ~0.00003 frente a `theta_slope_enter=0.010`. La intersección tendencia+pullback+resume+volumen es casi vacía, por lo que la muestra es diminuta y no cosechable neto de costos.

No se recalibraron parámetros contra el conjunto de prueba: hacerlo violaría el pre-registro y produciría overfitting. Un ajuste legítimo requiere una nueva `parameter_version` con grid/budget train-only y un experimento independiente.

## Veredicto

**`NO_GO` para POL-101 bajo `p101/1`.**

- POL-101 (p101/1): `POLICY_FAIL` / `NO_GO` — no supera costo ni gate.
- POL-102 / POL-103: no evaluadas en esta corrida; permanecen `CANDIDATE_UNVALIDATED`.
- No hay claim de edge ni rentabilidad. El resultado confirma el valor del control `NULL_HOLD`: abstenerse domina a esta configuración neto de costos.

## Trabajo futuro legítimo

1. Nueva `parameter_version` con espacios/budget train-only pre-registrados (sin mirar OOS).
2. Calibrar `atr_min/max`, `theta_slope_*` y bandas de pullback a la escala real de 1h en el tramo de entrenamiento.
3. Reejecutar el gate en un experimento independiente; evaluar POL-102/POL-103 con el mismo protocolo.
4. Solo si una política supera el gate: considerar shadow/paper con autorización separada. Nada de esto habilita live.
