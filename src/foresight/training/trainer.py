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
from dataclasses import dataclass, field, replace

import numpy as np
import torch
from torch import nn

from ..models.config import CoreConfig
from ..models.types import ContractError, GraphWindowBatch
from ..models.world_model import ForesightWorldModel
from .losses import LossBreakdown, LossWeights, compute_clip_loss
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
    positive_weight: float = 1.0
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
        return self.batch_step(
            [(windows, targets)], epoch=epoch, horizon_bins=horizon_bins
        )

    def batch_step(
        self,
        batch: list[tuple[list[GraphWindowBatch], ClipTargets]],
        *,
        epoch: int = 1,
        horizon_bins: int | None = None,
    ) -> StepLog:
        """One optimization step over ``batch`` clips (Section 35
        ``batch_clips``): per-clip losses are averaged — each clip's loss is
        already normalized by its valid targets (I.2) — gradients accumulate
        across the batch, then a single clipped AdamW step runs.

        Refuses test splits before any gradient is computed (TR02).
        """
        if not batch:
            raise ContractError("a batch needs at least one clip")
        for _, targets in batch:
            assert_trainable_split(targets.split)
        horizon = horizon_bins or self.curriculum.horizon_for_epoch(epoch)
        horizon = min(horizon, min(t.horizon_bins for _, t in batch))

        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        totals: list[LossBreakdown] = []
        for windows, targets in batch:
            observed = self.model.observe_clip(windows)
            outputs = self.model.roll_out(
                observed,
                horizon,
                candidate_pairs=targets.candidate_pairs,
                task_mask=targets.task_mask,
            )
            breakdown = compute_clip_loss(
                outputs, targets, self.weights,
                positive_weight=self.positive_weight,
            )
            (breakdown.total / len(batch)).backward()
            totals.append(breakdown)
        grad_norm = float(
            nn.utils.clip_grad_norm_(self.model.parameters(), self.gradient_clip)
        )
        self.optimizer.step()

        n = len(totals)
        mean = lambda pick: sum(pick(b) for b in totals) / n  # noqa: E731
        log = StepLog(
            epoch=epoch,
            horizon_bins=horizon,
            loss={
                "survival": mean(lambda b: b.detach_dict()["survival"]),
                "observable": mean(lambda b: b.detach_dict()["observable"]),
                "edge": mean(lambda b: b.detach_dict()["edge"]),
                "stage": mean(lambda b: b.detach_dict()["stage"]),
                "total": mean(lambda b: b.detach_dict()["total"]),
                "survival_count": sum(b.survival_count for b in totals),
                "edge_count": sum(b.edge_count for b in totals),
                "stage_count": sum(b.stage_count for b in totals),
                "per_bin_survival": [
                    mean(lambda b, i=i: b.detach_dict()["per_bin_survival"][i])
                    for i in range(horizon)
                ],
            },
            grad_norm=grad_norm,
            sampling_policy=self.sampling_policy,
        )
        self.step_logs.append(log)
        return log

    def batched_step(
        self,
        stacked_windows: list[GraphWindowBatch],
        clip_targets: list[ClipTargets],
        candidates: "CandidatePairs",
        *,
        epoch: int = 1,
        horizon_bins: int | None = None,
    ) -> StepLog:
        """Batched optimization step: one forward/backward over B stacked
        clips (G.2 batching), per-clip D.6 losses averaged (I.2 normalization
        is per clip), single clipped AdamW step.

        ``stacked_windows`` is the clip's window sequence stacked across the
        batch (``graphs.stack_windows`` per timestep); ``candidates`` is the
        stacked pair set (``graphs.stack_candidates``). Per-clip outputs are
        sliced from the batched rollout before the loss, so the frozen
        per-clip target contract is preserved.
        """
        from ..models.types import CandidatePairs  # noqa: F401  (annotation)

        if not clip_targets:
            raise ContractError("a batch needs at least one clip")
        for targets in clip_targets:
            assert_trainable_split(targets.split)
        horizon = horizon_bins or self.curriculum.horizon_for_epoch(epoch)
        horizon = min(horizon, min(t.horizon_bins for t in clip_targets))

        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        observed = self.model.observe_clip(stacked_windows)
        outputs = self.model.roll_out(
            observed, horizon, candidate_pairs=candidates,
            task_mask=clip_targets[0].task_mask,
        )
        b = observed.entity_memory.shape[0]
        totals: list[LossBreakdown] = []
        for i, targets in enumerate(clip_targets):
            member_rows = None
            if outputs[0].edge_logits is not None:
                member_rows = (candidates.batch_index == i).nonzero(as_tuple=True)[0]
            sliced = [
                replace(
                    step,
                    node_mean=step.node_mean[i : i + 1],
                    node_log_scale=step.node_log_scale[i : i + 1],
                    global_mean=step.global_mean[i : i + 1],
                    global_log_scale=step.global_log_scale[i : i + 1],
                    hazard_logits=step.hazard_logits[i : i + 1],
                    tactic_logits=step.tactic_logits[i : i + 1],
                    edge_logits=(
                        None if member_rows is None
                        else step.edge_logits[member_rows]
                    ),
                    hazard_task_mask=step.hazard_task_mask,
                )
                for step in outputs
            ]
            totals.append(
                compute_clip_loss(
                    sliced, targets, self.weights,
                    positive_weight=self.positive_weight,
                )
            )
        # One backward through the shared batched graph: per-clip losses are
        # averaged (each already normalized by its valid targets, I.2).
        (sum(bd.total for bd in totals) / b).backward()
        grad_norm = float(
            nn.utils.clip_grad_norm_(self.model.parameters(), self.gradient_clip)
        )
        self.optimizer.step()

        n = len(totals)
        mean = lambda pick: sum(pick(tb) for tb in totals) / n  # noqa: E731
        log = StepLog(
            epoch=epoch,
            horizon_bins=horizon,
            loss={
                "survival": mean(lambda tb: tb.detach_dict()["survival"]),
                "observable": mean(lambda tb: tb.detach_dict()["observable"]),
                "edge": mean(lambda tb: tb.detach_dict()["edge"]),
                "stage": mean(lambda tb: tb.detach_dict()["stage"]),
                "total": mean(lambda tb: tb.detach_dict()["total"]),
                "survival_count": sum(tb.survival_count for tb in totals),
                "edge_count": sum(tb.edge_count for tb in totals),
                "stage_count": sum(tb.stage_count for tb in totals),
                "per_bin_survival": [
                    mean(lambda tb, i=i: tb.detach_dict()["per_bin_survival"][i])
                    for i in range(horizon)
                ],
            },
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
