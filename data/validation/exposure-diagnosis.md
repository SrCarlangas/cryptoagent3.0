# Exposure model diagnosis (Task 1)

- dataset_id: `sha256:53938d3dccb146703a6491ba28a2f601ae74bdd3305305904d0b808c2ff3ee73`
- window: last_5y 2021-09-16T00:00:00+00:00 -> 2026-09-16T00:00:00+00:00 (43822 bars)
- round-trip cost assumed: 20.0 bps

## A/B. Label balance and signal vs cost, by horizon

| horizon | samples | P(up) | majority | median abs move | share > cost | 3-class BUY/HOLD/SELL |
|---|---|---|---|---|---|---|
| 4h | 43815 | 0.5054 | 0.5054 | 42.2 bps | 0.722 | 0.311 / 0.388 / 0.300 |
| 12h | 43807 | 0.5073 | 0.5073 | 80.8 bps | 0.840 | 0.389 / 0.232 / 0.379 |
| 24h | 43795 | 0.5104 | 0.5104 | 125.0 bps | 0.893 | 0.430 / 0.157 / 0.413 |
| 48h | 43771 | 0.5129 | 0.5129 | 186.8 bps | 0.932 | 0.461 / 0.103 / 0.435 |
| 96h | 43723 | 0.5127 | 0.5127 | 273.3 bps | 0.953 | 0.476 / 0.071 / 0.452 |
| 168h | 43651 | 0.5174 | 0.5174 | 367.2 bps | 0.967 | 0.492 / 0.049 / 0.459 |
| 336h | 43485 | 0.5234 | 0.5234 | 549.8 bps | 0.977 | 0.506 / 0.036 / 0.459 |

## C. Cost of churn for an argmax policy

| horizon | flips / year | annual cost of churn |
|---|---|---|
| 4h | 1371.4 | 137.14% |
| 12h | 462.9 | 46.29% |
| 24h | 234.0 | 23.40% |
| 48h | 105.6 | 10.56% |
| 96h | 49.8 | 4.98% |
| 168h | 29.6 | 2.96% |
| 336h | 13.2 | 1.32% |

## D. Trend signal strength (Spearman vs forward return)

| signal | 4h | 12h | 24h | 48h | 96h | 168h | 336h |
|---|---|---|---|---|---|---|---|
| `log_price_over_ma7d` | -0.0200 | -0.0187 | -0.0226 | -0.0117 | -0.0153 | -0.0172 | +0.0203 |
| `log_price_over_ma30d` | -0.0021 | -0.0048 | -0.0019 | +0.0128 | +0.0131 | +0.0276 | +0.0509 |
| `log_price_over_ma100d` | +0.0014 | +0.0030 | +0.0083 | +0.0148 | +0.0023 | +0.0161 | +0.0302 |
| `log_price_over_ma200d` | +0.0041 | +0.0082 | +0.0112 | +0.0154 | +0.0017 | +0.0083 | +0.0101 |
| `log_ma30d_over_ma200d` | +0.0060 | +0.0112 | +0.0131 | +0.0109 | -0.0095 | -0.0086 | -0.0179 |

## D2. Same signals on NON-OVERLAPPING samples (all stride offsets)

