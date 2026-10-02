"""Frontier-model client for Phase B: the SAME agent with a different brain.

APARCADO 2026-10-01, SIN CORRER. El dueno declino gastar tokens de terceros, y la pregunta de
la Fase B se respondio gratis con `research/bound_clients.py`: midiendo el TECHO (un cerebro
con prevision perfecta) en vez de comprando un cerebro mejor. Este modulo se conserva porque
la medicion de cotas mostro que la arquitectura SI tiene margen (+207.8% con prevision perfecta
frente a +68.9% del modelo local), asi que pagar por un modelo frontera volveria a ser
razonable si alguna vez se autoriza. No esta cableado a ningun backtest y se niega a arrancar
sin una credencial real, asi que no puede gastar nada por accidente.

Phase B of `roadmap.md` asks one question and it is the cheapest decisive one left: does a
frontier model have the momentum edge that `qwen3:30b-a3b` does not? The timing correlation of
the local model has been measured at zero four times (+0.01, +0.02, -0.11, +0.03, standard
error 0.15). If a much stronger model finds nothing either, the edge is not in the model.

For that question to mean anything, **only the model may change**. This client therefore
replicates `OllamaClient.verdict` exactly:

- the same `SYSTEM_PROMPT`, imported rather than copied, so it cannot drift
- the same `VERDICT_SCHEMA` fields and the same validation, including the deliberate leniency
  that downgrades an unknown posture to NEUTRAL instead of handing the account to the fallback
- temperature 0
- the same `AgentVerdict` out, the same `LLMUnavailable` on failure

Anything else held constant too: prompt, playbook, stops, cadence, costs, dataset.

Cost, which `roadmap.md` B.1 requires to be recorded: the state block runs ~3.5k input tokens
and the capped answer ~900 output tokens, so a 60-decision run is roughly 210k in / 54k out.
At list prices for a frontier tier (~$3 per million in, ~$15 per million out) that is about
**$1.50 per run** -- three orders of magnitude cheaper than the 3.7 hours of local GPU time the
same run costs on the server, and it does not require stopping the live agent.

Credentials: read from the environment at run time. The key is never written to the repo, never
logged and never printed, and this module refuses to run without it rather than falling back to
something that looks like it worked.

Usage:
    ANTHROPIC_API_KEY=... PYTHONPATH=src:research .venv/bin/python \\
        research/backtest_llm_agent.py --decisions 60 --step-days 5 --end-day 1560 \\
        --provider anthropic --model claude-sonnet-4-5
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

import certifi

from btc_decision_agent.application.llm_agent import (
    EXPOSURE_VALUES,
    POSTURE_VALUES,
    SYSTEM_PROMPT,
    AgentVerdict,
    LLMUnavailable,
    Posture,
)

ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_FRONTIER_MODEL = "claude-sonnet-4-5"
KEY_VARIABLE = "ANTHROPIC_API_KEY"

# Priced per million tokens, for the dollar figure B.1 asks to be recorded. List prices move;
# they are recorded here so a run's cost can be recomputed rather than guessed later.
USD_PER_MILLION_INPUT = 3.0
USD_PER_MILLION_OUTPUT = 15.0

_PLACEHOLDER_PREFIXES = ("your_", "sk-xxx", "changeme", "<", "replace")
"""A `.env` shipped with `ANTHROPIC_API_KEY=your_anthropic_api_key` must not be treated as a
credential. Sending a placeholder produces a 401 that looks like a transient outage, and this
project has already lost weeks to a channel that reported success while delivering nothing."""


def resolve_key(variable: str = KEY_VARIABLE) -> str:
    """Read the key from the environment, refusing placeholders loudly."""
    value = (os.environ.get(variable) or "").strip()
    if not value:
        raise LLMUnavailable(
            f"{variable} no esta en el entorno. La Fase B necesita una credencial real; "
            "no se escribe en el repo ni se registra en ningun log."
        )
    lowered = value.lower()
    if any(lowered.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
        raise LLMUnavailable(
            f"{variable} parece un placeholder ({value[:7]}..., {len(value)} caracteres), "
            "no una credencial. Enviarlo produce un 401 que se confunde con una caida."
        )
    return value


class FrontierClient:
    """Drop-in replacement for `OllamaClient`, talking to a hosted frontier model.

    Deliberately NOT a subclass: nothing of the local client's transport is reused, so there is
    no inherited behaviour that could quietly differ between the two arms of the comparison.
    What is shared is imported by name -- the prompt, the vocabularies and the verdict type.
    """

    def __init__(
        self,
        endpoint: str = ANTHROPIC_ENDPOINT,
        model: str = DEFAULT_FRONTIER_MODEL,
        *,
        timeout_s: float = 600.0,
        max_retries: int = 4,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._key = resolve_key()
        self._context = ssl.create_default_context(cafile=certifi.where())
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    # -- cost accounting -----------------------------------------------------------------

    def usd_spent(self) -> float:
        """Dollars billed so far, from the provider's own token counts."""
        return (
            self.input_tokens / 1_000_000 * USD_PER_MILLION_INPUT
            + self.output_tokens / 1_000_000 * USD_PER_MILLION_OUTPUT
        )

    def cost_summary(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd_spent": round(self.usd_spent(), 4),
            "usd_per_million_input": USD_PER_MILLION_INPUT,
            "usd_per_million_output": USD_PER_MILLION_OUTPUT,
        }

    # -- the one method the backtest calls -----------------------------------------------

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        """One request with bounded retries on the provider's own retryable statuses."""
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                "x-api-key": self._key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            method="POST",
        )
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_s, context=self._context
                ) as response:
                    payload: dict[str, Any] = json.load(response)
                    return payload
            except urllib.error.HTTPError as error:
                if error.code in {401, 403}:
                    # Never retried: a bad credential is not a transient outage, and retrying
                    # it just turns a clear failure into a slow one.
                    raise LLMUnavailable(
                        f"credencial rechazada por el proveedor (HTTP {error.code})"
                    ) from error
                if error.code in {429, 500, 502, 503, 529}:
                    last = error
                    import time

                    time.sleep(min(2.0**attempt, 30.0))
                    continue
                raise LLMUnavailable(f"HTTP {error.code} del proveedor") from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last = error
                import time

                time.sleep(min(2.0**attempt, 30.0))
        raise LLMUnavailable(f"proveedor inalcanzable tras {self.max_retries} intentos: {last!r}")

    def verdict(self, state_block: str, *, think: bool, num_predict: int = 900) -> AgentVerdict:
        """Same signature, same validation and same failure mode as `OllamaClient.verdict`.

        `think` is accepted and recorded so the two arms share an interface, but no extended
        reasoning is requested: the local arm was measured with `think=False`, and enabling it
        on one side only would change two things at once.
        """
        instruction = (
            state_block
            + "\n\nCual debe ser la exposicion ahora?"
            + "\n\nResponde UNICAMENTE con un objeto JSON con las claves exactas: "
            '"exposicion_objetivo" (INVERTIDO o EN LIQUIDEZ), "postura" '
            "(DEFENSIVA, NEUTRAL o AGRESIVA), \"conviccion\" (0 a 1), "
            '"movimiento_esperado_pct" (numero) y "razon" (texto breve). '
            "Sin markdown, sin texto antes ni despues."
        )
        body = {
            "model": self.model,
            "max_tokens": num_predict,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": instruction}],
        }

        started = datetime.now(tz=UTC)
        payload = self._post(body)
        seconds = (datetime.now(tz=UTC) - started).total_seconds()

        usage = payload.get("usage") or {}
        self.input_tokens += int(usage.get("input_tokens", 0))
        self.output_tokens += int(usage.get("output_tokens", 0))
        self.calls += 1

        blocks = payload.get("content") or []
        content = "".join(
            str(block.get("text", "")) for block in blocks if block.get("type") == "text"
        ).strip()
        if payload.get("stop_reason") == "max_tokens" and not content:
            raise LLMUnavailable("respuesta truncada por limite de tokens")
        if not content:
            raise LLMUnavailable("respuesta vacia del proveedor")

        # A hosted model may wrap JSON in a fence even when told not to. Stripping it is
        # formatting tolerance, not validation tolerance: every field below is still checked.
        if content.startswith("```"):
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:]
            content = content.strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            raise LLMUnavailable(
                f"JSON invalido: {error}; contenido={content[:200]!r}"
            ) from error

        target = str(parsed.get("exposicion_objetivo", "")).upper()
        if target not in set(EXPOSURE_VALUES):
            raise LLMUnavailable(f"exposicion_objetivo invalida: {target!r}")
        posture = str(parsed.get("postura", "")).upper()
        if posture not in set(POSTURE_VALUES):
            # Same deliberate leniency as the local client: an unknown posture is a formatting
            # slip, not a reason to hand the account to the fallback. Diverging here would make
            # the two arms fail differently on the same model output.
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
            thinking="",
            seconds=seconds,
            deliberated=think,
        )
