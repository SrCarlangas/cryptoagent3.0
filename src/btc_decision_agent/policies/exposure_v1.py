"""Frozen identity for the local exposure agent that holds order authority.

The agent's behaviour lives in learned weights, not in parameters, so this file
carries only the identity stamped onto every journal entry and client order id.
The weights themselves are versioned inside the policy document, which records its
own dataset id, training window and promotion evidence.
"""

STRATEGY_VERSION = "EXPOSURE-AGENT-V1"
PARAMETER_VERSION = "exp/1"
POLICY_DOCUMENT = "data/models/local-exposure-agent-v1.json"
FREEZE_DATE = "2026-09-24"

__all__ = [
    "FREEZE_DATE",
    "PARAMETER_VERSION",
    "POLICY_DOCUMENT",
    "STRATEGY_VERSION",
]
