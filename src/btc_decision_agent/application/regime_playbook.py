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
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from typing import Any

from btc_decision_agent.application.llm_tools import EXPOSURE_CASH, EXPOSURE_INVESTED
from btc_decision_agent.application.realtime_demo import RealtimeParams

D = Decimal

PLAYBOOK_VERSION = "regime-playbook/1.3.0"
"""1.1.0 puts the break-even ratchet under the playbook's control.

Until then `ExecutionPlan.apply` left `break_even_activation_fraction` and
`break_even_lock_fraction` at the engine defaults of 0.5% and 0.25%, so the per-regime
stop geometry this module computes was overridden on every trade that went green.
"""


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
MIN_BREAK_EVEN_ACTIVATION = D("0.02")
MAX_BREAK_EVEN_ACTIVATION = D("0.30")
MIN_BREAK_EVEN_LOCK = D("0.002")
MAX_BREAK_EVEN_LOCK = D("0.06")

LEGACY_BREAK_EVEN_ACTIVATION = D("0.005")
LEGACY_BREAK_EVEN_LOCK = D("0.0025")
"""The engine defaults that governed every exit before the playbook owned this.

They are kept only so a plan persisted by an older build keeps the geometry its open
position was opened under. Changing the stop rule underneath a live position is the
failure this class was written to prevent, so a legacy plan keeps legacy behaviour and
only new plans get the regime's own break-even geometry.
"""


