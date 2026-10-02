"""Tests for the research bounds, with the oracle's acausality as the centrepiece.

`OracleClient` reads the forward return of the interval it is deciding. That is the point --
it bounds what a perfect brain could score inside this architecture -- and it is also exactly
the kind of object that must never end up on a path that can place an order. These tests pin
both the arithmetic and the firewall.
"""

from __future__ import annotations

import inspect

from bound_clients import OracleClient, RandomClient


def _closes(values: list[float]) -> list[float]:
    return list(values)


class TestOracleIsAnUpperBoundAndKnowsIt:
    def test_it_goes_long_when_the_interval_actually_rises(self) -> None:
        client = OracleClient(_closes([100.0, 101.0, 102.0, 110.0]), [0], step_days=3)
        verdict = client.verdict("ignorado", think=False)
        assert verdict.target_exposure == "INVERTIDO"
        assert verdict.posture == "AGRESIVA"

    def test_it_steps_aside_when_the_interval_actually_falls(self) -> None:
        client = OracleClient(_closes([100.0, 99.0, 98.0, 90.0]), [0], step_days=3)
        verdict = client.verdict("ignorado", think=False)
        assert verdict.target_exposure == "EN LIQUIDEZ"
        assert verdict.posture == "DEFENSIVA"

    def test_the_cursor_advances_one_decision_per_call(self) -> None:
        """The backtest calls verdict exactly once per decision, in day order."""
        closes = _closes([100.0, 110.0, 90.0, 100.0, 120.0])
        client = OracleClient(closes, [0, 2], step_days=1)
        first = client.verdict("", think=False)
        second = client.verdict("", think=False)
        assert first.target_exposure == "INVERTIDO"  # 100 -> 110
        assert second.target_exposure == "INVERTIDO"  # 90 -> 100
        assert client.cursor == 2

    def test_it_declares_itself_acausal_in_the_reason_it_records(self) -> None:
        """A trace reader must not mistake a bound for a strategy."""
        client = OracleClient(_closes([100.0, 110.0]), [0], step_days=1)
        reason = client.verdict("", think=False).reason
        assert "ORACULO" in reason
        assert "no es una estrategia" in reason

    def test_a_flat_interval_does_not_crash_and_steps_aside(self) -> None:
        client = OracleClient(_closes([100.0, 100.0]), [0], step_days=1)
        assert client.verdict("", think=False).target_exposure == "EN LIQUIDEZ"


class TestOracleFirewall:
    def test_the_oracle_is_not_importable_from_the_production_package(self) -> None:
        """It lives in research/, never under src/, so no runtime path can reach it."""
        assert "research" in inspect.getfile(OracleClient)
        assert "btc_decision_agent" not in inspect.getfile(OracleClient)

    def test_it_ignores_the_evidence_block_entirely(self) -> None:
        """Proves the bound is foresight, not a cleverer reading of the same evidence."""
        closes = _closes([100.0, 110.0])
        a = OracleClient(closes, [0], step_days=1).verdict("bloque A", think=False)
        b = OracleClient(closes, [0], step_days=1).verdict("bloque B muy distinto", think=False)
        assert a.target_exposure == b.target_exposure
        assert a.conviction == b.conviction


class TestRandomIsANull:
    def test_the_same_seed_reproduces_the_same_decisions(self) -> None:
        closes = _closes([100.0] * 20)
        days = list(range(10))
        first = [
            RandomClient(closes, days, 1, seed=7).verdict("", think=False).target_exposure
            for _ in range(1)
        ]
        second = [
            RandomClient(closes, days, 1, seed=7).verdict("", think=False).target_exposure
            for _ in range(1)
        ]
        assert first == second

    def test_different_seeds_can_differ(self) -> None:
        closes = _closes([100.0] * 40)
        days = list(range(30))

        def run(seed: int) -> list[str]:
            client = RandomClient(closes, days, 1, seed=seed)
            return [client.verdict("", think=False).target_exposure for _ in days]

        assert run(1) != run(999)

    def test_the_long_rate_is_honoured_within_sampling_noise(self) -> None:
        closes = _closes([100.0] * 2100)
        days = list(range(2000))
        client = RandomClient(closes, days, 1, long_rate=0.67, seed=42)
        longs = sum(
            client.verdict("", think=False).target_exposure == "INVERTIDO" for _ in days
        )
        assert 0.64 < longs / len(days) < 0.70

    def test_it_declares_itself_the_null(self) -> None:
        client = RandomClient(_closes([100.0, 100.0]), [0], 1)
        assert "AZAR" in client.verdict("", think=False).reason
