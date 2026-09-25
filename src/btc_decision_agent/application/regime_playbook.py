"""Per-regime strategies whose behavioural parameters the regime itself defines.

Why this exists
---------------
Until now the agent chose only a direction: invested or in cash. Everything else
was one fixed setting regardless of what the market was doing. A 3% stop and a 95%
allocation in a deep bear and in a strong uptrend alike. Measured over 100 replayed
decisions that produced the specific failure the owner objected to: in a strong
uptrend the agent was invested only 41% of the time, and a fixed tight stop kept
taking it out of trends on noise.

So a regime no longer selects only an exposure, it selects a strategy, and each
strategy carries its own risk budget, stop geometry, holding horizon and burden of
proof.

The design constraint that shapes everything here
-------------------------------------------------
The agent cannot estimate magnitudes. It declared a +35.31% expected move over a few
days in one decision. So it is NOT asked for numbers. It picks a POSTURE, which is a
qualitative judgement it is good at, and every number is then derived from the
regime's pre-registered bounds and from measured volatility. The model chooses how
aggressive to be; arithmetic decides what that means in basis points.

The coupling that makes this non-obvious
----------------------------------------
`size_entry_percentage` computes `min(cash * allocation, equity * risk / stop)`. The
risk cap divides by the stop distance, so widening a stop SHRINKS the position for a
fixed risk budget. Widening the stop in a strong uptrend to avoid being shaken out
would therefore have quietly cut the position instead of letting it run. Each
strategy therefore sets its risk budget alongside its stop, and the two are chosen
together rather than one at a time.

Stops are expressed in multiples of measured daily volatility, never in fixed
percentages. A 3% stop is loose in quiet markets and is hit by noise in violent
ones; "2.5 daily standard deviations" means the same thing in both.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from typing import Any

from btc_decision_agent.application.llm_tools import EXPOSURE_CASH, EXPOSURE_INVESTED
from btc_decision_agent.application.realtime_demo import RealtimeParams

D = Decimal

PLAYBOOK_VERSION = "regime-playbook/1.0.0"


class Posture(str, Enum):
    """How aggressively to express the regime's strategy.

    Qualitative on purpose. The agent judges posture; the playbook turns it into
    numbers, because the agent has demonstrated it cannot produce numbers.
    """

    DEFENSIVA = "DEFENSIVA"
    NEUTRAL = "NEUTRAL"
    AGRESIVA = "AGRESIVA"


POSTURE_VALUES: tuple[str, ...] = tuple(item.value for item in Posture)

# Hard limits. Everything the playbook produces is clamped into these, so no regime,
# posture or volatility reading can push the live engine outside a range that was
# reviewed. RealtimeParams.__post_init__ additionally requires every stop fraction to
# sit strictly inside (0, 1), so a stop can never be disabled by setting it to zero.
MIN_ALLOCATION = D("0.10")
MAX_ALLOCATION = D("0.95")
MIN_STOP_FRACTION = D("0.015")
MAX_STOP_FRACTION = D("0.22")
MIN_RISK_FRACTION = D("0.005")
MAX_RISK_FRACTION = D("0.12")
MIN_TRAIL_FRACTION = D("0.010")
MAX_TRAIL_FRACTION = D("0.18")


@dataclass(frozen=True)
class RegimeStrategy:
    """One regime's strategy, including the parameters of its own behaviour."""

    name: str
    allocation_at_neutral: Decimal
    """Share of available cash deployed at NEUTRAL posture and average conviction."""

    stop_vol_multiple: Decimal
    """Initial stop distance in multiples of 30-day daily volatility."""

    trail_vol_multiple: Decimal
    """Trailing distance behind the high, also in volatility multiples."""

    trail_activation_vol_multiple: Decimal
    """How far in profit, in volatility multiples, before the trail engages."""

    risk_per_trade: Decimal
    """Share of equity risked to the stop. Set WITH the stop, never independently:
    the sizing formula divides by the stop distance, so a wide stop needs a larger
    risk budget to express the same conviction."""

    horizon_hours: int
    """Intended holding period. Drives how long an outcome is measured over, so the
    record judges a trend-following decision on a trend's timescale rather than on
    tomorrow's noise."""

    default_exposure: str
    """Where the capital sits in this regime unless there is a reason not to.

    A burden of proof needs a side that carries it, and expressing it as two separate
    minimums did not work. Gating only CHANGES left the status quo unexamined: the
    agent began in cash, wanted cash, so nothing changed and no threshold ever
    applied. Measured on the most bullish window in the dataset it sat out a +185%
    advance declaring 0.50 conviction for cash in regime 3, which is well under the
    0.70 that side supposedly required, and the requirement never bit."""

    min_conviction_to_deviate: float
    """Conviction needed to hold the OTHER exposure instead of the default.

    In a strong uptrend the default is invested, so being in cash is what must be
    argued for. In a deep bear the default is cash and being invested is what must be
    argued for. Below the threshold the default stands, which means 'I do not know'
    resolves to the side the regime favours rather than to inaction."""

    doctrine: str
    """One line shown to the agent, so it knows the strategy it is operating inside."""


