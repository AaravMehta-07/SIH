"""Clip target construction from episode ground truth (Build Spec D.6).

For one clip at cutoff ``d`` with horizon H bins of 30 seconds:

- ``event_y``/``risk_mask`` are ``[N, H, J]``. A first event at bin b puts a
  single 1 at bin b and stops the risk mask there. An event that already
  occurred at or before ``d`` removes the entity from that task's risk set
  (initial-onset exclusion, Section 11) while its traffic history stays in
  the prefix (``retain_precursor_attack_history``). Censored follow-up keeps
  negative labels only through complete observed bins (Section 15).
- Stage labels ``[N, H, 5]``: tactic activity windows projected onto bins;
  several tactics may coexist.
- Future node/global targets: the transformed-space features of the future
  windows (observable decoder training signal, Section 14).
- Edge labels on the frozen all-directed-internal-pairs candidate set
  (Section 15: train on all directed pairs within the capped scope).
"""

from __future__ import annotations

import numpy as np
import torch

from ..features.transforms import FeatureScaler, transform_window
from ..features.windows import RawGraphWindow, window_bounds
from ..models.types import CandidatePairs
from ..training.targets import ClipTargets

_NS = 1_000_000_000
WINDOW_NS = 30 * _NS


def all_pair_candidates(num_nodes: int) -> CandidatePairs:
    """Every directed internal pair (u != v) of the clip's entity union."""
    pairs = [
        (u, v) for u in range(num_nodes) for v in range(num_nodes) if u != v
    ]
    return CandidatePairs(
        batch_index=torch.zeros(len(pairs), dtype=torch.int64),
        source=torch.tensor([u for u, _ in pairs], dtype=torch.int64),
        target=torch.tensor([v for _, v in pairs], dtype=torch.int64),
    )


def _bin_of(event_time_ns: int, cutoff_ns: int, horizon: int) -> int | None:
    """1-indexed future bin containing ``event_time_ns``; None if outside
    (d, d + H*30s]. Bin j covers (d + (j-1)*30s, d + j*30s] (Section 15)."""
    delta = event_time_ns - cutoff_ns
    if delta <= 0:
        return 0  # at or before the cutoff: already observed
    b = int(np.ceil(delta / WINDOW_NS))
    return b if b <= horizon else None


