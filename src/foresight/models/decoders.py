"""Observation decoders (Build Spec Section 14, H.2; ADR-001).

The node decoder maps the endpoint representation 192 -> 128 -> 88 (44 means and
44 log-scales for the standardized future node values); the global decoder reads
the imagined top-layer global hidden state 128 -> 64 -> 48 (24 means and 24
log-scales). Log-scales are bounded to [-5, 3] at the likelihood boundary (H.5).
These emissions model marginal predictive distributions in the documented
transformed feature space; they are not full packet simulators (Section 14).
"""

from __future__ import annotations

from torch import Tensor, nn


class NodeObservationDecoder(nn.Module):
    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        node_values: int,
        *,
        log_scale_min: float = -5.0,
        log_scale_max: float = 3.0,
    ) -> None:
        super().__init__()
        self.node_values = node_values
        self.log_scale_min = log_scale_min
        self.log_scale_max = log_scale_max
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ELU(),
            nn.Linear(hidden_dim, 2 * node_values),
        )

    def forward(self, endpoint: Tensor) -> tuple[Tensor, Tensor]:
        """``[B, N, 192]`` -> (mean ``[B, N, 44]``, clamped log-scale ``[B, N, 44]``)."""
        out = self.net(endpoint)
        mean, log_scale = out[..., : self.node_values], out[..., self.node_values :]
        log_scale = log_scale.clamp(self.log_scale_min, self.log_scale_max)
        return mean, log_scale


class GlobalObservationDecoder(nn.Module):
    """Reads the (imagined) top-layer global hidden state (H.2)."""

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        global_values: int,
        *,
        log_scale_min: float = -5.0,
        log_scale_max: float = 3.0,
    ) -> None:
        super().__init__()
        self.global_values = global_values
        self.log_scale_min = log_scale_min
        self.log_scale_max = log_scale_max
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ELU(),
            nn.Linear(hidden_dim, 2 * global_values),
        )

    def forward(self, global_h_top: Tensor) -> tuple[Tensor, Tensor]:
        """``[B, 128]`` -> (mean ``[B, 24]``, clamped log-scale ``[B, 24]``)."""
        out = self.net(global_h_top)
        mean, log_scale = (
            out[..., : self.global_values],
            out[..., self.global_values :],
        )
        log_scale = log_scale.clamp(self.log_scale_min, self.log_scale_max)
        return mean, log_scale