PLAYBOOK: dict[int, RegimeStrategy] = {
    0: RegimeStrategy(
        name="recuperacion lateral",
        allocation_at_neutral=D("0.45"),
        stop_vol_multiple=D("2.0"),
        trail_vol_multiple=D("1.6"),
        trail_activation_vol_multiple=D("1.0"),
        risk_per_trade=D("0.02"),
        horizon_hours=48,
        default_exposure=EXPOSURE_CASH,
        min_conviction_to_deviate=0.60,
        doctrine=(
            "Lateral bajo la media de 200d. Los rebotes fallan mas de lo que "
            "continuan: tamano medio, stop ceñido, horizonte corto. Estar invertido "
            "es lo que debe justificarse."
        ),
    ),
    1: RegimeStrategy(
        name="bajista profundo",
        allocation_at_neutral=D("0.20"),
        stop_vol_multiple=D("1.6"),
        trail_vol_multiple=D("1.2"),
        trail_activation_vol_multiple=D("0.8"),
        risk_per_trade=D("0.01"),
        horizon_hours=24,
        default_exposure=EXPOSURE_CASH,
        min_conviction_to_deviate=0.80,
        doctrine=(
            "Caida sostenida con volatilidad alta. Preservar capital manda: tamano "
            "minimo, stop corto, horizonte corto. Invertir aqui exige conviccion "
            "muy alta; la liquidez es la posicion por defecto."
        ),
    ),
    2: RegimeStrategy(
        name="consolidacion sobre tendencia",
        allocation_at_neutral=D("0.65"),
        stop_vol_multiple=D("2.5"),
        trail_vol_multiple=D("2.0"),
        trail_activation_vol_multiple=D("1.2"),
        risk_per_trade=D("0.035"),
        horizon_hours=96,
        default_exposure=EXPOSURE_INVESTED,
        min_conviction_to_deviate=0.55,
        doctrine=(
            "Sobre tendencia con momento plano. La tendencia de fondo sigue viva: "
            "tamano alto, stop holgado para no salir por ruido, horizonte medio."
        ),
    ),
    3: RegimeStrategy(
        name="alcista fuerte",
        allocation_at_neutral=D("0.90"),
        stop_vol_multiple=D("3.5"),
        trail_vol_multiple=D("2.8"),
        trail_activation_vol_multiple=D("1.5"),
        risk_per_trade=D("0.09"),
        horizon_hours=168,
        default_exposure=EXPOSURE_INVESTED,
        min_conviction_to_deviate=0.70,
        doctrine=(
            "Tendencia alcista establecida. Aqui se fluye con el movimiento: tamano "
            "maximo, stop ANCHO para que el ruido no te saque de la tendencia, "
            "horizonte largo. ESTAR EN LIQUIDEZ es lo que debe justificarse; "
            "quedarse fuera de una subida es una decision, no una posicion neutral."
        ),
    ),
}

_POSTURE_SIZE: dict[Posture, Decimal] = {
    Posture.DEFENSIVA: D("0.55"),
    Posture.NEUTRAL: D("1.00"),
    Posture.AGRESIVA: D("1.30"),
}
_POSTURE_STOP: dict[Posture, Decimal] = {
    # Defensive means a tighter stop and aggressive a wider one, because the point of
    # aggression here is to survive noise inside a trend, not to risk more per unit.
    Posture.DEFENSIVA: D("0.75"),
    Posture.NEUTRAL: D("1.00"),
    Posture.AGRESIVA: D("1.25"),
}


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


