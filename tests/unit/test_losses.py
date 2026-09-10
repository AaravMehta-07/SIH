"""Section 15 training-objective tests.

TR01: the masked censored-likelihood loss must match a hand calculation on
golden hazards q = [0.10, 0.20, 0.30] both for an observed event at bin 2 and
for a censored follow-up ending at bin 2; masked bins contribute nothing.
"""

from __future__ import annotations

import math

import pytest
import torch

from conftest import build_candidates, build_clip, build_targets
from foresight.models.types import ContractError
from foresight.training.losses import (
    LossWeights,
    compute_clip_loss,
    masked_bce,
    masked_gaussian_nll,
    masked_multilabel_bce,
    masked_survival_nll,
    observable_nll,
)


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


GOLDEN_LOGITS = torch.tensor([[logit(0.10), logit(0.20), logit(0.30)]])


class TestTR01SurvivalHandCalculation:
    def test_observed_event_at_bin_2(self):
        """Bins 1-2 are at risk, the event lands in bin 2:
        L = -(log(0.9) + log(0.2)) / 2."""
        logits = GOLDEN_LOGITS  # [N=1, H=3]
        event_y = torch.tensor([[0.0, 1.0, 0.0]])
        risk_mask = torch.tensor([[True, True, False]])
        loss, n = masked_survival_nll(logits, event_y, risk_mask)
        expected = -(math.log(0.9) + math.log(0.20)) / 2
        assert n == 2
        assert float(loss) == pytest.approx(expected, abs=1e-6)

    def test_censored_followup_ends_at_bin_2(self):
        """No event observed through bin 2; bin 3 is unresolved and contributes
        no negative label: L = -(log(0.9) + log(0.8)) / 2."""
        event_y = torch.zeros(1, 3)
        risk_mask = torch.tensor([[True, True, False]])
        loss, n = masked_survival_nll(GOLDEN_LOGITS, event_y, risk_mask)
        expected = -(math.log(0.9) + math.log(0.80)) / 2
        assert n == 2
        assert float(loss) == pytest.approx(expected, abs=1e-6)

    def test_masked_bins_contribute_nothing(self):
        """A (hypothetical) label in a masked bin cannot change the loss."""
        event_y = torch.tensor([[0.0, 1.0, 1.0]])
        risk_mask = torch.tensor([[True, True, False]])
        loss_masked, _ = masked_survival_nll(GOLDEN_LOGITS, event_y, risk_mask)
        event_y2 = torch.tensor([[0.0, 1.0, 0.0]])
        loss_clean, _ = masked_survival_nll(GOLDEN_LOGITS, event_y2, risk_mask)
        assert float(loss_masked) == pytest.approx(float(loss_clean), abs=1e-7)

    def test_full_followup_no_event(self):
        event_y = torch.zeros(1, 3)
        risk_mask = torch.ones(1, 3, dtype=torch.bool)
        loss, n = masked_survival_nll(GOLDEN_LOGITS, event_y, risk_mask)
        expected = -(math.log(0.9) + math.log(0.8) + math.log(0.7)) / 3
        assert n == 3
        assert float(loss) == pytest.approx(expected, abs=1e-6)

    def test_all_masked_gives_zero_without_division_error(self):
        event_y = torch.zeros(1, 3)
        risk_mask = torch.zeros(1, 3, dtype=torch.bool)
        loss, n = masked_survival_nll(GOLDEN_LOGITS, event_y, risk_mask)
        assert n == 0
        assert float(loss) == 0.0

    def test_separate_tasks_are_separate_processes(self):
        """Two tasks on one entity: each keeps its own event/mask (the J axis)."""
        logits = GOLDEN_LOGITS.unsqueeze(-1).repeat(1, 1, 2)  # [N=1, H=3, J=2]
        event_y = torch.zeros(1, 3, 2)
        event_y[0, 1, 0] = 1.0  # task 0: event bin 2
        event_y[0, 2, 1] = 1.0  # task 1: event bin 3
        risk_mask = torch.zeros(1, 3, 2, dtype=torch.bool)
        risk_mask[0, :2, 0] = True
        risk_mask[0, :3, 1] = True
        loss, n = masked_survival_nll(logits, event_y, risk_mask)
        expected = -(
            math.log(0.9) + math.log(0.2) + math.log(0.9) + math.log(0.8) + math.log(0.3)
        ) / 5
        assert n == 5
        assert float(loss) == pytest.approx(expected, abs=1e-6)

    def test_extreme_logits_stay_finite(self):
        """logsigmoid is the stable form: |z| = 60 must not produce inf/nan."""
        logits = torch.tensor([[60.0, -60.0, 0.0]])
        event_y = torch.tensor([[1.0, 1.0, 0.0]])
        risk_mask = torch.ones(1, 3, dtype=torch.bool)
        loss, _ = masked_survival_nll(logits, event_y, risk_mask)
        assert torch.isfinite(loss)


