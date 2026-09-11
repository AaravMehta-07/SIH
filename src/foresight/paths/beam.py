"""Beam search over the next-mark decoder (Build Spec Section 20).

Default width 8, depth 4, with explicit truncated mass. A path ends at STOP
(no further events in the horizon) or OUTSIDE (the true next event lies
outside the candidate set); beams still alive at depth exhaustion count as
truncated search mass, as does the probability pruned away by the width
limit. ``no_event_mass`` is the probability of STOP at step 0.

Reported path probabilities are products of the decoder's autoregressive
conditionals over a candidate universe — ranked hypotheses, never a
calibrated attack-path posterior (``calibrated: false``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import torch

from .candidates import CandidateSet, MarkOption, OUTSIDE, STOP
from .model import NextMarkDecoder

BEAM_WIDTH = 8
BEAM_DEPTH = 4


@dataclass
class PathHypothesis:
    marks: tuple[MarkOption, ...]
    log_prob: float
    terminal: str | None = None  # None | "stop" | "outside" | "depth"

    @property
    def probability(self) -> float:
        return float(torch.exp(torch.tensor(self.log_prob)))

    def to_json(self) -> dict:
        return {
            "marks": [
                {
                    "task_index": m.task_index,
                    "source": m.source,
                    "target": m.target,
                    "time_bin": m.time_bin,
                    "time_window_seconds": (
                        [m.time_bin * 300, (m.time_bin + 1) * 300]
                        if m.kind == "candidate"
                        else None
                    ),
                }
                for m in self.marks
                if m.kind == "candidate"
            ],
            "probability": round(self.probability, 6),
            "terminal": self.terminal,
        }


@dataclass
class PathSearchResult:
    paths: list[PathHypothesis] = field(default_factory=list)
    outside_paths: list[PathHypothesis] = field(default_factory=list)
    no_event_mass: float = 0.0
    outside_candidate_mass: float = 0.0
    truncated_search_mass: float = 0.0

    def to_json(self) -> dict:
        total = (
            sum(p.probability for p in self.paths)
            + self.outside_candidate_mass
            + self.no_event_mass
            + self.truncated_search_mass
        )
        return {
            "ranked_paths": [p.to_json() for p in self.paths],
            "no_event_mass": round(self.no_event_mass, 6),
            "outside_candidate_mass": round(self.outside_candidate_mass, 6),
            "truncated_search_mass": round(self.truncated_search_mass, 6),
            "mass_accounting_total": round(total, 6),
        }


@torch.no_grad()
def beam_search(
    decoder: NextMarkDecoder,
    entity_memory: torch.Tensor,   # [1, N, 64]
    global_context: torch.Tensor,  # [1, 24]
    ext_bucket: torch.Tensor,      # [E]
    pair_src: torch.Tensor,        # [P]
    pair_tgt: torch.Tensor,        # [P]
    candidates: CandidateSet,
    *,
    width: int = BEAM_WIDTH,
    depth: int = BEAM_DEPTH,
) -> PathSearchResult:
    """Free generation: predicted marks are fed back (Section 20)."""
    decoder.eval()
    node_vecs = decoder.node_vectors(entity_memory, ext_bucket)
    h = decoder.initial_hidden(entity_memory, global_context)  # [1, H]

    def node_index(name: str) -> int:
        try:
            return candidates.node_names.index(name)
        except ValueError:
            return -1

    # Beam state: one row per active hypothesis.
    # histories are (type_idx, src, tgt, bin) per step, kept as python lists.
    result = PathSearchResult()
    alive: list[dict] = [
        {"h": h, "log_prob": 0.0, "marks": (), "history": []}
    ]

    for step in range(depth):
        if not alive:
            break
        bsz = len(alive)
        h_stack = torch.cat([b["h"] for b in alive], dim=0)  # [B, H]
        if step == 0:
            t_idx, src, tgt, b_idx = NextMarkDecoder.bos_batch(bsz, h.device)
        else:
            t_idx = torch.tensor(
                [b["history"][-1][0] for b in alive], device=h.device
            )
            src = torch.tensor(
                [b["history"][-1][1] for b in alive], device=h.device
            )
            tgt = torch.tensor(
                [b["history"][-1][2] for b in alive], device=h.device
            )
            b_idx = torch.tensor(
                [b["history"][-1][3] for b in alive], device=h.device
            )
        node_stack = node_vecs.expand(bsz, -1, -1)
        emb = decoder.mark_embedding(node_stack, t_idx, src, tgt, b_idx)
        h_stack = decoder.cell(emb, h_stack)
        log_probs = decoder.score_options(
            h_stack, node_stack, pair_src, pair_tgt, emb
        )  # [B, C+2]

        stop_idx = candidates.stop_index
        outside_idx = candidates.outside_index

        # Expand: keep the best `width` continuations overall.
        # Completed hypotheses (STOP/OUTSIDE) are frozen with their mass.
        next_alive: list[dict] = []
        for bi, beam in enumerate(alive):
            lp = log_probs[bi]
            if step == 0:
                result.no_event_mass = float(lp[stop_idx].exp())
            # Expand each beam over its best `width` options; STOP and
            # OUTSIDE options complete hypotheses with their accumulated
            # probability, candidate options continue the beam.
            top = torch.topk(lp, k=min(width, lp.shape[-1]))
            for log_p, opt_idx in zip(top.values.tolist(), top.indices.tolist()):
                new_log = beam["log_prob"] + log_p
                if opt_idx == stop_idx:
                    if step > 0:
                        result.paths.append(
                            PathHypothesis(beam["marks"], new_log, "stop")
                        )
                elif opt_idx == outside_idx:
                    hyp = PathHypothesis(beam["marks"], new_log, "outside")
                    result.outside_paths.append(hyp)
                    result.outside_candidate_mass += hyp.probability
                else:
                    option = candidates.options[opt_idx]
                    mark = MarkOption(
                        "candidate",
                        option.task_index,
                        option.source,
                        option.target,
                        option.time_bin,
                    )
                    next_alive.append(
                        {
                            "h": h_stack[bi : bi + 1],
                            "log_prob": new_log,
                            "marks": beam["marks"] + (mark,),
                            "history": [
                                *beam["history"],
                                (
                                    option.task_index,
                                    node_index(option.source),
                                    node_index(option.target),
                                    option.time_bin,
                                ),
                            ],
                        }
                    )
        # Rank continuations, keep width.
        next_alive.sort(key=lambda b: -b["log_prob"])
        alive = next_alive[:width]

    # Depth-exhausted beams and width-pruned mass are truncated search mass.
    accounted = (
        sum(p.probability for p in result.paths)
        + result.outside_candidate_mass
        + result.no_event_mass
        + sum(math.exp(b["log_prob"]) for b in alive)
    )
    result.truncated_search_mass = max(0.0, 1.0 - accounted)
    for b in alive:
        result.paths.append(PathHypothesis(b["marks"], b["log_prob"], "depth"))
    result.paths.sort(key=lambda p: -p.probability)
    return result
