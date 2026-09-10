"""Survival probability contract (Build Spec Section 12, I.5; Appendix R.2).

Golden example 1 (Section 35): hazards [0.10, 0.20, 0.30] must yield
event mass [0.100, 0.180, 0.216], cumulative risk [0.100, 0.280, 0.496],
no-event mass 0.504, and (R.2) a conditional median in bin 2.
"""

from __future__ import annotations

import math

import pytest
import torch

from foresight.models.survival import (
    ConditionalETA,
    EventDistribution,
    conditional_eta,
    distribution_from_hazards,
    hazards_from_logits,
    mixture_from_distributions,
)
from foresight.models.types import ContractError


def close(a, b, tol=1e-12):
    return abs(float(a) - float(b)) <= tol


GOLDEN_HAZARDS = torch.tensor([0.10, 0.20, 0.30], dtype=torch.float64)


class TestGoldenExample1:
    def test_exact_values(self):
        d = distribution_from_hazards(GOLDEN_HAZARDS)
        assert torch.allclose(
            d.event_mass, torch.tensor([0.100, 0.180, 0.216], dtype=torch.float64),
            atol=1e-12,
        )
        assert torch.allclose(
            d.cumulative_risk, torch.tensor([0.100, 0.280, 0.496], dtype=torch.float64),
            atol=1e-12,
        )
        assert close(d.no_event_mass, 0.504)
        assert d.bin_seconds == 30
        assert d.horizon_bins == 3

    def test_conditional_median_is_bin_2(self):
        """R.2: for golden example 1 the conditional median is bin 2 —
        0.28 / 0.496 = 0.5645 >= 0.5 while 0.10 / 0.496 < 0.5."""
        d = distribution_from_hazards(GOLDEN_HAZARDS)
        eta = conditional_eta(d, min_occurrence_probability=0.0)
        assert eta is not None
        assert eta.median_bin == 2
        assert eta.median_seconds == 60
        assert close(eta.occurrence_probability, 0.496)

    def test_hazards_are_preserved(self):
        d = distribution_from_hazards(GOLDEN_HAZARDS)
        assert torch.allclose(d.hazards, GOLDEN_HAZARDS)


class TestSurvivalMath:
    def test_zero_hazards(self):
        d = distribution_from_hazards(torch.zeros(60))
        assert torch.count_nonzero(d.event_mass) == 0
        assert torch.count_nonzero(d.cumulative_risk) == 0
        assert close(d.no_event_mass, 1.0)

    def test_certain_first_bin(self):
        d = distribution_from_hazards(torch.tensor([1.0, 0.0, 0.0], dtype=torch.float64))
        assert torch.allclose(
            d.event_mass, torch.tensor([1.0, 0.0, 0.0], dtype=torch.float64)
        )
        assert torch.allclose(
            d.cumulative_risk, torch.tensor([1.0, 1.0, 1.0], dtype=torch.float64)
        )
        assert close(d.no_event_mass, 0.0)
        eta = conditional_eta(d, min_occurrence_probability=0.5)
        assert eta.median_bin == 1

    def test_unit_first_bin(self):
        d = distribution_from_hazards(torch.tensor([1.0, 0.5, 0.5], dtype=torch.float64))
        assert torch.allclose(
            d.event_mass, torch.tensor([1.0, 0.0, 0.0], dtype=torch.float64), atol=1e-12
        )
        assert close(d.no_event_mass, 0.0)

    def test_monotone_cumulative_and_bounds(self):
        torch.manual_seed(0)
        for _ in range(50):
            q = torch.rand(60, dtype=torch.float64)
            d = distribution_from_hazards(q)
            assert (d.cumulative_risk >= -1e-12).all()
            assert (d.cumulative_risk <= 1 + 1e-12).all()
            diffs = d.cumulative_risk[1:] - d.cumulative_risk[:-1]
            assert (diffs >= -1e-15).all(), "cumulative risk must be nondecreasing"
            assert (d.event_mass >= -1e-15).all()

    def test_mass_conservation(self):
        torch.manual_seed(1)
        for _ in range(50):
            q = torch.rand(60, dtype=torch.float64)
            d = distribution_from_hazards(q)
            total = float(d.event_mass.sum()) + float(d.no_event_mass)
            assert close(total, 1.0, tol=1e-10)
            # cumulative[j] must equal sum of event mass up to j
            assert torch.allclose(
                d.cumulative_risk, torch.cumsum(d.event_mass, dim=-1), atol=1e-12
            )

    def test_small_hazards_stable(self):
        """1 - S computed via log1p must survive tiny hazards without cancellation."""
        d = distribution_from_hazards(torch.full((60,), 1e-9, dtype=torch.float64))
        assert d.cumulative_risk[0] > 0
        # exact value is 1 - (1 - 1e-9)**60; the log1p path stays within ~2e-15
        # (no catastrophic cancellation, unlike naive 1 - prod in float32)
        assert close(d.cumulative_risk[-1], 1.0 - (1.0 - 1e-9) ** 60, tol=1e-14)

    def test_out_of_range_hazards_rejected(self):
        with pytest.raises(ContractError):
            distribution_from_hazards(torch.tensor([0.1, 1.1]))
        with pytest.raises(ContractError):
            distribution_from_hazards(torch.tensor([-0.1, 0.1]))

    def test_batched_hazards(self):
        q = torch.tensor(
            [[0.1, 0.2, 0.3], [0.5, 0.0, 0.0]], dtype=torch.float64
        )
        d = distribution_from_hazards(q)
        assert d.event_mass.shape == (2, 3)
        assert close(d.no_event_mass[0], 0.504)
        assert close(d.no_event_mass[1], 0.5)

    def test_bin_seconds_validated(self):
        with pytest.raises(ContractError):
            distribution_from_hazards(torch.tensor([0.1]), bin_seconds=0)


