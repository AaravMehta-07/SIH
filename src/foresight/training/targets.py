"""Typed training-target contract (Build Spec Appendix D.6, Section 15).

This is the tensor boundary the labels module must produce for one clip.
Shapes are per-clip (single graph, N entities, H horizon bins, J event tasks):

- event_y, risk_mask: [N, H, J]. Exactly one bin of event_y is 1 when the
  first event of a task is observed; risk_mask stops after that bin.
  Censored follow-up keeps zeros only through complete observed bins
  (unresolved bins contribute no negative labels).
- stage_labels, stage_mask: [N, H, 5] — several tactics may coexist.
- node_values, node_valid: [N, H, 44] future node targets (transformed
  space, matching what the model decodes) with validity masks.
- global_values, global_valid: [H, 24].
- edge_labels, edge_mask: [E, H] on frozen candidate pairs; unseen edges
  during sensor failure are unknown (mask False), not negatives.
- task_mask: [J] — manifest-supported tasks; unsupported tasks are masked
  from losses.

J is not hard-coded to 5; the task manifest governs.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from foresight.models.types import CandidatePairs, ContractError

TRAINABLE_SPLITS = ("train", "development", "calibration")
NON_TRAINABLE_SPLITS = ("test", "locked_test")
ALL_SPLITS = TRAINABLE_SPLITS + NON_TRAINABLE_SPLITS


@dataclass(frozen=True)
class ClipTargets:
    event_y: torch.Tensor          # float [N, H, J], values in {0, 1}
    risk_mask: torch.Tensor        # bool  [N, H, J]
    stage_labels: torch.Tensor     # float [N, H, 5]
    stage_mask: torch.Tensor       # bool  [N, H, 5]
    node_values: torch.Tensor      # float [N, H, 44]
    node_valid: torch.Tensor       # bool  [N, H, 44]
    global_values: torch.Tensor    # float [H, 24]
    global_valid: torch.Tensor     # bool  [H, 24]
    edge_labels: torch.Tensor      # float [E, H]
    edge_mask: torch.Tensor        # bool  [E, H]
    candidate_pairs: CandidatePairs
    task_mask: torch.Tensor        # bool [J]
    split: str
    num_event_tasks: int

    @property
    def num_nodes(self) -> int:
        return int(self.event_y.shape[0])

    @property
    def horizon_bins(self) -> int:
        return int(self.event_y.shape[1])

    @property
    def num_tasks(self) -> int:
        return int(self.event_y.shape[2])

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        N, H, J = self.event_y.shape
        if self.event_y.dim() != 3:
            raise ContractError(f"event_y must be [N, H, J], got {tuple(self.event_y.shape)}")
        for name in ("risk_mask",):
            t = getattr(self, name)
            if t.shape != (N, H, J):
                raise ContractError(f"{name} must be [{N}, {H}, {J}], got {tuple(t.shape)}")
            if t.dtype != torch.bool:
                raise ContractError(f"{name} must be bool, got {t.dtype}")
        if self.event_y.dtype not in (torch.float32, torch.float64):
            raise ContractError(f"event_y must be float, got {self.event_y.dtype}")
        if not torch.logical_or(self.event_y == 0, self.event_y == 1).all():
            raise ContractError("event_y must contain only 0/1 values")
        if self.num_event_tasks != J:
            raise ContractError(
                f"num_event_tasks {self.num_event_tasks} does not match event_y tasks {J}"
            )
        if self.task_mask.shape != (J,) or self.task_mask.dtype != torch.bool:
            raise ContractError(f"task_mask must be bool [{J}]")

        # Censoring rules (Section 15 / I.2): per (entity, task) the risk mask
        # is a contiguous prefix of bins; an observed event sits at the last
        # masked bin and is the only positive label.
        contiguous = torch.cumprod(self.risk_mask.int(), dim=1).bool()
        if not torch.equal(contiguous, self.risk_mask):
            raise ContractError("risk_mask must be a contiguous prefix of bins")
        event_any = self.event_y.sum(dim=1) > 0          # [N, J]
        event_count = self.event_y.sum(dim=1)            # [N, J]
        if (event_count > 1).any():
            raise ContractError("at most one event bin per (entity, task)")
        last_masked = self.risk_mask.sum(dim=1).long()   # [N, J] bins before stop
        event_bin = self.event_y.argmax(dim=1).long() + 1  # 1-indexed, 0 when none
        bad_event = event_any & (event_bin != last_masked)
        if bad_event.any():
            raise ContractError("risk_mask must stop exactly at the event bin")
        if (event_any & (last_masked == 0)).any():
            raise ContractError("an event requires at least one masked bin")

        if self.stage_labels.shape != (N, H, 5):
            raise ContractError(f"stage_labels must be [{N}, {H}, 5], got {tuple(self.stage_labels.shape)}")
        if self.stage_mask.shape != (N, H, 5) or self.stage_mask.dtype != torch.bool:
            raise ContractError(f"stage_mask must be bool [{N}, {H}, 5]")

        if self.node_values.shape != (N, H, 44):
            raise ContractError(f"node_values must be [{N}, {H}, 44], got {tuple(self.node_values.shape)}")
        if self.node_valid.shape != (N, H, 44) or self.node_valid.dtype != torch.bool:
            raise ContractError(f"node_valid must be bool [{N}, {H}, 44]")

        if self.global_values.shape != (H, 24):
            raise ContractError(f"global_values must be [{H}, 24], got {tuple(self.global_values.shape)}")
        if self.global_valid.shape != (H, 24) or self.global_valid.dtype != torch.bool:
            raise ContractError(f"global_valid must be bool [{H}, 24]")

        E = self.edge_labels.shape[0]
        if self.edge_labels.shape != (E, H):
            raise ContractError(f"edge_labels must be [E, {H}], got {tuple(self.edge_labels.shape)}")
        if self.edge_mask.shape != (E, H) or self.edge_mask.dtype != torch.bool:
            raise ContractError(f"edge_mask must be bool [E, {H}]")
        num_pairs = int(self.candidate_pairs.batch_index.shape[0])
        if E != num_pairs:
            raise ContractError(
                f"edge targets refer to frozen candidate pairs: {E} rows vs "
                f"{num_pairs} pairs"
            )

        if self.split not in ALL_SPLITS:
            raise ContractError(
                f"split must be one of {ALL_SPLITS}, got {self.split!r}"
            )


def assert_trainable_split(split: str) -> None:
    """TR02: training/model-selection commands refuse test splits."""
    if split in NON_TRAINABLE_SPLITS:
        raise ContractError(
            f"split {split!r} must never be opened by training or model selection"
        )
    if split not in ALL_SPLITS:
        raise ContractError(f"unknown split {split!r}; expected one of {ALL_SPLITS}")
