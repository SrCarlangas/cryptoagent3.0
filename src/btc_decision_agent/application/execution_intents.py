"""Durable SQLite intent ledger for exactly-once-ish DEMO order recovery.

An intent is committed before export. Startup resolves every non-terminal intent
against Binance before strategic decisions are enabled.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

_TERMINAL = frozenset(
    {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH", "NOT_FOUND"}
)


@dataclass(frozen=True)
class ExecutionIntent:
    client_order_id: str
    event_id: str
    action: str
    side: str
    requested_quote: Decimal | None
    requested_base: Decimal | None
    status: str
    exchange_order_id: str | None
    created_at: datetime
    updated_at: datetime
    response: dict[str, Any] | None

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL


class ExecutionIntentStore:
    """Small transactional ledger; one process owns writes under the runtime lock."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_intents (
                    client_order_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    side TEXT NOT NULL,
                    requested_quote TEXT,
                    requested_base TEXT,
                    status TEXT NOT NULL,
                    exchange_order_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    response_json TEXT
                )
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row) -> ExecutionIntent:
        response = json.loads(row["response_json"]) if row["response_json"] else None
        return ExecutionIntent(
            client_order_id=str(row["client_order_id"]),
            event_id=str(row["event_id"]),
            action=str(row["action"]),
            side=str(row["side"]),
            requested_quote=(
                Decimal(str(row["requested_quote"]))
                if row["requested_quote"] is not None
                else None
            ),
            requested_base=(
                Decimal(str(row["requested_base"]))
                if row["requested_base"] is not None
                else None
            ),
            status=str(row["status"]),
            exchange_order_id=(
                str(row["exchange_order_id"])
                if row["exchange_order_id"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            response=response,
        )

    def prepare(
        self,
        *,
        client_order_id: str,
        event_id: str,
        action: str,
        side: str,
        requested_quote: Decimal | None = None,
        requested_base: Decimal | None = None,
    ) -> ExecutionIntent:
        now = datetime.now(tz=UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO execution_intents (
                    client_order_id, event_id, action, side,
                    requested_quote, requested_base, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?)
                """,
                (
                    client_order_id,
                    event_id,
                    action,
                    side,
                    format(requested_quote, "f") if requested_quote is not None else None,
                    format(requested_base, "f") if requested_base is not None else None,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM execution_intents WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        assert row is not None
        return self._decode(row)

    def mark(
        self,
        client_order_id: str,
        status: str,
        *,
        exchange_order_id: str | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(tz=UTC).isoformat()
        payload = json.dumps(response, separators=(",", ":"), sort_keys=True) if response else None
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE execution_intents
                SET status = ?, exchange_order_id = COALESCE(?, exchange_order_id),
                    updated_at = ?, response_json = COALESCE(?, response_json)
                WHERE client_order_id = ?
                """,
                (status, exchange_order_id, now, payload, client_order_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown execution intent {client_order_id}")

    def unresolved(self) -> tuple[ExecutionIntent, ...]:
        placeholders = ",".join("?" for _ in _TERMINAL)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM execution_intents WHERE status NOT IN ({placeholders}) ORDER BY created_at",
                tuple(sorted(_TERMINAL)),
            ).fetchall()
        return tuple(self._decode(row) for row in rows)

    def get(self, client_order_id: str) -> ExecutionIntent | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM execution_intents WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        return self._decode(row) if row is not None else None


__all__ = ["ExecutionIntent", "ExecutionIntentStore"]
