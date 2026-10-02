"""Tests for the pre-registered gate, focused on the criteria added by the 2026-10-01 pivot.

The gate had NO tests before this file, which is the same shape as the nine structural
defects catalogued in `handover.md`: an intention declared and nothing checking it. A gate is
the one artefact in this project whose correctness cannot be inferred from a run looking
plausible, because its whole job is to refuse plausible runs.

The property under test is not "the agent passes". It is that the gate asks the question it
claims to ask, and that a criterion it cannot evaluate FAILS rather than passes.
"""

from __future__ import annotations

from scripts.gate_llm_agent import (
    MAX_DRAWDOWN_RATIO,
    MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
    MIN_DECISIONS_PER_REGIME,
    MIN_REGIME_EXPOSURE_SPREAD,
    _discrimination_check,
    _risk_matched_check,
    evaluate,
)


def _trace(spec: dict[int, tuple[int, float]]) -> list[dict]:
    """A trace with `count` decisions at `share` exposure for each regime in `spec`."""
    out: list[dict] = []
    for regime, (count, share) in spec.items():
        out.extend({"regime": regime, "share_target": share} for _ in range(count))
    return out


def _report(
    *,
    agent_return: float,
    agent_drawdown: float,
    hold_return: float,
    hold_drawdown: float,
    quant_return: float = -50.0,
    commission: float = 1.0,
    decisions: int = 60,
    long_share: float = 0.5,
    direction_changes: int = 5,
) -> dict:
    """A minimal report shaped like the backtest's, with every hygiene criterion passing."""
    return {
        "llm_agent": {
            "net_return_pct": agent_return,
            "max_drawdown_pct": agent_drawdown,
            "decisions": decisions,
            "model_failures": 0,
            "long_share": long_share,
            "direction_changes": direction_changes,
            "switches": direction_changes,
            "commission_paid_pct": commission,
        },
        "buy_and_hold": {"net_return_pct": hold_return, "max_drawdown_pct": hold_drawdown},
        "quant_policy": {"net_return_pct": quant_return, "max_drawdown_pct": hold_drawdown},
        "window": {"days": 300, "step_days": 5, "start_day_index": 0, "end_day_index": 300},
    }


class TestRiskMatchedComparisonRisingLeg:
    """The null hypothesis of the pivoted product: just hold less BTC."""

    def test_an_agent_worse_than_static_sizing_does_not_pass(self) -> None:
        """The hole the first draft of this gate had: 80% of a free alternative is a loss."""
        _, passed, detail = _risk_matched_check(
            agent_return=40.0,
            agent_drawdown=10.0,
            reference_return=100.0,
            reference_drawdown=20.0,
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=1.0,
        )
        assert not passed, detail  # static 0.5x gives +50%; 40% is strictly dominated

    def test_matching_static_sizing_net_of_its_own_commission_passes(self) -> None:
        _, passed, _ = _risk_matched_check(
            agent_return=49.0,
            agent_drawdown=10.0,
            reference_return=100.0,
            reference_drawdown=20.0,
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=1.0,
        )
        assert passed  # 49 >= 50 - 1

    def test_an_agent_that_beats_static_sizing_at_its_own_risk_passes(self) -> None:
        _, passed, _ = _risk_matched_check(
            agent_return=60.0,
            agent_drawdown=10.0,
            reference_return=100.0,
            reference_drawdown=20.0,
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=1.0,
        )
        assert passed  # 60 >= 50 - 1

    def test_the_benchmark_scales_with_the_agents_own_drawdown(self) -> None:
        """Cutting risk harder lowers the bar, which is the trade being rewarded."""
        _, passed, _ = _risk_matched_check(
            agent_return=25.0,
            agent_drawdown=5.0,
            reference_return=100.0,
            reference_drawdown=20.0,
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=1.0,
        )
        assert passed  # 25 >= 0.25 * 100 - 1

    def test_the_measured_bull_window_fails_as_recorded(self) -> None:
        """The numbers written into the gate's own docstring must be what it computes.

        Uses the archived trace's own values, so a drift between the documented figures and
        the arithmetic shows up here instead of in a report nobody rechecks.
        """
        _, passed, detail = _risk_matched_check(
            agent_return=68.94,
            agent_drawdown=16.99,
            reference_return=184.44,
            reference_drawdown=20.00,
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=1.68,
        )
        assert not passed
        # Assert the arithmetic, not the rounded text: pinning a formatted decimal makes a
        # test fail on a cosmetic change and tells you nothing about correctness.
        fraction = 16.99 / 20.00
        risk_matched = fraction * 184.44
        required = risk_matched - 1.68
        assert abs(risk_matched - 156.7) < 0.1
        assert abs(required - 155.0) < 0.1
        assert required > 68.94  # the agent is nowhere near it
        assert "estatico habria dado" in detail


