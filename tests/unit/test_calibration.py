"""Hazard calibration tests (Build Spec Appendix I.4).

The affine calibrator (shared slope + intercept, regularized horizon-group
intercepts for bins 1-10 / 11-30 / 31-60) is fitted by survival likelihood;
recovery is checked against known ground-truth parameters, calibrated hazards
must produce monotone survival by construction, and sparse cells must fall
back to pooled calibrators or explicit abstention.
"""

from __future__ import annotations

import math

import pytest
import torch

from foresight.calibration.hazard import (
    HORIZON_GROUPS,
    CalibratorSet,
    HazardCalibrator,
    calibration_support,
    fit_hazard_calibrator,
    horizon_group_index,
    horizon_group_vector,
)
from foresight.models.survival import distribution_from_hazards, hazards_from_logits
from foresight.models.types import ContractError

TRUE_A, TRUE_B = 1.3, -0.35
TRUE_G = (0.25, -0.15, 0.05)


def logit(p):
    return math.log(p / (1.0 - p))


def make_calibration_data(
    *,
    num_examples: int = 20000,
    horizon_bins: int = 20,
    seed: int = 0,
    true_a: float = TRUE_A,
    true_b: float = TRUE_B,
    true_g: tuple[float, ...] = TRUE_G,
):
    """Raw logits whose affine transform equals the logit of the true hazards.

    Labels are sampled by exact inverse-CDF from the true survival
    distribution, so the survival-likelihood MLE recovers the parameters.
    """
    gen = torch.Generator().manual_seed(seed)
    H = horizon_bins
    groups = horizon_group_vector(H)
    # True hazards vary across bins (0.02..0.08) so all groups are exercised.
    base = torch.linspace(0.08, 0.02, H).double()
    true_logits = torch.tensor(
        [logit(float(q)) for q in base], dtype=torch.float64
    )
    g = torch.tensor(true_g).double()
    # raw z satisfies: a*z + b + g[group] = logit(q)
    raw = (true_logits - true_b - g[groups]) / true_a
    raw = raw + 0.01 * torch.randn(num_examples, H, generator=gen).double()

    event_y = torch.zeros(num_examples, H)
    risk_mask = torch.ones(num_examples, H, dtype=torch.bool)
    u = torch.rand(num_examples, generator=gen).double()
    survival = torch.cumprod(1.0 - base, dim=0)
    cum_mass = 1.0 - survival  # cumulative risk after bin j
    prev = torch.cat([torch.zeros(H).double(), cum_mass[:-1]])
    for k in range(num_examples):
        hit = (cum_mass >= u[k]).nonzero()
        if hit.numel() > 0:
            j = int(hit[0, 0])
            event_y[k, j] = 1.0
            risk_mask[k, j + 1 :] = False
    return raw.float(), event_y, risk_mask


class TestHorizonGroups:
    def test_group_boundaries(self):
        assert horizon_group_index(1) == 0
        assert horizon_group_index(10) == 0
        assert horizon_group_index(11) == 1
        assert horizon_group_index(30) == 1
        assert horizon_group_index(31) == 2
        assert horizon_group_index(60) == 2

    def test_bins_past_60_stay_in_last_group(self):
        assert horizon_group_index(61) == 2
        assert horizon_group_index(120) == 2

    def test_groups_match_spec(self):
        assert HORIZON_GROUPS == ((1, 10), (11, 30), (31, 60))

    def test_vector(self):
        v = horizon_group_vector(35)
        assert v[0] == 0 and v[9] == 0
        assert v[10] == 1 and v[29] == 1
        assert v[30] == 2 and v[34] == 2