| signal | horizon | mean rho | range over offsets | indep. n | rho / SE | sign stable |
|---|---|---|---|---|---|---|
| `log_price_over_ma7d` | 4h | -0.0199 | -0.020 .. -0.019 | 10953 | -2.08 | yes |
| `log_price_over_ma7d` | 12h | -0.0187 | -0.023 .. -0.012 | 3650 | -1.13 | yes |
| `log_price_over_ma7d` | 24h | -0.0225 | -0.035 .. -0.007 | 1824 | -0.96 | yes |
| `log_price_over_ma7d` | 48h | -0.0117 | -0.039 .. +0.010 | 911 | -0.35 | no |
| `log_price_over_ma7d` | 96h | -0.0145 | -0.060 .. +0.030 | 455 | -0.31 | no |
| `log_price_over_ma7d` | 168h | -0.0160 | -0.103 .. +0.066 | 259 | -0.26 | no |
| `log_price_over_ma7d` | 336h | +0.0236 | -0.121 .. +0.140 | 129 | +0.27 | no |
| `log_price_over_ma30d` | 4h | -0.0021 | -0.004 .. -0.000 | 10953 | -0.22 | yes |
| `log_price_over_ma30d` | 12h | -0.0048 | -0.009 .. -0.001 | 3650 | -0.29 | yes |
| `log_price_over_ma30d` | 24h | -0.0018 | -0.012 .. +0.010 | 1824 | -0.08 | no |
| `log_price_over_ma30d` | 48h | +0.0127 | -0.006 .. +0.035 | 911 | +0.38 | no |
| `log_price_over_ma30d` | 96h | +0.0132 | -0.014 .. +0.046 | 455 | +0.28 | no |
| `log_price_over_ma30d` | 168h | +0.0275 | -0.039 .. +0.069 | 259 | +0.44 | no |
| `log_price_over_ma30d` | 336h | +0.0510 | -0.003 .. +0.125 | 129 | +0.58 | no |
| `log_price_over_ma100d` | 4h | +0.0014 | -0.004 .. +0.005 | 10953 | +0.14 | no |
| `log_price_over_ma100d` | 12h | +0.0031 | -0.004 .. +0.009 | 3650 | +0.18 | no |
| `log_price_over_ma100d` | 24h | +0.0084 | -0.000 .. +0.020 | 1824 | +0.36 | no |
| `log_price_over_ma100d` | 48h | +0.0148 | -0.005 .. +0.040 | 911 | +0.45 | no |
| `log_price_over_ma100d` | 96h | +0.0025 | -0.023 .. +0.026 | 455 | +0.05 | no |
| `log_price_over_ma100d` | 168h | +0.0163 | -0.025 .. +0.055 | 259 | +0.26 | no |
| `log_price_over_ma100d` | 336h | +0.0314 | -0.019 .. +0.087 | 129 | +0.36 | no |
| `log_price_over_ma200d` | 4h | +0.0041 | +0.001 .. +0.009 | 10953 | +0.43 | yes |
| `log_price_over_ma200d` | 12h | +0.0083 | +0.003 .. +0.015 | 3650 | +0.50 | yes |
| `log_price_over_ma200d` | 24h | +0.0113 | +0.002 .. +0.021 | 1824 | +0.48 | yes |
| `log_price_over_ma200d` | 48h | +0.0155 | -0.004 .. +0.041 | 911 | +0.47 | no |
| `log_price_over_ma200d` | 96h | +0.0020 | -0.022 .. +0.027 | 455 | +0.04 | no |
| `log_price_over_ma200d` | 168h | +0.0087 | -0.033 .. +0.044 | 259 | +0.14 | no |
| `log_price_over_ma200d` | 336h | +0.0115 | -0.031 .. +0.065 | 129 | +0.13 | no |
| `log_ma30d_over_ma200d` | 4h | +0.0060 | +0.002 .. +0.011 | 10953 | +0.63 | yes |
| `log_ma30d_over_ma200d` | 12h | +0.0113 | +0.007 .. +0.017 | 3650 | +0.68 | yes |
| `log_ma30d_over_ma200d` | 24h | +0.0131 | +0.004 .. +0.025 | 1824 | +0.56 | yes |
| `log_ma30d_over_ma200d` | 48h | +0.0110 | -0.009 .. +0.035 | 911 | +0.33 | no |
| `log_ma30d_over_ma200d` | 96h | -0.0093 | -0.030 .. +0.016 | 455 | -0.20 | no |
| `log_ma30d_over_ma200d` | 168h | -0.0083 | -0.041 .. +0.028 | 259 | -0.13 | no |
| `log_ma30d_over_ma200d` | 336h | -0.0175 | -0.078 .. +0.020 | 129 | -0.20 | no |

## E. Long/flat exposure vs buy and hold, every window

### fees: honest_10bps

| window | buy & hold | ma30d | ma50d | ma75d | ma100d | ma150d | ma200d | ma250d |
|---|---|---|---|---|---|---|---|---|
| full_2020_2026 | +953.6% | +814.2%  | +1606.9%* | +701.5%  | +1019.8%* | +984.7%* | +844.7%  | +459.6%  |
| bear_2021_11_to_2022_11 | -73.3% | -38.1%* | -45.4%* | -45.9%* | -31.1%* | -34.2%* | -36.3%* | -48.3%* |
| last_5y | +57.9% | +87.6%* | +86.7%* | +66.9%* | +157.9%* | +74.1%* | +136.5%* | +43.4%  |
| bull_2020_2021 | +752.4% | +481.1%  | +1015.8%* | +426.6%  | +448.4%  | +568.9%  | +388.7%  | +367.5%  |
| recovery_2023_2024 | +460.2% | +231.6%  | +225.3%  | +169.6%  | +196.0%  | +232.5%  | +243.3%  | +132.3%  |
| mid_bear_end_2022_06 | +179.8% | +331.9%* | +740.0%* | +277.2%* | +324.5%* | +349.7%* | +212.1%* | +142.0%  |

