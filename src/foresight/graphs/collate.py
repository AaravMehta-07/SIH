"""Window collation into the frozen GraphWindowBatch contract (G.2, S).

The entity union is stable for the whole 20-window clip (G.2): every window
is collated against the same ``ordered_entity_ids``, with ``node_present``
distinguishing padding and ``node_observation_valid`` distinguishing healthy
idle from a failed observation channel (D.5).
"""

from __future__ import annotations

import numpy as np
import torch

from ..features.transforms import FeatureScaler, transform_window
from ..features.windows import RawGraphWindow
from ..models.types import ContractError, GraphWindowBatch


def entity_union(windows: list[RawGraphWindow]) -> tuple[str, ...]:
    """Stable clip union: the scope's ordered entity list is already stable;
    collation verifies it rather than rebuilding it from observations (G.2 —
    membership never depends on future labels)."""
    if not windows:
        raise ContractError("a clip needs at least one window")
    first = windows[0].ordered_entity_ids
    for w in windows[1:]:
        if w.ordered_entity_ids != first:
            raise ContractError(
                "entity union must be stable across the clip (G.2): "
                f"{first} vs {w.ordered_entity_ids}"
            )
    return first


def collate_windows(
    windows: list[RawGraphWindow], scaler: FeatureScaler
) -> list[GraphWindowBatch]:
    """Scale and collate the clip's windows (single-graph batch, B=1)."""
    entity_ids = entity_union(windows)
    n = len(entity_ids)
    batches: list[GraphWindowBatch] = []
    for window in windows:
        node_x, edge_x, global_x, _nv, _ev, _gv = transform_window(window, scaler)
        if node_x.shape[0] != n:
            raise ContractError(
                f"window has {node_x.shape[0]} nodes, expected clip union {n}"
            )
        edge_index = torch.from_numpy(
            np.ascontiguousarray(window.edge_index)
        ).long()
        batch = GraphWindowBatch(
            x=torch.from_numpy(np.ascontiguousarray(node_x)),
            edge_index=edge_index,
            edge_attr=torch.from_numpy(np.ascontiguousarray(edge_x)),
            batch=torch.zeros(n, dtype=torch.int64),
            slot_index=torch.arange(n, dtype=torch.int64),
            node_present=torch.from_numpy(
                np.ascontiguousarray(window.node_present)
            ).unsqueeze(0),
            node_observation_valid=torch.from_numpy(
                np.ascontiguousarray(window.node_observation_valid)
            ).unsqueeze(0),
            global_raw=torch.from_numpy(np.ascontiguousarray(global_x)).unsqueeze(0),
        )
        batch.validate()
        batches.append(batch)
    return batches


def stack_windows(windows: list[GraphWindowBatch]) -> GraphWindowBatch:
    """Stack same-timestep window batches of several clips into one
    batched graph (G.2): concatenated node rows, offset edge indices, no
    cross-graph edges (GR01). All inputs must share the slot count."""
    if not windows:
        raise ContractError("stacking needs at least one window")
    n = windows[0].num_slots
    for w in windows:
        if w.num_slots != n:
            raise ContractError("stacked windows must share the slot count")
        w.validate()

    x = torch.cat([w.x for w in windows], dim=0)
    edge_attr = (
        torch.cat([w.edge_attr for w in windows], dim=0)
        if any(w.num_edges for w in windows)
        else torch.zeros((0, windows[0].edge_attr.shape[1]), dtype=torch.float32)
    )
    edge_cols = []
    offset = 0
    for w in windows:
        if w.num_edges:
            edge_cols.append(w.edge_index + offset)
        offset += w.num_nodes
    edge_index = (
        torch.cat(edge_cols, dim=1) if edge_cols
        else torch.zeros((2, 0), dtype=torch.int64)
    )
    batch = torch.cat([w.batch + i for i, w in enumerate(windows)], dim=0)
    slot_index = torch.cat([w.slot_index for w in windows], dim=0)
    return GraphWindowBatch(
        x=x,
        edge_index=edge_index,
        edge_attr=edge_attr,
        batch=batch,
        slot_index=slot_index,
        node_present=torch.cat([w.node_present for w in windows], dim=0),
        node_observation_valid=torch.cat(
            [w.node_observation_valid for w in windows], dim=0
        ),
        global_raw=torch.cat([w.global_raw for w in windows], dim=0),
    )