class TestAffineRecovery:
    def test_fit_recovers_ground_truth(self):
        raw, event_y, risk_mask = make_calibration_data()
        cal = fit_hazard_calibrator(raw, event_y, risk_mask, task_index=0)
        assert cal.fitted and not cal.abstained
        # Slope and intercept are weakly identified along a common valley
        # (a*z + b is nearly flat over the data's logit range), so individual
        # parameters get loose bounds — what must be recovered is the affine
        # transform and the likelihood.
        assert cal.slope == pytest.approx(TRUE_A, abs=0.2)

        groups = horizon_group_vector(raw.shape[1])
        true_calibrated = (
            TRUE_A * raw + TRUE_B + torch.tensor(TRUE_G)[groups].unsqueeze(0)
        )
        fitted_calibrated = cal.apply(raw)
        mean_abs_diff = float((fitted_calibrated - true_calibrated).abs().mean())
        assert mean_abs_diff < 0.1, (
            f"fitted transform drifts from ground truth: {mean_abs_diff}"
        )

        def total_nll(logits):
            m = risk_mask.float()
            per = event_y * torch.nn.functional.logsigmoid(logits) + (
                1 - event_y
            ) * torch.nn.functional.logsigmoid(-logits)
            return float(-(m * per).sum())

        assert total_nll(fitted_calibrated) <= total_nll(true_calibrated) + 1e-3

    def test_identity_when_data_already_calibrated(self):
        raw, event_y, risk_mask = make_calibration_data(
            true_a=1.0, true_b=0.0, true_g=(0.0, 0.0, 0.0), seed=3
        )
        cal = fit_hazard_calibrator(raw, event_y, risk_mask, task_index=0)
        assert cal.slope == pytest.approx(1.0, abs=0.1)
        assert cal.intercept == pytest.approx(0.0, abs=0.15)


class TestApplyAndMonotonicity:
    def test_apply_matches_affine_formula(self):
        cal = HazardCalibrator(
            task_index=0,
            slope=2.0,
            intercept=0.5,
            group_intercepts=(0.1, -0.2, 0.05),
            horizon_bins=35,
            min_events=20,
            fit_event_count=50,
            fit_example_count=10,
            fitted=True,
        )
        z = torch.zeros(35)
        out = cal.apply(z)
        # bin 1 (group 0): 0.5 + 0.1; bin 11 (group 1): 0.5 - 0.2; bin 31: 0.55
        assert float(out[0]) == pytest.approx(0.6)
        assert float(out[10]) == pytest.approx(0.3)
        assert float(out[30]) == pytest.approx(0.55)

    def test_apply_preserves_leading_shape(self):
        cal = HazardCalibrator(
            task_index=0, slope=1.0, intercept=0.0, group_intercepts=(0.0, 0.0, 0.0),
            horizon_bins=10, min_events=20, fit_event_count=50,
            fit_example_count=10, fitted=True,
        )
        z = torch.randn(4, 7, 10)
        assert cal.apply(z).shape == (4, 7, 10)

    def test_calibrated_survival_monotone_by_construction(self):
        """Apply calibrated hazards, THEN derive survival: cumulative risk is
        nondecreasing and mass is conserved for arbitrary raw logits."""
        raw, event_y, risk_mask = make_calibration_data(num_examples=400, seed=5)
        cal = fit_hazard_calibrator(raw, event_y, risk_mask, task_index=0)
        torch.manual_seed(0)
        z = torch.randn(50, 20) * 3
        calibrated = cal.apply(z)
        d = distribution_from_hazards(hazards_from_logits(calibrated))
        assert bool(
            (d.cumulative_risk[..., 1:] >= d.cumulative_risk[..., :-1] - 1e-12).all()
        )
        total = d.event_mass.sum(dim=-1) + d.no_event_mass
        assert torch.allclose(
            total, torch.ones(50, dtype=torch.float64), atol=1e-9
        )

    def test_fit_improves_survival_likelihood(self):
        """On miscalibrated logits, the fitted transform lowers the survival
        NLL relative to the raw logits (the fit is doing real work)."""
        raw, event_y, risk_mask = make_calibration_data(seed=11)
        cal = fit_hazard_calibrator(raw, event_y, risk_mask, task_index=0)

        def nll(logits):
            m = risk_mask.float()
            per = event_y * torch.nn.functional.logsigmoid(logits) + (
                1 - event_y
            ) * torch.nn.functional.logsigmoid(-logits)
            return float(-(m * per).sum() / m.sum().clamp(min=1))

        assert nll(cal.apply(raw)) < nll(raw)


