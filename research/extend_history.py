"""Extend the frozen BTCUSDT hourly dataset back to Binance's own inception (2017-08).

Why a NEW directory instead of rewriting the existing one: every result recorded in
`tasks.md`, `REGIME-STUDY-ATTEMPTS.md` and `exposure-diagnosis.md` cites
`dataset_id sha256:53938d3d...`. Mutating that dataset would silently invalidate the
provenance of all of them. The extended series gets its own id and its own directory, so
both remain reproducible.

What this buys, and what it does NOT buy: the new data lands at the FRONT of the series
(2017-08 -> 2019-12), so it is genuinely unseen and can host a clean confirmation test. It
does NOT un-spend the 2025-04 -> 2026-09 holdout, which was measured on 2026-10-01 and is
recorded as spent.

Assumptions this changes, declared before measuring:
- Binance spot BTCUSDT began trading 2017-08-17. There is no earlier data from this
  provider, so 2017-08 is a hard floor, not a choice.
- Early Binance is a thinner venue: lower volume and more frequent outages than 2020+.
  The integrity report below prints gaps per year so that is visible rather than assumed.

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.extend_history --i-want-network
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from btc_decision_agent.adapters.backfill import (
    BackfillConfig,
    HistoricalDataset,
    PublicKlineBackfill,
)

SOURCE = Path("data/history/btcusdt-1h")
TARGET = Path("data/history/btcusdt-1h-2017")
BINANCE_BTCUSDT_INCEPTION = datetime(2017, 8, 17, tzinfo=UTC)


def existing_rows() -> tuple[list[dict[str, Any]], str]:
    manifest, rows = HistoricalDataset(SOURCE).load()
    return list(rows), manifest.dataset_id


def fetch_earlier(until: datetime) -> list[dict[str, Any]]:
    """Pull closed hourly klines from inception up to `until`, exclusive."""
    config = BackfillConfig(
        symbol="BTCUSDT",
        interval="1h",
        start=BINANCE_BTCUSDT_INCEPTION,
        end=until,
    )
    backfill = PublicKlineBackfill(config, enabled=True)
    collected: list[dict[str, Any]] = []
    for row in backfill.iter_closed_klines():
        collected.append(row)
        if len(collected) % 5000 == 0:
            print(f"  ... {len(collected)} barras")
    return collected


def integrity_report(rows: list[dict[str, Any]]) -> None:
    """Print what a reader needs to trust the series, including what is wrong with it."""
    ordered = sorted(rows, key=lambda item: int(item["open_time"]))
    times = [int(item["open_time"]) for item in ordered]
    print(f"  filas: {len(ordered)}  unicas: {len(set(times))}")
    if len(set(times)) != len(times):
        print("  AVISO: hay open_time duplicados")

    hour = 3_600_000
    gaps_per_year: Counter[str] = Counter()
    missing_per_year: Counter[str] = Counter()
    worst: tuple[int, str] | None = None
    for previous, current in pairwise(ordered):
        delta = int(current["open_time"]) - int(previous["open_time"])
        if delta == hour:
            continue
        year = datetime.fromtimestamp(int(previous["open_time"]) / 1000, tz=UTC).strftime("%Y")
        missing = delta // hour - 1
        gaps_per_year[year] += 1
        missing_per_year[year] += missing
        moment = datetime.fromtimestamp(int(previous["open_time"]) / 1000, tz=UTC).isoformat()
        if worst is None or missing > worst[0]:
            worst = (missing, moment)

    print("  huecos por anio (numero de huecos / horas ausentes):")
    for year in sorted(set(gaps_per_year) | set(missing_per_year)):
        print(f"    {year}: {gaps_per_year[year]:>3} huecos / {missing_per_year[year]:>5} horas")
    if worst:
        print(f"  hueco mayor: {worst[0]} horas tras {worst[1]}")

    negative = [item for item in ordered if float(item["low"]) <= 0.0]
    inverted = [item for item in ordered if float(item["high"]) < float(item["low"])]
    print(f"  precios no positivos: {len(negative)}   high < low: {len(inverted)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extend the hourly dataset back to 2017.")
    parser.add_argument(
        "--i-want-network",
        action="store_true",
        help="Required. Makes outbound requests to Binance public market data.",
    )
    args = parser.parse_args()
    if not args.i_want_network:
        print("Requiere --i-want-network: este comando sale a la red publica de Binance.")
        return 2

    current, source_id = existing_rows()
    first_existing = min(int(row["open_time"]) for row in current)
    boundary = datetime.fromtimestamp(first_existing / 1000, tz=UTC)
    print(f"dataset actual: {source_id}")
    print(f"  {len(current)} filas, empieza {boundary.isoformat()}")
    print(f"descargando {BINANCE_BTCUSDT_INCEPTION.date()} -> {boundary.date()} ...")

    earlier = fetch_earlier(boundary)
    print(f"  descargadas {len(earlier)} barras nuevas")
    if not earlier:
        print("No se descargo nada. Abortado sin escribir.")
        return 1

    merged: dict[int, dict[str, Any]] = {int(row["open_time"]): row for row in earlier}
    overlaps = sum(1 for row in current if int(row["open_time"]) in merged)
    for row in current:
        merged[int(row["open_time"])] = row  # the frozen rows win on any overlap
    rows = list(merged.values())
    print(f"  solapes resueltos a favor del dataset congelado: {overlaps}")

    print("integridad de la serie fusionada:")
    integrity_report(rows)

    config = BackfillConfig(symbol="BTCUSDT", interval="1h", start=BINANCE_BTCUSDT_INCEPTION)
    manifest = HistoricalDataset(TARGET).write(config, rows)
    print(f"\nescrito en {TARGET}")
    print(f"  dataset_id {manifest.dataset_id}")
    print(f"  {manifest.row_count} filas  {manifest.first_open_time} -> {manifest.last_close_time}")
    print(f"  huecos documentados: {manifest.gap_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
