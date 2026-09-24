"""Deterministic tools that ground the LLM agent in real numbers.

Design rule, and the reason this module exists: the agent must never estimate a
quantity that can be computed. Every figure it reasons about is produced here, in
Python, from real Binance data or from the frozen five-year dataset. The LLM's job
is judgement, not arithmetic.

Two lessons from measuring the model are baked in:

1. Names must be unambiguous. An earlier prompt called realised volatility `vol30`
   and the model read it as "volume" and reasoned about liquidity. Every field
   rendered for the agent now says what it is.

2. Historical analogues are worthless without their outcome. An analogue tells the
   agent "this happened before"; the outcome tells it "and here is what followed".
   Only the second is evidence, so the index stores forward returns and this module
   always renders them.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from btc_decision_agent.application.exposure_agent import (
    ExposureAction,
    PolicyDecision,
    PortfolioState,
    RegimeMixturePolicy,
    compose_features,
)
from btc_decision_agent.application.exposure_features import (
    MARKET_FEATURE_NAMES,
    MIN_DAILY_HISTORY,
    market_features,
)

D = Decimal
DEFAULT_INDEX = "data/models/history-index.json"

REGIME_NAMES: dict[int, str] = {
    0: "recuperacion_lateral",
    1: "bajista_profundo",
    2: "consolidacion_sobre_tendencia",
    3: "alcista_fuerte",
}


@dataclass(frozen=True)
class Analogue:
    """A past day whose market shape resembled now, plus what actually followed."""

    distance: float
    price: float
    ret_7d_pct: float
    ret_30d_pct: float
    ret_90d_pct: float


class HistoryIndex:
    """Nearest-neighbour lookup over five years of daily situations.

    Distance is computed on per-feature standardised units so no single feature
    dominates simply because its raw scale is larger.
    """

    def __init__(self, path: str | Path = DEFAULT_INDEX) -> None:
        raw: object = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("history index must be a JSON object")
        if tuple(raw.get("feature_names", ())) != MARKET_FEATURE_NAMES:
            raise ValueError("history index feature schema mismatch")
        self.dataset_id = str(raw.get("dataset_id", "unknown"))
        self.scales: list[float] = [float(v) for v in raw["feature_scales"]]
        self.rows: list[dict[str, Any]] = list(raw["rows"])
        if not self.rows:
            raise ValueError("history index is empty")
        self.horizons: tuple[int, ...] = tuple(
            int(value) for value in raw.get("horizons_days", (7, 30, 90))
        )
        self.max_horizon: int = max(self.horizons)
        """Longest forward window stored per row.

        This is the embargo length. Every row carries what happened over the next
        `max_horizon` days, so a row is only safe to show on day D if its whole
        outcome window closed before D. Filtering on `day_index < D` alone is not
        enough and is actively misleading: measured on this index, the median
        nearest neighbour sits 7 days back, so more than half of the analogues
        would hand the agent the price it is about to trade at.
        """

    @property
    def days(self) -> int:
        return len(self.rows)

    def _visible(self, row: dict[str, Any], before_day: int | None) -> bool:
        """Whether `row` may be shown to an agent deciding on day `before_day`.

        Purge-and-embargo: the row's forward window must have closed strictly
        before the decision day. `before_day is None` means live use, where the
        index only contains days whose outcomes are already complete history.
        """
        if before_day is None:
            return True
        return int(row["day_index"]) + self.max_horizon < before_day

    def base_rates(self, *, before_day: int | None = None) -> dict[str, float]:
        """Unconditional priors, so the agent can tell 'better than usual' apart
        from 'usual'. Without this an analogue mean of +4% looks like a signal when
        it is simply the average of the whole period.

        Respects the same purge-and-embargo cutoff as `analogues`: a base rate
        computed over days whose outcomes have not finished resolving would leak the
        future just as surely.
        """
        thirty = [
            float(row["forward"]["ret_30d_pct"])
            for row in self.rows
            if self._visible(row, before_day)
        ]
        if not thirty:
            return {"dias_indexados": 0.0, "prob_30d_positivo": 0.0, "ret_30d_medio_pct": 0.0}
        return {
            "dias_indexados": float(len(thirty)),
            "prob_30d_positivo": sum(1 for v in thirty if v > 0) / len(thirty),
            "ret_30d_medio_pct": sum(thirty) / len(thirty),
        }

    def analogues(
        self,
        features: Sequence[float],
        count: int = 8,
        *,
        before_day: int | None = None,
    ) -> list[Analogue]:
        """Nearest past situations, optionally restricted to fully resolved days.

        `before_day` exists for backtesting and is not optional there. Replaying a
        decision for day D while the index still contains days after D would let the
        agent read its own future, which is the most common way a backtest of this
        shape ends up reporting fiction.

        The cutoff is not `day_index < D`. Each row carries the return over the next
        `max_horizon` days, so a row at D-1 encodes the price at D+89. Rows are
        therefore purged until their entire outcome window predates D. This costs
        `max_horizon` days of index depth and is the difference between a measurement
        and a story.

        In live use there is no cutoff because no future exists yet: the index is
        built only over days whose outcomes have already happened.
        """
        if len(features) != len(self.scales):
            raise ValueError("feature length mismatch against the history index")
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in self.rows:
            if not self._visible(row, before_day):
                continue
            stored = row["features"]
            total = 0.0
            for index, scale in enumerate(self.scales):
                delta = (float(stored[index]) - float(features[index])) / scale
                total += delta * delta
            scored.append((math.sqrt(total), row))
        scored.sort(key=lambda item: item[0])
        out: list[Analogue] = []
        for distance, row in scored[:count]:
            forward = row["forward"]
            out.append(
                Analogue(
                    distance=distance,
                    price=float(row["price"]),
                    ret_7d_pct=float(forward["ret_7d_pct"]),
                    ret_30d_pct=float(forward["ret_30d_pct"]),
                    ret_90d_pct=float(forward["ret_90d_pct"]),
                )
            )
        return out

    @staticmethod
    def summarise(analogues: Sequence[Analogue]) -> dict[str, float]:
        if not analogues:
            return {}
        thirty = [item.ret_30d_pct for item in analogues]
        return {
            "casos": float(len(thirty)),
            "ret_30d_medio_pct": sum(thirty) / len(thirty),
            "ret_30d_peor_pct": min(thirty),
            "ret_30d_mejor_pct": max(thirty),
            "prob_positivo": sum(1 for v in thirty if v > 0) / len(thirty),
        }


def market_view(daily_closes: Sequence[Decimal], price: Decimal) -> dict[str, Any]:
    """Human-readable market state, with the raw feature vector alongside it.

    The readable block is what the agent reasons over; the vector is what the
    quantitative model and the history index consume. Both come from the same
    call so they can never disagree.
    """
    if len(daily_closes) < MIN_DAILY_HISTORY:
        raise ValueError(
            f"se requieren {MIN_DAILY_HISTORY} cierres diarios completos, hay {len(daily_closes)}"
        )
    closes = [float(value) for value in daily_closes]
    spot = float(price)
    vector = market_features(closes, spot)
    named = dict(zip(MARKET_FEATURE_NAMES, vector, strict=True))

    def average(window: int) -> float:
        return sum(closes[-window:]) / window

    window_200 = closes[-200:]
    return {
        "_vector": vector,
        "precio_actual": round(spot, 2),
        "media_movil_7d": round(average(7), 2),
        "media_movil_30d": round(average(30), 2),
        "media_movil_200d": round(average(200), 2),
        "precio_vs_media_200d_pct": round((math.exp(named["log_price_over_ma200"]) - 1.0) * 100.0, 2),
        "precio_vs_media_30d_pct": round((math.exp(named["log_price_over_ma30"]) - 1.0) * 100.0, 2),
        "retorno_1d_pct": round((math.exp(named["return_1d"]) - 1.0) * 100.0, 2),
        "retorno_7d_pct": round((math.exp(named["return_7d"]) - 1.0) * 100.0, 2),
        "retorno_30d_pct": round((math.exp(named["return_30d"]) - 1.0) * 100.0, 2),
        "retorno_90d_pct": round((math.exp(named["return_90d"]) - 1.0) * 100.0, 2),
        "volatilidad_diaria_30d_pct": round(named["volatility_30d"] * 100.0, 2),
        "volatilidad_diaria_90d_pct": round(named["volatility_90d"] * 100.0, 2),
        "volatilidad_expandiendose": named["volatility_ratio_30_90"] > 1.0,
        "desde_maximo_200d_pct": round((math.exp(named["log_price_over_high_200d"]) - 1.0) * 100.0, 2),
        "desde_minimo_200d_pct": round((math.exp(named["log_price_over_low_200d"]) - 1.0) * 100.0, 2),
        "maximo_200d": round(max(window_200), 2),
        "minimo_200d": round(min(window_200), 2),
        "dias_de_historia": len(closes),
    }


def position_view(
    *,
    position_long: bool,
    btc_qty: Decimal,
    usdt_free: Decimal,
    price: Decimal,
    entry_price: Decimal | None,
    holding_hours: int,
    active_stop: Decimal | None,
) -> dict[str, Any]:
    equity = usdt_free + btc_qty * price
    unrealized = (
        (float(price) / float(entry_price) - 1.0) * 100.0
        if position_long and entry_price is not None and entry_price > 0
        else 0.0
    )
    return {
        "exposicion_actual": "LARGO" if position_long else "PLANO",
        "btc": float(btc_qty),
        "usdt_libre": round(float(usdt_free), 2),
        "equity_total_usdt": round(float(equity), 2),
        "precio_entrada": float(entry_price) if entry_price is not None else None,
        "pnl_no_realizado_pct": round(unrealized, 2),
        "horas_en_posicion": holding_hours,
        "stop_en_exchange": float(active_stop) if active_stop is not None else None,
        "caida_hasta_stop_pct": (
            round((float(active_stop) / float(price) - 1.0) * 100.0, 2)
            if active_stop is not None and price > 0
            else None
        ),
    }


def cost_view(round_trip_cost_bps: Decimal, allocation_fraction: Decimal) -> dict[str, Any]:
    """The economics of acting, stated so the agent cannot ignore them.

    The project measured that unbounded churn costs 137% of capital per year, so
    the cost of switching is presented as a threshold the expected move must clear,
    not as a footnote.
    """
    cost_pct = float(round_trip_cost_bps) / 100.0
    return {
        "comision_ida_y_vuelta_bps": float(round_trip_cost_bps),
        "comision_ida_y_vuelta_pct": round(cost_pct, 4),
        "movimiento_minimo_para_cubrir_pct": round(cost_pct, 4),
        "porcentaje_del_capital_por_operacion": round(float(allocation_fraction) * 100.0, 1),
        "nota": (
            "cambiar de exposicion cuesta esta comision; si el movimiento esperado "
            "a favor es menor, cambiar destruye valor aunque la direccion sea correcta"
        ),
    }


def quant_view(
    policy: RegimeMixturePolicy,
    market_vector: Sequence[float],
    portfolio: PortfolioState,
) -> dict[str, Any]:
    """The trained model's opinion, offered as an advisor the agent may override.

    This is where the five years of training enter the decision: the policy was
    fitted and walk-forward validated on 2021-2026 and keeps learning online.
    """
    features = compose_features(list(market_vector), portfolio)
    outcome: PolicyDecision = policy.decide(features, portfolio)
    regime = outcome.dominant_regime
    return {
        "p_largo": round(outcome.action_probabilities[ExposureAction.TARGET_LONG.value], 4),
        "recomienda": "LARGO" if outcome.action == ExposureAction.TARGET_LONG else "PLANO",
        "regimen": regime,
        "nombre_regimen": REGIME_NAMES.get(regime, f"regimen_{regime}"),
        "reparto_regimenes": [round(value, 3) for value in outcome.regime_responsibilities],
        "version": outcome.policy_version,
        "pasos_entrenados": policy.trained_steps,
        "nota": (
            "modelo cuantitativo entrenado con 5 anos (2021-2026) y validado "
            "walk-forward; sigue aprendiendo en linea. Es un asesor, no una orden"
        ),
    }


def render_state_block(
    market: dict[str, Any],
    position: dict[str, Any],
    cost: dict[str, Any],
    quant: dict[str, Any],
    analogues: Sequence[Analogue],
    analogue_summary: dict[str, float],
    base_rates: dict[str, float],
    memory_block: str = "",
) -> str:
    """Render everything into the single prompt block the agent reasons over.

    One block, one round. Measuring showed that letting the model discover these
    values through successive tool calls cost 714 seconds per decision versus 45,
    because every round re-processes a growing context for information we could
    simply have computed up front.
    """

    def kv(data: dict[str, Any], skip: tuple[str, ...] = ()) -> str:
        return "\n".join(
            f"  {key} = {value}"
            for key, value in data.items()
            if key not in skip and not key.startswith("_")
        )

    lines = [
        "MERCADO (calculado desde datos reales de Binance):",
        kv(market),
        "",
        "TU POSICION (reconciliada contra el exchange):",
        kv(position),
        "",
        "COSTO DE ACTUAR:",
        kv(cost),
        "",
        "MODELO CUANTITATIVO (asesor entrenado con 5 anos):",
        kv(quant),
        "",
        f"BASE RATE DE 5 ANOS ({int(base_rates.get('dias_indexados', 0))} dias):",
        f"  prob_30d_positivo = {base_rates.get('prob_30d_positivo', 0):.4f}",
        f"  ret_30d_medio_pct = {base_rates.get('ret_30d_medio_pct', 0):+.2f}",
        "  (compara los analogos contra esto: si coinciden, no hay senal)",
        "",
        "SITUACIONES HISTORICAS PARECIDAS Y LO QUE PASO DESPUES:",
    ]
    for item in analogues:
        lines.append(
            f"  precio {item.price:.0f} (distancia {item.distance:.2f}) -> "
            f"7d {item.ret_7d_pct:+.1f}%  30d {item.ret_30d_pct:+.1f}%  90d {item.ret_90d_pct:+.1f}%"
        )
    if analogue_summary:
        lines.append(
            f"  RESUMEN: {int(analogue_summary['casos'])} casos, 30d medio "
            f"{analogue_summary['ret_30d_medio_pct']:+.2f}%, "
            f"peor {analogue_summary['ret_30d_peor_pct']:+.1f}%, "
            f"mejor {analogue_summary['ret_30d_mejor_pct']:+.1f}%, "
            f"positivos {analogue_summary['prob_positivo']:.2f}"
        )
    if memory_block:
        lines.extend(["", memory_block])
    return "\n".join(lines)


__all__ = [
    "DEFAULT_INDEX",
    "REGIME_NAMES",
    "Analogue",
    "HistoryIndex",
    "cost_view",
    "market_view",
    "position_view",
    "quant_view",
    "render_state_block",
]
