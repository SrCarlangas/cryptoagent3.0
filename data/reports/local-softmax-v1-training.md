# Local softmax training report

- Model: `LOCAL-SOFTMAX-BTC-1H-4H-V1`
- Dataset: `sha256:53938d3dccb146703a6491ba28a2f601ae74bdd3305305904d0b808c2ff3ee73`
- Exact source window: `2021-09-16T01:00:00+00:00` to `2026-09-16T01:00:00+00:00` (end exclusive), **5 calendar years**
- Temporal split: 33,640 train / 8,411 holdout, no shuffle; 4 boundary examples purged
- Promotion: **REJECTED** (accuracy > majority baseline and log_loss < uniform baseline)
- Labels: 4h opportunity net of 20 bps round-trip costs; HOLD band 10 bps

## Holdout metrics

- Accuracy: 0.399001
- Macro F1: 0.339868
- Log loss: 1.096240
- Majority baseline accuracy: 0.402568
- Uniform baseline log loss: 1.098612

## Limitations

- The 1h dataset has no historical BBO spread or aggTrade order flow; spread is missing and flow uses a signed-candle proxy.
- The 1h dataset cannot reproduce 5m/30m runtime features; both use the completed 1h candle return proxy.
- Historical portfolio position, PnL, stop distance and breaker state are unavailable and use neutral values.
- This is multi-source tabular evidence, not visual multimodal learning, and holdout metrics do not establish live trading profitability.
