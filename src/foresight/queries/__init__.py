"""Tier B evidence acquisition (Build Spec Section 21, Appendix N.3).

One targeted evidence request: ``identity_session_detail`` for uncertain
credential use. The default stretch policy is the sanctioned transparent
rule (Section 21): propose the query when an entity's lateral-movement
occurrence probability sits in the uncertain band, where analyst identity
context plausibly changes the decision.

Requests are allowlisted, scoped, costed and expiring; execution returns
``answered`` / ``unavailable`` / ``denied`` / ``expired`` states without
inventing observations. The answer is a new observation with its own
occurrence/availability/receipt times; it produces a NEW forecast version
and never rewrites the old seal. Identity answers are analyst context —
the Section-35 feature registry is frozen, so model scores do not change,
and that boundary is disclosed with every answer.
"""

from .engine import (
    QueryAnswer,
    QueryEngine,
    QueryProposal,
    UNCERTAIN_RULE,
)

__all__ = [
    "QueryAnswer",
    "QueryEngine",
    "QueryProposal",
    "UNCERTAIN_RULE",
]
