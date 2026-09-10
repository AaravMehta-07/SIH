"""Shared fixtures: synthetic golden graph windows (Build Spec R.1 spirit).

The builders produce legal ``GraphWindowBatch`` tensors for the 88/22/48 contract
with deterministic seeds, so model tests never depend on other modules being
implemented (Team Work Distribution: "Develop against typed fixtures").
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from foresight.models.config import CoreConfig, load_core_config
from foresight.models.types import CandidatePairs, GraphWindowBatch
from foresight.models.world_model import ForesightWorldModel

REPO_ROOT = Path(__file__).resolve().parents[1]

NODE_VALUES = 44
EDGE_VALUES = 11
GLOBAL_VALUES = 24


@pytest.fixture(scope="session")
def core_config() -> CoreConfig:
    return load_core_config(REPO_ROOT / "configs" / "core.yaml")


@pytest.fixture()
def model(core_config: CoreConfig) -> ForesightWorldModel:
    torch.manual_seed(0)
    m = ForesightWorldModel.from_config(core_config, num_event_tasks=5)
    m.eval()
    return m


def build_window(
    *,
    num_graphs: int = 1,
    num_slots: int = 4,
    present: torch.Tensor | None = None,
    observation_valid: torch.Tensor | None = None,
    edges: list[list[tuple[int, int]]] | None = None,
    global_raw: torch.Tensor | None = None,
    seed: int = 0,
) -> GraphWindowBatch:
    """Deterministic synthetic window batch honoring the D.5 tensor contract.

    Observed nodes get random features with mostly-true validity bits; present
    but unobserved nodes get zero values with zero validity bits (invalid values
    are zero with validity bit zero, F.8).
    """
    gen = torch.Generator().manual_seed(seed)
    if present is None:
        present = torch.ones(num_graphs, num_slots, dtype=torch.bool)
    if observation_valid is None:
        observation_valid = torch.ones(num_graphs, num_slots, dtype=torch.bool)
    if present.shape != (num_graphs, num_slots):
        raise ValueError("present must be [num_graphs, num_slots]")
    if observation_valid.shape != (num_graphs, num_slots):
        raise ValueError("observation_valid must be [num_graphs, num_slots]")

    # Node rows: graph-major, ascending slot order among present slots.
    rows: list[tuple[int, int]] = []  # (graph, slot) in row order
    row_of: dict[tuple[int, int], int] = {}
    for b in range(num_graphs):
        for s in range(num_slots):
            if bool(present[b, s]):
                row_of[(b, s)] = len(rows)
                rows.append((b, s))
    if not rows:
        raise ValueError("empty scopes are rejected before model pooling (D.5)")

    batch = torch.tensor([b for b, _ in rows], dtype=torch.int64)
    slot_index = torch.tensor([s for _, s in rows], dtype=torch.int64)
    x = torch.zeros(len(rows), 2 * NODE_VALUES)
    for i, (b, s) in enumerate(rows):
        if bool(observation_valid[b, s]):
            values = torch.randn(NODE_VALUES, generator=gen) * 0.5
            bits = (torch.rand(NODE_VALUES, generator=gen) < 0.9).float()
            x[i] = torch.cat([values, bits])

    if edges is None:
        edges = [[(0, 1), (1, 2)]] + [[] for _ in range(num_graphs - 1)]
    edge_list: list[tuple[int, int, int]] = []  # (b, src_slot, dst_slot)
    for b, edges_b in enumerate(edges):
        if b >= num_graphs:
            break
        for s_src, s_dst in edges_b:
            edge_list.append((b, s_src, s_dst))
    edge_index = torch.zeros(2, len(edge_list), dtype=torch.int64)
    edge_attr = torch.zeros(len(edge_list), 2 * EDGE_VALUES)
    for i, (b, s_src, s_dst) in enumerate(edge_list):
        edge_index[0, i] = row_of[(b, s_src)]
        edge_index[1, i] = row_of[(b, s_dst)]
        values = torch.randn(EDGE_VALUES, generator=gen) * 0.5
        bits = (torch.rand(EDGE_VALUES, generator=gen) < 0.9).float()
        edge_attr[i] = torch.cat([values, bits])

    if global_raw is None:
        global_raw = torch.randn(num_graphs, 2 * GLOBAL_VALUES, generator=gen)

    window = GraphWindowBatch(
        x=x,
        edge_index=edge_index,
        edge_attr=edge_attr,
        batch=batch,
        slot_index=slot_index,
        node_present=present,
        node_observation_valid=observation_valid,
        global_raw=global_raw,
    )
    window.validate()
    return window


def build_clip(
    num_windows: int = 20, seed: int = 0, **window_kwargs
) -> list[GraphWindowBatch]:
    """A clip of windows sharing one stable entity union (G.2)."""
    if "num_graphs" in window_kwargs or "num_slots" in window_kwargs:
        shape = (
            window_kwargs.get("num_graphs", 1),
            window_kwargs.get("num_slots", 4),
        )
    else:
        shape = (1, 4)
    present = window_kwargs.pop("present", None)
    if present is None:
        present = torch.ones(*shape, dtype=torch.bool)
    observation_valid = window_kwargs.pop("observation_valid", None)
    if observation_valid is None:
        observation_valid = torch.ones(*shape, dtype=torch.bool)
    return [
        build_window(
            present=present,
            observation_valid=observation_valid,
            seed=seed + i,
            **window_kwargs,
        )
        for i in range(num_windows)
    ]


def build_candidates(
    num_graphs: int = 1, pairs: list[tuple[int, int, int]] | None = None
) -> CandidatePairs:
    """Candidate pairs as (graph, src_slot, dst_slot)."""
    if pairs is None:
        pairs = [(0, 0, 1), (0, 1, 2), (0, 2, 3)]
    return CandidatePairs(
        batch_index=torch.tensor([p[0] for p in pairs], dtype=torch.int64),
        source=torch.tensor([p[1] for p in pairs], dtype=torch.int64),
        target=torch.tensor([p[2] for p in pairs], dtype=torch.int64),
    )


def build_targets(
    *,
    num_nodes: int = 4,
    horizon_bins: int = 60,
    num_tasks: int = 5,
    candidates: CandidatePairs | None = None,
    event_specs: dict[tuple[int, int], int] | None = None,
    censor_bins: int | None = None,
    task_mask: torch.Tensor | None = None,
    node_valid: torch.Tensor | None = None,
    global_valid: torch.Tensor | None = None,
    edge_mask: torch.Tensor | None = None,
    split: str = "train",
    seed: int = 0,
):
    """Deterministic synthetic ClipTargets (Appendix D.6).

    ``event_specs[(n, t)] = k >= 1`` places the first observed event of task t
    for entity n in bin k (risk bins stop at k). ``= 0`` marks a censored row
    with follow-up of ``censor_bins`` (default: full horizon). Unlisted rows
    are censored with full follow-up.
    """
    from foresight.training.targets import ClipTargets

    gen = torch.Generator().manual_seed(seed)
    N, H, J = num_nodes, horizon_bins, num_tasks
    if candidates is None:
        candidates = build_candidates()
    if censor_bins is None:
        censor_bins = H

    event_y = torch.zeros(N, H, J)
    risk_mask = torch.ones(N, H, J, dtype=torch.bool)
    for (n, t), k in (event_specs or {}).items():
        if k >= 1:
            event_y[n, k - 1, t] = 1.0
            risk_mask[n, :, t] = False
            risk_mask[n, :k, t] = True
        else:
            risk_mask[n, :, t] = False
            risk_mask[n, :censor_bins, t] = True

    stage_labels = (torch.rand(N, H, 5, generator=gen) < 0.2).float()
    stage_mask = torch.ones(N, H, 5, dtype=torch.bool)
    node_values = torch.randn(N, H, NODE_VALUES, generator=gen)
    if node_valid is None:
        node_valid = torch.rand(N, H, NODE_VALUES, generator=gen) < 0.95
    global_values = torch.randn(H, GLOBAL_VALUES, generator=gen)
    if global_valid is None:
        global_valid = torch.rand(H, GLOBAL_VALUES, generator=gen) < 0.95
    E = int(candidates.batch_index.shape[0])
    edge_labels = (torch.rand(E, H, generator=gen) < 0.3).float()
    if edge_mask is None:
        edge_mask = torch.rand(E, H, generator=gen) < 0.9
    if task_mask is None:
        task_mask = torch.ones(J, dtype=torch.bool)

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
        num_event_tasks=num_tasks,
    )


def observed_state(model: ForesightWorldModel, clip: list[GraphWindowBatch]):
    state = model.zero_state(clip[0].node_present)
    for window in clip:
        state = model.observe_window(state, window)
    return state
