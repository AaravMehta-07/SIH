"""Tensor-level contracts for the FORESIGHT world model.

``GraphWindowBatch`` is the tensor contract produced by ``graphs.collate`` (Appendix S)
from the D.5 ``GraphWindow`` records of one decision clip. It is the typed fixture
boundary the model module develops against while the ingest/features/graphs modules
are built in parallel (Team Work Distribution: "Develop against typed fixtures").

``WorldState`` is the H.1 world-model state ``z = (R, h, c, g)``.

All arrays are float32 model tensors. Timestamps never enter the model as features
(Build Spec Section 7); identity is carried by slot sidecars, never embedded
(Build Spec Section 8, G.1).
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor


class ContractError(RuntimeError):
    """Raised when a tensor input violates the model contract (shape, dtype, scope)."""


class NonFiniteTensorError(RuntimeError):
    """Raised when a state or input tensor contains non-finite values (MO05).

    The runtime layer translates this into an explicit ``numeric_failure`` health
    status; it must never be swallowed into a zero-valued forecast (Build Spec H.5).
    """


def _require_finite(tensor: Tensor, name: str) -> None:
    if tensor.numel() == 0:
        return
    if not bool(torch.isfinite(tensor).all()):
        raise NonFiniteTensorError(
            f"{name} contains non-finite values; refusing to produce a forecast "
            f"(Build Spec H.5, test MO05)"
        )


@dataclass
class GraphWindowBatch:
    """One observation window for a batch of graphs (D.5, H.1).

    Fields:
        x: float32 ``[T, node_input]`` graph inputs for the real (present) nodes of
            all graphs, concatenated graph-major in slot order. Layout per node is
            scaled values then validity bits (D.5: 44 + 44 = 88).
        edge_index: int64 ``[2, E]`` observed directed edges as rows into ``x``
            (batch-global). Only observed communication creates edges; reverse
            communication is a separate observed edge (G.3). No cross-graph edges.
        edge_attr: float32 ``[E, edge_input]``; layout is values then validity bits
            (11 + 11 = 22).
        batch: int64 ``[T]`` graph index of each node row.
        slot_index: int64 ``[T]`` entity slot of each node row within its graph's
            padded entity array. ``(batch, slot_index)`` pairs are unique.
        node_present: bool ``[B, N]`` — real entity vs padding (G.2). The entity
            union is stable for the whole 20-window clip.
        node_observation_valid: bool ``[B, N]`` — healthy idle (valid zero features)
            vs failed observation channel (D.5). The GRU update mask is
            ``node_present & node_observation_valid`` (ADR-001, G.2).
        global_raw: float32 ``[B, global_input]``; values then validity bits
            (24 + 24 = 48).

    Computational GAT self-loops are added by the graph encoder with explicit zero
    edge attributes; collate must not include them (ADR-001, G.3).
    """

    x: Tensor
    edge_index: Tensor
    edge_attr: Tensor
    batch: Tensor
    slot_index: Tensor
    node_present: Tensor
    node_observation_valid: Tensor
    global_raw: Tensor

    @property
    def batch_size(self) -> int:
        return int(self.node_present.shape[0])

    @property
    def num_slots(self) -> int:
        return int(self.node_present.shape[1])

    @property
    def num_nodes(self) -> int:
        return int(self.x.shape[0])

    @property
    def num_edges(self) -> int:
        return int(self.edge_index.shape[1])

    def validate(self) -> None:
        """Validate shapes, dtypes, scope consistency and finiteness."""
        t = self.num_nodes
        e = self.num_edges
        b = self.batch_size
        n = self.num_slots

        if self.x.dim() != 2:
            raise ContractError(f"x must be [T, node_input], got {tuple(self.x.shape)}")
        if self.edge_index.dim() != 2 or self.edge_index.shape[0] != 2:
            raise ContractError(
                f"edge_index must be [2, E], got {tuple(self.edge_index.shape)}"
            )
        if self.edge_attr.dim() != 2:
            raise ContractError(
                f"edge_attr must be [E, edge_input], got {tuple(self.edge_attr.shape)}"
            )
        if self.edge_attr.shape[0] != e:
            raise ContractError(
                f"edge_attr rows ({self.edge_attr.shape[0]}) != num edges ({e})"
            )
        if self.batch.shape != (t,):
            raise ContractError(f"batch must be [T]={t}, got {tuple(self.batch.shape)}")
        if self.slot_index.shape != (t,):
            raise ContractError(
                f"slot_index must be [T]={t}, got {tuple(self.slot_index.shape)}"
            )
        if self.node_present.shape != (b, n) or self.node_observation_valid.shape != (
            b,
            n,
        ):
            raise ContractError(
                f"node masks must be [B, N] = [{b}, {n}], got "
                f"{tuple(self.node_present.shape)} / "
                f"{tuple(self.node_observation_valid.shape)}"
            )
        if self.global_raw.dim() != 2 or self.global_raw.shape[0] != b:
            raise ContractError(
                f"global_raw must be [B, global_input] = [{b}, *], got "
                f"{tuple(self.global_raw.shape)}"
            )
        if self.x.dtype != torch.float32 or self.edge_attr.dtype != torch.float32:
            raise ContractError("x and edge_attr must be float32")
        if self.global_raw.dtype != torch.float32:
            raise ContractError("global_raw must be float32")
        if self.node_present.dtype != torch.bool or (
            self.node_observation_valid.dtype != torch.bool
        ):
            raise ContractError("node masks must be bool")

        if e > 0:
            src, dst = self.edge_index
            if int(src.max()) >= t or int(dst.max()) >= t or (
                int(src.min()) < 0 or int(dst.min()) < 0
            ):
                raise ContractError("edge endpoints must index into x rows [0, T)")
            cross = self.batch[src] != self.batch[dst]
            if bool(cross.any()):
                raise ContractError(
                    "cross-graph edges are forbidden (GR01: batched graphs cannot "
                    "communicate across samples)"
                )
        if t > 0:
            if not bool((self.node_present[self.batch, self.slot_index]).all()):
                raise ContractError(
                    "every graph-batch node row must map to a present entity slot"
                )
            pairs = torch.stack([self.batch, self.slot_index], dim=1)
            if int(pairs.unique(dim=0).shape[0]) != t:
                raise ContractError(
                    "(batch, slot_index) pairs must be unique per node row"
                )

        _require_finite(self.x, "window.x")
        _require_finite(self.edge_attr, "window.edge_attr")
        _require_finite(self.global_raw, "window.global_raw")


@dataclass
class CandidatePairs:
    """Frozen candidate edge pairs for the future-communication head (Section 14).

    Indices reference the padded ``[B, N]`` entity arrays of the clip (D.6: edge
    targets refer to the forecast's frozen candidate pairs and never silently add
    future-known hosts to the input graph).
    """

    batch_index: Tensor  # int64 [E]
    source: Tensor  # int64 [E] slot
    target: Tensor  # int64 [E] slot

    def validate(self, batch_size: int, num_slots: int) -> None:
        for name, idx in (
            ("batch_index", self.batch_index),
            ("source", self.source),
            ("target", self.target),
        ):
            if idx.dim() != 1 or idx.dtype != torch.int64:
                raise ContractError(
                    f"candidate pair field {name!r} must be a 1-D int64 tensor"
                )
        if not (
            self.batch_index.shape == self.source.shape == self.target.shape
        ):
            raise ContractError("candidate pair fields must have equal length")
        if self.batch_index.numel() > 0:
            if int(self.batch_index.max()) >= batch_size or (
                int(self.batch_index.min()) < 0
            ):
                raise ContractError("candidate batch_index out of range")
            for name, idx in (("source", self.source), ("target", self.target)):
                if int(idx.max()) >= num_slots or int(idx.min()) < 0:
                    raise ContractError(f"candidate {name} slot out of range")


@dataclass
class WorldState:
    """World-model state ``z = (R, h, c, g)`` (Build Spec H.1).

    Attributes:
        entity_memory: float32 ``[B, N, entity_embedding]`` per-entity GRU memory.
        global_h / global_c: float32 ``[num_layers, B, global_lstm_hidden]`` — the
            full two-layer LSTM state (A29: both hidden and cell survive round-trip).
        global_context: float32 ``[B, global_adapter_output]`` adapted global context.
        node_present: bool ``[B, N]`` — stable entity-union membership of the clip.
    """

    entity_memory: Tensor
    global_h: Tensor
    global_c: Tensor
    global_context: Tensor
    node_present: Tensor

    @classmethod
    def zeros(
        cls,
        node_present: Tensor,
        *,
        entity_embedding: int,
        lstm_hidden: int,
        lstm_layers: int,
        global_adapter_output: int,
    ) -> "WorldState":
        """Documented zero state for a scope (Build Spec Section 26, G.2).

        Training and serving both start each clip from this zero state so the
        20-window context is identical in both (Section 13).
        """
        b, n = node_present.shape
        device = node_present.device
        return cls(
            entity_memory=torch.zeros(b, n, entity_embedding, device=device),
            global_h=torch.zeros(lstm_layers, b, lstm_hidden, device=device),
            global_c=torch.zeros(lstm_layers, b, lstm_hidden, device=device),
            global_context=torch.zeros(b, global_adapter_output, device=device),
            node_present=node_present,
        )

    def clone(self) -> "WorldState":
        """Fresh-storage clone that preserves autograd (MO04: rollout modifies a
        copied state only; H.1: no in-place operation may corrupt a state required
        for backpropagation or a parallel forecast)."""
        return WorldState(
            entity_memory=self.entity_memory.clone(),
            global_h=self.global_h.clone(),
            global_c=self.global_c.clone(),
            global_context=self.global_context.clone(),
            node_present=self.node_present.clone(),
        )

    def validate_finite(self) -> None:
        _require_finite(self.entity_memory, "state.entity_memory")
        _require_finite(self.global_h, "state.global_h")
        _require_finite(self.global_c, "state.global_c")
        _require_finite(self.global_context, "state.global_context")


@dataclass
class DecodedStep:
    """Decoded outputs for one (real or imagined) state (Build Spec H.2).

    Heads emit raw logits; sigmoid is applied only at probability readout
    (Section 13). Node-row outputs for padding slots are computed but carry no
    meaning; consumers mask with ``node_present``.
    """

    node_mean: Tensor  # float32 [B, N, node_values]
    node_log_scale: Tensor  # float32 [B, N, node_values], clamped to [log_scale_min, log_scale_max]
    global_mean: Tensor  # float32 [B, global_values]
    global_log_scale: Tensor  # float32 [B, global_values], clamped
    hazard_logits: Tensor  # float32 [B, N, J]
    tactic_logits: Tensor  # float32 [B, N, num_tactic_tags]
    edge_logits: Tensor | None  # float32 [E] when candidate pairs were given
    hazard_task_mask: Tensor | None  # bool [J] — False dims are unsupported tasks

    @property
    def horizon_note(self) -> str:
        return "state after transition j represents bin j (Section 14)"