@dataclass(frozen=True)
class RegimeStrategy:
    """One regime's strategy, including the parameters of its own behaviour."""

    name: str
    allocation_at_neutral: Decimal
    """Share of available cash deployed at NEUTRAL posture and average conviction."""

    stop_vol_multiple: Decimal
    """Initial stop distance in multiples of 30-day daily volatility."""

    trail_vol_multiple: Decimal
    """Trailing distance behind the high, in multiples of HORIZON volatility.

    Horizon, not daily. This is a unit correction, not a tuning: the multiples below are
    unchanged. A strategy declares how long it means to hold, and then measured its exit
    threshold against a single day's volatility, so the exit rule knew nothing about the
    horizon it was supposed to protect. 2.8 sigma means one thing over 24 hours and
    something entirely different over 168.

    Scaled by sqrt(horizon / 24 h), the leash matches the give-back a position must
    tolerate to survive the holding period the regime asked for. For the deep bear, whose
    horizon is 24 hours, the scaling factor is exactly 1 and nothing changes, which is the
    check that this follows from the horizons rather than from a window's returns.

    Measured on 60 replayed bull-window decisions, the daily-scaled leash was the binding
    constraint once the break-even floor was fixed: 19 stop exits on 17 entries, a position
    open in 50.6% of hours, +13.21%. Removing the trailing stop while KEEPING the initial
    protective stop gave +48.76% with 2 stop exits and 89.9% of hours invested. Removing
    the stop entirely gave +46.27%, so the initial stop earns its place and the trailing
    stop was costing 35 points. On the falling window the same change is neutral, +0.3.

    The initial stop stays on DAILY volatility deliberately. It answers how wrong the
    thesis can be before it is abandoned, which is a per-trade risk statement and is what
    the position size is derived from. The trail answers how much give-back to tolerate
    while holding to a horizon, which is horizon-relative by nature.
    """

    trail_activation_vol_multiple: Decimal
    """How far in profit before the trail engages, also in HORIZON volatility multiples."""

    break_even_activation_vol_multiple: Decimal
    """Profit, in volatility multiples, before the stop ratchets up to break even.

    This exists because leaving it out silently overrode everything else here. The engine
    defaults were 0.5% to activate and a floor at 0.25% above entry, and
    `ExecutionPlan.apply` substituted the allocation, the stop, the trailing stop, the
    trailing activation and the risk budget but not these two. So every regime and every
    posture inherited a quarter-percent leash the moment a trade went 0.5% green.

    BTC covers 0.5% in an hour routinely. Measured on 100 replayed decisions the effect
    was not marginal: it fired on half of all exits, and pushing it out of reach cut stop
    exits from 10 to 5 and raised the time actually holding a position by 70%. It also
    pre-empted the trailing stop completely, which is why disabling the trailing stop
    changed nothing at all: at 0.5% the break-even floor engaged long before the trailing
    stop's 2 to 3% activation, so the trailing geometry the playbook computed per regime
    was dead code.

    The regime 3 doctrine shown to the agent promises a wide stop so noise cannot shake it
    out of a trend it intends to hold for 168 hours. The engine had it on a 0.25% leash.
    """

    break_even_lock_vol_multiple: Decimal
    """Where the floor sits above entry once the ratchet engages, in volatility multiples.

    Bound by an invariant rather than chosen freely: the floor may never be tighter than
    the trailing stop already is at the moment the ratchet engages. Otherwise the ratchet
    becomes the exposure policy again, just at a different number.
    """

    risk_per_trade: Decimal
    """CEILING on the share of equity this regime will risk to its stop, not a target.

    It used to be a target, and that made it a second, hidden allocation policy. Sizing is
    `min(cash * allocation, equity * risk / stop)`, so with three independent knobs for two
    degrees of freedom the smaller one silently won. And because the ceiling was a fixed
    fraction of equity while the stop scales with volatility, the ratio `risk / stop` FELL
    as volatility rose. It cut the position hardest exactly when volatility expanded, which
    in a strong advance is most of the way up.

    Measured on the bull window run, in 11 of 60 decisions the cap overrode the regime's
    declared allocation, and not marginally: on day 1550 regime 2 asked for 75% and the cap
    delivered 35%, on day 1555 regime 3 asked for 90% and got 66%. Averaged over its 19
    decisions regime 2 targeted 34.5% against a declared allocation of 65 to 75%.

    Now the risk actually taken is derived, `allocation * stop`, which is simply the
    arithmetic truth of what a position loses at its stop. This value is the ceiling, and
    when it binds the ALLOCATION is reduced explicitly so the two agree, instead of letting
    the sizing formula quietly pick the smaller number.

    Each regime's ceiling is set by one rule rather than chosen per regime: what its own
    declared allocation and stop imply at twice typical volatility, that is 4% daily,
    bounded by MAX_RISK_FRACTION. So it does not bind in ordinary conditions and does bind
    in violent ones, which is what a ceiling is for.
    """

    horizon_hours: int
    """Intended holding period. Two things read it, and for a while neither did.

    It scales the trailing leash, so the exit rule tolerates the give-back a position must
    survive to reach this horizon. See trail_vol_multiple.

    And it is the horizon each decision's outcome is measured over in AgentMemory, so the
    record judges a trend-following decision on a trend's timescale rather than on
    tomorrow's noise. That second claim sat in this docstring while nothing implemented it:
    the memory used one fixed horizon, 24 hours in production, for every regime. A decision
    meant to hold for 168 hours was therefore scored by the next day's price, and at a one
    day horizon BTC after costs is close to a coin flip, so the agent's own measured record
    told it that being invested does not pay. It reads those statistics in its prompt, which
    is a direct route from a mismeasured outcome to systematic caution.
    """

    default_exposure: str
    """Where capital normally sits in this regime. DOCTRINE, not a control.

    It is shown to the agent as part of the regime's description and it no longer
    overrides the agent's choice. It used to: a conviction threshold let the regime
    reverse the direction the agent had asked for, and measured on the same 60 recorded
    decisions that override cost 39 points, +60.65% against +99.70% without it, while
    also nearly doubling the number of round trips, 14 against 27.

    That override was mine, added when the agent was OBSERVED sitting out a +185%
    advance at 0.50 conviction. The observation was real and the diagnosis was wrong:
    that run had a break-even ratchet liquidating every position that went 0.5% green
    and a memory scoring 168 hour decisions on tomorrow's price. The agent's preference
    for cash was partly a rational response to an execution layer that could not hold a
    position and to a record that told it holding did not pay. With those fixed its
    direction calls carry signal: decisions at 0.70 conviction or more returned +1.86%
    per interval against +0.27% below 0.60, an effect of 1.7 standard errors.

    So the division of labour is now explicit. The agent decides WHETHER to be invested.
    The regime decides HOW MUCH, WITH WHAT STOP and FOR HOW LONG. That is what makes
    full direction authority safe rather than reckless: in a deep bear the agent may say
    invested and it gets 20% of capital behind a 1.6 sigma stop, because the magnitudes
    were never the part the agent was good at."""

    doctrine: str
    """One line shown to the agent, so it knows the strategy it is operating inside."""