def build_clip_targets(
    *,
    entity_ids: tuple[str, ...],
    ground_truth,               # iterable of GroundTruth
    stage_windows,              # iterable of (entity, tactic_idx, from_ns, to_ns)
    cutoff_ns: int,
    horizon: int = 60,
    future_windows: list[RawGraphWindow] | None = None,
    scaler: FeatureScaler | None = None,
    qualified_tasks: tuple[int, ...] = (0, 1, 2, 3, 4),
    split: str = "train",
    followup_end_ns: int | None = None,
) -> ClipTargets:
    """Assemble the D.6 target object for one clip.

    ``future_windows`` are the raw full-information windows after the cutoff
    (oldest first, length >= horizon); with a scaler they produce the
    transformed observable targets.
    """
    n = len(entity_ids)
    j = 5
    slot_of = {name: i for i, name in enumerate(entity_ids)}

    event_y = torch.zeros(n, horizon, j)
    risk_mask = torch.zeros(n, horizon, j, dtype=torch.bool)
    task_mask = torch.zeros(j, dtype=torch.bool)
    for t in qualified_tasks:
        task_mask[t] = True

    followup_end = followup_end_ns if followup_end_ns is not None else cutoff_ns + horizon * WINDOW_NS

    first_event: dict[tuple[int, int], int] = {}
    for g in ground_truth:
        if g.entity not in slot_of:
            continue
        first_event[(slot_of[g.entity], g.task_index)] = g.event_time_ns

    for slot in range(n):
        for t in range(j):
            if not task_mask[t]:
                continue  # unsupported dims stay masked (D.6)
            event_time = first_event.get((slot, t))
            if event_time is not None:
                b = _bin_of(event_time, cutoff_ns, horizon)
                if b is None:
                    # Event beyond the modeled horizon: censored-at-horizon
                    # follow-up is complete only through the last full bin.
                    risk_mask[slot, :, t] = True
                elif b == 0:
                    # Already-onset entity: excluded from this task's risk set
                    # (Section 11 initial-onset rule).
                    pass
                else:
                    event_y[slot, b - 1, t] = 1.0
                    risk_mask[slot, :b, t] = True
            else:
                # No event: censored at observed follow-up; incomplete bins
                # contribute no negative labels (Section 15).
                complete = int((followup_end - cutoff_ns) // WINDOW_NS)
                if complete > 0:
                    risk_mask[slot, : min(complete, horizon), t] = True

    # Stage labels: tactic activity windows projected onto future bins.
    stage_labels = torch.zeros(n, horizon, 5)
    stage_mask = torch.ones(n, horizon, 5, dtype=torch.bool)
    for entity, tactic_idx, from_ns, to_ns in stage_windows:
        if entity not in slot_of:
            continue
        slot = slot_of[entity]
        for h in range(horizon):
            bin_start = cutoff_ns + h * WINDOW_NS
            bin_end = bin_start + WINDOW_NS
            if from_ns < bin_end and to_ns > bin_start:
                stage_labels[slot, h, tactic_idx] = 1.0

    # Observable future targets in the transformed space (Section 14).
    if future_windows is not None and scaler is not None and len(future_windows):
        node_values, node_valid, global_values, global_valid = future_window_targets(
            future_windows[:horizon], scaler, horizon
        )
    else:
        node_values = torch.zeros(n, horizon, 44)
        node_valid = torch.zeros(n, horizon, 44, dtype=torch.bool)
        global_values = torch.zeros(horizon, 24)
        global_valid = torch.zeros(horizon, 24, dtype=torch.bool)

    # Edge labels on the frozen candidate set: all directed internal pairs.
    candidates = all_pair_candidates(n)
    e_pairs = int(candidates.source.shape[0])
    edge_labels = torch.zeros(e_pairs, horizon)
    edge_mask = torch.ones(e_pairs, horizon, dtype=torch.bool)
    if future_windows is not None:
        for h, window in enumerate(future_windows[:horizon]):
            if window.window_index < 0:
                continue
            active = set(
                zip(window.edge_index[0].tolist(), window.edge_index[1].tolist())
            )
            for e in range(e_pairs):
                u = int(candidates.source[e])
                v = int(candidates.target[e])
                if (u, v) in active:
                    edge_labels[e, h] = 1.0

    return ClipTargets(
        event_y=event_y,
        risk_mask=risk_mask,
        stage_labels=stage_labels,
        stage_mask=stage_mask,
        node_values=node_values,
        node_valid=node_valid,
        global_values=global_values,
        global_valid=global_valid,
        edge_labels=edge_labels,
        edge_mask=edge_mask,
        candidate_pairs=candidates,
        task_mask=task_mask,
        split=split,
        num_event_tasks=j,
    )


def future_window_targets(
    windows: list[RawGraphWindow], scaler: FeatureScaler, horizon: int
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Transformed-space [N, H, 44] / [H, 24] future observable targets."""
    n = len(windows[0].ordered_entity_ids) if windows else 0
    node_values = torch.zeros(n, horizon, 44)
    node_valid = torch.zeros(n, horizon, 44, dtype=torch.bool)
    global_values = torch.zeros(horizon, 24)
    global_valid = torch.zeros(horizon, 24, dtype=torch.bool)
    for h, window in enumerate(windows[:horizon]):
        node_x, _edge_x, _global_x, nv, _ev, gv = transform_window(window, scaler)
        node_values[:, h, :] = torch.from_numpy(node_x[:, :44])
        node_valid[:, h, :] = torch.from_numpy(nv)
        global_values[h, :] = torch.from_numpy(_global_x[:24])
        global_valid[h, :] = torch.from_numpy(gv)
    return node_values, node_valid, global_values, global_valid


def stage_activity_from_stages(stages) -> list[tuple[str, int, int, int]]:
    """Normalize campaign stage records into (entity, tactic_idx, from, to)."""
    out = []
    for s in stages:
        out.append((s.entity, s.tactic_index, s.from_ns, s.to_ns))
    return out
