"""Tier A candidate-edge projection (Build Spec Section 20, Tier B boundary).

Tier A may show a ranked candidate-edge projection: marginal future
communication probabilities from the edge head. It MUST NOT be labeled a
calibrated attack-path probability (Section 4, A18). The Tier B typed-event
path engine (beam search, next-mark decoder) remains ``not_supported`` until
its own acceptance gates pass (T.3: an optional module may be correctly
disabled).
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

PATH_ENGINE_STATUS = "not_supported"
PATH_ENGINE_NOTE = (
    "Tier B typed-event path search is not implemented; ranked edges are "
    "marginal future-communication probabilities, not a joint path "
    "posterior (Section 20)"
)


@dataclass(frozen=True)
class CandidateEdgeProjection:
    """Ranked candidate edges for one forecast (Section 20, Tier A)."""

    edges: tuple[tuple[str, str, float], ...]  # (source, target, probability)
    status: str = "candidate_projection"
    calibrated: bool = False

    def to_json(self) -> dict:
        return {
            "edges": [
                {"source": s, "target": t, "probability": p}
                for s, t, p in self.edges
            ],
            "status": self.status,
            "calibrated": self.calibrated,
            "note": PATH_ENGINE_NOTE,
        }


def rank_candidate_edges(
    edge_logits: torch.Tensor,
    candidate_pairs,
    entity_ids: tuple[str, ...],
    *,
    horizon_bins: int,
    top_k: int = 8,
) -> CandidateEdgeProjection:
    """Rank candidate pairs by marginal future communication within the
    horizon (edge head output; sigmoid at readout only)."""
    if edge_logits is None:
        return CandidateEdgeProjection(edges=())
    # edge_logits: [E, H] — a pair "communicates in the horizon" if any bin
    # fires; report the max-probability bin as the marginal estimate.
    probs = torch.sigmoid(edge_logits).max(dim=1).values
    values, order = torch.topk(probs, min(top_k, probs.shape[0]))
    edges = []
    for rank, idx in enumerate(order.tolist()):
        src = entity_ids[int(candidate_pairs.source[idx])]
        tgt = entity_ids[int(candidate_pairs.target[idx])]
        edges.append((src, tgt, float(values[rank])))
    return CandidateEdgeProjection(edges=tuple(edges))
