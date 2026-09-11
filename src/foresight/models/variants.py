"""Heterogeneous ensemble members (Build Spec I.5, Tier B item 4).

I.5: "Different encoders, transitions and heads are independently trained;
three dropout calls or three heads do not meet this contract." The locked
Tier A profile keeps the Section-13 reference exactly; the Tier B ensemble
adds two architecturally distinct members that share only the frozen
interface dimensions (entity memory 64, endpoint readout 192, edge readout
256, global LSTM 152/128/2 — Section 35):

- ``gate``  : two-layer GAT encoder (6x16 concat, 8x8 average), a GRUCell
              *gated* entity transition (next = GRU(input, current) rather
              than identity-plus-delta), narrow 32-wide heads and a direct
              LayerNorm global-context map.
- ``wide``  : three-layer GAT encoder at different widths (6x24, 4x36,
              8x8), a sigmoid-gated residual transition
              (next = current + gate * MLP(endpoint)) and deep
              two-hidden-layer heads (192 -> 96 -> 48 -> J).

Every variant implements the same H.1 tensor interface, so the runtime,
trainer and evaluation harness run all members unchanged.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch_geometric.nn import GATConv, GraphNorm

from .config import CoreConfig
from .decoders import GlobalObservationDecoder, NodeObservationDecoder
from .global_adapter import GlobalAdapter
from .heads import EdgeHead, HazardHead, TacticHead
from .transition import TransitionPrior, masked_mean_max_pool
from .types import WorldState
from .world_model import ForesightWorldModel

VARIANTS: tuple[str, ...] = ("reference", "gate", "wide")


def _with_self_loops(edge_index: Tensor, edge_attr: Tensor, num_nodes: int):
    from torch_geometric.utils import remove_self_loops

    edge_index, edge_attr = remove_self_loops(edge_index, edge_attr)
    loops = torch.arange(num_nodes, device=edge_index.device).repeat(2, 1)
    loop_attr = edge_attr.new_zeros(num_nodes, edge_attr.shape[1])
    return torch.cat([edge_index, loops], dim=1), torch.cat(
        [edge_attr, loop_attr], dim=0
    )


class GatedGraphEncoder(nn.Module):
    """Two-layer directed GAT: 88 -> 96 (6x16 concat) -> 64 (8 averaged heads)."""

    def __init__(self, node_input: int, edge_input: int, *, dropout: float = 0.1):
        super().__init__()
        self.gat1 = GATConv(
            node_input, 16, heads=6, concat=True, edge_dim=edge_input,
            add_self_loops=False, dropout=dropout,
        )
        self.norm1 = GraphNorm(96)
        self.gat2 = GATConv(
            96, 64, heads=8, concat=False, edge_dim=edge_input,
            add_self_loops=False, dropout=dropout,
        )
        self.norm2 = GraphNorm(64)

    def forward(self, x, edge_index, edge_attr, batch) -> Tensor:
        num_nodes = x.shape[0]
        edge_index, edge_attr = _with_self_loops(edge_index, edge_attr, num_nodes)
        h = F.elu(self.norm1(self.gat1(x, edge_index, edge_attr), batch))
        h = F.elu(self.norm2(self.gat2(h, edge_index, edge_attr), batch))
        return h


class WideGraphEncoder(nn.Module):
    """Three-layer directed GAT at wide intermediate widths: 88 -> 144 (6x24
    concat) -> 144 (4x36 concat) -> 64 (8 averaged heads)."""

    def __init__(self, node_input: int, edge_input: int, *, dropout: float = 0.1):
        super().__init__()
        self.gat1 = GATConv(
            node_input, 24, heads=6, concat=True, edge_dim=edge_input,
            add_self_loops=False, dropout=dropout,
        )
        self.norm1 = GraphNorm(144)
        self.gat2 = GATConv(
            144, 36, heads=4, concat=True, edge_dim=edge_input,
            add_self_loops=False, dropout=dropout,
        )
        self.norm2 = GraphNorm(144)
        self.gat3 = GATConv(
            144, 64, heads=8, concat=False, edge_dim=edge_input,
            add_self_loops=False, dropout=dropout,
        )
        self.norm3 = GraphNorm(64)

    def forward(self, x, edge_index, edge_attr, batch) -> Tensor:
        num_nodes = x.shape[0]
        edge_index, edge_attr = _with_self_loops(edge_index, edge_attr, num_nodes)
        h = F.elu(self.norm1(self.gat1(x, edge_index, edge_attr), batch))
        h = F.elu(self.norm2(self.gat2(h, edge_index, edge_attr), batch))
        h = F.elu(self.norm3(self.gat3(h, edge_index, edge_attr), batch))
        return h


class GruTransition(nn.Module):
    """Gated entity transition: ``next = GRUCell(project(endpoint), current)``.

    A GRU's learned update/reset gates keep per-entity information without
    the explicit additive residual of the reference prior — a genuinely
    different dynamics family with the same H.3 input contract (192-wide
    endpoint representation). The global context uses a direct LayerNorm
    map from the top hidden state.
    """

    def __init__(self, entity_dim: int, global_hidden: int, global_context_dim: int):
        super().__init__()
        self.entity_dim = entity_dim
        self.global_hidden = global_hidden
        self.project = nn.Linear(entity_dim + global_hidden, entity_dim)
        self.cell = nn.GRUCell(entity_dim, entity_dim)
        self.global_mlp = nn.Sequential(
            nn.Linear(global_hidden, 64), nn.ELU(), nn.Linear(64, global_context_dim)
        )
        self.global_norm = nn.LayerNorm(global_context_dim)

    def forward(self, state: WorldState):
        h_top = state.global_h[-1]
        b, n, _ = state.entity_memory.shape
        endpoint = torch.cat(
            [state.entity_memory, h_top.unsqueeze(1).expand(b, n, self.global_hidden)],
            dim=-1,
        )
        flat = self.cell(
            self.project(endpoint).reshape(b * n, self.entity_dim),
            state.entity_memory.reshape(b * n, self.entity_dim),
        )
        entity_next = flat.reshape(b, n, self.entity_dim)
        global_next = self.global_norm(
            state.global_context + self.global_mlp(h_top)
        )
        pooled = masked_mean_max_pool(entity_next, state.node_present)
        lstm_input = torch.cat([pooled, global_next], dim=-1)
        return entity_next, global_next, lstm_input


class GatedResidualTransition(nn.Module):
    """Sigmoid-gated residual: ``next = current + sigmoid(gate) * MLP(endpoint)``.

    The gate lets each entity modulate how far the MLP delta may move its
    memory — between the reference's always-on residual and a direct map.
    Global context keeps the reference residual form at different widths.
    """

    def __init__(self, entity_dim: int, global_hidden: int, global_context_dim: int):
        super().__init__()
        self.global_hidden = global_hidden
        endpoint_dim = entity_dim + global_hidden
        self.gate = nn.Sequential(
            nn.Linear(endpoint_dim, 64), nn.ELU(), nn.Linear(64, entity_dim)
        )
        self.delta = nn.Sequential(
            nn.Linear(endpoint_dim, 96), nn.ELU(), nn.Linear(96, entity_dim)
        )
        self.global_mlp = nn.Sequential(
            nn.Linear(global_hidden, 48), nn.ELU(), nn.Linear(48, global_context_dim)
        )

    def forward(self, state: WorldState):
        h_top = state.global_h[-1]
        b, n, _ = state.entity_memory.shape
        endpoint = torch.cat(
            [state.entity_memory, h_top.unsqueeze(1).expand(b, n, self.global_hidden)],
            dim=-1,
        )
        entity_next = state.entity_memory + torch.sigmoid(
            self.gate(endpoint)
        ) * self.delta(endpoint)
        global_next = state.global_context + self.global_mlp(h_top)
        pooled = masked_mean_max_pool(entity_next, state.node_present)
        lstm_input = torch.cat([pooled, global_next], dim=-1)
        return entity_next, global_next, lstm_input


class NarrowHazardHead(nn.Module):
    """192 -> 32 -> J (single narrow hidden layer)."""

    def __init__(self, input_dim: int, num_tasks: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 32), nn.ELU(), nn.Linear(32, num_tasks)
        )

    def forward(self, endpoint: Tensor) -> Tensor:
        return self.net(endpoint)


class NarrowTacticHead(nn.Module):
    def __init__(self, input_dim: int, num_tags: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 32), nn.ELU(), nn.Linear(32, num_tags)
        )

    def forward(self, endpoint: Tensor) -> Tensor:
        return self.net(endpoint)


class NarrowEdgeHead(nn.Module):
    def __init__(self, input_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 32), nn.ELU(), nn.Linear(32, 1)
        )

    def forward(self, pair_repr: Tensor) -> Tensor:
        return self.net(pair_repr).squeeze(-1)


class DeepHazardHead(nn.Module):
    """192 -> 96 -> 48 -> J (two hidden layers)."""

    def __init__(self, input_dim: int, num_tasks: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 96), nn.ELU(),
            nn.Linear(96, 48), nn.ELU(),
            nn.Linear(48, num_tasks),
        )

    def forward(self, endpoint: Tensor) -> Tensor:
        return self.net(endpoint)


class DeepTacticHead(nn.Module):
    def __init__(self, input_dim: int, num_tags: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 96), nn.ELU(),
            nn.Linear(96, 48), nn.ELU(),
            nn.Linear(48, num_tags),
        )

    def forward(self, endpoint: Tensor) -> Tensor:
        return self.net(endpoint)


class DeepEdgeHead(nn.Module):
    def __init__(self, input_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 96), nn.ELU(),
            nn.Linear(96, 48), nn.ELU(),
            nn.Linear(48, 1),
        )

    def forward(self, pair_repr: Tensor) -> Tensor:
        return self.net(pair_repr).squeeze(-1)


def build_world_model(
    config: CoreConfig, *, variant: str = "reference", num_event_tasks: int = 5
) -> ForesightWorldModel:
    """Assemble a world model of the requested variant.

    The H.1 interface, frozen Section-35 dimensions and the observation
    semantics are identical across variants; only the encoder, transition
    and head families differ (I.5 heterogeneous ensemble).
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
    model = ForesightWorldModel.from_config(config, num_event_tasks=num_event_tasks)
    if variant == "reference":
        return model

    f, m = config.features, config.model
    if variant == "gate":
        model.graph_encoder = GatedGraphEncoder(
            f.node_input, f.edge_input, dropout=m.attention_dropout
        )
        model.prior = GruTransition(
            m.entity_embedding, m.global_lstm_hidden, f.global_adapter_output
        )
        model.hazard_head = NarrowHazardHead(m.endpoint_head_input, num_event_tasks)
        model.tactic_head = NarrowTacticHead(
            m.endpoint_head_input, m.num_tactic_tags
        )
        model.edge_head = NarrowEdgeHead(m.edge_head_input)
    elif variant == "wide":
        model.graph_encoder = WideGraphEncoder(
            f.node_input, f.edge_input, dropout=m.attention_dropout
        )
        model.prior = GatedResidualTransition(
            m.entity_embedding, m.global_lstm_hidden, f.global_adapter_output
        )
        model.hazard_head = DeepHazardHead(m.endpoint_head_input, num_event_tasks)
        model.tactic_head = DeepTacticHead(m.endpoint_head_input, m.num_tactic_tags)
        model.edge_head = DeepEdgeHead(m.edge_head_input)
    return model


def variant_of(model: ForesightWorldModel) -> str:
    """Infer the variant name of an assembled model (for manifests)."""
    enc = type(model.graph_encoder).__name__
    prior = type(model.prior).__name__
    if enc == "DirectedGraphEncoder" and prior == "TransitionPrior":
        return "reference"
    if enc == "GatedGraphEncoder" and prior == "GruTransition":
        return "gate"
    if enc == "WideGraphEncoder" and prior == "GatedResidualTransition":
        return "wide"
    return "custom"
