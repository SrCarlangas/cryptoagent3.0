"""Targeted evidence for generic event-time/observed-time replay ordering."""

from __future__ import annotations

from datetime import timedelta

import pytest
from btc_decision_agent.replay.engine import DeterministicReplay, InjectedClock, ReplayItem
from tests.helpers import NOW, D


@pytest.mark.replay
def test_replay_orders_by_observation_and_is_byte_deterministic() -> None:
    items = (
        ReplayItem(NOW, NOW + timedelta(seconds=2), "later", {"value": D("2"), "provenance": "fixture:b"}),
        ReplayItem(NOW - timedelta(seconds=1), NOW + timedelta(seconds=1), "earlier", {"value": D("1"), "provenance": "fixture:a"}),
    )

    def handler(payload: dict[str, object], clock: InjectedClock) -> dict[str, object]:
        return {"payload": payload, "observed_at": clock.now()}

    first = DeterministicReplay(InjectedClock(NOW), handler).run(items)
    second = DeterministicReplay(InjectedClock(NOW), handler).run(reversed(items))
    assert first == second
    assert first.index(b"fixture:a") < first.index(b"fixture:b")


@pytest.mark.replay
def test_replay_clock_rejects_time_regression() -> None:
    clock = InjectedClock(NOW)
    with pytest.raises(ValueError, match="cannot move backward"):
        clock.set(NOW - timedelta(microseconds=1))
