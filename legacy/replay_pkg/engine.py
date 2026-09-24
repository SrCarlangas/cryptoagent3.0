"""Deterministic offline replay with an injected clock and byte-canonical output."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from btc_decision_agent.domain.canonical import canonical_json


@dataclass
class InjectedClock:
    current: datetime

    def __post_init__(self) -> None:
        if self.current.tzinfo is None or self.current.utcoffset() != UTC.utcoffset(self.current):
            raise ValueError("clock must start in UTC")

    def now(self) -> datetime:
        return self.current

    def set(self, value: datetime) -> None:
        if value < self.current:
            raise ValueError("replay clock cannot move backward")
        self.current = value


@dataclass(frozen=True)
class ReplayItem[T]:
    event_time: datetime
    observed_at: datetime
    identity: str
    payload: T


class DeterministicReplay[T, R]:
    def __init__(self, clock: InjectedClock, handler: Callable[[T, InjectedClock], R]) -> None:
        self.clock, self.handler = clock, handler

    def run(self, items: Iterable[ReplayItem[T]]) -> bytes:
        ordered = sorted(items, key=lambda item: (item.observed_at, item.event_time, item.identity))
        outputs: list[R] = []
        for item in ordered:
            self.clock.set(item.observed_at)
            outputs.append(self.handler(item.payload, self.clock))
        return b"\n".join(canonical_json(output) for output in outputs) + (b"\n" if outputs else b"")
