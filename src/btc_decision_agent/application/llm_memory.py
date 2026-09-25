"""Persistent memory that lets the agent learn without touching model weights.

What this module is, stated plainly
-----------------------------------
It does NOT train the model. The weights of qwen3:30b-a3b are frozen and nothing
here changes them: there is no fine-tuning, no adapter, no gradient. What this does
is keep a record of what the agent decided, what it expected, and what actually
happened, compute ordinary statistics over that record, and put the result in the
agent's prompt before it decides again.

That is in-context conditioning, not parametric learning, and the vocabulary here
says so on purpose. Calling these "lessons the agent learned" would suggest the
model improved. It did not. It is the same model, better informed about itself.

The danger this module is built around
--------------------------------------
A naive reflection loop is worse than no record at all. If the agent concludes "buy
when volatility expands" after three lucky trades, it will entrench noise as
doctrine and act on it with confidence. The project already established that this
asset has no reliable point-in-time signal: of twenty signal/horizon pairs measured
on non-overlapping samples, none reached one standard error.

So no pattern here is marked as SUPPORTED on the strength of a story. It is promoted
only when it has enough independent samples AND an effect larger than its own
standard error. Everything else is shown to the agent explicitly labelled as
insufficient evidence, which is itself useful information: it tells the agent not
to trust its own hunch.

Calibration is tracked for the same reason. If the agent says 0.9 conviction and is
right half the time, it is told so in its own prompt.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from btc_decision_agent.application.llm_tools import EXPOSURE_INVESTED

D = Decimal
SCHEMA_VERSION = "llm-agent-memory/1.0.0"
DEFAULT_PATH = "data/live/llm-agent-memory.sqlite3"

MIN_SAMPLES_FOR_SUPPORT = 8
"""Below this a pattern is a coincidence, not a finding."""

MIN_EFFECT_IN_STANDARD_ERRORS = 1.5
"""How far the mean outcome must sit from zero, measured in its own standard
error, before the pattern may be described as supported by the record."""

_DDL = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decided_at TEXT NOT NULL,
    event_id TEXT,
    features TEXT NOT NULL,
    regime INTEGER,
    quant_p_long REAL,
    target_exposure TEXT NOT NULL,
    exposure_before TEXT NOT NULL,
    derived_order TEXT NOT NULL,
    conviction REAL,
    expected_move_pct REAL,
    posture TEXT,
    reason TEXT,
    thinking TEXT,
    price_at_decision TEXT NOT NULL,
    acted INTEGER NOT NULL DEFAULT 0,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolved_at TEXT,
    price_at_resolution TEXT,
    realized_pct REAL,
    UNIQUE(decided_at, event_id)
);
CREATE INDEX IF NOT EXISTS idx_resolved ON decisions(resolved);
CREATE INDEX IF NOT EXISTS idx_regime ON decisions(regime, target_exposure);
CREATE INDEX IF NOT EXISTS idx_posture ON decisions(regime, posture);
"""


@dataclass(frozen=True)
class PastDecision:
    decided_at: str
    regime: int | None
    target_exposure: str
    derived_order: str
    conviction: float | None
    expected_move_pct: float | None
    realized_pct: float | None
    reason: str


@dataclass(frozen=True)
class MeasuredPattern:
    """A regularity the agent's own record supports, or explicitly does not.

    Named for what it is. This is a statistic computed over past decisions, not
    something the model learned: the weights never change. The label the agent and
    the dashboard both see says "con respaldo" or "no concluyente" rather than
    "leccion", because "lesson" implies knowledge acquired and would misdescribe
    every part of this pipeline.
    """

    scope: str
    samples: int
    mean_realized_pct: float
    effect_in_standard_errors: float
    supported: bool

    def render(self) -> str:
        verdict = "CON RESPALDO" if self.supported else "NO CONCLUYENTE"
        return (
            f"  [{verdict}] {self.scope}: {self.samples} casos, "
            f"resultado medio {self.mean_realized_pct:+.2f}%, "
            f"efecto {self.effect_in_standard_errors:.1f} errores estandar"
        )


