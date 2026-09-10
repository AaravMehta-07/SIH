"""Masked training objectives (Build Spec Section 15, Appendix I.2).

Every loss is normalized by its valid targets only:

- ``L_survival = -sum(valid_risk_bins * (y_event*log(q) + (1-y_event)*log1p(-q)))
  / max(1, count(valid_risk_bins))`` where ``q = sigmoid(hazard_logits)``.
  Observed first events end the risk bins at the event; censored follow-up ends
  them at the last complete bin; unresolved later bins contribute no negative
  labels. Multiple event types are separate risk processes (the J axis).
- ``L_obs``: masked Gaussian NLL of future node and global observables, node
  and global terms normalized separately then averaged equally; when one entire
  group is absent the available group is used without an invented count.
- ``L_edge = masked_bce`` over frozen candidate pairs; unseen edges during
  sensor failure are unknown (mask False), never negatives.
- ``L_stage = masked_multilabel_bce`` over the five tactic tags.

``L = 1.0*L_survival + 0.5*L_obs + 0.2*L_edge + 0.2*L_stage`` (Section 35).

The survival NLL is computed with ``logsigmoid`` on raw logits — the stable
form of ``log(q)`` and ``log1p(-q)`` — so no probability clamping is needed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor, nn

from ..models.types import ContractError, DecodedStep
from .targets import ClipTargets

LOG_2PI = math.log(2.0 * math.pi)


@dataclass(frozen=True)
class LossWeights:
    survival: float = 1.0
    observable: float = 0.5
    edge: float = 0.2
    stage: float = 0.2

    @classmethod
    def from_config(cls, loss_dict: dict) -> "LossWeights":
        try:
            return cls(
                survival=float(loss_dict["survival"]),
                observable=float(loss_dict["observable"]),
                edge=float(loss_dict["edge"]),
                stage=float(loss_dict["stage"]),
            )
        except KeyError as exc:
            raise ContractError(f"missing loss weight: {exc}") from exc


def _count(mask: Tensor) -> int:
    return int(mask.sum())


def masked_survival_nll(
    hazard_logits: Tensor, event_y: Tensor, risk_mask: Tensor
) -> tuple[Tensor, int]:
    """Censored-discrete-time survival NLL over valid risk bins.

    ``hazard_logits``/``event_y``/``risk_mask`` share shape ``[..., H, J]``.
    Returns ``(loss_scalar, valid_bin_count)``.
    """
    if not (hazard_logits.shape == event_y.shape == risk_mask.shape):
        raise ContractError(
            "survival inputs must share shape; got "
            f"{tuple(hazard_logits.shape)} / {tuple(event_y.shape)} / "
            f"{tuple(risk_mask.shape)}"
        )
    mask = risk_mask.to(hazard_logits.dtype)
    log_q = nn.functional.logsigmoid(hazard_logits)      # log q
    log_1mq = nn.functional.logsigmoid(-hazard_logits)   # log(1 - q)
    per_bin = event_y * log_q + (1.0 - event_y) * log_1mq
    n = _count(risk_mask)
    loss = -(mask * per_bin).sum() / max(1, n)
    return loss, n


def per_bin_survival_nll(
    hazard_logits: Tensor, event_y: Tensor, risk_mask: Tensor
) -> Tensor:
    """Mean survival NLL per horizon bin over valid entries — shape ``[H]``
    (I.1: per-bin loss summaries are logged each epoch). All leading (entity,
    batch) and trailing (task) axes are reduced; the horizon axis stays."""
    log_q = nn.functional.logsigmoid(hazard_logits)
    log_1mq = nn.functional.logsigmoid(-hazard_logits)
    per_bin = -(event_y * log_q + (1.0 - event_y) * log_1mq)
    mask = risk_mask.to(per_bin.dtype)
    H = per_bin.shape[-2]
    if H == 0:
        return per_bin.new_zeros(0)
    reduce_dims = tuple(i for i in range(per_bin.dim()) if i != per_bin.dim() - 2)
    total = (mask * per_bin).sum(dim=reduce_dims) if reduce_dims else (mask * per_bin)
    counts = mask.sum(dim=reduce_dims) if reduce_dims else mask
    return total / counts.clamp(min=1.0).to(total.dtype)


def masked_gaussian_nll(
    values: Tensor, mean: Tensor, log_scale: Tensor, valid: Tensor
) -> tuple[Tensor, int]:
    """Masked Gaussian NLL ``0.5*((v-m)/s)^2 + log_scale + 0.5*log(2*pi)``."""
    mask = valid.to(values.dtype)
    residual = (values - mean) * torch.exp(-log_scale)
    per = 0.5 * residual.square() + log_scale + 0.5 * LOG_2PI
    n = _count(valid)
    loss = (mask * per).sum() / max(1, n)
    return loss, n


def masked_bce(
    logits: Tensor, labels: Tensor, mask: Tensor
) -> tuple[Tensor, int]:
    """Masked binary cross-entropy on raw logits (sigmoid never applied inside)."""
    mask = mask.to(logits.dtype)
    per = nn.functional.binary_cross_entropy_with_logits(
        logits, labels.to(logits.dtype), reduction="none"
    )
    n = _count(mask)
    loss = (mask * per).sum() / max(1, n)
    return loss, n


def masked_multilabel_bce(
    logits: Tensor, labels: Tensor, mask: Tensor
) -> tuple[Tensor, int]:
    """Multi-label tactic BCE — independent BCE per tag, tactics may coexist."""
    return masked_bce(logits, labels, mask)


def observable_nll(
    node_values: Tensor | None,
    node_mean: Tensor | None,
    node_log_scale: Tensor | None,
    node_valid: Tensor | None,
    global_values: Tensor | None,
    global_mean: Tensor | None,
    global_log_scale: Tensor | None,
    global_valid: Tensor | None,
) -> tuple[Tensor, dict[str, float]]:
    """``L_obs``: node and global groups normalized separately, then averaged
    equally over the groups that are present (Section 15). An entirely absent
    group is recorded and the available group is used without dividing by an
    invented count; when neither group has valid entries the loss is 0."""
    terms: dict[str, float] = {}
    parts: list[Tensor] = []

    if node_values is not None and int(node_valid.sum()) > 0:
        node_loss, node_n = masked_gaussian_nll(
            node_values, node_mean, node_log_scale, node_valid
        )
        parts.append(node_loss)
        terms["node"] = float(node_loss.detach())
        terms["node_count"] = node_n
    else:
        terms["node"] = None  # type: ignore[assignment]

    if global_values is not None and int(global_valid.sum()) > 0:
        g_loss, g_n = masked_gaussian_nll(
            global_values, global_mean, global_log_scale, global_valid
        )
        parts.append(g_loss)
        terms["global"] = float(g_loss.detach())
        terms["global_count"] = g_n
    else:
        terms["global"] = None  # type: ignore[assignment]

    if not parts:
        anchor = next(
            (t for t in (node_mean, global_mean) if t is not None), None
        )
        if anchor is None:
            return torch.tensor(0.0), terms
        return anchor.sum() * 0.0, terms
    loss = sum(parts) / len(parts)
    return loss, terms


@dataclass
class LossBreakdown:
    """Per-component losses and valid-target counts for one step (I.1 logging)."""

    survival: Tensor
    observable: Tensor
    edge: Tensor
    stage: Tensor
    total: Tensor
    survival_count: int
    edge_count: int
    stage_count: int
    node_count: int
    global_count: int
    per_bin_survival: Tensor  # [H'] mean NLL per bin
    horizon_bins: int

    def detach_dict(self) -> dict[str, float]:
        return {
            "survival": float(self.survival.detach()),
            "observable": float(self.observable.detach()),
            "edge": float(self.edge.detach()),
            "stage": float(self.stage.detach()),
            "total": float(self.total.detach()),
            "survival_count": self.survival_count,
            "edge_count": self.edge_count,
            "stage_count": self.stage_count,
            "node_count": self.node_count,
            "global_count": self.global_count,
            "horizon_bins": self.horizon_bins,
            "per_bin_survival": [
                float(x) for x in self.per_bin_survival.detach().tolist()
            ],
        }


def _stack_steps(outputs: list[DecodedStep]) -> dict[str, Tensor]:
    """Stack a rollout's DecodedSteps along the horizon axis (bin j = index j-1).

    All model outputs carry a leading batch axis (B=1 here); it is dropped so
    the stacked tensors are ``[H', ...]`` per-clip.
    """
    if not outputs:
        raise ContractError("loss computation needs at least one decoded step")
    b = outputs[0].hazard_logits.shape[0]
    if b != 1:
        raise ContractError(
            "ClipTargets are per-clip [N, H, J]; batched training must collapse "
            f"or loop the batch dimension (got B={b})"
        )
    stacked = {
        "hazard_logits": torch.stack(
            [o.hazard_logits for o in outputs], dim=0
        )[:, 0],  # [H', N, J]
        "tactic_logits": torch.stack(
            [o.tactic_logits for o in outputs], dim=0
        )[:, 0],  # [H', N, 5]
        "node_mean": torch.stack([o.node_mean for o in outputs], dim=0)[:, 0],
        "node_log_scale": torch.stack(
            [o.node_log_scale for o in outputs], dim=0
        )[:, 0],
        "global_mean": torch.stack([o.global_mean for o in outputs], dim=0)[:, 0],
        "global_log_scale": torch.stack(
            [o.global_log_scale for o in outputs], dim=0
        )[:, 0],
    }
    if any(o.edge_logits is None for o in outputs):
        stacked["edge_logits"] = None  # type: ignore[assignment]
    else:
        stacked["edge_logits"] = torch.stack(
            [o.edge_logits for o in outputs], dim=0
        ).t()  # [E, H']
    return stacked


def compute_clip_loss(
    outputs: list[DecodedStep], targets: ClipTargets, weights: LossWeights
) -> LossBreakdown:
    """Combined Section-15 objective for one clip's rollout.

    ``outputs`` may cover fewer bins than the targets' full horizon (curriculum
    rollouts train only on the bins they produce; Section 15 rollout curriculum).
    Unsupported tasks (``task_mask`` False) are masked from the losses (D.6).
    """
    s = _stack_steps(outputs)
    H_roll = s["hazard_logits"].shape[0]
    if H_roll > targets.horizon_bins:
        raise ContractError(
            f"rollout produced {H_roll} bins but targets cover only "
            f"{targets.horizon_bins}"
        )

    # [N, H', J] — outputs are [H', N, J] because state after transition j
    # represents bin j (Section 14).
    hazard_logits = s["hazard_logits"].permute(1, 0, 2)
    event_y = targets.event_y[:, :H_roll, :].to(hazard_logits.dtype)
    risk_mask = targets.risk_mask[:, :H_roll, :] & targets.task_mask
    survival, survival_n = masked_survival_nll(hazard_logits, event_y, risk_mask)
    bin_summary = per_bin_survival_nll(hazard_logits, event_y, risk_mask)

    tactic_logits = s["tactic_logits"].permute(1, 0, 2)  # [N, H', 5]
    stage_labels = targets.stage_labels[:, :H_roll, :].to(tactic_logits.dtype)
    stage_mask = targets.stage_mask[:, :H_roll, :]
    stage, stage_n = masked_multilabel_bce(tactic_logits, stage_labels, stage_mask)

    node_valid = targets.node_valid[:, :H_roll, :]
    global_valid = targets.global_valid[:H_roll, :]
    observable, obs_terms = observable_nll(
        targets.node_values[:, :H_roll, :],      # [N, H', 44] future values
        s["node_mean"].permute(1, 0, 2),         # [H', N, 44] -> [N, H', 44]
        s["node_log_scale"].permute(1, 0, 2),
        node_valid,
        targets.global_values[:H_roll, :],       # [H', 24] future values
        s["global_mean"],                        # [H', 24]
        s["global_log_scale"],
        global_valid,
    )

    if s["edge_logits"] is not None:
        edge, edge_n = masked_bce(
            s["edge_logits"],
            targets.edge_labels[:, :H_roll].to(s["edge_logits"].dtype),
            targets.edge_mask[:, :H_roll],
        )
    else:
        edge = survival * 0.0
        edge_n = 0

    total = (
        weights.survival * survival
        + weights.observable * observable
        + weights.edge * edge
        + weights.stage * stage
    )

    return LossBreakdown(
        survival=survival,
        observable=observable,
        edge=edge,
        stage=stage,
        total=total,
        survival_count=survival_n,
        edge_count=edge_n,
        stage_count=stage_n,
        node_count=obs_terms.get("node_count", 0),
        global_count=obs_terms.get("global_count", 0),
        per_bin_survival=bin_summary,
        horizon_bins=H_roll,
    )
