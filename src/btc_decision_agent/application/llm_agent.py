"""The LLM agent that operates the account, and the engine that lets it.

The agent is a local Qwen3-30B-A3B model reached over Ollama on loopback. It reads a
fully computed state block, reasons, and chooses what the exposure SHOULD be. The
order is derived from that choice, never asked for directly.

Four design decisions here came out of measurement, not preference:

Target exposure, not an action
    Asking the model to pick BUY/HOLD/SELL produced a systematic bias toward
    inaction: flat in a strong uptrend, with every historical analogue showing
    +19% to +28%, it answered HOLD, which while flat means never entering. Asking
    instead what the exposure should be removes the option of doing nothing from
    the answer space, and the same four scenarios then scored 4/4.

One round with precomputed state
    Letting the model discover the state through successive tool calls cost 714
    seconds per decision because every round re-processes a growing context. All of
    our tools are cheap local computations, so the state is computed up front and
    the decision takes ~45 seconds.

Schema-forced output
    Ollama's `format` guarantees the shape of the reply. It does not guarantee the
    model finishes, so the token budget is generous and a truncated reply is treated
    as a failure rather than parsed optimistically.

Think hard only before spending money
    Full reasoning costs 333 seconds against 45. So routine cycles run without it,
    and when the cheap pass wants to CHANGE exposure the decision is re-taken with
    reasoning enabled before any order is placed.

Safety posture: if the model is slow, unreachable, or returns something incoherent,
the agent does not guess and the system does not go unprotected. It falls back to
the quantitative policy that was walk-forward validated on five years. An LLM
outage must never mean an unmanaged position.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from btc_decision_agent.application.exposure_agent import (
    ACTIONS,
    ExposureAction,
    PolicyDecision,
    PortfolioState,
    RegimeMixturePolicy,
    TradeDecision,
    compose_features,
    decision_for,
)
from btc_decision_agent.application.exposure_features import MIN_DAILY_HISTORY
from btc_decision_agent.application.llm_memory import AgentMemory, render_memory_block
from btc_decision_agent.application.llm_tools import (
    EXPOSURE_CASH,
    EXPOSURE_INVESTED,
    EXPOSURE_VALUES,
    HistoryIndex,
    cost_view,
    market_view,
    position_view,
    quant_view,
    render_state_block,
)
from btc_decision_agent.application.realtime_demo import (
    EvidenceSnapshot,
    ProtectiveDecisionEngine,
    RealtimeDecision,
    RealtimeParams,
    ReconciledPosition,
)
from btc_decision_agent.application.regime_playbook import (
    POSTURE_VALUES,
    Posture,
    render_playbook_block,
    resolve_exposure,
    resolve_plan,
)
from btc_decision_agent.domain.contracts import Action, PositionState

_LOGGER = logging.getLogger(__name__)
D = Decimal

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen3:30b-a3b"
AGENT_VERSION = "LLM-EXPOSURE-AGENT-V1"

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "exposicion_objetivo": {"type": "string", "enum": list(EXPOSURE_VALUES)},
        "postura": {"type": "string", "enum": list(POSTURE_VALUES)},
        "conviccion": {"type": "number"},
        "movimiento_esperado_pct": {"type": "number"},
        "razon": {"type": "string"},
    },
    "required": [
        "exposicion_objetivo",
        "postura",
        "conviccion",
        "movimiento_esperado_pct",
        "razon",
    ],
}

SYSTEM_PROMPT = """Eres el operador de una cuenta BTC/USDT en Binance. Tu mision es
obtener la maxima rentabilidad neta posible a lo largo del tiempo.

No eliges una orden. Eliges dos cosas, evaluadas desde cero:

1) La EXPOSICION que debe haber ahora:
  INVERTIDO = el capital debe estar en BTC
  EN LIQUIDEZ = el capital debe estar en USDT

2) La POSTURA con la que ejecutar la estrategia de tu regimen:
  DEFENSIVA = menos capital, stop mas ceñido
  NEUTRAL   = la estrategia del regimen tal cual
  AGRESIVA  = mas capital, stop mas ancho para no salir por ruido

No declaras numeros de tamano ni de stop: salen de la volatilidad medida y de limites
fijados de antemano. Cada regimen tiene su propia estrategia y su propia carga de la
prueba, y las veras en el bloque ESTRATEGIA DEL REGIMEN. Leelas antes de decidir.
El sistema comparara tu eleccion con la exposicion actual y derivara la orden.