class TestRiskMatchedComparisonFallingLeg:
    """The leg the retired criterion skipped, which is where the free lunch was hiding."""

    def test_losing_more_than_static_sizing_does_not_pass(self) -> None:
        _, passed, detail = _risk_matched_check(
            agent_return=-5.0,
            agent_drawdown=6.0,
            reference_return=-13.0,
            reference_drawdown=39.0,
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=0.0,
        )
        assert not passed, detail  # static 0.154x would lose only ~2.0%

    def test_losing_less_than_static_sizing_passes(self) -> None:
        _, passed, _ = _risk_matched_check(
            agent_return=-1.5,
            agent_drawdown=6.0,
            reference_return=-13.0,
            reference_drawdown=39.0,
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=0.0,
        )
        assert passed

    def test_the_allowance_is_the_commission_a_static_holder_would_not_pay(self) -> None:
        """Derived from the run, not chosen: without it the agent is charged twice."""
        _, without, _ = _risk_matched_check(
            agent_return=-2.2,
            agent_drawdown=6.0,
            reference_return=-13.0,
            reference_drawdown=39.0,
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=0.0,
        )
        _, with_allowance, _ = _risk_matched_check(
            agent_return=-2.2,
            agent_drawdown=6.0,
            reference_return=-13.0,
            reference_drawdown=39.0,
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=0.5,
        )
        assert not without
        assert with_allowance

    def test_the_measured_bear_window_fails_by_a_hair_as_recorded(self) -> None:
        """-2.39% against a -2.34% limit: a tie, meaning the deciding added nothing."""
        _, passed, detail = _risk_matched_check(
            agent_return=-2.39,
            agent_drawdown=6.1,
            reference_return=-12.86,
            reference_drawdown=39.5,
            minimum=MIN_CAPTURE_OF_RISK_MATCHED_HOLD,
            commission_pct=0.36,
        )
        assert not passed
        assert "-2.0%" in detail


class TestUnevaluableCriteriaFail:
    def test_a_reference_without_drawdown_fails_rather_than_passes(self) -> None:
        _, passed, detail = _risk_matched_check(
            agent_return=50.0,
            agent_drawdown=10.0,
            reference_return=100.0,
            reference_drawdown=0.0,
            minimum=0.80,
            commission_pct=1.0,
        )
        assert not passed
        assert "no evaluable" in detail

    def test_a_missing_commission_field_fails_the_commission_criterion(self) -> None:
        report = _report(
            agent_return=50.0, agent_drawdown=5.0, hold_return=40.0, hold_drawdown=20.0
        )
        del report["llm_agent"]["commission_paid_pct"]
        checks, _ = evaluate(report)
        commission_check = next(name for name, _, _ in checks if "comision" in name)
        passed = next(ok for name, ok, _ in checks if name == commission_check)
        assert not passed


class TestDrawdownRatioCriterion:
    def test_a_marginal_cut_does_not_count_as_material(self) -> None:
        report = _report(
            agent_return=200.0, agent_drawdown=17.0, hold_return=184.0, hold_drawdown=20.0
        )
        checks, approved = evaluate(report)
        ratio = next(ok for name, ok, _ in checks if "material" in name)
        assert not ratio  # 0.85x against a 0.60x limit
        assert not approved

    def test_a_material_cut_counts(self) -> None:
        report = _report(
            agent_return=200.0, agent_drawdown=11.0, hold_return=184.0, hold_drawdown=20.0
        )
        checks, _ = evaluate(report)
        assert next(ok for name, ok, _ in checks if "material" in name)

    def test_the_limit_is_the_declared_constant(self) -> None:
        """Guards the constant against a silent edit, which is how a gate gets weakened."""
        assert MAX_DRAWDOWN_RATIO == 0.60
        assert MIN_CAPTURE_OF_RISK_MATCHED_HOLD == 1.00


class TestDiscriminationIsConditioningNotHeadcount:
    """The repair of 2026-10-01: minority share counted decisions, not conditioning."""

    def test_a_flat_agent_fails_however_its_decisions_are_spread(self) -> None:
        _, passed, detail = _discrimination_check(
            _trace({0: (30, 0.02), 1: (30, 0.03)}), long_share=0.5, minority=0.5
        )
        assert not passed, detail

    def test_an_agent_whose_exposure_tracks_regime_passes(self) -> None:
        _, passed, _ = _discrimination_check(
            _trace({0: (10, 0.0), 3: (20, 0.85)}), long_share=0.6, minority=0.4
        )
        assert passed

    def test_a_regime_seen_once_cannot_carry_the_criterion(self) -> None:
        """The bear window's hole: 4 decisions in rarely-seen regimes faked discrimination."""
        _, passed, detail = _discrimination_check(
            _trace({0: (40, 0.029), 1: (16, 0.0), 2: (3, 0.78), 3: (1, 0.95)}),
            long_share=0.12,
            minority=0.12,
        )
        assert not passed
        assert "3%" in detail  # the spread of the regimes that DO clear the floor

    def test_the_measured_bull_window_passes_as_recorded(self) -> None:
        _, passed, _ = _discrimination_check(
            _trace({0: (11, 0.0), 2: (21, 0.716), 3: (28, 0.845)}),
            long_share=0.67,
            minority=0.33,
        )
        assert passed

    def test_fewer_than_two_usable_regimes_is_unevaluable_and_fails(self) -> None:
        _, passed, detail = _discrimination_check(
            _trace({0: (40, 0.0), 1: (2, 0.9)}), long_share=0.05, minority=0.05
        )
        assert not passed
        assert "no evaluable" in detail

    def test_an_older_report_without_regimes_falls_back_rather_than_crashing(self) -> None:
        """A historical verdict must not be silently recomputed into a different answer."""
        _, passed, detail = _discrimination_check(None, long_share=0.67, minority=0.33)
        assert passed
        assert "informe antiguo" in detail

    def test_the_spread_is_measured_between_the_extreme_regimes(self) -> None:
        """Assert the arithmetic, not the formatting."""
        trace = _trace({0: (10, 0.10), 1: (10, 0.40), 2: (10, 0.75)})
        _, passed, _ = _discrimination_check(trace, long_share=0.5, minority=0.5)
        assert passed  # 0.75 - 0.10 = 0.65 >= 0.30

    def test_the_declared_constants_are_what_the_code_uses(self) -> None:
        assert MIN_REGIME_EXPOSURE_SPREAD == 0.30
        assert MIN_DECISIONS_PER_REGIME == 5