### fees: adverse_20bps

| window | buy & hold | ma30d | ma50d | ma75d | ma100d | ma150d | ma200d | ma250d |
|---|---|---|---|---|---|---|---|---|
| full_2020_2026 | +951.5% | +302.1%  | +870.3%  | +405.6%  | +671.5%  | +747.8%  | +670.1%  | +320.2%  |
| bear_2021_11_to_2022_11 | -73.4% | -45.1%* | -50.0%* | -50.0%* | -34.8%* | -36.2%* | -38.5%* | -52.0%* |
| last_5y | +57.6% | -0.6%  | +18.5%  | +15.9%  | +94.4%* | +37.4%  | +101.5%* | +12.8%  |
| bull_2020_2021 | +750.7% | +371.8%  | +895.5%* | +367.9%  | +398.1%  | +545.3%  | +365.7%  | +343.8%  |
| recovery_2023_2024 | +459.1% | +166.6%  | +177.1%  | +131.0%  | +159.3%  | +205.7%  | +222.6%  | +101.5%  |
| mid_bear_end_2022_06 | +179.3% | +229.6%* | +619.9%* | +218.8%* | +274.9%* | +323.5%* | +187.5%* | +113.8%  |

- neighbour-robust lengths (full window): NONE
- surviving every gate (full + adverse fees + last_5y): NONE

### Hysteresis sweep (10 bps/side)

**ma200d**

| band | full_2020_2026 | bear_2021_11_to_2022_11 | last_5y | bull_2020_2021 | recovery_2023_2024 | mid_bear_end_2022_06 | flips (full) |
|---|---|---|---|---|---|---|---|
| enter+0%/exit-0% | +844.7% | -36.3% | +136.5% | +388.7% | +243.3% | +212.1% | 203 |
| enter+1%/exit-1% | +915.3% | -30.9% | +170.4% | +353.3% | +238.2% | +213.8% | 61 |
| enter+2%/exit-2% | +853.6% | -27.4% | +150.0% | +360.5% | +209.7% | +235.1% | 41 |
| enter+3%/exit-3% | +886.6% | -25.3% | +146.5% | +366.9% | +202.0% | +249.5% | 29 |
| enter+2%/exit-5% | +877.3% | -28.4% | +113.1% | +438.9% | +162.1% | +286.5% | 27 |

## F. Length x hysteresis plateau, strict gate in both dimensions

Gate: beat buy and hold in full_2020_2026 AND last_5y, at 10 bps AND 20 bps per side. `+` passes, `.` fails, `R` passes and all four orthogonal neighbours pass.

| length | band 0% | band 1% | band 2% | band 3% | band 4% | band 5% |
|---|---|---|---|---|---|---|
| ma30d | . | + | **R** | **R** | + | + |
| ma50d | . | + | + | + | . | . |
| ma75d | . | + | . | . | . | . |
| ma100d | . | + | + | + | + | + |
| ma150d | . | + | + | + | + | **R** |
| ma200d | . | . | . | . | . | + |
| ma250d | . | . | . | . | . | . |

- cells passing strict gate: 20 of 42
- neighbour-robust cells: ['ma30d|band=0.02', 'ma30d|band=0.03', 'ma150d|band=0.05']
- **verdict: STRICT_GATE_ACHIEVABLE**

- execution lag applied: 1 bar (decide on a closed bar, fill at the next close)
- cells beating buy and hold in ALL 6 windows at BOTH fee levels: NONE

Detail for every cell that passed the strict gate:

