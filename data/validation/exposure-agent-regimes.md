# Do the agent's regimes mean anything?

- dataset_id: `sha256:53938d3dccb146703a6491ba28a2f601ae74bdd3305305904d0b808c2ff3ee73`
- policy: `LOCAL-EXPOSURE-AGENT-V1`, 4 regimes, 7292 training steps
- evaluated on 1826 daily states from a flat book

## Conditions under which each regime dominates

| regime | share | log_price_over_ma200 | log_price_over_ma30 | return_30d | return_90d | volatility_30d | volatility_ratio_30_90 | log_price_over_high_200d | own P(long) | mixture P(long) |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 33.6% | -0.0634 | +0.0473 | +0.0522 | -0.0676 | +0.0254 | +0.9397 | -0.3290 | 0.510 | 0.508 |
| 1 | 19.9% | -0.2615 | -0.1049 | -0.1839 | -0.2382 | +0.0335 | +1.1089 | -0.5661 | 0.477 | 0.416 |
| 2 | 22.9% | +0.1945 | -0.0094 | -0.0086 | +0.2015 | +0.0239 | +0.9307 | -0.1018 | 0.510 | 0.525 |
| 3 | 23.5% | +0.1726 | +0.0383 | +0.1206 | +0.2096 | +0.0217 | +0.9236 | -0.0959 | 0.606 | 0.560 |

## Verdict

- active regimes: 4 of 4
- spread in trend context (log price over 200d average) across regimes: 0.4560
- spread in each regime's own preference for being long: 0.129

**Regimes are real.** They activate in measurably different trend contexts AND hold different views on whether to be exposed, so the agent is adjusting strategy by regime rather than averaging one rule.
