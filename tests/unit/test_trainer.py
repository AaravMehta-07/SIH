"""Trainer tests (Build Spec I.1): TR02 split guard, gradient flow and
clipping, curriculum schedule, per-component/per-bin logging (TR03) and an
optimization smoke test on a synthetic clip."""

from __future__ import annotations

import copy

import pytest
import torch

from conftest import build_clip, build_targets
from foresight.models.types import ContractError
from foresight.training.trainer import (
    CurriculumSchedule,
    Trainer,
    set_seed,
)


@pytest.fixture()
def trainer(model, core_config):
    return Trainer.from_config(model, core_config, seed=0)


class TestTR02TestSplitGuard:
    @pytest.mark.parametrize("split", ["test", "locked_test"])
    def test_test_splits_refused_before_any_gradient(self, trainer, split):
        clip = build_clip(num_windows=20, seed=0)
        targets = build_targets(horizon_bins=4, split=split)
        params_before = [p.detach().clone() for p in trainer.model.parameters()]
        with pytest.raises(ContractError, match="never be opened"):
            trainer.train_step(clip, targets)
        for before, after in zip(
            params_before, [p.detach() for p in trainer.model.parameters()]
        ):
            assert torch.equal(before, after), "no gradient work may happen on a test split"

    def test_no_step_log_for_refused_split(self, trainer):
        clip = build_clip(num_windows=20, seed=0)
        targets = build_targets(horizon_bins=4, split="locked_test")
        with pytest.raises(ContractError):
            trainer.train_step(clip, targets)
        assert trainer.step_logs == []


class TestTrainerStep:
    def test_step_produces_finite_logged_losses(self, trainer):
        clip = build_clip(num_windows=20, seed=1)
        targets = build_targets(horizon_bins=4)
        log = trainer.train_step(clip, targets, epoch=1)
        assert log.horizon_bins == 1  # curriculum starts at one step
        assert log.sampling_policy == "natural_class_prevalence"
        for key in ("survival", "observable", "edge", "stage", "total"):
            assert torch.isfinite(torch.tensor(log.loss[key])), key
        assert len(log.loss["per_bin_survival"]) == 1
        assert log.grad_norm >= 0.0

    def test_weights_update(self, trainer):
        clip = build_clip(num_windows=20, seed=2)
        targets = build_targets(horizon_bins=4)
        before = [p.detach().clone() for p in trainer.model.parameters()]
        trainer.train_step(clip, targets, epoch=1)
        changed = any(
            not torch.equal(b, p.detach())
            for b, p in zip(before, trainer.model.parameters())
        )
        assert changed, "one optimization step must move the parameters"

    def test_horizon_capped_by_targets(self, trainer):
        clip = build_clip(num_windows=20, seed=3)
        targets = build_targets(horizon_bins=2)
        log = trainer.train_step(clip, targets, horizon_bins=30)
        assert log.horizon_bins == 2

    def test_from_config_defaults_match_section_35(self, trainer):
        assert trainer.learning_rate == 0.001
        assert trainer.weight_decay == 0.0001
        assert trainer.gradient_clip == 1.0
        assert trainer.epochs_max == 40
        assert trainer.curriculum.horizons == (1, 3, 10, 30, 60)
        assert trainer.weights.survival == 1.0
        assert trainer.weights.observable == 0.5
        assert trainer.weights.edge == 0.2
        assert trainer.weights.stage == 0.2
        assert type(trainer.optimizer).__name__ == "AdamW"


class TestCurriculumSchedule:
    def test_starts_at_one_step(self):
        assert CurriculumSchedule().horizon_for_epoch(1) == 1

    def test_transitions_control_expansion(self):
        schedule = CurriculumSchedule(
            horizons=(1, 3, 10, 30, 60), transition_epochs=(3, 7, 15, 30)
        )
        assert schedule.horizon_for_epoch(1) == 1
        assert schedule.horizon_for_epoch(2) == 1
        assert schedule.horizon_for_epoch(3) == 3
        assert schedule.horizon_for_epoch(6) == 3
        assert schedule.horizon_for_epoch(7) == 10
        assert schedule.horizon_for_epoch(29) == 30
        assert schedule.horizon_for_epoch(40) == 60

    def test_manual_transitions_are_recorded(self):
        schedule = CurriculumSchedule(
            horizons=(1, 3, 10, 30, 60),
            recorded_transitions=((3, 3), (7, 10)),
        )
        assert schedule.recorded_transitions == ((3, 3), (7, 10))

    def test_bad_transition_count_rejected(self):
        with pytest.raises(ContractError):
            CurriculumSchedule(horizons=(1, 3), transition_epochs=(1, 2, 3))

    def test_horizons_never_advance_without_transitions(self):
        schedule = CurriculumSchedule()
        assert schedule.horizon_for_epoch(40) == 1


class TestTR03LoggingPolicy:
    def test_run_summary_records_sampling_policy_and_weights(self, trainer):
        clip = build_clip(num_windows=20, seed=4)
        targets = build_targets(horizon_bins=4)
        trainer.train_step(clip, targets, epoch=1)
        summary = trainer.run_summary()
        assert summary["sampling_policy"] == "natural_class_prevalence"
        assert summary["seed"] == 0
        assert summary["loss_weights"] == {
            "survival": 1.0,
            "observable": 0.5,
            "edge": 0.2,
            "stage": 0.2,
        }
        assert summary["curriculum_horizons"] == [1, 3, 10, 30, 60]
        step = summary["steps"][0]
        assert step["horizon_bins"] == 1
        assert "per_bin_survival" in step
        assert step["sampling_policy"] == "natural_class_prevalence"

    def test_seed_reproducibility(self, model, core_config):
        """Section 35 seeds 0-4: same seed, same trajectory."""
        clip = build_clip(num_windows=20, seed=7)
        targets = build_targets(horizon_bins=4, seed=7)

        set_seed(0)
        t1 = Trainer.from_config(copy.deepcopy(model), core_config, seed=0)
        l1 = [t1.train_step(clip, targets).loss["total"] for _ in range(3)]

        set_seed(0)
        t2 = Trainer.from_config(copy.deepcopy(model), core_config, seed=0)
        l2 = [t2.train_step(clip, targets).loss["total"] for _ in range(3)]

        assert l1 == pytest.approx(l2, abs=1e-9)


class TestOptimizationSmoke:
    def test_loss_decreases_on_synthetic_clip(self, model, core_config):
        """Repeated steps on one synthetic clip must drive the total loss down
        (the objective is optimizable through the real interfaces)."""
        trainer = Trainer.from_config(model, core_config, seed=0)
        clip = build_clip(num_windows=20, seed=8)
        targets = build_targets(horizon_bins=4, seed=8)
        first = trainer.train_step(clip, targets, epoch=1, horizon_bins=4).loss["total"]
        last = None
        for _ in range(14):
            last = trainer.train_step(clip, targets, epoch=1, horizon_bins=4).loss["total"]
        assert last < first, f"loss must decrease: first={first}, last={last}"
        assert last < first * 0.95
