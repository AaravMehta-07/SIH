"""Tier B intervention and safe response (Build Spec Sections 22-23, O).

One authorized range action (``block_edge``) with a paired no-action
continuation from the same cutoff, same seed (Section 22). Execution runs
in the disclosed synthetic range ONLY — simulator success is not production
proof, and no real-world control effect is ever claimed.

The action state machine (Section 23 table): proposed -> authorized ->
executing -> succeeded/failed/unknown, with expiry/recovery via the
reconciler. Approval is bound to the exact proposal and expiry; the
executor is a separate module with its own policy; dry-run is the default
and the kill switch always returns to dry-run.
"""

from .proposals import (
    ACTION_POLICY,
    ActionProposal,
    ActionStateMachine,
    IllegalTransitionError,
    check_policy,
    new_proposal,
    sign_approval,
)
from .range import RangeTrialResult, paired_trial

__all__ = [
    "ACTION_POLICY",
    "ActionProposal",
    "ActionStateMachine",
    "IllegalTransitionError",
    "check_policy",
    "new_proposal",
    "sign_approval",
    "RangeTrialResult",
    "paired_trial",
]