Como decidir:
1. BTC tiene deriva positiva de largo plazo. Estar EN LIQUIDEZ renuncia a esa
   deriva, asi que EN LIQUIDEZ debe justificarse con evidencia. No es el default
   seguro. En regimen alcista fuerte esto se endurece: quedarse fuera de una
   tendencia establecida es una decision costosa y necesita mas conviccion que
   entrar.
2. Estar INVERTIDO durante una caida sostenida destruye capital. INVERTIDO tambien
   se justifica con evidencia.
3. Declara en movimiento_esperado_pct cuanto crees que se movera el precio a tu favor
   en los proximos dias. Se realista: una cifra inflada no desbloquea nada porque se
   acota contra la volatilidad observada, y queda registrada para medir tu
   calibracion.
   ENTRAR cuesta comision: si el movimiento esperado no cubre el costo de ida y
   vuelta, entrar destruye valor aunque tu direccion sea correcta.
   SALIR no se bloquea por costo. Dejar de estar expuesto no es una apuesta que deba
   cubrir comision, es dejar de sostener una. Si crees que debes estar EN LIQUIDEZ,
   dilo sin preocuparte por la comision.
4. Compara los analogos historicos contra el base rate. Si los analogos rinden como
   el promedio de 5 anos, no hay senal: no es razon para actuar.
5. Solo trata como regla lo que tu historial medido marque CON RESPALDO. Lo marcado
   NO CONCLUYENTE es ruido todavia.
6. Si tu calibracion muestra que aciertas menos de lo que declaras, baja tu
   conviccion y exige mas evidencia antes de cambiar.
7. Cita numeros concretos del estado en tu razon. No inventes cifras.

Todos los numeros del estado ya estan calculados a partir de datos reales. No
recalcules, no estimes: usalos."""


class LLMUnavailable(Exception):
    """The model could not be reached, timed out, or replied incoherently."""


@dataclass(frozen=True)
class AgentVerdict:
    target_exposure: str
    posture: str
    conviction: float
    expected_move_pct: float
    reason: str
    thinking: str
    seconds: float
    deliberated: bool

    @property
    def wants_long(self) -> bool:
        return self.target_exposure == EXPOSURE_INVESTED


class OllamaClient:
    """Minimal loopback client. No third party ever sees this account's state."""

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        *,
        timeout_s: float = 600.0,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout_s = timeout_s

    def verdict(self, state_block: str, *, think: bool, num_predict: int = 900) -> AgentVerdict:
        body = {
            "model": self.model,
            "stream": False,
            "think": think,
            "format": VERDICT_SCHEMA,
            "options": {"temperature": 0, "num_predict": num_predict},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": state_block + "\n\nCual debe ser la exposicion ahora?",
                },
            ],
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        started = datetime.now(tz=UTC)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise LLMUnavailable(f"modelo inalcanzable: {error!r}") from error
        except json.JSONDecodeError as error:
            raise LLMUnavailable(f"respuesta no es JSON: {error}") from error

        seconds = (datetime.now(tz=UTC) - started).total_seconds()
        message = payload.get("message") or {}
        content = (message.get("content") or "").strip()
        if payload.get("done_reason") == "length" and not content:
            raise LLMUnavailable("respuesta truncada por limite de tokens")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            raise LLMUnavailable(f"JSON invalido: {error}; contenido={content[:200]!r}") from error

        target = str(parsed.get("exposicion_objetivo", "")).upper()
        if target not in set(EXPOSURE_VALUES):
            raise LLMUnavailable(f"exposicion_objetivo invalida: {target!r}")
        posture = str(parsed.get("postura", "")).upper()
        if posture not in set(POSTURE_VALUES):
            # Degraded rather than rejected: an unknown posture is a formatting slip,
            # not a reason to hand the account to the fallback. The exposure, which is
            # the decision that moves money, was valid.
            posture = Posture.NEUTRAL.value
        try:
            conviction = float(parsed.get("conviccion", 0.0))
            expected = float(parsed.get("movimiento_esperado_pct", 0.0))
        except (TypeError, ValueError) as error:
            raise LLMUnavailable(f"campos numericos invalidos: {error}") from error

        return AgentVerdict(
            target_exposure=target,
            posture=posture,
            conviction=max(0.0, min(1.0, conviction)),
            expected_move_pct=expected,
            reason=str(parsed.get("razon", ""))[:1200],
            thinking=str(message.get("thinking") or "")[:6000],
            seconds=seconds,
            deliberated=think,
        )