class AgentMemory:
    """Append-only record of decisions and their measured outcomes."""

    def __init__(
        self,
        path: str | Path = DEFAULT_PATH,
        *,
        horizon_hours: int = 24,
        read_only: bool = False,
    ) -> None:
        """`read_only` exists so observers can reuse the statistics without owning
        the database.

        The dashboard has to report the same calibration and the same support gate
        the agent is held to; reimplementing them there would let the two drift, and
        a dashboard showing a looser gate than the agent obeys is a lie. But it runs
        under a sandbox that mounts the data directory read-only, so it cannot run
        the DDL or take a write lock. This flag skips both.
        """
        self.path = Path(path)
        self.read_only = read_only
        self.horizon = timedelta(hours=horizon_hours)
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(f"memoria no encontrada: {self.path}")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_DDL)
            # CREATE TABLE IF NOT EXISTS cannot add a column to a table that already
            # exists, so a database written before postures were recorded needs the
            # column added explicitly. Idempotent, and cheap enough to run every time.
            existing = {row[1] for row in conn.execute("PRAGMA table_info(decisions)")}
            if "posture" not in existing:
                conn.execute("ALTER TABLE decisions ADD COLUMN posture TEXT")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            return conn
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.row_factory = sqlite3.Row
        return conn

    def record(
        self,
        *,
        decided_at: datetime,
        event_id: str,
        features: Sequence[float],
        regime: int | None,
        quant_p_long: float | None,
        target_exposure: str,
        exposure_before: str,
        derived_order: str,
        conviction: float | None,
        expected_move_pct: float | None,
        reason: str,
        thinking: str,
        price: Decimal,
        acted: bool,
        posture: str | None = None,
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO decisions (
                    decided_at, event_id, features, regime, quant_p_long,
                    target_exposure, exposure_before, derived_order, conviction,
                    expected_move_pct, posture, reason, thinking, price_at_decision,
                    acted
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    decided_at.isoformat(),
                    event_id,
                    json.dumps([round(float(v), 6) for v in features]),
                    regime,
                    quant_p_long,
                    target_exposure,
                    exposure_before,
                    derived_order,
                    conviction,
                    expected_move_pct,
                    posture,
                    reason[:2000],
                    thinking[:4000],
                    format(price, "f"),
                    1 if acted else 0,
                ),
            )
            conn.commit()

    def resolve_pending(self, now: datetime, price: Decimal) -> int:
        """Measure the outcome of decisions whose horizon has elapsed.

        The outcome is signed by the exposure the agent chose: holding BTC earns the
        move, standing aside earns the move avoided. That way a correct decision to
        stay flat during a fall is recorded as a win, which is exactly what it was.
        """
        cutoff = (now - self.horizon).isoformat()
        resolved = 0
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, decided_at, target_exposure, price_at_decision "
                "FROM decisions WHERE resolved=0 AND decided_at<=?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                entry = float(row["price_at_decision"])
                if entry <= 0:
                    continue
                move_pct = (float(price) / entry - 1.0) * 100.0
                realized = (
                    move_pct if row["target_exposure"] == EXPOSURE_INVESTED else -move_pct
                )
                conn.execute(
                    "UPDATE decisions SET resolved=1, resolved_at=?, "
                    "price_at_resolution=?, realized_pct=? WHERE id=?",
                    (now.isoformat(), format(price, "f"), realized, row["id"]),
                )
                resolved += 1
            conn.commit()
        return resolved

    def similar_past(
        self, features: Sequence[float], count: int = 5, *, only_resolved: bool = True
    ) -> list[PastDecision]:
        """The agent's own closest past situations, with what they earned."""
        query = "SELECT * FROM decisions"
        if only_resolved:
            query += " WHERE resolved=1"
        with closing(self._connect()) as conn:
            rows = conn.execute(query).fetchall()
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            stored = json.loads(row["features"])
            if len(stored) != len(features):
                continue
            distance = math.sqrt(
                sum((float(a) - float(b)) ** 2 for a, b in zip(stored, features, strict=True))
            )
            scored.append((distance, row))
        scored.sort(key=lambda item: item[0])
        return [
            PastDecision(
                decided_at=str(row["decided_at"]),
                regime=row["regime"],
                target_exposure=str(row["target_exposure"]),
                derived_order=str(row["derived_order"]),
                conviction=row["conviction"],
                expected_move_pct=row["expected_move_pct"],
                realized_pct=row["realized_pct"],
                reason=str(row["reason"] or "")[:160],
            )
            for _distance, row in scored[:count]
        ]

    def calibration(self) -> dict[str, Any]:
        """Stated conviction versus realised hit rate, bucketed.

        Overconfidence is the failure mode most likely to cost money here, and it is
        invisible unless measured against outcomes.
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT conviction, realized_pct FROM decisions "
                "WHERE resolved=1 AND conviction IS NOT NULL"
            ).fetchall()
        buckets: dict[str, list[float]] = {"0.5-0.7": [], "0.7-0.85": [], "0.85-1.0": []}
        for row in rows:
            conviction = float(row["conviction"])
            realized = float(row["realized_pct"] or 0.0)
            if conviction < 0.7:
                buckets["0.5-0.7"].append(realized)
            elif conviction < 0.85:
                buckets["0.7-0.85"].append(realized)
            else:
                buckets["0.85-1.0"].append(realized)
        out: dict[str, Any] = {"total_resueltas": len(rows), "buckets": {}}
        for name, values in buckets.items():
            if not values:
                continue
            out["buckets"][name] = {
                "casos": len(values),
                "acierto": sum(1 for v in values if v > 0) / len(values),
                "resultado_medio_pct": sum(values) / len(values),
            }
        return out

    def measured_patterns(self) -> list[MeasuredPattern]:
        """Regularities grouped by (regime, chosen exposure), gated by statistics.

        Not "lessons": nothing is learned here. This aggregates outcomes the agent
        already produced and marks which groups the record can actually support.
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT regime, target_exposure, realized_pct FROM decisions "
                "WHERE resolved=1 AND realized_pct IS NOT NULL"
            ).fetchall()
        groups: dict[tuple[Any, str], list[float]] = {}
        for row in rows:
            key = (row["regime"], str(row["target_exposure"]))
            groups.setdefault(key, []).append(float(row["realized_pct"]))

        out: list[MeasuredPattern] = []
        for (regime, exposure), values in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            count = len(values)
            mean = sum(values) / count
            if count > 1:
                variance = sum((v - mean) ** 2 for v in values) / (count - 1)
                stderr = math.sqrt(variance / count)
            else:
                stderr = float("inf")
            effect = abs(mean) / stderr if stderr > 0 else 0.0
            supported = (
                count >= MIN_SAMPLES_FOR_SUPPORT and effect >= MIN_EFFECT_IN_STANDARD_ERRORS
            )
            out.append(
                MeasuredPattern(
                    scope=f"regimen {regime} eligiendo {exposure}",
                    samples=count,
                    mean_realized_pct=mean,
                    effect_in_standard_errors=effect if math.isfinite(effect) else 0.0,
                    supported=supported,
                )
            )
        return out

    def stats(self) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            total = conn.execute("SELECT COUNT(*) c FROM decisions").fetchone()["c"]
            resolved = conn.execute(
                "SELECT COUNT(*) c FROM decisions WHERE resolved=1"
            ).fetchone()["c"]
            acted = conn.execute("SELECT COUNT(*) c FROM decisions WHERE acted=1").fetchone()["c"]
            avg = conn.execute(
                "SELECT AVG(realized_pct) a FROM decisions WHERE resolved=1"
            ).fetchone()["a"]
        return {
            "decisiones_totales": total,
            "resueltas": resolved,
            "ordenes_ejecutadas": acted,
            "resultado_medio_pct": float(avg) if avg is not None else None,
        }


