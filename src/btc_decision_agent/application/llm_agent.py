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
from btc_decision_agent.domain.contracts import Action, PositionState

_LOGGER = logging.getLogger(__name__)
D = Decimal

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen3:30b-a3b"
AGENT_VERSION = "LLM-EXPOSURE-AGENT-V1"

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "exposicion_objetivo": {"type": "string", "enum": ["LARGO", "PLANO"]},
        "conviccion": {"type": "number"},
        "movimiento_esperado_pct": {"type": "number"},
        "razon": {"type": "string"},
    },
    "required": ["exposicion_objetivo", "conviccion", "movimiento_esperado_pct", "razon"],
}

SYSTEM_PROMPT = """Eres el operador de una cuenta BTC/USDT en Binance. Tu mision es
obtener la maxima rentabilidad neta posible a lo largo del tiempo.

No eliges una orden. Eliges cual DEBE SER la exposicion ahora, evaluada desde cero:
  LARGO = el capital debe estar en BTC
  PLANO = el capital debe estar en USDT
El sistema comparara tu eleccion con la exposicion actual y derivara la orden.

Como decidir:
1. BTC tiene deriva positiva de largo plazo. Estar PLANO renuncia a esa deriva, asi
   que PLANO debe justificarse con evidencia. No es el default seguro.
2. Estar LARGO durante una caida sostenida destruye capital. LARGO tambien se
   justifica con evidencia.
3. Cambiar de exposicion cuesta comision. Declara en movimiento_esperado_pct cuanto
   crees que se movera el precio a tu favor en los proximos dias. Si ese movimiento
   es menor que el costo de cambiar, cambiar destruye valor aunque tu direccion sea
   correcta.
4. Compara los analogos historicos contra el base rate. Si los analogos rinden como
   el promedio de 5 anos, no hay senal: no es razon para actuar.
5. Solo trata como regla lo que tu historial marque como LECCION. Lo marcado como
   CANDIDATA es ruido todavia.
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
    conviction: float
    expected_move_pct: float
    reason: str
    thinking: str
    seconds: float
    deliberated: bool

    @property
    def wants_long(self) -> bool:
        return self.target_exposure == "LARGO"


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
        if target not in {"LARGO", "PLANO"}:
            raise LLMUnavailable(f"exposicion_objetivo invalida: {target!r}")
        try:
            conviction = float(parsed.get("conviccion", 0.0))
            expected = float(parsed.get("movimiento_esperado_pct", 0.0))
        except (TypeError, ValueError) as error:
            raise LLMUnavailable(f"campos numericos invalidos: {error}") from error

        return AgentVerdict(
            target_exposure=target,
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
        block = render_state_block(
            market,
            position,
            cost,
            quant,
            analogues,
            self.history.summarise(analogues),
            self.history.base_rates(),
            render_memory_block(self.memory, vector),
        )
        self.last_state_block = block
        self.last_quant = quant
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

    def clears_cost(self, verdict: AgentVerdict, params: RealtimeParams) -> bool:
        """Economic gate on ACTING, not on thinking.

        The project measured unbounded churn at 137% of capital per year. So the
        agent may reconsider continuously, but moving the book requires it to state
        an expected move that covers the round trip.
        """
        cost_pct = float(params.round_trip_cost_bps) / 100.0
        return verdict.expected_move_pct >= cost_pct


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
                    "LARGO" if fallback.action == ExposureAction.TARGET_LONG else "PLANO"
                ),
                "p_long": fallback.action_probabilities[ExposureAction.TARGET_LONG.value],
            }
            _LOGGER.warning("LLM no disponible (%s); usando modelo cuantitativo", failure)
            reason = f"FALLBACK_QUANT_{fallback.decision.value}"
            if fallback.decision == TradeDecision.BUY:
                return RealtimeDecision(Action.ENTER_LONG, reason, evidence, agent_decision=fallback)
            if fallback.decision == TradeDecision.SELL:
                return RealtimeDecision(
                    Action.EXIT_LONG, reason, evidence, True, agent_decision=fallback
                )
            return RealtimeDecision(Action.HOLD, reason, evidence, agent_decision=fallback)

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
                    "LARGO" if fallback.action == ExposureAction.TARGET_LONG else "PLANO"
                ),
                "p_long": fallback.action_probabilities[ExposureAction.TARGET_LONG.value],
            }
            reason = f"FALLBACK_QUANT_{fallback.decision.value}"
            if fallback.decision == TradeDecision.BUY:
                return RealtimeDecision(Action.ENTER_LONG, reason, evidence, agent_decision=fallback)
            if fallback.decision == TradeDecision.SELL:
                return RealtimeDecision(
                    Action.EXIT_LONG, reason, evidence, True, agent_decision=fallback
                )
            return RealtimeDecision(Action.HOLD, reason, evidence, agent_decision=fallback)

        if finished is None:
            # Acting on a verdict already applied would re-order on every event.
            self._last_explanation = {
                "reused_verdict": verdict.target_exposure,
                "conviction": verdict.conviction,
                "deliberating": self.deliberating,
                "deliberations": self._deliberations,
            }
            return RealtimeDecision(Action.HOLD, "AGENT_VERDICT_UNCHANGED", evidence)
        action = (
            ExposureAction.TARGET_LONG if verdict.wants_long else ExposureAction.TARGET_FLAT
        )
        trade = decision_for(action, is_long)
        wants_change = trade in {TradeDecision.BUY, TradeDecision.SELL}
        clears = self.agent.clears_cost(verdict, self.params)

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

        acted = wants_change and clears
        self.agent.memory.record(
            decided_at=now,
            event_id=evidence.event_id,
            features=vector,
            regime=int(quant.get("regimen", 0)),
            quant_p_long=float(quant.get("p_largo", 0.0)),
            target_exposure=verdict.target_exposure,
            exposure_before="LARGO" if is_long else "PLANO",
            derived_order=trade.value,
            conviction=verdict.conviction,
            expected_move_pct=verdict.expected_move_pct,
            reason=verdict.reason,
            thinking=verdict.thinking,
            price=evidence.price,
            acted=acted,
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
        }

        suffix = "D" if verdict.deliberated else "F"
        reason = (
            f"AGENT_{trade.value}_R{quant.get('regimen', 0)}"
            f"_C{round(verdict.conviction * 100)}_{suffix}"
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
            return RealtimeDecision(Action.ENTER_LONG, reason, evidence, agent_decision=record)
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
