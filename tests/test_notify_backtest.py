"""The notifier must never describe a run that did not happen.

These tests exist because of a measured incident: the notifier was armed on a PID that
had already exited (the launch captured a wrapper process, not the backtest), so its
wait returned immediately, it read the previous run's trace off the default path and
announced `*Backtest terminado* ... APROBADO` with the numbers of a different window to
Slack. The backtest it claimed to report was one decision into sixty.

Nothing in the suite covered the notifier at the time, which is the same shape as the
eight structural defects this project has already found: an intention declared and
nothing checking it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from scripts.notify_backtest import NotTheRunWeWatched, fresher_than, wait_for


def _dead_pid() -> int:
    """A PID that is certainly not running: start a trivial child and reap it."""
    child = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    return child.pid


class TestWaitForRefusesADeadPid:
    def test_a_pid_that_is_already_gone_is_an_error_not_a_completion(self) -> None:
        with pytest.raises(NotTheRunWeWatched) as caught:
            wait_for(_dead_pid())
        assert "no existe al empezar a esperar" in str(caught.value)

    def test_the_error_tells_the_operator_how_to_find_the_real_pid(self) -> None:
        with pytest.raises(NotTheRunWeWatched) as caught:
            wait_for(_dead_pid())
        assert "[b]acktest_llm_agent" in str(caught.value)


class TestFreshnessOfTheReport:
    def test_a_trace_older_than_the_vigil_is_refused(self, tmp_path: Path) -> None:
        stale = tmp_path / "llm-agent-backtest.json"
        stale.write_text("{}", encoding="utf-8")
        four_days = 4 * 24 * 3600
        os.utime(stale, (time.time() - four_days, time.time() - four_days))

        with pytest.raises(NotTheRunWeWatched) as caught:
            fresher_than(stale, watch_started=time.time())
        message = str(caught.value)
        assert "ANTES de empezar a vigilar" in message
        assert "corrida anterior" in message

    def test_the_refusal_states_how_stale_the_trace_is(self, tmp_path: Path) -> None:
        stale = tmp_path / "llm-agent-backtest.json"
        stale.write_text("{}", encoding="utf-8")
        two_hours = 2 * 3600
        os.utime(stale, (time.time() - two_hours, time.time() - two_hours))

        with pytest.raises(NotTheRunWeWatched) as caught:
            fresher_than(stale, watch_started=time.time())
        assert "2.0 h" in str(caught.value)

    def test_a_trace_written_during_the_vigil_is_accepted(self, tmp_path: Path) -> None:
        fresh = tmp_path / "llm-agent-backtest.json"
        watch_started = time.time() - 10
        fresh.write_text("{}", encoding="utf-8")

        fresher_than(fresh, watch_started)  # must not raise
