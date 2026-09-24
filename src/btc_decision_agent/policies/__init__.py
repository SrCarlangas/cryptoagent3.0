"""Frozen identity of the strategy that holds order authority.

Earlier versions of this package held hand-written decision policies. Those were
retired to legacy/ when the learned agent took over; behaviour now lives in the
policy document's weights, not in code here.
"""

from .exposure_v1 import (
    FREEZE_DATE,
    PARAMETER_VERSION,
    POLICY_DOCUMENT,
    STRATEGY_VERSION,
)

__all__ = [
    "FREEZE_DATE",
    "PARAMETER_VERSION",
    "POLICY_DOCUMENT",
    "STRATEGY_VERSION",
]