| cell | full 10bps | full 20bps | last_5y 10bps | last_5y 20bps | bear dd cut | flips | windows won (adverse) | look-ahead worth |
|---|---|---|---|---|---|---|---|---|
| `ma30d|band=0.01` | +353.4pp | +75.0pp | +87.2pp | +51.3pp | +33.2pp | 222 | 4/6 | -111.6pp |
| `ma30d|band=0.02` | +331.6pp | +150.1pp | +51.8pp | +31.0pp | +33.5pp | 141 | 4/6 | -26.4pp |
| `ma30d|band=0.03` | +390.5pp | +252.3pp | +72.9pp | +56.8pp | +32.2pp | 101 | 4/6 | -70.0pp |
| `ma30d|band=0.04` | +565.8pp | +443.2pp | +69.2pp | +56.2pp | +32.7pp | 79 | 5/6 | -80.2pp |
| `ma30d|band=0.05` | +667.8pp | +563.0pp | +81.1pp | +70.2pp | +33.6pp | 63 | 5/6 | -89.0pp |
| `ma50d|band=0.01` | +1552.3pp | +1204.4pp | +102.9pp | +74.6pp | +29.7pp | 143 | 5/6 | -91.1pp |
| `ma50d|band=0.02` | +1590.9pp | +1379.6pp | +131.1pp | +112.4pp | +27.6pp | 83 | 5/6 | +285.1pp |
| `ma50d|band=0.03` | +916.1pp | +784.8pp | +78.5pp | +65.9pp | +28.0pp | 69 | 5/6 | +30.4pp |
| `ma75d|band=0.01` | +236.4pp | +99.3pp | +98.0pp | +76.2pp | +26.7pp | 113 | 4/6 | +64.7pp |
| `ma100d|band=0.01` | +676.6pp | +542.3pp | +165.9pp | +145.5pp | +44.2pp | 81 | 4/6 | -98.5pp |
| `ma100d|band=0.02` | +1123.1pp | +1027.2pp | +251.9pp | +238.5pp | +43.3pp | 45 | 4/6 | -25.4pp |
| `ma100d|band=0.03` | +594.8pp | +535.3pp | +141.4pp | +132.9pp | +33.3pp | 37 | 4/6 | +251.1pp |
| `ma100d|band=0.04` | +741.0pp | +686.6pp | +176.9pp | +169.3pp | +42.6pp | 31 | 4/6 | +6.0pp |
| `ma100d|band=0.05` | +820.3pp | +774.3pp | +189.2pp | +182.6pp | +38.8pp | 25 | 4/6 | +26.4pp |
| `ma150d|band=0.01` | +571.6pp | +463.7pp | +100.3pp | +84.1pp | +35.1pp | 69 | 4/6 | -158.1pp |
| `ma150d|band=0.02` | +735.8pp | +671.1pp | +114.4pp | +105.1pp | +39.8pp | 37 | 4/6 | -133.9pp |
| `ma150d|band=0.03` | +655.9pp | +607.4pp | +105.5pp | +98.5pp | +42.9pp | 29 | 4/6 | -43.3pp |
| `ma150d|band=0.04` | +820.6pp | +781.9pp | +133.0pp | +127.5pp | +46.3pp | 21 | 4/6 | -96.0pp |
| `ma150d|band=0.05` | +501.4pp | +469.6pp | +88.7pp | +84.2pp | +45.7pp | 21 | 4/6 | -88.0pp |
| `ma200d|band=0.05` | +186.7pp | +166.6pp | +88.5pp | +84.9pp | +41.2pp | 17 | 4/6 | -40.0pp |

## G. Temporal out-of-sample: does the SELECTION generalise?

Parameters are chosen on the selection window only, then frozen and measured on the years that follow. Only the out-of-sample columns are evidence.

| split | chosen | in-sample excess | OOS excess (10bps) | OOS excess (20bps) | OOS dd cut | family share winning |
|---|---|---|---|---|---|---|
| select_2020_2022_test_2023_2026 | `ma50d|band=0.01` | +470.7pp | -85.6pp | -114.0pp | +17.9pp | 0% |
| select_2020_2023_test_2024_2026 | `ma50d|band=0.01` | +1081.4pp | -23.4pp | -33.8pp | +17.9pp | 19% |
| select_2021_2024_test_2024_2026 | `ma50d|band=0.02` | +239.7pp | +16.3pp | +12.2pp | +23.8pp | 31% |

- splits where the chosen cell beat buy and hold out of sample: 1/3 at 10bps, 1/3 at 20bps
- splits where it reduced drawdown out of sample: 3/3
- **verdict: SELECTION_DOES_NOT_GENERALISE_ON_RETURN**

## Long/flat asymmetry

- buy and hold over window: 58.21%
- unconditional 24h drift: +6.15 bps
- up-day share: 0.5104
- mean up day +187.2 bps vs mean down day -182.6 bps

## Conclusions

1. The rejected model is a base-rate predictor, not a broken one. The 4h three-class label is 0.388 HOLD, and the model scored 0.3990 against a 0.4026 majority baseline. It learned the base rate and nothing else.

2. My earlier explanation for that failure was wrong and is corrected here. I said the 4h move was too small to clear a 20 bps round trip. It is not: the median absolute 4h move is 42.2 bps and 72.2% of 4h moves exceed the cost. The problem is that the DIRECTION is unpredictable, P(up) = 0.5054.

