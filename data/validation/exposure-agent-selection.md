# Local exposure agent: training and selection

- dataset_id: `sha256:53938d3dccb146703a6491ba28a2f601ae74bdd3305305904d0b808c2ff3ee73`
- daily perception: 2451 days, 2 with fewer than 20 hourly bars
- objective: maximum net profitability. Buy and hold is context, not a gate.

## Walk-forward folds

- `fold_1_test_2023H2`: train from 2021-09-16, test 2023-07-01 to 2024-06-30
- `fold_2_test_2024H2`: train from 2021-09-16, test 2024-07-01 to 2025-06-30
- `fold_3_test_2025H2`: train from 2021-09-16, test 2025-07-01 to 2026-09-15

## Configurations ranked by mean OUT-OF-SAMPLE return

| config | mean OOS | worst OOS | mean OOS dd | folds profitable |
|---|---|---|---|---|
| `cadence=24h|regimes=4|lr=0.02|epochs=4` | +48.83% | -9.83% | 26.61% | 2/3 |
| `cadence=24h|regimes=4|lr=0.08|epochs=4` | +42.19% | -7.43% | 29.48% | 2/3 |
| `cadence=12h|regimes=2|lr=0.02|epochs=4` | +38.67% | -24.03% | 32.41% | 2/3 |
| `cadence=6h|regimes=4|lr=0.08|epochs=4` | +36.22% | -23.90% | 30.42% | 2/3 |
| `cadence=12h|regimes=2|lr=0.08|epochs=4` | +35.95% | -20.51% | 30.83% | 2/3 |
| `cadence=24h|regimes=2|lr=0.02|epochs=4` | +35.17% | -7.13% | 28.80% | 2/3 |
| `cadence=6h|regimes=4|lr=0.02|epochs=4` | +34.47% | -28.51% | 33.79% | 2/3 |
| `cadence=48h|regimes=4|lr=0.08|epochs=4` | +33.60% | -23.71% | 32.07% | 2/3 |
| `cadence=48h|regimes=2|lr=0.02|epochs=4` | +33.22% | -19.63% | 32.98% | 2/3 |
| `cadence=12h|regimes=4|lr=0.02|epochs=4` | +33.16% | -15.59% | 31.42% | 2/3 |
| `cadence=24h|regimes=2|lr=0.08|epochs=4` | +29.24% | -22.37% | 32.11% | 2/3 |
| `cadence=6h|regimes=2|lr=0.02|epochs=4` | +29.23% | -40.12% | 36.55% | 2/3 |
| `cadence=12h|regimes=4|lr=0.08|epochs=4` | +28.09% | -37.28% | 35.01% | 2/3 |
| `cadence=6h|regimes=2|lr=0.08|epochs=4` | +27.44% | -18.74% | 32.59% | 2/3 |
| `cadence=48h|regimes=4|lr=0.02|epochs=4` | +24.00% | -22.09% | 30.96% | 2/3 |
| `cadence=48h|regimes=2|lr=0.08|epochs=4` | +21.20% | -39.37% | 36.05% | 2/3 |

## Chosen: `cadence=24h|regimes=4|lr=0.02|epochs=4`

| fold | agent OOS | buy & hold (context) | agent dd | b&h dd | buys | sells | exposure |
|---|---|---|---|---|---|---|---|
| fold_1_test_2023H2 | +107.18% | +105.60% | 21.43% | 22.69% | 7 | 6 | 98.3% |
| fold_2_test_2024H2 | +49.14% | +69.92% | 23.97% | 30.94% | 12 | 11 | 70.7% |
| fold_3_test_2025H2 | -9.83% | -29.69% | 34.42% | 53.74% | 31 | 30 | 54.3% |

## Robustness

- seed stability: mean +42.42%, worst +33.94%, best +56.02%, spread 22.08pp, 5/5 seeds profitable
- adverse 20bps fees: mean OOS +44.67%, worst -13.14%, 2/3 folds profitable

## Final policy trained on the full five years

- saved to `data/models/local-exposure-agent-v1.json`
- regime usage: 27.1%, 23.5%, 25.1%, 24.3%
- decisions: {'BUY': 444, 'HOLD': 936, 'SELL': 443}