class TestHazardsFromLogits:
    def test_sigmoid_readout(self):
        logits = torch.tensor([0.0, 20.0, -20.0, 3.0], dtype=torch.float64)
        q = hazards_from_logits(logits)
        assert close(q[0], 0.5)
        assert close(q[1], 1.0, tol=1e-8)
        assert close(q[2], 0.0, tol=1e-8)
        assert close(q[3], 1.0 / (1.0 + math.exp(-3.0)))

    def test_output_is_valid_hazards(self):
        torch.manual_seed(2)
        q = hazards_from_logits(torch.randn(100, 5) * 50)
        d = distribution_from_hazards(q)
        assert torch.isfinite(d.event_mass).all()


class TestConditionalETA:
    def test_withheld_below_threshold(self):
        """The countdown is withheld when occurrence probability is insufficient
        (Section 12) — a low-confidence ETA is None, not an invented value."""
        d = distribution_from_hazards(torch.tensor([0.10, 0.10, 0.10]))
        assert float(d.cumulative_risk[-1]) == pytest.approx(0.271)
        assert conditional_eta(d, min_occurrence_probability=0.35) is None

    def test_returned_at_threshold(self):
        d = distribution_from_hazards(torch.tensor([0.10, 0.10, 0.10]))
        eta = conditional_eta(d, min_occurrence_probability=0.271)
        assert eta is not None

    def test_never_withheld_at_zero_threshold_when_certain(self):
        d = distribution_from_hazards(torch.tensor([1.0]))
        eta = conditional_eta(d, min_occurrence_probability=0.99)
        assert eta is not None and eta.median_bin == 1

    def test_zero_occurrence_withheld(self):
        d = distribution_from_hazards(torch.zeros(10))
        assert conditional_eta(d, min_occurrence_probability=0.0) is None

    def test_quantiles_bracket_median(self):
        q = torch.tensor([0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        d = distribution_from_hazards(q)
        eta = conditional_eta(
            d,
            min_occurrence_probability=0.5,
            lower_quantile=0.25,
            upper_quantile=0.75,
        )
        assert eta is not None
        assert eta.lower_quantile_bin <= eta.median_bin <= eta.upper_quantile_bin
        assert eta.median_seconds == eta.median_bin * 30

    def test_eta_consistent_with_distribution(self):
        """CA02: any published ETA must be consistent with the published
        distribution — the median bin is the first bin whose conditional
        cumulative reaches 0.5, and occurrence equals cumulative[-1]."""
        torch.manual_seed(3)
        for _ in range(20):
            q = torch.rand(30, dtype=torch.float64)
            d = distribution_from_hazards(q)
            eta = conditional_eta(d, min_occurrence_probability=0.3)
            if eta is None:
                assert float(d.cumulative_risk[-1]) < 0.3
                continue
            occ = float(d.cumulative_risk[-1])
            assert close(eta.occurrence_probability, occ, tol=1e-9)
            cond = d.cumulative_risk / occ
            j = eta.median_bin  # 1-indexed
            assert float(cond[j - 1]) >= 0.5 - 1e-12
            if j > 1:
                assert float(cond[j - 2]) < 0.5


class TestCA03EnsembleMixture:
    def test_mixture_averages_distributions_not_hazards(self):
        d1 = distribution_from_hazards(GOLDEN_HAZARDS)
        d2 = distribution_from_hazards(
            torch.tensor([0.30, 0.30, 0.30], dtype=torch.float64)
        )
        mix = mixture_from_distributions([d1, d2])

        # Mixture event mass and cumulative are the member averages.
        assert torch.allclose(
            mix.event_mass, (d1.event_mass + d2.event_mass) / 2, atol=1e-12
        )
        assert torch.allclose(
            mix.cumulative_risk, (d1.cumulative_risk + d2.cumulative_risk) / 2,
            atol=1e-12,
        )
        assert close(mix.no_event_mass, (0.504 + float(d2.no_event_mass)) / 2)

        # Averaged hazards are NOT the mixture hazards (the exact CA03 trap).
        avg_hazards = (d1.hazards + d2.hazards) / 2
        assert not torch.allclose(mix.hazards, avg_hazards, atol=1e-6)

        # Recovered hazards are consistent: event_mass[j] = S_prev[j] * q[j].
        survival_prev = torch.cat(
            [torch.ones(1, dtype=torch.float64), 1.0 - mix.cumulative_risk[:-1]]
        )
        assert torch.allclose(
            mix.event_mass, survival_prev * mix.hazards, atol=1e-9
        )

    def test_mixture_of_identical_members_is_member(self):
        d = distribution_from_hazards(torch.tensor([0.10, 0.20, 0.30]))
        mix = mixture_from_distributions([d, d, d])
        assert torch.allclose(mix.event_mass, d.event_mass, atol=1e-12)
        assert torch.allclose(mix.cumulative_risk, d.cumulative_risk, atol=1e-12)
        assert close(mix.no_event_mass, float(d.no_event_mass))
        assert torch.allclose(mix.hazards, d.hazards, atol=1e-12)

    def test_mixture_mass_conservation(self):
        d1 = distribution_from_hazards(torch.tensor([0.1, 0.2, 0.3, 0.1]))
        d2 = distribution_from_hazards(torch.tensor([0.0, 0.9, 0.05, 0.05]))
        d3 = distribution_from_hazards(torch.tensor([0.5, 0.5, 0.5, 0.5]))
        mix = mixture_from_distributions([d1, d2, d3])
        total = float(mix.event_mass.sum()) + float(mix.no_event_mass)
        assert close(total, 1.0, tol=1e-10)
        diffs = mix.cumulative_risk[1:] - mix.cumulative_risk[:-1]
        assert (diffs >= -1e-15).all()

    def test_mixture_horizon_mismatch_rejected(self):
        d1 = distribution_from_hazards(torch.tensor([0.1, 0.2]))
        d2 = distribution_from_hazards(torch.tensor([0.1, 0.2, 0.3]))
        with pytest.raises(ContractError):
            mixture_from_distributions([d1, d2])

    def test_mixture_bin_size_mismatch_rejected(self):
        d1 = distribution_from_hazards(torch.tensor([0.1]), bin_seconds=30)
        d2 = distribution_from_hazards(torch.tensor([0.1]), bin_seconds=60)
        with pytest.raises(ContractError):
            mixture_from_distributions([d1, d2])

    def test_mixture_empty_rejected(self):
        with pytest.raises(ContractError):
            mixture_from_distributions([])

    def test_eta_from_mixture(self):
        """The mixture feeds conditional_eta like any member distribution."""
        d1 = distribution_from_hazards(torch.tensor([0.10, 0.20, 0.30]))
        d2 = distribution_from_hazards(torch.tensor([0.60, 0.10, 0.10]))
        mix = mixture_from_distributions([d1, d2])
        eta = conditional_eta(mix, min_occurrence_probability=0.5)
        assert eta is not None
        assert 1 <= eta.median_bin <= 3