def stack_candidates(candidates: list) -> "CandidatePairs":
    """Stack per-clip candidate pair sets with batch indices (Section 14)."""
    from ..models.types import CandidatePairs as _CP

    sources, targets, batches = [], [], []
    for b, c in enumerate(candidates):
        sources.append(c.source)
        targets.append(c.target)
        batches.append(torch.full((c.source.shape[0],), b, dtype=torch.int64))
    if not sources:
        return _CP(
            batch_index=torch.zeros(0, dtype=torch.int64),
            source=torch.zeros(0, dtype=torch.int64),
            target=torch.zeros(0, dtype=torch.int64),
        )
    return _CP(
        batch_index=torch.cat(batches),
        source=torch.cat(sources),
        target=torch.cat(targets),
    )


def collate_batch(
    per_graph_windows: list[list[RawGraphWindow]],
    scaler: FeatureScaler,
    *,
    num_slots: int | None = None,
) -> GraphWindowBatch:
    """Collate one window index across a batch of graphs (G.2 padding).

    Pads every graph to the maximum N in the batch only; real nodes and real
    edges go through PyG-style batching with no message-passing edges to
    padding (GR01) and no cross-graph edges. ``(batch, slot_index)`` pairs
    stay unique.
    """
    if not per_graph_windows:
        raise ContractError("batch needs at least one graph")
    b = len(per_graph_windows)
    n_max = num_slots or max(len(w.ordered_entity_ids) for w in (
        g[0] for g in per_graph_windows
    ))

    x_rows: list[np.ndarray] = []
    edge_rows: list[np.ndarray] = []
    edge_index_cols: list[np.ndarray] = []
    batch_index: list[int] = []
    slot_index: list[int] = []
    node_present = np.zeros((b, n_max), dtype=bool)
    node_obs_valid = np.zeros((b, n_max), dtype=bool)
    global_rows: list[np.ndarray] = []

    row_offset = 0
    for g, windows in enumerate(per_graph_windows):
        window = windows[0]  # caller passes one window per graph
        node_x, edge_x, global_x, _nv, _ev, _gv = transform_window(window, scaler)
        n = len(window.ordered_entity_ids)
        if n > n_max:
            raise ContractError("graph exceeds the batch's padded slot count")
        node_present[g, :n] = window.node_present
        node_obs_valid[g, :n] = window.node_observation_valid
        x_rows.append(node_x)
        batch_index.extend([g] * n)
        slot_index.extend(range(n))
        if len(window.edge_index):
            local = window.edge_index.astype(np.int64)
            edge_index_cols.append(local + row_offset)
            edge_rows.append(edge_x)
        row_offset += n
        global_rows.append(global_x)

    x = np.concatenate(x_rows, axis=0) if x_rows else np.zeros((0, 88), np.float32)
    if edge_index_cols:
        edge_index = np.concatenate(edge_index_cols, axis=1)
        edge_attr = np.concatenate(edge_rows, axis=0)
    else:
        edge_index = np.zeros((2, 0), dtype=np.int64)
        edge_attr = np.zeros((0, 22), np.float32)

    batch = GraphWindowBatch(
        x=torch.from_numpy(np.ascontiguousarray(x)),
        edge_index=torch.from_numpy(np.ascontiguousarray(edge_index)),
        edge_attr=torch.from_numpy(np.ascontiguousarray(edge_attr)),
        batch=torch.tensor(batch_index, dtype=torch.int64),
        slot_index=torch.tensor(slot_index, dtype=torch.int64),
        node_present=torch.from_numpy(node_present),
        node_observation_valid=torch.from_numpy(node_obs_valid),
        global_raw=torch.from_numpy(
            np.ascontiguousarray(np.stack(global_rows))
        ),
    )
    batch.validate()
    return batch