PLAYBOOK: dict[int, RegimeStrategy] = {
    0: RegimeStrategy(
        name="recuperacion lateral",
        allocation_at_neutral=D("0.45"),
        stop_vol_multiple=D("2.0"),
        trail_vol_multiple=D("1.6"),
        trail_activation_vol_multiple=D("1.0"),
        break_even_activation_vol_multiple=D("2.6"),
        break_even_lock_vol_multiple=D("0.5"),
        risk_per_trade=D("0.036"),
        horizon_hours=48,
        default_exposure=EXPOSURE_CASH,
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
        break_even_activation_vol_multiple=D("2.0"),
        break_even_lock_vol_multiple=D("0.4"),
        risk_per_trade=D("0.013"),
        horizon_hours=24,
        default_exposure=EXPOSURE_CASH,
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
        break_even_activation_vol_multiple=D("3.2"),
        break_even_lock_vol_multiple=D("0.6"),
        risk_per_trade=D("0.065"),
        horizon_hours=96,
        default_exposure=EXPOSURE_INVESTED,
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
        break_even_activation_vol_multiple=D("4.3"),
        break_even_lock_vol_multiple=D("0.8"),
        risk_per_trade=D("0.12"),
        horizon_hours=168,
        default_exposure=EXPOSURE_INVESTED,
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


def _horizon_scale(horizon_hours: int) -> Decimal:
    """sqrt(horizon / one day). Converts a daily volatility into a horizon volatility.

    Random walk scaling. One day returns 1, so a strategy whose horizon is a single day is
    unaffected and the change is confined to the regimes that actually declare a longer
    holding period.
    """
    if horizon_hours <= 24:
        return D("1")
    return (D(horizon_hours) / D("24")).sqrt()


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
    break_even_activation_fraction: Decimal
    break_even_lock_fraction: Decimal
    risk_per_trade_fraction: Decimal
    horizon_hours: int
    daily_vol_pct: float | None
    strategy_name: str
    version: str = PLAYBOOK_VERSION

    def apply(self, params: RealtimeParams) -> RealtimeParams:
        """Return params with this plan's behaviour substituted in.

        `replace` re-runs RealtimeParams.__post_init__, so an out-of-range plan fails
        loudly here rather than reaching the exchange.

        Every field `_active_stop` reads must be listed here. The break-even pair was
        missing and that single omission overrode the whole playbook: the regime's stop
        geometry was computed, persisted and displayed while a hard-coded 0.25% floor
        decided the actual exits.
        """
        return replace(
            params,
            allocation_fraction=self.allocation_fraction,
            stop_loss_fraction=self.stop_loss_fraction,
            trailing_stop_fraction=self.trailing_stop_fraction,
            trailing_activation_fraction=self.trailing_activation_fraction,
            break_even_activation_fraction=self.break_even_activation_fraction,
            break_even_lock_fraction=self.break_even_lock_fraction,
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
            "break_even_activation_fraction": format(self.break_even_activation_fraction, "f"),
            "break_even_lock_fraction": format(self.break_even_lock_fraction, "f"),
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
            # A plan persisted before the playbook owned the break-even ratchet keeps the
            # geometry its position was opened under. Loosening a stop underneath an open
            # position is the one direction of surprise that costs capital rather than
            # opportunity, so absence resolves to the legacy values, not to the new ones.
            break_even_activation_fraction=D(
                str(raw.get("break_even_activation_fraction", LEGACY_BREAK_EVEN_ACTIVATION))
            ),
            break_even_lock_fraction=D(
                str(raw.get("break_even_lock_fraction", LEGACY_BREAK_EVEN_LOCK))
            ),
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
    # The trail is measured against the volatility of the HOLDING PERIOD, not of one day.
    # sqrt of time, so a 168 hour horizon widens the leash by sqrt(7). See
    # RegimeStrategy.trail_vol_multiple: measured on the bull window, the daily-scaled
    # leash was exiting every position on ordinary pullbacks and costing 35 points.
    horizon_vol = vol * _horizon_scale(strategy.horizon_hours)
    trail = _clamp(
        strategy.trail_vol_multiple * horizon_vol * posture_stop,
        MIN_TRAIL_FRACTION,
        MAX_TRAIL_FRACTION,
    )
    activation = _clamp(
        strategy.trail_activation_vol_multiple * horizon_vol, MIN_TRAIL_FRACTION, MAX_TRAIL_FRACTION
    )
    # The risk actually taken is DERIVED from the allocation and the stop, because
    # `allocation * stop` is simply what the position loses if the stop fills. The regime's
    # risk_per_trade is a ceiling on that, and when it binds the allocation comes down
    # explicitly so the two agree. Previously the two disagreed and sizing silently used
    # `min(allocation, risk / stop)`, which cut the position hardest when volatility was
    # highest. See RegimeStrategy.risk_per_trade.
    ceiling = _clamp(
        strategy.risk_per_trade * _POSTURE_SIZE[chosen], MIN_RISK_FRACTION, MAX_RISK_FRACTION
    )
    if allocation * stop > ceiling:
        # No MIN_ALLOCATION floor on this path, deliberately. A property test found the
        # floor overriding the ceiling: a deep bear at 12% daily volatility needs a 14.4%
        # stop, which at the regime's 0.72% risk ceiling allows a 5% position, and forcing
        # it up to the 10% floor doubled the risk past what the regime permits. A floor on
        # position size exists to avoid dust, and dust is already handled by the exchange's
        # minimum notional in plan_adjustment. Between a floor on size and a ceiling on
        # risk, the ceiling wins.
        allocation = min(MAX_ALLOCATION, ceiling / stop)
    # min() rather than the product alone: ceiling / stop * stop leaves a rounding residue
    # in Decimal, and a ceiling that is exceeded by one unit in the last place is still a
    # ceiling that is exceeded.
    risk = _clamp(min(ceiling, allocation * stop), MIN_RISK_FRACTION, MAX_RISK_FRACTION)

    # The break-even ratchet scales with posture like the stop and the trail do, so an
    # aggressive posture pushes the floor further out rather than keeping a scalper's leash
    # on a trend trade.
    break_even_activation = _clamp(
        strategy.break_even_activation_vol_multiple * vol * posture_stop,
        MIN_BREAK_EVEN_ACTIVATION,
        MAX_BREAK_EVEN_ACTIVATION,
    )
    break_even_lock = _clamp(
        strategy.break_even_lock_vol_multiple * vol * posture_stop,
        MIN_BREAK_EVEN_LOCK,
        MAX_BREAK_EVEN_LOCK,
    )
    # The invariant. At the moment the ratchet engages the high sits at
    # entry * (1 + activation), so the trailing stop is already at
    # entry * (1 + activation) * (1 - trail). A floor above that level would be TIGHTER
    # than the trail, which is how a 0.25% floor came to govern a strategy that advertised
    # a 5% stop. Computed from the clamped numbers rather than the multiples, because it is
    # clamping that breaks the relationship the multiples were chosen to satisfy.
    floor_ceiling = (D("1") + break_even_activation) * (D("1") - trail) - D("1")
    if floor_ceiling < MIN_BREAK_EVEN_LOCK:
        # No floor can sit below the trail here. Push the ratchet out of reach and let the
        # trailing stop do the job alone rather than silently tighten the leash.
        break_even_activation = MAX_BREAK_EVEN_ACTIVATION
        break_even_lock = MIN_BREAK_EVEN_LOCK
    else:
        break_even_lock = min(break_even_lock, floor_ceiling)

    return ExecutionPlan(
        regime=int(regime) if regime is not None else 1,
        posture=chosen.value,
        allocation_fraction=allocation,
        stop_loss_fraction=stop,
        trailing_stop_fraction=trail,
        trailing_activation_fraction=activation,
        break_even_activation_fraction=break_even_activation,
        break_even_lock_fraction=break_even_lock,
        risk_per_trade_fraction=risk,
        horizon_hours=strategy.horizon_hours,
        daily_vol_pct=daily_vol_pct,
        strategy_name=strategy.name,
    )


@dataclass(frozen=True)
class RegimeTracker:
    """The regime in force, which a new label has to earn before it replaces it.

    Why this exists
    ---------------
    The burden of proof hangs off a regime label, and the label is not stable. Measured on
    300 days at a 5 day step it changed on 37% of transitions, and 31% of transitions
    INVERTED the default exposure, because regime 0 defaults to cash and regime 3 defaults
    to invested and the sequence alternates between them.

    The consequence was round trips nobody chose. Of 15 direction changes in that run, 9
    were imposed by the playbook AGAINST what the agent asked for: it wanted to be invested
    in regime 0 on 12 of 17 decisions and was forced to cash on 8 of them, then forced back
    in when the label returned to 3. The agent and the playbook were fighting, and an
    oscillating label turned the disagreement into commission.

    The rule
    --------
    A new label is provisional until it has persisted for at least the HORIZON OF THE
    STRATEGY IT WOULD REPLACE. Nothing here is fitted: the horizons are the ones each
    strategy already declares, and the principle is that a strategy is not abandoned faster
    than it said it meant to hold. Leaving the deep bear, whose horizon is 24 hours, takes
    one observation. Leaving an established trend, whose horizon is 168 hours, takes a
    week's worth.

    What it does NOT delay
    ----------------------
    The protective stop, the trailing stop and the circuit breakers are untouched and still
    fire intraday. The agent can still choose cash on its own conviction at any moment. What
    has to wait is only the MECHANICAL default flip, which is the part that carried no
    judgement and generated the churn.

    Measured on the one window where the re-resolution could be validated against the
    recorded run, it is worth +29.5 points and REDUCES the number of changes, so it is not
    a return-for-churn trade. That is a single window and the argument above is what carries
    it; the holdout is what will test it.
    """

    regime: int
    """The regime whose strategy is in force."""

    since: datetime | None = None
    """When it took effect. None before the first observation."""

    pending: int | None = None
    """A different label seen recently, not yet in force."""

    pending_since: datetime | None = None

    def observe(self, label: int | None, at: datetime) -> RegimeTracker:
        """Fold in one observation and return the tracker that results."""
        observed = label if label is not None and label in PLAYBOOK else self.regime
        if self.since is None:
            return RegimeTracker(regime=observed, since=at)
        if observed == self.regime:
            return RegimeTracker(regime=self.regime, since=self.since)
        if observed != self.pending:
            return RegimeTracker(
                regime=self.regime, since=self.since, pending=observed, pending_since=at
            )
        assert self.pending_since is not None
        required = timedelta(hours=strategy_for(self.regime).horizon_hours)
        if at - self.pending_since >= required:
            return RegimeTracker(regime=observed, since=at)
        return RegimeTracker(
            regime=self.regime,
            since=self.since,
            pending=self.pending,
            pending_since=self.pending_since,
        )

    def to_dict(self) -> dict[str, Any]:
        def stamp(value: datetime | None) -> str | None:
            return value.isoformat() if value is not None else None

        return {
            "regime": self.regime,
            "since": stamp(self.since),
            "pending": self.pending,
            "pending_since": stamp(self.pending_since),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> RegimeTracker:
        if not raw:
            return cls(regime=1)

        def stamp(key: str) -> datetime | None:
            value = raw.get(key)
            return datetime.fromisoformat(str(value)) if value else None

        return cls(
            regime=int(raw.get("regime", 1)),
            since=stamp("since"),
            pending=(int(raw["pending"]) if raw.get("pending") is not None else None),
            pending_since=stamp("pending_since"),
        )


def resolve_target_allocation(
    *,
    regime: int | None,
    wants_invested: bool,
    conviction: float,
    allocation: Decimal,
) -> tuple[Decimal, Decimal]:
    """The share of equity to hold, expressing any disagreement as SIZE, not direction.

    Returns (target share of equity, weight the agent's view carried).

    Why this shape
    --------------
    Two previous attempts both failed, in opposite directions, and the failure was the same
    each time: a binary answer to a question that is not binary.

    The first let the regime REVERSE the agent's direction when conviction fell below a
    per-regime threshold. On one set of 60 recorded decisions that cost 39 points and nearly
    doubled the round trips, because 9 of 15 direction changes were the playbook and the
    agent overruling each other through an oscillating label.

    So it was removed, and the run that followed came in WORSE. Replaying that run's
    decisions with the override restored gives +90.93% against +61.18%: on a cautious agent
    the override destroyed value by forcing it out of positions, and on a confident agent it
    created value by keeping it in. The sign of the rule depends on the behaviour of the
    agent, which means neither answer generalises and choosing between them on one window is
    fitting to that window.

    The blend
    ---------
    On agreement, nothing happens: the agent's direction is executed at the plan's size.

    On disagreement the two are mixed, and the agent's weight is its own stated departure
    from indifference: `2 * |conviction - 0.5|`. There is no new parameter to choose. At 0.50
    the agent has said it does not know, so the regime's default stands. At 1.0 the agent
    carries it entirely. At 0.75 they split.

    What this buys, beyond not having to pick a side: a disagreement now costs a TRIM instead
    of a round trip. When the regime label flips under an agent asking to stay invested at
    0.85 conviction, the target moves from 90% to 63% rather than from 90% to 0%, so the same
    disagreement pays a quarter of the commission. The round trips were the original
    complaint about the override, and this removes the mechanism that produced them rather
    than removing the regime's voice.

    It also cannot be worse than both extremes at once: every target it produces lies between
    what the agent asked for and what the regime would have imposed.
    """
    strategy = strategy_for(regime)
    default_invested = strategy.default_exposure == EXPOSURE_INVESTED
    agent_target = allocation if wants_invested else D("0")
    if wants_invested == default_invested:
        return agent_target, D("1")
    regime_target = allocation if default_invested else D("0")
    # Not abs(): a conviction BELOW indifference must carry no weight, not the same weight
    # as the mirror value above it. The first version used abs() and gave 0.40 the same
    # 0.20 weight as 0.60, which would let a model that is less than half convinced of its
    # own call move the book as much as one that is more. Values under 0.5 appear in the
    # record (0.30, 0.40, 0.45), so this is a case that occurs rather than a hypothetical.
    weight = _clamp(D("2") * (D(str(conviction)) - D("0.5")), D("0"), D("1"))
    return agent_target * weight + regime_target * (D("1") - weight), weight


def render_playbook_block(regime: int | None, daily_vol_pct: float | None) -> str:
    """What the agent is told about the strategy it is operating inside."""
    strategy = strategy_for(regime)
    lines = [
        f"ESTRATEGIA DEL REGIMEN {regime if regime is not None else '?'} "
        f"({strategy.name}):",
        f"  {strategy.doctrine}",
        f"  horizonte previsto: {strategy.horizon_hours} h. Tu decision se juzgara por lo "
        f"que pase en esas {strategy.horizon_hours} h, no por lo que pase manana.",
        f"  lo habitual en este regimen: {strategy.default_exposure}",
        "  LA DIRECCION LA DECIDES TU y nada la invierte. El regimen decide el tamano, el "
        "stop y el horizonte.",
        "  Si tu direccion contradice lo habitual del regimen, la posicion queda a medio "
        "camino y tu conviccion decide cuanto pesa tu criterio: 0.50 cede al regimen, 1.00 "
        "manda del todo, 0.75 reparte. Contradecir al regimen sin conviccion te deja donde "
        "el regimen, no donde tu dijiste.",
    ]
    for posture in Posture:
        plan = resolve_plan(
            regime=regime, posture=posture.value, conviction=0.5, daily_vol_pct=daily_vol_pct
        )
        lines.append(
            f"  postura {posture.value:<10} -> asignacion {plan.allocation_fraction * 100:.0f}%, "
            f"stop {plan.stop_loss_fraction * 100:.1f}%, "
            f"arrastre {plan.trailing_stop_fraction * 100:.1f}% "
            f"(activa en +{plan.trailing_activation_fraction * 100:.1f}%), "
            f"piso en +{plan.break_even_lock_fraction * 100:.1f}% "
            f"tras +{plan.break_even_activation_fraction * 100:.1f}%"
        )
    lines.append(
        "  Eliges la DIRECCION y la POSTURA, no los numeros: se derivan de la "
        "volatilidad medida y de limites fijados de antemano."
    )
    return "\n".join(lines)


__all__ = [
    "DEAD_BAND",
    "LEGACY_BREAK_EVEN_ACTIVATION",
    "LEGACY_BREAK_EVEN_LOCK",
    "MAX_ALLOCATION",
    "MAX_BREAK_EVEN_ACTIVATION",
    "MAX_BREAK_EVEN_LOCK",
    "MAX_STOP_FRACTION",
    "MIN_ALLOCATION",
    "MIN_BREAK_EVEN_ACTIVATION",
    "MIN_BREAK_EVEN_LOCK",
    "MIN_STOP_FRACTION",
    "PLAYBOOK",
    "PLAYBOOK_VERSION",
    "POSTURE_VALUES",
    "ExecutionPlan",
    "ExposureAdjustment",
    "Posture",
    "RegimeStrategy",
    "RegimeTracker",
    "plan_adjustment",
    "render_playbook_block",
    "resolve_plan",
    "resolve_target_allocation",
    "strategy_for",
]


DEAD_BAND = D("0.15")
"""How far the position may drift from its target before it is worth adjusting.

Expressed in fractions of equity, so 0.15 is fifteen percentage points of exposure.

Derived from the measured noise in the target rather than picked. Over 98 replayed
decisions the posture changed on 49% of them, and adjacent postures differ by roughly
45 percentage points of allocation in the bull regime (50% defensive against 95%
aggressive). A 15 point band therefore absorbs the flicker that comes from conviction
wobbling inside one posture, while a genuine change of posture still moves the book.

It is a judgement and it is the parameter to watch: too narrow and the agent churns,
too wide and it never reaches its target. The gate already caps the switch rate at 30%,
so the churn side is measured rather than assumed.
"""


@dataclass(frozen=True)
class ExposureAdjustment:
    """What to do to bring the book to the plan's target exposure."""

    action: str
    """COMPRAR, VENDER or MANTENER."""

    quote_usdt: Decimal
    """Notional to buy. Zero unless action is COMPRAR."""

    base_qty: Decimal
    """Base quantity to sell. Zero unless action is VENDER."""

    current_share: Decimal
    target_share: Decimal
    reason: str

    @property
    def acts(self) -> bool:
        return self.action != "MANTENER"


def plan_adjustment(
    *,
    target_allocation: Decimal,
    btc_qty: Decimal,
    price: Decimal,
    usdt_free: Decimal,
    risk_per_trade_fraction: Decimal,
    stop_loss_fraction: Decimal,
    min_notional: Decimal,
    base_step: Decimal,
    dead_band: Decimal = DEAD_BAND,
) -> ExposureAdjustment:
    """Bring exposure to its target, scaling up or down rather than only on or off.

    This exists because of a measured failure, not a preference. Over 98 replayed
    decisions the agent entered while cautious (79% of entries were DEFENSIVA, which
    halves the position) and then turned aggressive while already holding (58% of
    holding decisions were AGRESIVA, asking for 95%). There were ZERO scaling orders in
    the whole run, because the only paths available were open-from-flat and close-to-
    zero. Participation froze at the size chosen in the moment of greatest doubt, which
    is the worst possible moment to freeze it, and the run captured +27.6% of a +184%
    advance.

    The target is a share of EQUITY, not of free cash. Asking for "95%" is only
    well defined against equity once a position already exists; against free cash it
    would mean something different at every moment. When the book is flat the two
    coincide, so entry sizing is unchanged.

    The risk cap still binds: a target is never larger than the loss budget divided by
    the stop distance, which is what keeps a wide stop from quietly becoming a large bet.
    """
    equity = usdt_free + btc_qty * price
    if equity <= 0 or price <= 0:
        return ExposureAdjustment(
            "MANTENER", D("0"), D("0"), D("0"), D("0"), "sin capital valorable"
        )

    capped = target_allocation
    if stop_loss_fraction > 0:
        by_risk = risk_per_trade_fraction / stop_loss_fraction
        capped = min(capped, by_risk)
    capped = max(D("0"), min(D("1"), capped))

    current_share = (btc_qty * price) / equity
    gap = capped - current_share

    # Opening and fully closing are changes of state, not drift, so the dead band does
    # not apply to them. Without this exemption a risk-capped target smaller than the
    # band could never be reached at all: a 10% target with a 15 point band left the
    # agent permanently flat, which a test caught before it ever ran.
    opening = current_share <= D("0.01") and capped > D("0")
    closing = capped <= D("0") and current_share > D("0")
    if not opening and not closing and abs(gap) < dead_band:
        return ExposureAdjustment(
            "MANTENER",
            D("0"),
            D("0"),
            current_share,
            capped,
            f"desvio {gap * 100:+.1f}pp dentro de la banda de {dead_band * 100:.0f}pp",
        )

    if gap > 0:
        quote = min(gap * equity, usdt_free).quantize(D("0.01"), rounding=ROUND_DOWN)
        if quote < min_notional:
            return ExposureAdjustment(
                "MANTENER",
                D("0"),
                D("0"),
                current_share,
                capped,
                f"ampliacion de {quote} por debajo del minimo nocional {min_notional}",
            )
        return ExposureAdjustment(
            "COMPRAR",
            quote,
            D("0"),
            current_share,
            capped,
            f"ampliar {gap * 100:+.1f}pp hasta {capped * 100:.0f}%",
        )

    # Reducing. Selling the whole position is left to the exposure decision itself; this
    # only trims the excess, so a target of zero still arrives here as a full exit.
    excess_value = (-gap) * equity
    raw_qty = min(excess_value / price, btc_qty)
    qty = (raw_qty / base_step).to_integral_value(rounding=ROUND_DOWN) * base_step
    if qty <= 0 or qty * price < min_notional:
        return ExposureAdjustment(
            "MANTENER",
            D("0"),
            D("0"),
            current_share,
            capped,
            f"reduccion de {qty} por debajo del minimo nocional",
        )
    return ExposureAdjustment(
        "VENDER",
        D("0"),
        qty,
        current_share,
        capped,
        f"reducir {gap * 100:+.1f}pp hasta {capped * 100:.0f}%",
    )