class TestSparseCells:
    def test_sparse_cell_abstains(self):
        raw, event_y, risk_mask = make_calibration_data(num_examples=100, seed=7)
        event_y[:] = 0.0
        event_y[:3, 0] = 1.0  # 3 events < min_events=20
        cal = fit_hazard_calibrator(raw, event_y, risk_mask, task_index=2, min_events=20)
        assert cal.abstained and not cal.fitted
        assert "sparse cell" in (cal.abstain_reason or "")
        assert cal.status == "abstained"

    def test_abstained_calibrator_is_identity(self):
        raw, _, _ = make_calibration_data(num_examples=10, seed=8)
        event_y = torch.zeros(10, 20)
        risk_mask = torch.ones(10, 20, dtype=torch.bool)
        cal = fit_hazard_calibrator(raw, event_y, risk_mask, task_index=0)
        assert torch.equal(cal.apply(raw), raw)

    def test_pooled_backoff(self):
        """A sparse task cell falls back to the pooled calibrator (I.4)."""
        raw, event_y, risk_mask = make_calibration_data(num_examples=1500, seed=9)
        pooled = fit_hazard_calibrator(
            raw, event_y, risk_mask, task_index=-1, pooled=True
        )
        assert pooled.fitted and pooled.pooled
        sparse = fit_hazard_calibrator(
            raw, torch.zeros_like(event_y), risk_mask, task_index=4
        )
        assert sparse.abstained
        cs = CalibratorSet(calibrators={}, pooled=pooled)
        logits = torch.randn(20)
        calibrated, status = cs.calibrate(logits, task=4)
        assert status == "pooled"
        assert not torch.equal(calibrated, logits)


class TestCalibratorSet:
    def test_task_cell_lookup(self):
        raw, event_y, risk_mask = make_calibration_data(num_examples=1500, seed=12)
        cal = fit_hazard_calibrator(raw, event_y, risk_mask, task_index=1)
        cs = CalibratorSet(calibrators={(1, None): cal})
        logits = torch.randn(20)
        calibrated, status = cs.calibrate(logits, task=1)
        assert status == "task"
        assert not torch.equal(calibrated, logits)

    def test_regime_specific_cell_preferred(self):
        raw_a, event_y_a, risk_mask_a = make_calibration_data(num_examples=1500, seed=13)
        raw_b, event_y_b, risk_mask_b = make_calibration_data(num_examples=1500, seed=14)
        generic = fit_hazard_calibrator(raw_a, event_y_a, risk_mask_a, task_index=0)
        regime = fit_hazard_calibrator(
            raw_b, event_y_b, risk_mask_b, task_index=0, regime="green"
        )
        assert not torch.allclose(
            torch.tensor(generic.group_intercepts),
            torch.tensor(regime.group_intercepts),
        )
        cs = CalibratorSet(calibrators={(0, None): generic, (0, "green"): regime})
        logits = torch.randn(20)
        calibrated, status = cs.calibrate(logits, task=0, regime="green")
        assert status == "task"
        assert torch.allclose(calibrated, regime.apply(logits))

    def test_empty_set_reports_uncalibrated(self):
        cs = CalibratorSet(calibrators={})
        logits = torch.randn(20)
        calibrated, status = cs.calibrate(logits, task=0)
        assert status == "uncalibrated"
        assert torch.equal(calibrated, logits)

    def test_serialization_round_trip(self):
        raw, event_y, risk_mask = make_calibration_data(num_examples=800, seed=14)
        cal = fit_hazard_calibrator(raw, event_y, risk_mask, task_index=3)
        restored = HazardCalibrator.from_dict(cal.to_dict())
        assert restored.to_dict() == cal.to_dict()
        z = torch.randn(6, 20)
        assert torch.equal(restored.apply(z), cal.apply(z))

    def test_shape_mismatch_rejected(self):
        raw, event_y, _ = make_calibration_data(num_examples=10, horizon_bins=20)
        with pytest.raises(ContractError):
            fit_hazard_calibrator(
                raw, event_y[:, :10], torch.ones(10, 10, dtype=torch.bool), task_index=0
            )


class TestCalibrationSupportReport:
    def test_tr03_support_report(self):
        _, event_y_2d, risk_mask_2d = make_calibration_data(num_examples=500, seed=15)
        event_y = torch.zeros(500, 20, 3)
        event_y[..., 0] = event_y_2d  # only task 0 observes events
        risk_mask = torch.ones(500, 20, 3, dtype=torch.bool)
        risk_mask[..., 0] = risk_mask_2d
        task_mask = torch.tensor([True, True, False])
        report = calibration_support(event_y, risk_mask, task_mask, min_events=20)
        assert report[0]["fit"] is True and report[0]["action"] == "fit_task_calibrator"
        assert report[1]["fit"] is False and report[1]["action"] == "pooled_or_abstain"
        assert report[2]["supported"] is False and report[2]["action"] == "not_supported"