def render_memory_block(memory: AgentMemory, features: Sequence[float]) -> str:
    """What the agent is told about its own track record, before deciding again."""
    stats = memory.stats()
    if not stats["decisiones_totales"]:
        return (
            "TU MEMORIA: vacia, esta es tu primera decision. No tienes historial "
            "propio todavia, asi que apoyate en los analogos historicos y en el "
            "modelo cuantitativo."
        )

    lines = [
        "TU HISTORIAL MEDIDO (no son intuiciones: son tus decisiones anteriores y lo",
        "que paso de verdad despues):",
        f"  decisiones={stats['decisiones_totales']} resueltas={stats['resueltas']} "
        f"ordenes={stats['ordenes_ejecutadas']} resultado_medio="
        + (
            f"{stats['resultado_medio_pct']:+.2f}%"
            if stats["resultado_medio_pct"] is not None
            else "n/d"
        ),
    ]

    similar = memory.similar_past(features, count=4)
    if similar:
        lines.append("  tus decisiones en situaciones parecidas:")
        for item in similar:
            got = f"{item.realized_pct:+.2f}%" if item.realized_pct is not None else "pendiente"
            expected = (
                f"{item.expected_move_pct:+.2f}%" if item.expected_move_pct is not None else "n/d"
            )
            lines.append(
                f"    {item.decided_at[:16]} regimen {item.regime} elegiste "
                f"{item.target_exposure} (esperabas {expected}) -> obtuviste {got}"
            )

    patterns = memory.measured_patterns()
    if patterns:
        lines.append("  patrones medidos en tu historial:")
        lines.extend(pattern.render() for pattern in patterns[:6])
        lines.append(
            "    NOTA: solo lo marcado CON RESPALDO tiene respaldo estadistico. "
            "Lo marcado NO CONCLUYENTE es ruido todavia, no lo uses como regla."
        )

    calibration = memory.calibration()
    if calibration["buckets"]:
        lines.append("  tu calibracion (conviccion declarada vs acierto real):")
        for name, data in calibration["buckets"].items():
            lines.append(
                f"    conviccion {name}: {data['casos']} casos, acertaste "
                f"{data['acierto']:.0%}, resultado medio {data['resultado_medio_pct']:+.2f}%"
            )
        lines.append(
            "    Si tu acierto es mucho menor que tu conviccion, estas sobreconfiado: "
            "baja la conviccion y exige mas evidencia antes de cambiar exposicion."
        )
    return "\n".join(lines)


__all__ = [
    "DEFAULT_PATH",
    "MIN_EFFECT_IN_STANDARD_ERRORS",
    "MIN_SAMPLES_FOR_SUPPORT",
    "SCHEMA_VERSION",
    "AgentMemory",
    "MeasuredPattern",
    "PastDecision",
    "render_memory_block",
]