class LLMTradingAgent:
    """Builds the state, asks the model, validates, and remembers."""

    def __init__(
        self,
        *,
        policy: RegimeMixturePolicy,
        history: HistoryIndex,
        memory: AgentMemory,
        client: OllamaClient | None = None,
        analogue_count: int = 8,
    ) -> None:
        self.policy = policy
        self.history = history
        self.memory = memory
        self.client = client or OllamaClient()
        self.analogue_count = analogue_count
        self.last_state_block = ""
        self.last_market: dict[str, Any] = {}
        self.last_quant: dict[str, Any] = {}

    def build_state(
        self,
        *,
        daily_closes: tuple[Decimal, ...],
        price: Decimal,
        position_long: bool,
        btc_qty: Decimal,
        usdt_free: Decimal,
        entry_price: Decimal | None,
        holding_hours: int,
        active_stop: Decimal | None,
        params: RealtimeParams,
    ) -> tuple[str, list[float], dict[str, Any]]:
        market = market_view(daily_closes, price)
        vector: list[float] = list(market["_vector"])
        portfolio = PortfolioState(
            position_long=position_long,
            round_trip_cost_bps=float(params.round_trip_cost_bps),
            holding_hours=holding_hours,
        )
        quant = quant_view(self.policy, vector, portfolio)
        position = position_view(
            position_long=position_long,
            btc_qty=btc_qty,
            usdt_free=usdt_free,
            price=price,
            entry_price=entry_price,
            holding_hours=holding_hours,
            active_stop=active_stop,
        )
        cost = cost_view(params.round_trip_cost_bps, params.allocation_fraction)
        analogues = self.history.analogues(vector, self.analogue_count)
        playbook = render_playbook_block(
            int(quant.get("regimen", 0)),
            market.get("volatilidad_diaria_30d_pct"),
        )
        block = render_state_block(
            market,
            position,
            cost,
            quant,
            analogues,
            self.history.summarise(analogues),
            self.history.base_rates(),
            render_memory_block(self.memory, vector) + "\n\n" + playbook,
        )
        self.last_state_block = block
        self.last_quant = quant
        self.last_market = market
        return block, vector, quant

    def decide(self, state_block: str, *, position_long: bool) -> AgentVerdict:
        """Cheap pass first; deliberate only when it wants to move the book."""
        verdict = self.client.verdict(state_block, think=False)
        if verdict.wants_long == position_long:
            return verdict
        # It wants to change exposure, which costs real money. Re-take the decision
        # with full reasoning before acting on it.
        try:
            considered = self.client.verdict(state_block, think=True, num_predict=2500)
        except LLMUnavailable as error:
            _LOGGER.warning("deliberacion fallo, se mantiene el fallo cerrado: %r", error)
            raise
        return considered

    def clears_cost(
        self,
        verdict: AgentVerdict,
        params: RealtimeParams,
        *,
        position_long: bool,
        daily_vol_pct: float | None = None,
    ) -> bool:
        """Economic gate on ENTERING. Exits are never blocked by it.

        The project measured unbounded churn at 137% of capital per year, so opening
        a position requires the agent to state an expected move that covers the round
        trip. That part stands.

        Applying the same test to exits was a mistake of mine and it was expensive.
        Measured over 100 replayed decisions, the agent wanted to move to cash 49
        times and was refused because its own declared expected move did not clear
        0.20%. The damage shows in the trades it did make: it entered at 79,861 and
        was held in until 64,143, a 20% loss it had asked to avoid.

        The asymmetry is not a tweak, it is the correct economics. Entering is a bet
        that has to beat its own transaction cost. Leaving is not a bet, it is
        declining to keep one, and the downside of staying is unbounded while the cost
        of leaving is 10 bps. A risk control that can be vetoed by a commission is not
        a risk control.
        """
        return self.clears_cost_static(
            wants_long=verdict.wants_long,
            position_long=position_long,
            expected_move_pct=verdict.expected_move_pct,
            round_trip_cost_bps=float(params.round_trip_cost_bps),
            daily_vol_pct=daily_vol_pct,
        )

    @staticmethod
    def clears_cost_static(
        *,
        wants_long: bool,
        position_long: bool,
        expected_move_pct: float,
        round_trip_cost_bps: float,
        daily_vol_pct: float | None,
    ) -> bool:
        """The rule itself, with no dependency on live objects.

        Exists so the backtest and production cannot drift apart. Replaying with
        different economics than the running system measures a system that does not
        exist, and the divergence is invisible because both sides look reasonable in
        isolation.
        """
        if position_long and not wants_long:
            return True
        expected = LLMTradingAgent.plausible_expected_move(expected_move_pct, daily_vol_pct)
        return expected >= round_trip_cost_bps / 100.0

    @staticmethod
    def plausible_expected_move(expected_pct: float, daily_vol_pct: float | None) -> float:
        """Bound a declared expected move by what the market could plausibly deliver.

        The agent declared +35.31% over a few days in one replayed decision. Since
        the entry gate is a threshold on this number, an inflated estimate lets the
        agent unlock any entry it likes by asserting a large enough move. The raw
        value is still recorded so calibration can measure the exaggeration; this is
        only what the gate is allowed to act on.

        The ceiling is three daily standard deviations over a three day horizon, which
        is generous: it permits roughly a 20% move at 4% daily volatility and still
        rejects fantasy.
        """
        if daily_vol_pct is None or daily_vol_pct <= 0.0:
            return expected_pct
        ceiling = 3.0 * daily_vol_pct * math.sqrt(3.0)
        return min(expected_pct, ceiling)