class TestGaussianNLL:
    def test_hand_calculation(self):
        """v=1, m=0, s=1 (log_scale=0): 0.5*1 + 0 + 0.5*log(2*pi)."""
        values = torch.tensor([[[1.0]]])       # [N=1, H=1, C=1]
        mean = torch.zeros(1, 1, 1)
        log_scale = torch.zeros(1, 1, 1)
        valid = torch.ones(1, 1, 1, dtype=torch.bool)
        loss, n = masked_gaussian_nll(values, mean, log_scale, valid)
        expected = 0.5 + 0.5 * math.log(2 * math.pi)
        assert n == 1
        assert float(loss) == pytest.approx(expected, abs=1e-6)

    def test_masked_entries_excluded(self):
        values = torch.tensor([1.0, 50.0])
        mean = torch.zeros(2)
        log_scale = torch.zeros(2)
        valid = torch.tensor([True, False])
        loss, n = masked_gaussian_nll(values, mean, log_scale, valid)
        expected = 0.5 + 0.5 * math.log(2 * math.pi)
        assert n == 1
        assert float(loss) == pytest.approx(expected, abs=1e-6)


class TestBCE:
    def test_hand_calculation(self):
        logits = torch.tensor([0.0])
        labels = torch.tensor([1.0])
        mask = torch.tensor([True])
        loss, n = masked_bce(logits, labels, mask)
        assert n == 1
        assert float(loss) == pytest.approx(-math.log(0.5), abs=1e-6)

    def test_multilabel_same_formula(self):
        """Multi-label tactic BCE is independent BCE per coexisting tag: two
        tags labeled 1 and 0 with logits 0 and -20 cost (0.693 + ~0) / 2."""
        logits = torch.tensor([[0.0, -20.0]])
        labels = torch.tensor([[1.0, 0.0]])
        mask = torch.ones(1, 2, dtype=torch.bool)
        loss, n = masked_multilabel_bce(logits, labels, mask)
        assert n == 2
        assert float(loss) == pytest.approx(-math.log(0.5) / 2, abs=1e-5)

    def test_unknown_edge_is_not_a_negative(self):
        """An unseen edge (mask False) contributes nothing even if labeled 0."""
        logits = torch.tensor([[0.0, 0.0]])
        labels = torch.tensor([[1.0, 1.0]])
        mask = torch.tensor([[True, False]])
        loss, n = masked_bce(logits, labels, mask)
        assert n == 1
        assert float(loss) == pytest.approx(-math.log(0.5), abs=1e-6)


class TestObservableNLL:
    def test_groups_averaged_equally(self):
        """Node and global are normalized separately then averaged equally —
        not pooled into one count."""
        node_values = torch.zeros(1, 1, 1)
        node_mean = torch.zeros(1, 1, 1)
        node_ls = torch.zeros(1, 1, 1)
        node_valid = torch.ones(1, 1, 1, dtype=torch.bool)
        g_values = torch.tensor([[2.0]])
        g_mean = torch.zeros(1, 1)
        g_ls = torch.zeros(1, 1)
        g_valid = torch.ones(1, 1, dtype=torch.bool)
        loss, terms = observable_nll(
            node_values, node_mean, node_ls, node_valid,
            g_values, g_mean, g_ls, g_valid,
        )
        base = 0.5 * math.log(2 * math.pi)  # v=0, m=0, s=1: no residual term
        expected = (base + (0.5 * 4.0 + 0.5 * math.log(2 * math.pi))) / 2
        assert terms["node_count"] == 1
        assert terms["global_count"] == 1
        assert float(loss) == pytest.approx(expected, abs=1e-6)

    def test_absent_group_uses_available_without_invented_count(self):
        node_valid = torch.zeros(1, 1, 1, dtype=torch.bool)
        g_values = torch.tensor([[2.0]])
        g_mean = torch.zeros(1, 1)
        g_ls = torch.zeros(1, 1)
        g_valid = torch.ones(1, 1, dtype=torch.bool)
        loss, terms = observable_nll(
            None, None, None, node_valid,
            g_values, g_mean, g_ls, g_valid,
        )
        expected = 0.5 * 4.0 + 0.5 * math.log(2 * math.pi)
        assert terms["node"] is None
        assert float(loss) == pytest.approx(expected, abs=1e-6)

    def test_both_absent_is_zero(self):
        loss, terms = observable_nll(
            None, None, None, None, None, None, None, None
        )
        assert float(loss) == 0.0
        assert terms["node"] is None and terms["global"] is None


