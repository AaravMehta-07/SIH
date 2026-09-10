"""Directed graph attention encoder (Build Spec Section 13, G.3; ADR-001).

Three directed GAT layers: 88 -> 128 (4x32 concatenated heads), 128 -> 128
(4x32 concatenated heads), 128 -> 64 (4x64 averaged heads). ELU and per-graph
GraphNorm over real nodes after each layer. Attention dropout 0.1 in training.

Computational self-loops carry explicit zero edge attributes and are constructed
deliberately here (GATConv ``add_self_loops=False``); observed self-loops are
removed first so no node is ever double-looped. Reverse edges are never fabricated.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch_geometric.nn import GATConv, GraphNorm
from torch_geometric.utils import remove_self_loops


class DirectedGraphEncoder(nn.Module):
    def __init__(
        self,
        node_input: int,
        edge_input: int,
        *,
        attention_dropout: float = 0.1,
        graph_norm_eps: float = 1e-5,
    ) -> None:
        super().__init__()
        self.edge_input = edge_input
        # 88 -> 128 with four 32-wide concatenated heads.
        self.gat1 = GATConv(
            node_input,
            32,
            heads=4,
            concat=True,
            edge_dim=edge_input,
            add_self_loops=False,
            dropout=attention_dropout,
        )
        self.norm1 = GraphNorm(128, eps=graph_norm_eps)
        # 128 -> 128 with four 32-wide concatenated heads.
        self.gat2 = GATConv(
            128,
            32,
            heads=4,
            concat=True,
            edge_dim=edge_input,
            add_self_loops=False,
            dropout=attention_dropout,
        )
        self.norm2 = GraphNorm(128, eps=graph_norm_eps)
        # 128 -> 64 with four 64-wide averaged heads.
        self.gat3 = GATConv(
            128,
            64,
            heads=4,
            concat=False,
            edge_dim=edge_input,
            add_self_loops=False,
            dropout=attention_dropout,
        )
        self.norm3 = GraphNorm(64, eps=graph_norm_eps)

    def _with_self_loops(
        self, edge_index: Tensor, edge_attr: Tensor, num_nodes: int
    ) -> tuple[Tensor, Tensor]:
        """One zero-attribute self-loop per real node, after dropping observed ones."""
        edge_index, edge_attr = remove_self_loops(edge_index, edge_attr)
        loops = torch.arange(num_nodes, device=edge_index.device).repeat(2, 1)
        loop_attr = edge_attr.new_zeros(num_nodes, self.edge_input)
        return torch.cat([edge_index, loops], dim=1), torch.cat(
            [edge_attr, loop_attr], dim=0
        )

    def forward(
        self, x: Tensor, edge_index: Tensor, edge_attr: Tensor, batch: Tensor
    ) -> Tensor:
        """Encode real nodes of a batched graph window; returns ``[T, 64]``."""
        num_nodes = x.shape[0]
        edge_index, edge_attr = self._with_self_loops(
            edge_index, edge_attr, num_nodes
        )
        h = F.elu(self.norm1(self.gat1(x, edge_index, edge_attr), batch))
        h = F.elu(self.norm2(self.gat2(h, edge_index, edge_attr), batch))
        h = F.elu(self.norm3(self.gat3(h, edge_index, edge_attr), batch))
        return h
