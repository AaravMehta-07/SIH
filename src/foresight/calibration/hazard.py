"""Discrete-hazard calibration (Build Spec Appendix I.4).

The learned hazard logits are miscalibrated by construction; I.4 corrects them
with an affine transform — a shared slope and intercept plus *regularized*
horizon-group intercepts (groups: bins 1-10, 11-30, 31-60) — fitted on the
calibration split by maximizing the discrete-time survival likelihood.

Calibrated hazards are applied BEFORE survival is derived, so cumulative risk
stays monotone by construction (S[0] = 1, event mass = S[j-1] * q[j]).

Sparse cells (few observed events for a task/regime) fall back to a pooled
calibrator or explicit abstention — never a silently uncalibrated forecast.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn

from ..models.types import ContractError

#: I.4 horizon groups: (first_bin, last_bin), 1-indexed.
HORIZON_GROUPS: tuple[tuple[int, int], ...] = ((1, 10), (11, 30), (31, 60))

#: Implementation defaults recorded in ADR-001 (Appendix T.1).
DEFAULT_MIN_EVENTS = 20
DEFAULT_FIT_MAX_ITER = 100
#: Weak zero-mean prior on the group intercepts, applied against the TOTAL
#: survival likelihood (not the per-bin average), so its influence fades as
#: calibration support grows and dominates only in sparse cells (I.4).
DEFAULT_GROUP_L2 = 10.0


def horizon_group_index(bin_index: int) -> int:
    """Group of a 1-indexed bin; bins past 60 stay in the last group."""
    for i, (lo, hi) in enumerate(HORIZON_GROUPS):
        if lo <= bin_index <= hi:
            return i
    return len(HORIZON_GROUPS) - 1


def horizon_group_vector(horizon_bins: int) -> Tensor:
    """int64 ``[H]`` group index of each bin (bin j = index j-1)."""
    if horizon_bins < 1:
        raise ContractError("horizon_bins must be >= 1")
    return torch.tensor(
        [horizon_group_index(j) for j in range(1, horizon_bins + 1)],
        dtype=torch.int64,
    )


@dataclass
class HazardCalibrator:
    """Affine hazard calibrator for one task (and optionally one regime).

    ``calibrated_logit = slope * raw_logit + intercept + group_intercept[g(j)]``
    """

    task_index: int
    slope: float
    intercept: float
    group_intercepts: tuple[float, ...]
    horizon_bins: int
    min_events: int
    fit_event_count: int
    fit_example_count: int
    fitted: bool
    regime: str | None = None
    pooled: bool = False
    abstained: bool = False
    abstain_reason: str | None = None

    @property
    def status(self) -> str:
        if self.abstained:
            return "abstained"
        if self.pooled:
            return "pooled"
        if self.fitted:
            return "task"
        return "uncalibrated"

    def apply(self, hazard_logits: Tensor) -> Tensor:
        """Apply the affine transform to raw hazard logits ``[..., H]``.

        Padding beyond the fitted horizon keeps the last group's intercept.
        """
        if hazard_logits.dim() < 1:
            raise ContractError("hazard_logits must be [..., H]")
        H = hazard_logits.shape[-1]
        device = hazard_logits.device
        groups = torch.tensor(
            [
                horizon_group_index(min(j, self.horizon_bins))
                for j in range(1, H + 1)
            ],
            dtype=torch.int64,
            device=device,
        )
        g = torch.tensor(self.group_intercepts, dtype=hazard_logits.dtype, device=device)
        if g.numel() < len(HORIZON_GROUPS):
            g = torch.cat([g, g.new_zeros(len(HORIZON_GROUPS) - g.numel())])
        a = torch.tensor(self.slope, dtype=hazard_logits.dtype, device=device)
        b = torch.tensor(self.intercept, dtype=hazard_logits.dtype, device=device)
        return a * hazard_logits + b + g[groups]

    def to_dict(self) -> dict:
        return {
            "task_index": self.task_index,
            "slope": self.slope,
            "intercept": self.intercept,
            "group_intercepts": list(self.group_intercepts),
            "horizon_bins": self.horizon_bins,
            "min_events": self.min_events,
            "fit_event_count": self.fit_event_count,
            "fit_example_count": self.fit_example_count,
            "fitted": self.fitted,
            "regime": self.regime,
            "pooled": self.pooled,
            "abstained": self.abstained,
            "abstain_reason": self.abstain_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HazardCalibrator":
        return cls(
            task_index=int(data["task_index"]),
            slope=float(data["slope"]),
            intercept=float(data["intercept"]),
            group_intercepts=tuple(float(x) for x in data["group_intercepts"]),
            horizon_bins=int(data["horizon_bins"]),
            min_events=int(data["min_events"]),
            fit_event_count=int(data["fit_event_count"]),
            fit_example_count=int(data["fit_example_count"]),
            fitted=bool(data["fitted"]),
            regime=data.get("regime"),
            pooled=bool(data.get("pooled", False)),
            abstained=bool(data.get("abstained", False)),
            abstain_reason=data.get("abstain_reason"),
        )


def _survival_nll(logits: Tensor, event_y: Tensor, mask: Tensor) -> Tensor:
    """Masked censored survival NLL normalized by valid bins (reporting form)."""
    m = mask.to(logits.dtype)
    per = event_y * nn.functional.logsigmoid(logits) + (
        1.0 - event_y
    ) * nn.functional.logsigmoid(-logits)
    n = int(mask.sum())
    return -(m * per).sum() / max(1, n)


def _survival_total_nll(logits: Tensor, event_y: Tensor, mask: Tensor) -> Tensor:
    """Un-normalized survival NLL — the fit objective, so the group-intercept
    prior keeps a data-size-independent meaning."""
    m = mask.to(logits.dtype)
    per = event_y * nn.functional.logsigmoid(logits) + (
        1.0 - event_y
    ) * nn.functional.logsigmoid(-logits)
    return -(m * per).sum()


def fit_hazard_calibrator(
    hazard_logits: Tensor,
    event_y: Tensor,
    risk_mask: Tensor,
    *,
    task_index: int,
    regime: str | None = None,
    min_events: int = DEFAULT_MIN_EVENTS,
    max_iter: int = DEFAULT_FIT_MAX_ITER,
    group_l2: float = DEFAULT_GROUP_L2,
    pooled: bool = False,
) -> HazardCalibrator:
    """Fit the I.4 affine calibrator from calibration-split tensors.

    ``hazard_logits``/``event_y``/``risk_mask`` are ``[K, H]`` — the flattened
    per-entity per-clip rows for one task (or a pooled stack when
    ``pooled=True``). The survival likelihood plus a weak zero-mean prior on
    the group intercepts is minimized with L-BFGS. Returns an abstained
    calibrator when fewer than ``min_events`` events are observed (I.4
    sparse-cell rule).
    """
    if not (hazard_logits.shape == event_y.shape == risk_mask.shape):
        raise ContractError("calibration inputs must share shape [K, H]")
    if hazard_logits.dim() != 2:
        raise ContractError("calibration inputs must be [K, H]")
    K, H = hazard_logits.shape
    event_count = int(event_y.sum())
    if event_count < min_events:
        return HazardCalibrator(
            task_index=task_index,
            slope=1.0,
            intercept=0.0,
            group_intercepts=(0.0,) * len(HORIZON_GROUPS),
            horizon_bins=H,
            min_events=min_events,
            fit_event_count=event_count,
            fit_example_count=K,
            fitted=False,
            regime=regime,
            pooled=pooled,
            abstained=True,
            abstain_reason=(
                f"sparse cell: {event_count} events < {min_events} required "
                "(I.4: use a pooled calibrator or abstain)"
            ),
        )

    z = hazard_logits.detach().float()
    y = event_y.detach().float()
    m = risk_mask.detach()
    groups = horizon_group_vector(H)

    a = torch.nn.Parameter(torch.tensor(1.0))
    b = torch.nn.Parameter(torch.tensor(0.0))
    g = torch.nn.Parameter(torch.zeros(len(HORIZON_GROUPS)))
    opt = torch.optim.LBFGS(
        [a, b, g], lr=1.0, max_iter=max_iter, line_search_fn="strong_wolfe"
    )

    def closure() -> Tensor:
        opt.zero_grad()
        calibrated = a * z + b + g[groups].unsqueeze(0)
        loss = _survival_total_nll(calibrated, y, m) + group_l2 * g.square().sum()
        loss.backward()
        return loss

    opt.step(closure)

    return HazardCalibrator(
        task_index=task_index,
        slope=float(a.detach()),
        intercept=float(b.detach()),
        group_intercepts=tuple(float(x) for x in g.detach()),
        horizon_bins=H,
        min_events=min_events,
        fit_event_count=event_count,
        fit_example_count=K,
        fitted=True,
        regime=regime,
        pooled=pooled,
    )


def calibration_support(
    event_y: Tensor,
    risk_mask: Tensor,
    task_mask: Tensor | None = None,
    *,
    min_events: int = DEFAULT_MIN_EVENTS,
) -> list[dict]:
    """TR03 support check: observed events per task on the calibration split and
    whether a per-task calibrator can be fitted (I.4 sparse-cell rule)."""
    if event_y.dim() != 3:
        raise ContractError("event_y must be [N, H, J]")
    J = event_y.shape[2]
    if task_mask is None:
        task_mask = torch.ones(J, dtype=torch.bool, device=event_y.device)
    report: list[dict] = []
    for t in range(J):
        events = int(event_y[..., t].sum())
        supported = bool(task_mask[t])
        report.append(
            {
                "task_index": t,
                "supported": supported,
                "event_count": events,
                "fit": supported and events >= min_events,
                "action": (
                    "fit_task_calibrator"
                    if supported and events >= min_events
                    else (
                        "pooled_or_abstain"
                        if supported
                        else "not_supported"
                    )
                ),
            }
        )
    return report


@dataclass
class CalibratorSet:
    """Appendix S calibration interface: ``calibrate(logits, task, regime)``.

    Lookup order: exact (task, regime) cell, then the task-level calibrator,
    then the pooled backoff. Every call reports which one was used.
    """

    calibrators: dict  # (task_index, regime|None) -> HazardCalibrator
    pooled: HazardCalibrator | None = None

    def calibrate(
        self, logits: Tensor, task: int, regime: str | None = None
    ) -> tuple[Tensor, str]:
        """Returns ``(calibrated_logits, status)`` with status one of
        ``task`` / ``pooled`` / ``uncalibrated`` / ``abstained``."""
        for key in ((task, regime), (task, None)):
            c = self.calibrators.get(key)
            if c is not None and c.fitted:
                return c.apply(logits), c.status
        if self.pooled is not None and self.pooled.fitted:
            return self.pooled.apply(logits), self.pooled.status
        if self.pooled is not None and self.pooled.abstained:
            return logits, "abstained"
        return logits, "uncalibrated"