class TestCombinedObjective:
    def test_weights_from_section_35(self):
        w = LossWeights()
        assert (w.survival, w.observable, w.edge, w.stage) == (1.0, 0.5, 0.2, 0.2)

    def test_compute_clip_loss_matches_component_formulas(self, model):
        clip = build_clip(num_windows=20, seed=3)
        targets = build_targets(horizon_bins=6)
        with torch.no_grad():
            observed = model.observe_clip(clip)
            outputs = model.roll_out(observed, 4, targets.candidate_pairs, targets.task_mask)
        weights = LossWeights()
        breakdown = compute_clip_loss(outputs, targets, weights)

        # Recompute the survival component by hand from the stacked logits.
        logits = (
            torch.stack([o.hazard_logits for o in outputs], dim=0)[:, 0]
            .permute(1, 0, 2)  # [H', N, J] -> [N, H', J]
        )
        event_y = targets.event_y[:, :4, :]
        risk_mask = targets.risk_mask[:, :4, :] & targets.task_mask
        survival_ref, n_surv = masked_survival_nll(logits, event_y, risk_mask)
        assert breakdown.survival_count == n_surv
        assert float(breakdown.survival) == pytest.approx(float(survival_ref), abs=1e-6)

        # Total is the Section-35 weighted sum of the components.
        expected_total = (
            1.0 * float(breakdown.survival)
            + 0.5 * float(breakdown.observable)
            + 0.2 * float(breakdown.edge)
            + 0.2 * float(breakdown.stage)
        )
        assert float(breakdown.total) == pytest.approx(expected_total, abs=1e-5)
        assert breakdown.horizon_bins == 4
        assert breakdown.per_bin_survival.shape == (4,)

    def test_short_rollout_uses_available_bins_only(self, model):
        """Curriculum rollouts train only on the bins they produce."""
        clip = build_clip(num_windows=20, seed=4)
        targets = build_targets(horizon_bins=6)
        with torch.no_grad():
            observed = model.observe_clip(clip)
            outputs = model.roll_out(observed, 1, targets.candidate_pairs, targets.task_mask)
        breakdown = compute_clip_loss(outputs, targets, LossWeights())
        assert breakdown.horizon_bins == 1
        assert breakdown.per_bin_survival.shape == (1,)

    def test_unsupported_tasks_masked_from_loss(self, model):
        clip = build_clip(num_windows=20, seed=5)
        candidates = build_candidates()
        task_mask = torch.tensor([True, False, False, False, False])
        targets = build_targets(horizon_bins=4, candidates=candidates, task_mask=task_mask)
        with torch.no_grad():
            observed = model.observe_clip(clip)
            outputs = model.roll_out(observed, 4, candidates, task_mask)
        breakdown = compute_clip_loss(outputs, targets, LossWeights())
        # Only task 0 rows contribute: N=4 entities * H=4 bins * 1 task.
        assert breakdown.survival_count == 16

    def test_rollout_longer_than_targets_rejected(self, model):
        clip = build_clip(num_windows=20, seed=6)
        targets = build_targets(horizon_bins=2)
        with torch.no_grad():
            observed = model.observe_clip(clip)
            outputs = model.roll_out(observed, 3, targets.candidate_pairs, targets.task_mask)
        with pytest.raises(ContractError, match="targets cover"):
            compute_clip_loss(outputs, targets, LossWeights())
