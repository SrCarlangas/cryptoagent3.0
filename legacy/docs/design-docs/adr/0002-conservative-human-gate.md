# ADR-0002: cierre conservador del gate humano

- Estado: aceptado por delegación explícita del usuario
- Fecha: 2026-09-15
- Alcance: fixtures versionados y replay local determinista, sin I/O de red;
  no autoriza OOS ejecutado, paper local/remoto, testnet, live, cuentas,
  credenciales ni órdenes

## Decisiones congeladas

### D-001 — producto

`BTC/USDT` Spot, `LONG/FLAT`, una posición, apalancamiento 0. Margin, Futures y SHORT quedan excluidos.

### D-002 — horizonte

- `H_decision = 1h`, evaluación al cierre `FINAL` de cada barra horaria.
- `H_context = 720` barras de 1h (30 días).
- Una decisión estratégica expira en la siguiente frontera horaria.
- La protección puede evaluarse por evento, pero nunca abrir posición.

### D-003 — mandato de riesgo conceptual

Perfil de fixtures, no recomendación financiera:

- capital: `10000 USDT`;
- riesgo máximo por decisión: `0.0025` del capital (0.25%);
- exposición máxima: `1000 USDT` (10% del capital);
- pérdida diaria máxima: `75 USDT` (0.75%);
- drawdown máximo: `500 USDT` (5%);
- Spot sin deuda; sizing redondeado siempre hacia abajo;
- `time_stop_is_protective = false`.

### D-009 — gate OOS pre-registrado

Los hard gates de integridad y seguridad son tolerancia cero. Una policy sólo puede promoverse si, simultáneamente:

- al menos 100 episodios de setup independientes (`n_min=100`);
- utilidad neta pareada sobre `NULL_HOLD` positiva por al menos 100 bps sobre capital en el agregado OOS (`margin_min=0.01`);
- utilidad positiva en al menos 70% de folds;
- PBO `< 0.20`;
- ningún fold viola pérdida diaria/drawdown del mandato;
- signo positivo en todos los vecinos inmediatos de parámetros HIGH y degradación mediana ≤25%;
- costos ADVERSE incluidos; `gross <= cost + uncertainty` falla;
- coverage de episodios entre 1% y 30%, reportada sin eliminar abstenciones.

No se ejecuta OOS en esta entrega porque no existe dataset histórico versionado. El gate queda congelado para un experimento futuro independiente.

### D-014 — budgets de freshness

Para `H_decision=1h`:

| Dato/uso | warning | hard max | lateness/grace | recovery |
|---|---:|---:|---:|---:|
| BBO costo | 1000 ms | 2000 ms | 500 ms skew | 3 eventos |
| L2 costo | 1000 ms | 2000 ms | heartbeat 30000 ms | nueva generación LIVE + 3 diffs |
| aggTrades flujo | 3000 ms | 5000 ms | 5000 ms lateness | 3 eventos |
| cierre kline 1h | 2000 ms | 5000 ms | 5000 ms close grace | FINAL reconciliada |
| ticker 24h opcional | 3000 ms | 5000 ms | 500 ms skew | 3 eventos |
| exchangeInfo | 12 h | 24 h | 500 ms skew | snapshot nuevo válido |

`β_bbo = β_depth = 1/1800`; los caps absolutos de 2 s dominan para 1h. Clock skew máximo: 500 ms. Budget ausente o incumplido ⇒ `BLOCKED`, nunca último valor.

### D-011 — plataforma

Se adopta ADR-0001.

## Razón

El perfil maximiza seguridad, reproducibilidad y falsabilidad; no pretende optimizar retorno. Los valores son conservadores y explícitos para evitar defaults ocultos. Cualquier cambio crea nuevas versiones de mandato, freshness, parámetros y experimento.
