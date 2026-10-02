"""Upper and lower bounds for the agent: what a PERFECT brain and a COIN would score.

This answers Phase B's question -- "is it the model, or is it the problem?" -- without buying
a single third-party token. Instead of swapping in a better brain and hoping, it measures the
ceiling:

- `OracleClient` knows the actual forward return of every decision interval and always picks
  the right side with full conviction. It is the **maximum the architecture can deliver with a
  perfect brain**, given the playbook's exposure caps, its stops, the 5-day cadence and real
  costs.
- `RandomClient` picks a side by seeded coin flip. It is the **null**: what the same machinery
  scores with no information at all.

The measured LLM then sits somewhere between, and WHERE decides what to do next:

- near the null and far below the oracle -> the architecture has room, and a better brain is
  worth paying for. Phase B becomes worth its ~$1.50.
- oracle itself low -> the ceiling is architectural (caps, stops, cadence, fees), and NO model
  can lift it. Phase B would be money spent to confirm a limit that is not in the model.

**The oracle is acausal by construction and is not a strategy.** It reads returns that had not
happened when it decides. It exists to bound the problem, exactly like `oracle_regimes` in
`research/regime_taxonomy.py`, and like that one it must never be reachable from a path that
could place an order. It is selected only by an explicit `--provider oracle` flag on a research
backtest.

Both clients are drop-in replacements for `OllamaClient`: same `verdict()` signature, same
`AgentVerdict` out. They advance an internal cursor because the backtest calls `verdict`
exactly once per decision, in day order, and neither of them can fail.

Usage:
    PYTHONPATH=src:research .venv/bin/python research/backtest_llm_agent.py \\
        --decisions 60 --step-days 5 --end-day 1560 --provider oracle
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

from btc_decision_agent.application.llm_agent import (
    EXPOSURE_VALUES,
    AgentVerdict,
    Posture,
)

INVESTED, CASH = EXPOSURE_VALUES
"""Taken from the module rather than retyped, so a vocabulary change cannot leave these
clients emitting a string the validator would reject."""


class _CursorClient:
    """Shared bookkeeping: walk the decision days in order, one call each."""

    def __init__(self, closes: Sequence[float], decision_days: Sequence[int], step_days: int):
        self.closes = list(closes)
        self.decision_days = list(decision_days)
        self.step_days = step_days
        self.cursor = 0

    def _forward_return(self) -> float:
        """Log return over the interval this decision actually governs. ACAUSAL."""
        if self.cursor >= len(self.decision_days):
            return 0.0
        day = self.decision_days[self.cursor]
        ahead = min(day + self.step_days, len(self.closes) - 1)
        start, end = self.closes[day], self.closes[ahead]
        if start <= 0.0 or end <= 0.0:
            return 0.0
        return math.log(end / start)


class OracleClient(_CursorClient):
    """Perfect foresight. The ceiling, not a strategy.

    Conviction and posture are set to the strongest the playbook honours in the direction it
    knows is right, so the bound is genuinely an upper bound: a weaker expression of perfect
    knowledge would understate what the architecture could do.
    """

    def verdict(self, state_block: str, *, think: bool, num_predict: int = 900) -> AgentVerdict:
        del state_block, num_predict  # A perfect brain needs no evidence block.
        move = self._forward_return()
        self.cursor += 1
        rising = move > 0.0
        return AgentVerdict(
            target_exposure=(INVESTED if rising else CASH),
            posture=(
                Posture.AGRESIVA.value if rising else Posture.DEFENSIVA.value
            ),
            conviction=0.95,
            expected_move_pct=(math.exp(move) - 1.0) * 100.0,
            reason="ORACULO: retorno futuro conocido. Cota superior, no es una estrategia.",
            thinking="",
            seconds=0.0,
            deliberated=think,
        )


class RandomClient(_CursorClient):
    """Seeded coin flip at a declared long rate. The null.

    The rate defaults to the long share the measured agent actually ran at on the bull window,
    so the null is matched on exposure and the comparison isolates TIMING rather than rewarding
    whichever arm happened to be invested more.
    """

    def __init__(
        self,
        closes: Sequence[float],
        decision_days: Sequence[int],
        step_days: int,
        *,
        long_rate: float = 0.67,
        seed: int = 20261001,
    ) -> None:
        super().__init__(closes, decision_days, step_days)
        self.long_rate = long_rate
        self._random = random.Random(seed)

    def verdict(self, state_block: str, *, think: bool, num_predict: int = 900) -> AgentVerdict:
        del state_block, num_predict
        self.cursor += 1
        rising = self._random.random() < self.long_rate
        return AgentVerdict(
            target_exposure=(INVESTED if rising else CASH),
            posture=Posture.NEUTRAL.value,
            conviction=0.60,
            expected_move_pct=0.0,
            reason=f"AZAR sembrado (tasa de exposicion {self.long_rate:.0%}). Hipotesis nula.",
            thinking="",
            seconds=0.0,
            deliberated=think,
        )
