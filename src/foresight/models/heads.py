"""Prediction heads (Build Spec Section 13, H.2; ADR-001).

All heads use ELU between linear layers and emit raw logits. Sigmoid is applied
only at probability readout, never inside BCE-with-logits (Section 13).
"""

from __future__ import annotations

from torch import Tensor, nn


class HazardHead(nn.Module):
    """Endpoint hazard head: 192 -> 64 -> J for J manifest-qualified event types.

    J is a constructor argument because it comes from the qualified task manifest
    at runtime (Section 11); it is never hard-coded to five.
    """

    def __init__(self, input_dim: int, hidden_dim: int, num_tasks: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ELU(),
            nn.Linear(hidden_dim, num_tasks),
        )

    def forward(self, endpoint: Tensor) -> Tensor:
        """``[..., 192]`` -> hazard logits ``[..., J]``."""
        return self.net(endpoint)


class TacticHead(nn.Module):
    """Multi-label ATT&CK tactic head: 192 -> 64 -> 5.

    Tactics can co-occur (Section 11), so this is multi-label, not a softmax.
    """

    def __init__(self, input_dim: int, hidden_dim: int, num_tags: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ELU(),
            nn.Linear(hidden_dim, num_tags),
        )

    def forward(self, endpoint: Tensor) -> Tensor:
        return self.net(endpoint)


class EdgeHead(nn.Module):
    """Future-communication edge head: 256 -> 64 -> 1.

    Input is ``[source_memory || target_memory || global_h_top]`` for each frozen
    candidate pair (Section 14: marginal future communication probability within
    the scope).
    """

    def __init__(self, input_dim: int, hidden_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ELU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, pair_repr: Tensor) -> Tensor:
        """``[E, 256]`` -> edge logits ``[E]``."""
        return self.net(pair_repr).squeeze(-1)
