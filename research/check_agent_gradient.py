"""Numerical verification of the exposure agent's expected-reward gradient.

The agent maximises J(theta) = sum_a pi_a(theta) * R_a. If the hand-derived
gradient through the mixture gate were wrong, training would still run and still
report plausible numbers while optimising nothing. This script compares the
analytic gradient used by RegimeMixturePolicy.update against central finite
differences of J, for both the expert weights and the gate weights.

Read-only. Prints the worst relative error; exits non-zero if it is not tiny.
"""

from __future__ import annotations

import random
import sys

from btc_decision_agent.application.exposure_agent import (
    ACTIONS,
    POLICY_FEATURE_NAMES,
    OnlineNormalizer,
    RegimeMixturePolicy,
)

EPSILON = 1e-5
"""Central-difference step. Too small and float64 cancellation dominates."""

ABSOLUTE_TOLERANCE = 1e-9
RELATIVE_TOLERANCE = 1e-5
"""Combined criterion. A pure relative test is meaningless for coordinates whose
true gradient is ~1e-7, where an absolute agreement of 1e-12 is already exact to
float precision."""


def identity_normalizer() -> OnlineNormalizer:
    """count=2 with unit m2 gives variance 1 and mean 0, i.e. transform = identity."""
    width = len(POLICY_FEATURE_NAMES)
    return OnlineNormalizer(count=2, means=[0.0] * width, m2=[1.0] * width)


def objective(policy: RegimeMixturePolicy, features: list[float], rewards: list[float]) -> float:
    normalized = policy.normalizer.transform(features)
    _augmented, _resp, _logits, probabilities = policy._forward(normalized)
    return sum(p * r for p, r in zip(probabilities, rewards, strict=True))


def analytic_gradients(
    policy: RegimeMixturePolicy, features: list[float], rewards: list[float]
) -> tuple[list[list[list[float]]], list[list[float]]]:
    """Reproduce exactly the direction that `update` moves the weights in."""
    normalized = policy.normalizer.transform(features)
    augmented, responsibilities, regime_logits, probabilities = policy._forward(normalized)
    expected = sum(p * r for p, r in zip(probabilities, rewards, strict=True))
    delta = [probabilities[a] * (rewards[a] - expected) for a in range(len(ACTIONS))]

    expert_grad = [
        [
            [delta[a] * responsibilities[k] * augmented[i] for i in range(len(augmented))]
            for a in range(len(ACTIONS))
        ]
        for k in range(policy.regimes)
    ]
    gate_signal = [
        sum(delta[a] * regime_logits[k][a] for a in range(len(ACTIONS)))
        for k in range(policy.regimes)
    ]
    baseline = sum(responsibilities[k] * gate_signal[k] for k in range(policy.regimes))
    gate_grad = [
        [
            responsibilities[k] * (gate_signal[k] - baseline) * augmented[i]
            for i in range(len(augmented))
        ]
        for k in range(policy.regimes)
    ]
    return expert_grad, gate_grad


def main() -> int:
    rng = random.Random(20260924)
    worst = 0.0
    checks = 0

    for trial in range(5):
        policy = RegimeMixturePolicy(regimes=3, normalizer=identity_normalizer())
        # Non-trivial weights, otherwise symmetry hides sign errors.
        for k in range(policy.regimes):
            for i in range(len(policy.gate[k])):
                policy.gate[k][i] = rng.uniform(-0.5, 0.5)
            for a in range(len(ACTIONS)):
                for i in range(len(policy.experts[k][a])):
                    policy.experts[k][a][i] = rng.uniform(-0.5, 0.5)

        features = [rng.uniform(-2.0, 2.0) for _ in POLICY_FEATURE_NAMES]
        rewards = [rng.uniform(-0.05, 0.05) for _ in ACTIONS]
        expert_grad, gate_grad = analytic_gradients(policy, features, rewards)

        # Sample a subset of coordinates; checking all of them is unnecessary.
        for _ in range(40):
            k = rng.randrange(policy.regimes)
            i = rng.randrange(len(policy.gate[k]))
            if rng.random() < 0.5:
                a = rng.randrange(len(ACTIONS))
                original = policy.experts[k][a][i]
                policy.experts[k][a][i] = original + EPSILON
                plus = objective(policy, features, rewards)
                policy.experts[k][a][i] = original - EPSILON
                minus = objective(policy, features, rewards)
                policy.experts[k][a][i] = original
                numeric = (plus - minus) / (2.0 * EPSILON)
                analytic = expert_grad[k][a][i]
                label = f"expert[{k}][{a}][{i}]"
            else:
                original = policy.gate[k][i]
                policy.gate[k][i] = original + EPSILON
                plus = objective(policy, features, rewards)
                policy.gate[k][i] = original - EPSILON
                minus = objective(policy, features, rewards)
                policy.gate[k][i] = original
                numeric = (plus - minus) / (2.0 * EPSILON)
                analytic = gate_grad[k][i]
                label = f"gate[{k}][{i}]"

            absolute = abs(numeric - analytic)
            allowed = ABSOLUTE_TOLERANCE + RELATIVE_TOLERANCE * abs(analytic)
            checks += 1
            margin = absolute / allowed
            if margin > worst:
                worst = margin
            if absolute > allowed:
                print(
                    f"MISMATCH trial={trial} {label} numeric={numeric:+.12f} "
                    f"analytic={analytic:+.12f} abs_err={absolute:.2e} allowed={allowed:.2e}"
                )

    print(
        f"checked {checks} coordinates; worst error was {worst:.3f}x the allowed "
        "tolerance (1.0 = exactly at the limit)"
    )
    if worst > 1.0:
        print("GRADIENT INCORRECT")
        return 1
    print("GRADIENT VERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
