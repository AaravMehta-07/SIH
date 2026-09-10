"""Training loop core (Build Spec Section 15, Appendix I.1).

Defaults come from Section 35: AdamW (lr 0.001, weight decay 0.0001), gradient
norm clip 1.0, max 40 epochs, batch 16 clips, rollout curriculum
[1, 3, 10, 30, 60], seeds 0-4, natural class prevalence by default.

I.1 rules implemented here:
- rollout training begins at one step and expands only according to development
  behavior; every curriculum transition is recorded;
- per-component and per-bin loss summaries are logged each step/epoch;
- the sampling/weighting policy is logged (TR03), never implicit;
- test and locked-test splits are refused before any gradient is computed
  (TR02).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import numpy as np
import torch
from torch import nn

from ..models.config import CoreConfig
from ..models.types import ContractError, GraphWindowBatch
from ..models.world_model import ForesightWorldModel
from .losses import LossWeights, compute_clip_loss
from .targets import ClipTargets, assert_trainable_split

DEFAULT_SAMPLING_POLICY = "natural_class_prevalence"


def set_seed(seed: int) -> None:
    """Seed everything that affects a training run (Section 35 seeds 0-4)."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


@dataclass(frozen=True)
class CurriculumSchedule:
    """Rollout horizon schedule (I.1).

    ``horizons`` follows Section 35's [1, 3, 10, 30, 60]. ``transition_epochs``
    are the 1-indexed epochs at which the next horizon becomes active; they are
    an explicit development decision (I.1: "expand ... only according to
    development behavior"), recorded in every run summary. When None the
    schedule never advances automatically — the caller advances it from
    development-set evidence and appends to ``recorded_transitions``.
    """

    horizons: tuple[int, ...] = (1, 3, 10, 30, 60)
    transition_epochs: tuple[int, ...] | None = None
    recorded_transitions: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        if not self.horizons or any(h < 1 for h in self.horizons):
            raise ContractError("horizons must be a non-empty list of bins >= 1")
        if self.transition_epochs is not None and (
            len(self.transition_epochs) != len(self.horizons) - 1
        ):
            raise ContractError(
                "transition_epochs needs exactly len(horizons)-1 entries"
            )

    def horizon_for_epoch(self, epoch: int) -> int:
        if self.transition_epochs is None:
            return self.horizons[0]
        idx = 0
        for t in self.transition_epochs:
            if epoch >= t:
                idx += 1
        return self.horizons[idx]


@dataclass
class StepLog:
    epoch: int
    horizon_bins: int
    loss: dict[str, float]
    grad_norm: float
    sampling_policy: str


@dataclass
class Trainer:
    """One training run of the world model against per-clip targets."""

    model: ForesightWorldModel
    weights: LossWeights
    learning_rate: float = 0.001
    weight_decay: float = 0.0001
    gradient_clip: float = 1.0
    epochs_max: int = 40
    curriculum: CurriculumSchedule = field(default_factory=CurriculumSchedule)
    sampling_policy: str = DEFAULT_SAMPLING_POLICY
    seed: int = 0

    def __post_init__(self) -> None:
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=self.learning_rate,
            weight_decay=self.weight_decay,
        )
        self.step_logs: list[StepLog] = []
        set_seed(self.seed)

    @classmethod
    def from_config(
        cls,
        model: ForesightWorldModel,
        config: CoreConfig,
        *,
        seed: int = 0,
        curriculum: CurriculumSchedule | None = None,
        sampling_policy: str = DEFAULT_SAMPLING_POLICY,
    ) -> "Trainer":
        t = config.training
        if curriculum is None:
            curriculum = CurriculumSchedule(
                horizons=tuple(t["rollout_curriculum"])
            )
        return cls(
            model=model,
            weights=LossWeights.from_config(t["loss"]),
            learning_rate=float(t["learning_rate"]),
            weight_decay=float(t["weight_decay"]),
            gradient_clip=float(t["gradient_clip"]),
            epochs_max=int(t["epochs_max"]),
            curriculum=curriculum,
            sampling_policy=sampling_policy,
            seed=seed,
        )

    def train_step(
        self,
        windows: list[GraphWindowBatch],
        targets: ClipTargets,
        *,
        epoch: int = 1,
        horizon_bins: int | None = None,
    ) -> StepLog:
        """One optimization step on one clip. Refuses test splits before any
        gradient is computed (TR02)."""
        assert_trainable_split(targets.split)
        horizon = horizon_bins or self.curriculum.horizon_for_epoch(epoch)
        if horizon > targets.horizon_bins:
            horizon = targets.horizon_bins

        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        observed = self.model.observe_clip(windows)
        outputs = self.model.roll_out(
            observed,
            horizon,
            candidate_pairs=targets.candidate_pairs,
            task_mask=targets.task_mask,
        )
        breakdown = compute_clip_loss(outputs, targets, self.weights)
        breakdown.total.backward()
        grad_norm = float(
            nn.utils.clip_grad_norm_(self.model.parameters(), self.gradient_clip)
        )
        self.optimizer.step()

        log = StepLog(
            epoch=epoch,
            horizon_bins=horizon,
            loss=breakdown.detach_dict(),
            grad_norm=grad_norm,
            sampling_policy=self.sampling_policy,
        )
        self.step_logs.append(log)
        return log

    def run_summary(self) -> dict:
        """I.1: every run records its sampling/weighting policy, loss weights,
        seed and curriculum transitions alongside the loss summaries."""
        return {
            "seed": self.seed,
            "sampling_policy": self.sampling_policy,
            "loss_weights": {
                "survival": self.weights.survival,
                "observable": self.weights.observable,
                "edge": self.weights.edge,
                "stage": self.weights.stage,
            },
            "learning_rate": self.learning_rate,
            "weight_decay": self.weight_decay,
            "gradient_clip": self.gradient_clip,
            "epochs_max": self.epochs_max,
            "curriculum_horizons": list(self.curriculum.horizons),
            "curriculum_transitions": list(self.curriculum.recorded_transitions),
            "steps": [
                {
                    "epoch": log.epoch,
                    "horizon_bins": log.horizon_bins,
                    "grad_norm": log.grad_norm,
                    "sampling_policy": log.sampling_policy,
                    **log.loss,
                }
                for log in self.step_logs
            ],
        }