@dataclass(frozen=True)
class ExecutionPlan:
    """Concrete, bounded parameters for one decision, plus why they are what they are.

    Persisted with the position. The stop is recomputed on every market event from
    `entry_price`, `high_since_entry` and these fractions, so if the plan were lost on
    restart the stop geometry would silently change underneath an open position.
    """

    regime: int
    posture: str
    allocation_fraction: Decimal
    stop_loss_fraction: Decimal
    trailing_stop_fraction: Decimal
    trailing_activation_fraction: Decimal
    risk_per_trade_fraction: Decimal
    horizon_hours: int
    daily_vol_pct: float | None
    strategy_name: str
    version: str = PLAYBOOK_VERSION

    def apply(self, params: RealtimeParams) -> RealtimeParams:
        """Return params with this plan's behaviour substituted in.

        `replace` re-runs RealtimeParams.__post_init__, so an out-of-range plan fails
        loudly here rather than reaching the exchange.
        """
        return replace(
            params,
            allocation_fraction=self.allocation_fraction,
            stop_loss_fraction=self.stop_loss_fraction,
            trailing_stop_fraction=self.trailing_stop_fraction,
            trailing_activation_fraction=self.trailing_activation_fraction,
            risk_per_trade_fraction=self.risk_per_trade_fraction,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "regime": self.regime,
            "posture": self.posture,
            "strategy_name": self.strategy_name,
            "allocation_fraction": format(self.allocation_fraction, "f"),
            "stop_loss_fraction": format(self.stop_loss_fraction, "f"),
            "trailing_stop_fraction": format(self.trailing_stop_fraction, "f"),
            "trailing_activation_fraction": format(self.trailing_activation_fraction, "f"),
            "risk_per_trade_fraction": format(self.risk_per_trade_fraction, "f"),
            "horizon_hours": self.horizon_hours,
            "daily_vol_pct": self.daily_vol_pct,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ExecutionPlan:
        return cls(
            regime=int(raw["regime"]),
            posture=str(raw["posture"]),
            allocation_fraction=D(str(raw["allocation_fraction"])),
            stop_loss_fraction=D(str(raw["stop_loss_fraction"])),
            trailing_stop_fraction=D(str(raw["trailing_stop_fraction"])),
            trailing_activation_fraction=D(str(raw["trailing_activation_fraction"])),
            risk_per_trade_fraction=D(str(raw["risk_per_trade_fraction"])),
            horizon_hours=int(raw["horizon_hours"]),
            daily_vol_pct=(
                float(raw["daily_vol_pct"]) if raw.get("daily_vol_pct") is not None else None
            ),
            strategy_name=str(raw.get("strategy_name", "")),
            version=str(raw.get("version", PLAYBOOK_VERSION)),
        )


def strategy_for(regime: int | None) -> RegimeStrategy:
    """The regime's strategy, defaulting to the most cautious one.

    An unknown regime resolves to the deep-bear strategy rather than to a middle
    setting, because the cost of being cautious in a rising market is an opportunity
    and the cost of being loose in a falling one is capital.
    """
    if regime is None or regime not in PLAYBOOK:
        return PLAYBOOK[1]
    return PLAYBOOK[regime]


def resolve_plan(
    *,
    regime: int | None,
    posture: str,
    conviction: float,
    daily_vol_pct: float | None,
) -> ExecutionPlan:
    """Turn a qualitative choice into bounded, concrete execution parameters.

    Conviction scales the position inside the regime's range, which finally gives the
    declared conviction consequences. It was previously measured, calibrated and then
    ignored: the agent said 0.70 or 0.85 and the position was 95% either way.
    """
    strategy = strategy_for(regime)
    try:
        chosen = Posture(posture)
    except ValueError:
        chosen = Posture.NEUTRAL

    # Conviction moves size within a band around the regime's neutral allocation.
    # 0.5 conviction leaves it unchanged; 1.0 adds half again; 0.0 halves it.
    conviction_scale = D(str(0.5 + max(0.0, min(1.0, conviction))))
    allocation = strategy.allocation_at_neutral * _POSTURE_SIZE[chosen] * conviction_scale
    allocation = _clamp(allocation, MIN_ALLOCATION, MAX_ALLOCATION)

    vol = D(str(daily_vol_pct)) / D("100") if daily_vol_pct and daily_vol_pct > 0 else None
    if vol is None:
        # No volatility reading: fall back to the regime's neutral geometry expressed
        # against a 2% daily move, which is close to BTC's long-run average.
        vol = D("0.02")
    posture_stop = _POSTURE_STOP[chosen]
    stop = _clamp(strategy.stop_vol_multiple * vol * posture_stop, MIN_STOP_FRACTION, MAX_STOP_FRACTION)
    trail = _clamp(
        strategy.trail_vol_multiple * vol * posture_stop, MIN_TRAIL_FRACTION, MAX_TRAIL_FRACTION
    )
    activation = _clamp(
        strategy.trail_activation_vol_multiple * vol, MIN_TRAIL_FRACTION, MAX_TRAIL_FRACTION
    )
    risk = _clamp(strategy.risk_per_trade * _POSTURE_SIZE[chosen], MIN_RISK_FRACTION, MAX_RISK_FRACTION)

    return ExecutionPlan(
        regime=int(regime) if regime is not None else 1,
        posture=chosen.value,
        allocation_fraction=allocation,
        stop_loss_fraction=stop,
        trailing_stop_fraction=trail,
        trailing_activation_fraction=activation,
        risk_per_trade_fraction=risk,
        horizon_hours=strategy.horizon_hours,
        daily_vol_pct=daily_vol_pct,
        strategy_name=strategy.name,
    )


def resolve_exposure(
    *, regime: int | None, wants_invested: bool, conviction: float
) -> tuple[bool, bool]:
    """Apply the regime's burden of proof to a declared exposure.

    Returns (exposure to act on, whether the agent's own choice was honoured).

    This is where "the regime changes the strategy" becomes behaviour rather than
    parameters. The regime sets where capital sits by default; deviating from it
    requires conviction. Under the threshold the default stands, so uncertainty
    resolves toward the side the regime favours instead of toward inaction.

    The previous version gated only CHANGES and was therefore toothless: an agent
    already sitting in the wrong place never triggered a change, so its position was
    never tested against the threshold. On the most bullish 300-day window available it
    sat out a +185% advance while repeatedly declaring 0.50 conviction for cash in a
    strong uptrend, which was far below what that side required.

    The direction still comes from the model: the conviction is the model's, and the
    thresholds were fixed in advance per regime. What this removes is the ability to
    hold an unargued position by default.
    """
    strategy = strategy_for(regime)
    default_invested = strategy.default_exposure == EXPOSURE_INVESTED
    if wants_invested == default_invested:
        return wants_invested, True
    if conviction >= strategy.min_conviction_to_deviate:
        return wants_invested, True
    return default_invested, False


def render_playbook_block(regime: int | None, daily_vol_pct: float | None) -> str:
    """What the agent is told about the strategy it is operating inside."""
    strategy = strategy_for(regime)
    lines = [
        f"ESTRATEGIA DEL REGIMEN {regime if regime is not None else '?'} "
        f"({strategy.name}):",
        f"  {strategy.doctrine}",
        f"  horizonte previsto: {strategy.horizon_hours} h",
        f"  exposicion por defecto de este regimen: {strategy.default_exposure}",
        f"  conviccion minima para desviarse de ella: "
        f"{strategy.min_conviction_to_deviate:.2f}",
        "  Si no alcanzas esa conviccion se aplica la exposicion por defecto: la duda "
        "no te deja fuera, te deja donde el regimen manda.",
    ]
    for posture in Posture:
        plan = resolve_plan(
            regime=regime, posture=posture.value, conviction=0.5, daily_vol_pct=daily_vol_pct
        )
        lines.append(
            f"  postura {posture.value:<10} -> asignacion {plan.allocation_fraction * 100:.0f}%, "
            f"stop {plan.stop_loss_fraction * 100:.1f}%, "
            f"arrastre {plan.trailing_stop_fraction * 100:.1f}%"
        )
    lines.append(
        "  Eliges la POSTURA, no los numeros: se derivan de la volatilidad medida y "
        "de limites fijados de antemano."
    )
    return "\n".join(lines)


__all__ = [
    "MAX_ALLOCATION",
    "MAX_STOP_FRACTION",
    "MIN_ALLOCATION",
    "MIN_STOP_FRACTION",
    "PLAYBOOK",
    "PLAYBOOK_VERSION",
    "POSTURE_VALUES",
    "ExecutionPlan",
    "Posture",
    "RegimeStrategy",
    "render_playbook_block",
    "resolve_exposure",
    "resolve_plan",
    "strategy_for",
]
