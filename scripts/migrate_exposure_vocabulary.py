"""Rewrite the retired LARGO/PLANO exposure names in an agent memory database.

Why this has to exist rather than being left to sort itself out: the agent's own
track record is read back with an equality test against the current vocabulary.
`calibration()` decides whether a decision was right by comparing the stored
exposure to EXPOSURE_INVESTED, and `measured_patterns()` groups by the stored
string. Rows left saying LARGO would be silently treated as if the agent had chosen
cash, inverting the sign of their outcome, and would form a separate group from the
identical decisions recorded afterwards. The agent would then be shown a track
record that is not its own.

Idempotent: running it twice is a no-op. Reports exactly what it changed.

Usage:
    python -m scripts.migrate_exposure_vocabulary [--memory path] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from btc_decision_agent.application.llm_tools import EXPOSURE_CASH, EXPOSURE_INVESTED

DEFAULT_MEMORY = "data/live/llm-agent-memory.sqlite3"

RETIRED = {"LARGO": EXPOSURE_INVESTED, "PLANO": EXPOSURE_CASH}
COLUMNS = ("target_exposure", "exposure_before")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate the exposure vocabulary in memory.")
    parser.add_argument("--memory", default=DEFAULT_MEMORY)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    path = Path(args.memory)
    if not path.is_file():
        print(f"memoria no encontrada: {path}")
        return 2

    with closing(sqlite3.connect(path, timeout=30.0)) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) c FROM decisions").fetchone()["c"]
        pending: dict[tuple[str, str], int] = {}
        for column in COLUMNS:
            for old in RETIRED:
                count = conn.execute(
                    f"SELECT COUNT(*) c FROM decisions WHERE {column} = ?", (old,)
                ).fetchone()["c"]
                if count:
                    pending[(column, old)] = count

        print(f"memoria: {path}")
        print(f"  filas totales: {total}")
        if not pending:
            print("  nada que migrar; el vocabulario ya es el actual")
            return 0
        for (column, old), count in sorted(pending.items()):
            print(f"  {column}: {count} filas con {old!r} -> {RETIRED[old]!r}")

        if args.dry_run:
            print("  --dry-run: no se escribio nada")
            return 0

        for column in COLUMNS:
            for old, new in RETIRED.items():
                conn.execute(
                    f"UPDATE decisions SET {column} = ? WHERE {column} = ?", (new, old)
                )
        conn.commit()

        left = sum(
            conn.execute(
                f"SELECT COUNT(*) c FROM decisions WHERE {column} = ?", (old,)
            ).fetchone()["c"]
            for column in COLUMNS
            for old in RETIRED
        )
    print(f"  migrado. filas con vocabulario retirado que quedan: {left}")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
