"""Global context adapter (Build Spec H.2).

Linear(48, 48), ELU, Linear(48, 24). Receives the 24 global values plus their 24
validity bits (48 channels) and emits the 24-dimensional global context.
"""

from __future__ import annotations

from torch import Tensor, nn


class GlobalAdapter(nn.Module):
    def __init__(self, global_input: int, output_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(global_input, global_input),
            nn.ELU(),
            nn.Linear(global_input, output_dim),
        )

    def forward(self, global_raw: Tensor) -> Tensor:
        """``[B, global_input]`` -> ``[B, output_dim]``."""
        return self.net(global_raw)