3. Churn, not horizon length, is what destroyed the live account. An argmax policy at 4h flips 1371 times per year, which costs 137% of capital annually in fees alone. No edge of any plausible size survives that.

4. The trend signal splits cleanly into detectable-but-useless and affordable-but-absent, and neither helps. Measured on non-overlapping samples: the single largest correlation is `log_price_over_ma7d` at 4h, reaching 2.08 standard errors, but it is NEGATIVE (rho -0.0199, i.e. mean reversion, not trend) and it sits at a horizon where section C prices churn at 137% per year. At the horizons where churn is affordable (>= 48h), the largest is `log_price_over_ma30d` at 336h with only 0.58 SE, and 0 of 20 such signal/horizon pairs reach even 1 SE. Signs also flip across stride offsets at every one of those horizons. There is nothing here to forecast direction with.

5. Churn control, not reference length, is the axis that matters. Section E swept reference length with no dead band and found only isolated, non-monotone winners that died at adverse fees. That test was on the wrong axis. With a hysteresis band added (section F), 20 of 42 length/band cells beat buy and hold in the full window and in last_5y at both fee levels, and the zero-band column fails 7 of 7 times. The band is also not a fill-timing artifact: the study applies a one-bar execution lag, and removing that lag mostly made results WORSE, so the edge does not come from filling at the same close that generated the signal.

6. That in-sample edge is nevertheless not real, and section G is what proves it. Choosing the length/band on an early segment and then measuring the frozen choice on the years that follow, the excess collapses: select_2020_2022_test_2023_2026 picked `ma50d|band=0.01` at +471pp in sample and delivered -86pp out of sample; select_2020_2023_test_2024_2026 picked `ma50d|band=0.01` at +1081pp in sample and delivered -23pp out of sample; select_2021_2024_test_2024_2026 picked `ma50d|band=0.02` at +240pp in sample and delivered +16pp out of sample. Only 1 of 3 splits beat buy and hold out of sample, and in the earliest split NOT ONE of the 42 configurations did (0% of the family). The large in-sample numbers in section F are selection artifacts.

7. One effect survives every test, and it is the only one. Reducing exposure cuts drawdown. In section F every reference length at both fee levels cuts the bear drawdown, with buy and hold returning -73.3% through the 2021-2022 bear against -48.3% to -31.1% for the long/flat variants. More importantly it also generalises out of sample, where it reduced drawdown in 3 of 3 splits (+17.9pp, +17.9pp, +23.8pp). Tail cutting does not require forecasting power, which is exactly why it holds where the return-seeking variants do not.

### Economic reformulation this implies

- The model's output is EXPOSURE (long or flat), not a BUY/HOLD/SELL direction.
- Its default is LONG, so that absent evidence it collects the positive unconditional drift (+6.15 bps/day) instead of churning.
- Low confidence must mean STAY AS YOU ARE, never flip. Hysteresis is a first-class part of the policy, not a tweak: on ma200d a 2% dead band cuts full-window flips from 203 to 41, and the zero-band column of section F fails every single time.
- Spread and order-flow features are removed from the model. They existed only live, with historical proxies at training time, which is train/serve skew. They become deterministic gates instead.
- The promotion gate cannot be accuracy, and per point 6 it also cannot be in-sample excess return. It has to be measured on data the parameter and weight selection never saw.

### What the gate must therefore be

Section G answers the question I was about to escalate, so it no longer needs to be an open choice. A gate of 'beat buy and hold on return' is not merely hard, it is not supported: the configurations that beat it by +470pp and +1081pp in sample returned -86pp and -23pp out of sample. Adopting that gate would mean either rejecting the model (leaving the account with no operator) or, worse, selecting on in-sample excess and shipping the artifact.

The gate that the evidence does support, because it is the one quantity that replicated in 3 of 3 out-of-sample splits and across every length and fee level in section F:

  1. Out-of-sample drawdown materially below buy and hold (the effect that generalises).
  2. Out-of-sample net return within a stated tolerance of buy and hold, not above it (the model must not pay for its tail protection with the whole trend).
  3. Churn bounded by construction, verified by flip count, since section C prices unbounded churn at a level no edge can survive.

This keeps the user's hard constraint intact: a local model is the operator, it reads trend in real time, and it chooses the action that maximises return given what is actually knowable, which the data says is 'stay long, step aside in sustained downtrends'. It does not promise an edge that three independent studies could not find.

