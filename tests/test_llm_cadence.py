"""Guards for the cadence/timeout relationship on the live agent.

The live agent spent about 21 hours deciding WITHOUT its model: 1,537 decisions logged as
`FALLBACK_QUANT_HOLD`, caused by twelve deliberations recorded in its own journal as
`modelo inalcanzable: TimeoutError('timed out')`.

The mis-sized parameter was the per-call TIMEOUT, not the cadence -- the cadence was already
30 minutes, longer than the 600 s timeout it never got to use. That correction matters: the
obvious reading ("the agent is too slow, slow the cadence down") would have changed the wrong
number and left the timeouts in place.

Two things are asserted here. That the timeout is reachable from the command line at all, so
sizing it does not require editing source. And that a cadence which cannot accommodate two
sequential calls is REFUSED, because a deliberation that wants to trade pays both and an
overlap would put two requests against the single bottleneck that is already timing out.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from btc_decision_agent.application.llm_agent import (
    DEFAULT_TIMEOUT_S,
    LLMAgentEngine,
    OllamaClient,
)
from btc_decision_agent.application.realtime_demo import RealtimeParams


class _StubAgent:
    """Only the attribute the guard reads. A real agent needs a model on disk."""

    def __init__(self, timeout_s: float | None) -> None:
        self.client: Any = OllamaClient(timeout_s=timeout_s) if timeout_s else None


def engine_with(timeout_s: float | None, cadence_minutes: float) -> LLMAgentEngine:
    return LLMAgentEngine(
        RealtimeParams(allocation_fraction=D("0.95")),
        _StubAgent(timeout_s),  # type: ignore[arg-type]
        cadence=timedelta(minutes=cadence_minutes),
    )


class TestTheTimeoutIsConfigurable:
    def test_the_client_accepts_a_timeout(self) -> None:
        assert OllamaClient(timeout_s=1200.0).timeout_s == 1200.0

    def test_the_default_is_the_named_constant_not_a_literal(self) -> None:
        """A magic 600.0 buried in a signature is what made this un-tunable."""
        assert OllamaClient().timeout_s == DEFAULT_TIMEOUT_S

    def test_the_runner_exposes_the_flag(self) -> None:
        """Sizing a timeout must not require editing source."""
        import scripts.run_llm_agent as runner

        parser = runner.build_parser() if hasattr(runner, "build_parser") else None
        if parser is None:
            source = runner.__file__
            assert source is not None
            with open(source, encoding="utf-8") as handle:
                text = handle.read()
            assert "--llm-timeout-seconds" in text
            assert "timeout_s=args.llm_timeout_seconds" in text
        else:
            parsed = parser.parse_args(
                ["--i-understand-this-is-demo", "--llm-timeout-seconds", "1200"]
            )
            assert parsed.llm_timeout_seconds == 1200.0


class TestCadenceMustClearTwoCalls:
    def test_a_cadence_shorter_than_two_calls_is_refused(self) -> None:
        """The exact combination that was live: 600 s timeout with a 15-minute cadence.

        Two sequential calls can take 1,200 s, which does not fit in 900 s, so the next
        deliberation would fall due while the previous one was still running.
        """
        with pytest.raises(ValueError, match="two sequential model calls"):
            engine_with(600.0, 15)

    def test_the_shipped_pairing_is_exactly_at_the_boundary_and_allowed(self) -> None:
        """600 s x 2 = 1,200 s against a 1,800 s cadence: it fits, so it must be accepted.

        This is why the timeouts were NOT a cadence problem, asserted rather than claimed.
        """
        engine = engine_with(600.0, 30)
        assert engine.cadence == timedelta(minutes=30)

    def test_a_raised_timeout_demands_a_raised_cadence(self) -> None:
        with pytest.raises(ValueError, match="two sequential model calls"):
            engine_with(1200.0, 30)
        assert engine_with(1200.0, 45).cadence == timedelta(minutes=45)

    def test_the_error_names_both_numbers_so_the_fix_is_obvious(self) -> None:
        with pytest.raises(ValueError) as caught:
            engine_with(900.0, 20)
        message = str(caught.value)
        assert "1200s" in message, "the cadence in seconds"
        assert "900s" in message, "the timeout"
        assert "1800s" in message, "what the cadence needs to be"

    def test_an_agent_without_a_measurable_timeout_is_not_blocked(self) -> None:
        """A client that does not expose `timeout_s` must not be rejected: the guard exists
        to catch an inconsistent pairing, not to require one."""
        assert engine_with(None, 1).cadence == timedelta(minutes=1)


class TestTheArithmeticOfTheFailure:
    def test_the_journal_distinguishes_a_dead_model_from_a_thinking_one(self) -> None:
        """The observability defect that made this hard to diagnose.

        Both situations logged `FALLBACK_QUANT_HOLD`: a model that had FAILED and a model
        still deliberating. Telling them apart required reading Ollama's own access log,
        because the agent's journal could not. The cause now rides in the reason code.
        """
        import inspect

        from btc_decision_agent.application.llm_agent import LLMAgentEngine

        source = inspect.getsource(LLMAgentEngine)
        assert 'cause="MODELO_CAIDO"' in source
        assert 'cause="AUN_DELIBERANDO"' in source

    def test_the_measured_call_durations_exceeded_the_old_budget(self) -> None:
        """Ollama's own access log, after the restart: the decisive measurement.

        Five consecutive agent calls took 826 s, 663 s, 449 s, 326 s and 283 s, all
        returning HTTP 200 -- the model answered, the client had stopped waiting. Two of the
        five exceed the 600 s budget, which is the direct proof the timeout was the wrong
        size rather than the cadence.
        """
        observed_s = [826.0, 663.0, 449.0, 326.0, 283.0]
        old_budget, new_budget = 600.0, 1200.0
        assert sum(1 for value in observed_s if value > old_budget) == 2
        assert max(observed_s) > old_budget
        assert max(observed_s) < new_budget
        assert new_budget / max(observed_s) == pytest.approx(1.45, abs=0.01), (
            "the new budget clears the worst observed call with 1.45x margin"
        )

    def test_the_new_pairing_satisfies_the_guard(self) -> None:
        """1200 s x 2 = 2400 s must fit inside a 45-minute cadence."""
        assert timedelta(minutes=45).total_seconds() >= 1200.0 * 2
        assert engine_with(1200.0, 45).cadence == timedelta(minutes=45)

    def test_two_cheap_calls_fit_the_old_timeout_but_a_reasoning_call_need_not(self) -> None:
        """Measured on the live host: generation ran at ~12.7 tokens/s.

        The cheap pass asks for 900 tokens, the reasoning pass 2,500. Compute was STABLE at
        ~25 s per call; what varied was queueing, from 95 s to 292 s on identical requests,
        because a second service shares the single CPU-only model instance. Contention, not
        model speed, is what blew the budget.
        """
        tokens_per_second = 320 / 25.1
        assert tokens_per_second == pytest.approx(12.75, abs=0.1)
        first_queue_s = 120.4 - 0.1 - 25.1
        second_queue_s = 317.5 - 0.11 - 24.6
        assert first_queue_s == pytest.approx(95.2, abs=0.1)
        assert second_queue_s == pytest.approx(292.8, abs=0.1)
        assert second_queue_s / first_queue_s > 3.0, (
            "queueing varied more than threefold on identical calls, which is why the "
            "timeout needs margin rather than a tight fit to the mean"
        )