class LLMAgentEngine(ProtectiveDecisionEngine):
    """Decision engine whose directional source is the local LLM agent.

    Guard order, strictest first. Only step 5 can originate a direction:
      1. circuit breakers         -> may force EXIT, never an entry
      2. exchange protective stop -> may force EXIT
      3. data quality gate        -> abstain on untrustworthy evidence
      4. perception sufficiency   -> abstain without 200 completed daily closes
      5. THE LLM AGENT            -> decides the exposure
      6. economic gate + cadence  -> acting must cover its cost
    """

    def __init__(
        self,
        params: RealtimeParams,
        agent: LLMTradingAgent,
        *,
        cadence: timedelta = timedelta(minutes=30),
    ) -> None:
        super().__init__(params)
        self.agent = agent
        self.cadence = cadence
        self._last_verdict_at: datetime | None = None
        self._last_verdict: AgentVerdict | None = None
        self._last_explanation: dict[str, Any] = {}
        self._fallbacks = 0
        # Deliberation runs off the event thread. A 333-second inference call on the
        # main loop starved the websocket keepalive, dropped the connection, and left
        # the protective layers unable to fire for the duration. Reasoning is slow by
        # nature, so it must never sit between a market event and a stop-loss.
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._pending_verdict: AgentVerdict | None = None
        self._pending_error: str | None = None
        self._deliberations = 0

    @property
    def deliberating(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    @property
    def deliberation_count(self) -> int:
        return self._deliberations

    def _spawn_deliberation(self, state_block: str, position_long: bool) -> None:
        """Ask the model in the background; the caller returns immediately."""

        def work() -> None:
            try:
                verdict = self.agent.decide(state_block, position_long=position_long)
            except LLMUnavailable as error:
                with self._lock:
                    self._pending_error = str(error)
                return
            except Exception as error:  # a worker crash must not kill the agent
                with self._lock:
                    self._pending_error = f"fallo inesperado: {error!r}"
                return
            with self._lock:
                self._pending_verdict = verdict

        self._deliberations += 1
        worker = threading.Thread(
            target=work, name="llm-deliberation", daemon=True
        )
        self._worker = worker
        worker.start()

    def _collect_deliberation(self) -> tuple[AgentVerdict | None, str | None]:
        with self._lock:
            verdict, error = self._pending_verdict, self._pending_error
            self._pending_verdict, self._pending_error = None, None
        return verdict, error

    @property
    def last_explanation(self) -> dict[str, Any]:
        return dict(self._last_explanation)

    @property
    def fallback_count(self) -> int:
        return self._fallbacks

    def _holding_hours(self, now: datetime) -> int:
        entry_at = self.state.entry_at
        if entry_at is None:
            return 0
        return max(int((now - entry_at).total_seconds() // 3600), 0)

    def _quant_fallback(
        self, vector: list[float], position_long: bool, holding_hours: int
    ) -> PolicyDecision:
        """The validated numeric policy, used when the LLM cannot be trusted."""
        portfolio = PortfolioState(
            position_long=position_long,
            round_trip_cost_bps=float(self.params.round_trip_cost_bps),
            holding_hours=holding_hours,
        )
        return self.agent.policy.decide(compose_features(vector, portfolio), portfolio)

    def _fallback_decision(
        self,
        fallback: PolicyDecision,
        evidence: EvidenceSnapshot,
        *,
        is_long: bool,
    ) -> RealtimeDecision:
        """Turn a fallback opinion into an action, WITHOUT letting it open a position.

        The fallback exists so an LLM outage never leaves an open position
        unmanaged. Managing a position means being able to leave it. It does not
        require being able to enter one, and letting it enter caused a real failure:
        the stop fired at 11:23, the LLM deliberated and chose EN LIQUIDEZ with 0.70
        conviction, and 34 minutes later a process restart wiped the in-memory verdict
        and the fallback immediately bought back in. A deliberate decision to hold
        cash was reversed by a restart.

        It also makes the code match what the architecture claims and the dashboard
        displays: only the LLM stage may originate a purchase. Exits stay open to the
        fallback because refusing to sell is the one failure with unbounded downside.

        The asymmetry has a cost worth stating: if the model is unreachable for a long
        time while flat, the account simply stays in cash. That is the safe direction,
        and being in cash is the one position that cannot lose money.
        """
        reason = f"FALLBACK_QUANT_{fallback.decision.value}"
        if fallback.decision == TradeDecision.SELL:
            return RealtimeDecision(
                Action.EXIT_LONG, reason, evidence, True, agent_decision=fallback
            )
        if fallback.decision == TradeDecision.BUY and not is_long:
            return RealtimeDecision(
                Action.HOLD,
                "FALLBACK_QUANT_ENTRY_SUPPRESSED",
                evidence,
                agent_decision=fallback,
            )
        return RealtimeDecision(Action.HOLD, reason, evidence, agent_decision=fallback)

    def evaluate(
        self, evidence: EvidenceSnapshot, position: ReconciledPosition
    ) -> RealtimeDecision:
        self.restore_position(position, now=evidence.at)
        self.update_equity(position.equity, evidence.at)
        now = evidence.at
        is_long = position.state == PositionState.LONG

        breaker = self.breaker_reason(position.equity)
        if breaker is not None:
            self._reset_candidate()
            self._last_explanation = {"veto": breaker}
            return RealtimeDecision(
                Action.EXIT_LONG if is_long else Action.HOLD, breaker, evidence, is_long
            )

        if is_long:
            high = max(self._state.high_since_entry or evidence.price, evidence.price)
            self._state = replace(
                self._state, high_since_entry=high, position_base_qty=position.btc_qty
            )
            active_stop = self._active_stop(evidence.price)
            if active_stop is not None and evidence.price <= active_stop:
                self._reset_candidate()
                self._last_explanation = {"veto": "PROTECTIVE_STOP"}
                return RealtimeDecision(
                    Action.EXIT_LONG,
                    "PROTECTIVE_STOP",
                    replace(evidence, active_stop_price=active_stop),
                    True,
                )

        if not evidence.qualified:
            self._reset_candidate()
            self._last_explanation = {"veto": evidence.reason}
            return RealtimeDecision(Action.HOLD, evidence.reason, evidence)

        if len(evidence.daily_closes) < MIN_DAILY_HISTORY:
            self._reset_candidate()
            self._last_explanation = {"veto": "PERCEPTION_INSUFFICIENT"}
            return RealtimeDecision(Action.HOLD, "PERCEPTION_INSUFFICIENT", evidence)

        holding_hours = self._holding_hours(now)
        # The vector is needed on every pass, both to act on a finished verdict and
        # to fall back to the numeric policy, so it is always computed. It is cheap.
        state_block, vector, quant = self.agent.build_state(
            daily_closes=evidence.daily_closes,
            price=evidence.price,
            position_long=is_long,
            btc_qty=position.btc_qty,
            usdt_free=position.usdt_free,
            entry_price=self._state.entry_price,
            holding_hours=holding_hours,
            active_stop=self._active_stop(evidence.price),
            params=self.params,
        )
        self.agent.memory.resolve_pending(now, evidence.price)

        finished, failure = self._collect_deliberation()
        if failure is not None:
            # Fail safe, not open: hand the wheel to the validated numeric policy
            # rather than leaving the position unmanaged.
            self._fallbacks += 1
            fallback = self._quant_fallback(vector, is_long, holding_hours)
            self._last_explanation = {
                "llm_unavailable": failure,
                "fallback": "modelo_cuantitativo_validado",
                "fallback_count": self._fallbacks,
                "target_exposure": (
                    EXPOSURE_INVESTED
                    if fallback.action == ExposureAction.TARGET_LONG
                    else EXPOSURE_CASH
                ),
                "p_long": fallback.action_probabilities[ExposureAction.TARGET_LONG.value],
            }
            _LOGGER.warning("LLM no disponible (%s); usando modelo cuantitativo", failure)
            return self._fallback_decision(fallback, evidence, is_long=is_long)

        if finished is not None:
            self._last_verdict = finished
            self._last_verdict_at = now

        # Start the next deliberation when the cadence allows and none is running.
        # This returns immediately; the market keeps being watched meanwhile.
        due = self._last_verdict_at is None or now - self._last_verdict_at >= self.cadence
        if due and not self.deliberating:
            self._spawn_deliberation(state_block, is_long)

        verdict = self._last_verdict
        if verdict is None:
            # No verdict yet. Until the first deliberation lands, the validated
            # numeric policy is in charge; the account is never unmanaged.
            fallback = self._quant_fallback(vector, is_long, holding_hours)
            self._last_explanation = {
                "status": "esperando_primera_deliberacion",
                "deliberating": self.deliberating,
                "fallback": "modelo_cuantitativo_validado",
                "target_exposure": (
                    EXPOSURE_INVESTED
                    if fallback.action == ExposureAction.TARGET_LONG
                    else EXPOSURE_CASH
                ),
                "p_long": fallback.action_probabilities[ExposureAction.TARGET_LONG.value],
            }
            return self._fallback_decision(fallback, evidence, is_long=is_long)

        if finished is None:
            # Acting on a verdict already applied would re-order on every event.
            self._last_explanation = {
                "reused_verdict": verdict.target_exposure,
                "conviction": verdict.conviction,
                "deliberating": self.deliberating,
                "deliberations": self._deliberations,
            }
            return RealtimeDecision(Action.HOLD, "AGENT_VERDICT_UNCHANGED", evidence)
        # The regime's burden of proof, applied to the POSITION and not only to
        # transitions. Gating changes alone left the status quo unexamined: an agent
        # already in the wrong place never triggered a change, so its exposure was never
        # tested. On the most bullish window available it sat out a +185% advance while
        # declaring 0.50 conviction for cash in a strong uptrend.
        effective_long, honoured = resolve_exposure(
            regime=int(quant.get("regimen", 0)),
            wants_invested=verdict.wants_long,
            conviction=verdict.conviction,
        )
        action = (
            ExposureAction.TARGET_LONG if effective_long else ExposureAction.TARGET_FLAT
        )
        trade = decision_for(action, is_long)
        wants_change = trade in {TradeDecision.BUY, TradeDecision.SELL}
        volatility = self.agent.last_market.get("volatilidad_diaria_30d_pct")
        clears = self.agent.clears_cost(
            verdict,
            self.params,
            position_long=is_long,
            daily_vol_pct=float(volatility) if volatility is not None else None,
        )

        record = PolicyDecision(
            action=action,
            decision=trade,
            action_probabilities={
                ExposureAction.TARGET_LONG.value: (
                    verdict.conviction if verdict.wants_long else 1.0 - verdict.conviction
                ),
                ExposureAction.TARGET_FLAT.value: (
                    1.0 - verdict.conviction if verdict.wants_long else verdict.conviction
                ),
            },
            regime_responsibilities=[
                float(value) for value in quant.get("reparto_regimenes", [])
            ],
            dominant_regime=int(quant.get("regimen", 0)),
            confidence=verdict.conviction,
            policy_version=AGENT_VERSION,
        )

        # The regime's strategy, resolved into bounded numbers. The agent chose a
        # posture; volatility and pre-registered limits decide what it means.
        plan = resolve_plan(
            regime=int(quant.get("regimen", 0)),
            posture=verdict.posture,
            conviction=verdict.conviction,
            daily_vol_pct=float(volatility) if volatility is not None else None,
        )
        acted = wants_change and clears
        self.agent.memory.record(
            decided_at=now,
            event_id=evidence.event_id,
            features=vector,
            regime=int(quant.get("regimen", 0)),
            quant_p_long=float(quant.get("p_largo", 0.0)),
            target_exposure=EXPOSURE_INVESTED if effective_long else EXPOSURE_CASH,
            exposure_before=EXPOSURE_INVESTED if is_long else EXPOSURE_CASH,
            derived_order=trade.value,
            conviction=verdict.conviction,
            expected_move_pct=verdict.expected_move_pct,
            reason=verdict.reason,
            thinking=verdict.thinking,
            price=evidence.price,
            acted=acted,
            posture=verdict.posture,
        )
        self._last_explanation = {
            "agent_version": AGENT_VERSION,
            "model": self.agent.client.model,
            "target_exposure": verdict.target_exposure,
            "conviction": verdict.conviction,
            "expected_move_pct": verdict.expected_move_pct,
            "clears_cost": clears,
            "deliberated": verdict.deliberated,
            "seconds": round(verdict.seconds, 1),
            "reason": verdict.reason,
            "thinking_chars": len(verdict.thinking),
            "quant_p_long": quant.get("p_largo"),
            "quant_recommends": quant.get("recomienda"),
            "regime": quant.get("regimen"),
            "regime_name": quant.get("nombre_regimen"),
            "agrees_with_quant": verdict.target_exposure == quant.get("recomienda"),
            "posture": verdict.posture,
            "strategy": plan.strategy_name,
            "choice_honoured": honoured,
            "effective_exposure": EXPOSURE_INVESTED if effective_long else EXPOSURE_CASH,
            "plan_allocation_pct": float(plan.allocation_fraction * 100),
            "plan_stop_pct": float(plan.stop_loss_fraction * 100),
            "plan_trail_pct": float(plan.trailing_stop_fraction * 100),
            "plan_risk_pct": float(plan.risk_per_trade_fraction * 100),
            "plan_horizon_hours": plan.horizon_hours,
        }

        suffix = "D" if verdict.deliberated else "F"
        reason = (
            f"AGENT_{trade.value}_R{quant.get('regimen', 0)}"
            f"_C{round(verdict.conviction * 100)}_{verdict.posture[:3]}_{suffix}"
            + ("" if honoured else "_REGIMEN_MANDA")
        )
        self._reset_candidate()

        if not wants_change:
            return RealtimeDecision(Action.HOLD, reason, evidence, agent_decision=record)
        if not clears:
            # It wants to move but its own expected move does not cover the round
            # trip. Refusing here is the economics the agent itself declared.
            return RealtimeDecision(
                Action.HOLD, f"{reason}_BELOW_COST", evidence, agent_decision=record
            )
        if trade == TradeDecision.BUY:
            return RealtimeDecision(
                Action.ENTER_LONG,
                reason,
                evidence,
                agent_decision=record,
                execution_plan=plan.to_dict(),
            )
        return RealtimeDecision(Action.EXIT_LONG, reason, evidence, True, agent_decision=record)


def build_agent(
    *,
    policy_path: str | Path,
    index_path: str | Path,
    memory_path: str | Path,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    horizon_hours: int = 24,
) -> LLMTradingAgent:
    return LLMTradingAgent(
        policy=RegimeMixturePolicy.load(policy_path),
        history=HistoryIndex(index_path),
        memory=AgentMemory(memory_path, horizon_hours=horizon_hours),
        client=OllamaClient(endpoint, model),
    )


__all__ = [
    "ACTIONS",
    "AGENT_VERSION",
    "DEFAULT_ENDPOINT",
    "DEFAULT_MODEL",
    "VERDICT_SCHEMA",
    "AgentVerdict",
    "LLMAgentEngine",
    "LLMTradingAgent",
    "LLMUnavailable",
    "OllamaClient",
    "build_agent",
]
