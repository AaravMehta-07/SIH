"""Learned transition prior MLPs (Build Spec Section 14, H.3; ADR-001).

The transition prior is deterministic in latent space and probabilistic in its
observable/event emissions (Section 14). This module predicts the next entity
memories and the next global context from the current state:

- Entity: endpoint representation ``[entity_memory || global_h_top]`` (192)
  -> 128 -> 64 next entity memory. The 192-wide input uses the 128-wide top
  hidden state, NOT the 24-wide adapter output (H.3 explicit dimension note).
- Global: current top hidden state (128) -> 64 -> 24 next global context.
- The LSTM advance uses the same shared global LSTM as observation and lives in
  ``ForesightWorldModel.transition_prior`` so one instance serves both paths.

No future observed graph is fed into the prior (MO03).
"""

from __future__ import annotations

import torch
from torch import Tensor, nn

from .types import WorldState


def masked_mean_max_pool(entity_memory: Tensor, node_present: Tensor) -> Tensor:
    """Masked mean and max pooling over present entities (Section 13, H.1).

    ``[B, N, D]`` + ``[B, N]`` bool -> ``[B, 2D]``. Empty scopes are rejected
    upstream before pooling (D.5); a defensive zero-present graph yields zeros.
    """
    mask = node_present.unsqueeze(-1).to(entity_memory.dtype)
    denom = mask.sum(dim=1).clamp_min(1.0)
    mean = (entity_memory * mask).sum(dim=1) / denom
    filled = entity_memory.masked_fill(
        ~node_present.unsqueeze(-1), torch.finfo(entity_memory.dtype).min
    )
    max_ = filled.amax(dim=1)
    any_present = node_present.any(dim=1, keepdim=True)
    max_ = torch.where(any_present, max_, torch.zeros_like(max_))
    return torch.cat([mean, max_], dim=-1)


class TransitionPrior(nn.Module):
    """Residual transition (ADR-001): ``next = current + MLP([current || h_top])``.

    A direct regression contracts entity memories toward the pooled mean at
    every rollout step (measured: per-entity memory std 0.39 -> 0.065 after a
    single transition), which erases entity-specific hazards by bin ~5. The
    residual parameterization predicts the *change* — identity-plus-delta —
    so entity discrimination survives long free rollouts. Shapes follow H.3
    exactly: 192 -> 128 -> 64 with ELU between linear layers.
    """

    def __init__(
        self,
        entity_dim: int,
        global_hidden: int,
        global_context_dim: int,
    ) -> None:
        super().__init__()
        self.entity_dim = entity_dim
        self.global_hidden = global_hidden
        endpoint_dim = entity_dim + global_hidden  # 192
        self.entity_mlp = nn.Sequential(
            nn.Linear(endpoint_dim, 128),
            nn.ELU(),
            nn.Linear(128, entity_dim),
        )
        self.global_mlp = nn.Sequential(
            nn.Linear(global_hidden, 64),
            nn.ELU(),
            nn.Linear(64, global_context_dim),
        )

    def forward(
        self, state: WorldState
    ) -> tuple[Tensor, Tensor, Tensor]:
        """Predict ``(next_entity_memory, next_global_context, lstm_input)``.

        ``lstm_input`` is the 152-wide ``[masked_mean+max of predicted memories ||
        predicted global context]`` consumed by the shared global LSTM advance.
        """
        h_top = state.global_h[-1]  # [B, 128]
        b, n, _ = state.entity_memory.shape
        endpoint = torch.cat(
            [
                state.entity_memory,
                h_top.unsqueeze(1).expand(b, n, self.global_hidden),
            ],
            dim=-1,
        )
        entity_next = state.entity_memory + self.entity_mlp(endpoint)  # [B, N, 64]
        global_next = state.global_context + self.global_mlp(h_top)    # [B, 24]
        pooled = masked_mean_max_pool(entity_next, state.node_present)  # [B, 128]
        lstm_input = torch.cat([pooled, global_next], dim=-1)  # [B, 152]
        return entity_next, global_next, lstm_input
