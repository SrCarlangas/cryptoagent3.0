"""Precompute the 5-year situation index the LLM agent consults.

The agent must never estimate a number it could look up. This script turns the
frozen hourly dataset into a compact index of daily situations: for each day, the
19 market features the agent sees plus WHAT ACTUALLY HAPPENED next (forward returns
at 7, 30 and 90 days).

Why an index instead of letting the agent read the dataset: the dataset is 58,769
hourly bars. Loading and scanning it inside a decision loop that already costs 40
seconds of inference would be wasteful, and handing raw bars to an LLM invites it
to do arithmetic badly. The index is ~1,800 rows of already-computed numbers.

The forward returns are the learning content. An analogue without its outcome is
trivia; an analogue with its outcome is evidence.

Writes data/models/history-index.json.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from multislot_sim import load_bars

from btc_decision_agent.application.exposure_features import (
    MARKET_FEATURE_NAMES,
    MIN_DAILY_HISTORY,
    market_features,
)
from btc_decision_agent.application.exposure_training import build_daily_perception

OUTPUT = Path("data/models/history-index.json")
HORIZONS_DAYS: tuple[int, ...] = (7, 30, 90)


def main() -> None:
    bars, dataset_id = load_bars()
    perception = build_daily_perception(bars)
    closes = perception.closes
    total_days = len(closes)

    rows: list[dict[str, Any]] = []
    # One row per day that has both enough history behind it and a measurable
    # future ahead of it. Days without an outcome are useless as evidence.
    for day in range(MIN_DAILY_HISTORY, total_days - max(HORIZONS_DAYS)):
        price = closes[day]
        features = market_features(closes[:day], price)
        forward: dict[str, float] = {}
        for horizon in HORIZONS_DAYS:
            future = closes[day + horizon]
            forward[f"ret_{horizon}d_pct"] = (future / price - 1.0) * 100.0
        rows.append(
            {
                "day_index": day,
                "price": round(price, 2),
                "features": [round(value, 6) for value in features],
                "forward": {key: round(value, 2) for key, value in forward.items()},
            }
        )

    # Per-feature scale, so nearest-neighbour distance is not dominated by
    # whichever feature happens to have the largest raw units.
    scales: list[float] = []
    for index in range(len(MARKET_FEATURE_NAMES)):
        column = [row["features"][index] for row in rows]
        mean = sum(column) / len(column)
        variance = sum((value - mean) ** 2 for value in column) / max(len(column) - 1, 1)
        scales.append(max(variance**0.5, 1e-9))

    payload = {
        "schema_version": "history-index/1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_id": dataset_id,
        "feature_names": list(MARKET_FEATURE_NAMES),
        "feature_scales": [round(value, 8) for value in scales],
        "horizons_days": list(HORIZONS_DAYS),
        "days": len(rows),
        "rows": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")

    forward_30 = [row["forward"]["ret_30d_pct"] for row in rows]
    positive = sum(1 for value in forward_30 if value > 0)
    print(f"dataset_id: {dataset_id}")
    print(f"dias indexados: {len(rows)} (de {total_days} dias totales)")
    print(f"tamano: {OUTPUT.stat().st_size / 1024:.0f} KB -> {OUTPUT}")
    print(f"base rate 30d positivo: {positive / len(forward_30):.4f}")
    print(
        f"retorno 30d medio: {sum(forward_30) / len(forward_30):+.2f}% "
        f"(min {min(forward_30):+.1f}% max {max(forward_30):+.1f}%)"
    )


if __name__ == "__main__":
    main()
