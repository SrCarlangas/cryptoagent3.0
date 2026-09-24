# Multi-slot ladder study (BAR_PROXY 1h approximation)

- Dataset: `sha256:53938d3dccb146703a6491ba28a2f601ae74bdd3305305904d0b808c2ff3ee73`
- Starting capital: 4,635.54 USDT
- Fees: 10 bps per side observed, 20 bps adverse scenario
- Configurations swept: 192
- **Verdict: DO_NOT_DEPLOY_AS_PRIMARY_RETURN_STRATEGY**

## Baselines

| window | buy & hold | max DD |
|---|---:|---:|
| full_2020_2026 | 953.65% | 77.2% |
| bear_2021_11_to_2022_11 | -73.34% | 77.2% |
| last_5y | 57.89% | 77.2% |
| bull_2020_2021 | 752.40% | 60.5% |
| recovery_2023_2024 | 460.24% | 32.3% |
| mid_bear_end_2022_06 | 179.82% | 74.0% |

## Protections applied to the best bear-ranked ladder

| protection | full 2020-2026 | bear 2021-22 | max DD | beats B&H full | beats B&H bear |
|---|---:|---:|---:|:--:|:--:|
| none | 82.91% | -19.41% | 29.6% | no | yes |
| regime_200d | 52.67% | -15.97% | 17.5% | no | yes |
| tranche_stop_15 | 27.07% | -19.40% | 22.4% | no | yes |
| tranche_stop_20 | 34.19% | -21.36% | 24.3% | no | yes |
| disaster_25 | 24.96% | -19.41% | 24.7% | no | yes |
| disaster_35 | 82.91% | -19.41% | 29.6% | no | yes |
| regime_plus_disaster_25 | 52.67% | -15.97% | 17.5% | no | yes |
| regime_plus_disaster_35 | 52.67% | -15.97% | 17.5% | no | yes |
| full_stack_15_25 | 36.51% | -4.22% | 7.0% | no | yes |
| full_stack_20_35 | 31.38% | -4.51% | 8.8% | no | yes |

Buy & hold reference: full 953.65%, bear -73.34%.

## Trend-following challenger (regime entry + regime exit)

| MA | full 2020-2026 | max DD | bear 2021-22 | adverse fees | beats B&H |
|---|---:|---:|---:|---:|:--:|
| 600h (25d) | 409.08% | 46.8% | -37.46% | 82.19% | no |
| 900h (37d) | 1209.08% | 45.6% | -31.21% | 544.21% | yes |
| 1200h (50d) | 1028.73% | 55.4% | -48.45% | 541.62% | yes |
| 1800h (75d) | 899.34% | 55.3% | -49.28% | 531.71% | no |
| 2400h (100d) | 1234.88% | 41.5% | -34.78% | 821.53% | yes |
| 3600h (150d) | 868.92% | 48.7% | -33.63% | 657.35% | no |
| 4800h (200d) | 627.76% | 66.2% | -37.40% | 493.29% | no |
| 6000h (250d) | 282.72% | 74.6% | -45.35% | 187.40% | no |
| 7200h (300d) | 397.17% | 73.5% | -43.47% | 308.56% | no |

Surviving the neighbour (overfit) test: none.
Beating buy & hold at adverse fees: none.
Deployable after both tests: none.

## Rejected by design

All slots full means price fell through every ladder level, which is the point of maximum unrealized loss. Selling there realizes the worst loss and frees capital to re-buy an asset that just demonstrated it keeps falling. Capacity must come from wider spacing or a reserved tranche, not forced capitulation.

## Limitations

- 1h bars cannot reproduce the runtime 5m/30m tactical features.
- No historical BBO spread or aggTrade order flow is available.
- Take-profit requires a confirmed close; stops trigger on the low and fill at the worse of stop and open.
- Documented dataset gaps restart indicator warmup and are never bridged.
- This can reject a design; it cannot prove live profitability.
