"""Source-linked explanations (Build Spec Section 19, Appendix K.1).

Grouped deletion/occlusion: remove the source events behind one traffic
group, recompute features on the altered legal prefix, rerun the same model
and record the score delta. Comprehensiveness and sufficiency are measured
against matched-size random controls; a negative/suppressive contribution is
not an implementation error (K.1).

Every evidence item carries the legal-prefix packet rows that produced it
(EX02) — no future packet is ever cited.
"""

from .attribution import (
    AttributionBudget,
    EvidenceItem,
    ExplanationResult,
    explain_target,
)
from .paths import CandidateEdgeProjection, rank_candidate_edges

__all__ = [
    "AttributionBudget",
    "EvidenceItem",
    "ExplanationResult",
    "explain_target",
    "CandidateEdgeProjection",
    "rank_candidate_edges",
]
