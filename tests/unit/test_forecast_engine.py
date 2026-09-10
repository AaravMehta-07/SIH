"""Section 26 inference-engine tests — the synthetic vertical slice.

A synthetic clip flows through the real interfaces: observe loop -> rollout
from a copied state -> per-bin hazards -> optional calibration -> survival
transform -> conditional ETA -> typed ForecastResult. This is the Team Work
Distribution's done-criterion for the world-model area, run end to end with no
stubs, plus the I.5 ensemble path.
"""

from __future__ import annotations

import pytest
import torch

from conftest import build_candidates, build_clip, build_targets
from foresight.calibration.hazard import (
    CalibratorSet,
    fit_hazard_calibrator,
)
from foresight.models.types import ContractError, NonFiniteTensorError
from foresight.models.world_model import ForesightWorldModel
from foresight.runtime.forecast import (
    DEFAULT_DISPLAY_ETA_THRESHOLD,
    EnsembleForecaster,
    ForecastEngine,
    ForecastRequest,
)


@pytest.fixture()
def request60(core_config):
    return ForecastRequest.from_config(core_config)


@pytest.fixture()
def clip():
    return build_clip(num_windows=20, seed=11)


class TestVerticalSlice:
    def test_full_pipeline_through_real_interfaces(self, model, clip, request60):
        engine = ForecastEngine(model)
        result = engine.forecast(clip, request60)
        assert result.horizon_bins == 60
        assert result.bin_seconds == 30
        assert result.published_horizons_seconds == (300, 900, 1800)
        assert len(result.entities) == 4  # all four slots present
        for entity in result.entities:
            assert len(entity.task_forecasts) == 5
            for tf in entity.task_forecasts:
                assert tf.status == "supported"
                assert tf.distribution is not None
                assert tf.distribution.horizon_bins == 60
        assert result.node_mean.shape == (60, 4, 44)
        assert result.global_mean.shape == (60, 24)
        assert result.tactic_logits.shape == (60, 4, 5)
        assert result.edge_logits is None  # no candidates requested

    def test_distributions_are_valid_survival_curves(self, model, clip, request60):
        result = ForecastEngine(model).forecast(clip, request60)
        for entity in result.entities:
            for tf in entity.task_forecasts:
                d = tf.distribution
                cum = d.cumulative_risk
                assert bool((cum[..., 1:] >= cum[..., :-1] - 1e-12).all())
                total = float(d.event_mass.sum()) + float(d.no_event_mass)
                assert total == pytest.approx(1.0, abs=1e-9)
                assert bool((d.hazards >= 0).all()) and bool((d.hazards <= 1).all())

    def test_eta_consistent_with_distribution(self, model, clip, request60):
        """CA02 carried through the engine: a published ETA matches the
        published distribution; a withheld ETA records its reason."""
        result = ForecastEngine(model).forecast(clip, request60)
        for entity in result.entities:
            for tf in entity.task_forecasts:
                occurrence = float(tf.distribution.cumulative_risk[-1])
                if tf.conditional_eta is not None:
                    assert tf.eta_withheld_reason is None
                    eta = tf.conditional_eta
                    assert eta.occurrence_probability == pytest.approx(
                        occurrence, abs=1e-9
                    )
                    cond = tf.distribution.cumulative_risk / occurrence
                    j = eta.median_bin
                    assert float(cond[j - 1]) >= 0.5 - 1e-12
                    if j > 1:
                        assert float(cond[j - 2]) < 0.5
                else:
                    assert tf.eta_withheld_reason is not None
                    assert (
                        occurrence < request60.min_occurrence_probability
                        or occurrence == 0.0
                    )

    def test_unsupported_tasks_get_explicit_status(self, model, clip, core_config):
        base = ForecastRequest.from_config(core_config)
        request = ForecastRequest(
            horizon_bins=base.horizon_bins,
            bin_seconds=base.bin_seconds,
            task_mask=torch.tensor([True, True, False, False, False]),
            min_occurrence_probability=base.min_occurrence_probability,
            published_horizons_seconds=base.published_horizons_seconds,
        )
        result = ForecastEngine(model).forecast(clip, request)
        for entity in result.entities:
            statuses = [tf.status for tf in entity.task_forecasts]
            assert statuses == ["supported", "supported"] + ["not_supported"] * 3
            for tf in entity.task_forecasts[2:]:
                assert tf.distribution is None
                assert tf.conditional_eta is None
                assert "not qualified" in tf.eta_withheld_reason

    def test_observed_state_is_frozen_by_forecast(self, model, clip, request60):
        """Section 26: the rollout modifies a copied state only — forecasting
        must not disturb the model or the observed context."""
        with torch.no_grad():
            before = model.observe_clip(clip)
            ForecastEngine(model).forecast(clip, request60)
            after = model.observe_clip(clip)
        assert torch.equal(before.entity_memory, after.entity_memory)
        assert torch.equal(before.global_h, after.global_h)
        assert torch.equal(before.global_c, after.global_c)

    def test_deterministic(self, model, clip, request60):
        engine = ForecastEngine(model)
        r1 = engine.forecast(clip, request60)
        r2 = engine.forecast(clip, request60)
        assert torch.equal(r1.node_mean, r2.node_mean)
        for e1, e2 in zip(r1.entities, r2.entities):
            for tf1, tf2 in zip(e1.task_forecasts, e2.task_forecasts):
                assert torch.equal(
                    tf1.distribution.hazards, tf2.distribution.hazards
                )
                assert tf1.conditional_eta == tf2.conditional_eta

    def test_calibration_applied_and_monotone(self, model, clip, core_config, request60):
        """Fitted I.4 calibrators enter the pipeline; calibrated distributions
        stay monotone and the status is reported per task."""
        with torch.no_grad():
            observed = model.observe_clip(clip)
            outputs = model.roll_out(observed, 60, None, None)
        # Build calibration data from the engine's own logits for entity 0,
        # with labels sampled from a plausible hazard profile.
        gen = torch.Generator().manual_seed(3)
        K = 400
        base = torch.linspace(0.10, 0.02, 60).double()
        logits = torch.stack(
            [outputs[j].hazard_logits[0, 0, 0] for j in range(60)]
        ).unsqueeze(0).expand(K, 60)
        event_y = torch.zeros(K, 60)
        risk_mask = torch.ones(K, 60, dtype=torch.bool)
        u = torch.rand(K, generator=gen).double()
        survival = torch.cumprod(1.0 - base, dim=0)
        cum_mass = 1.0 - survival
        for k in range(K):
            hit = (cum_mass >= u[k]).nonzero()
            if hit.numel() > 0:
                j = int(hit[0, 0])
                event_y[k, j] = 1.0
                risk_mask[k, j + 1 :] = False
        cal = fit_hazard_calibrator(logits, event_y, risk_mask, task_index=0)
        assert cal.fitted
        cs = CalibratorSet(calibrators={(0, None): cal})
        result = ForecastEngine(model, calibrator_set=cs).forecast(clip, request60)
        for entity in result.entities:
            assert entity.task_forecasts[0].calibration_status == "task"
            assert (
                entity.task_forecasts[1].calibration_status == "uncalibrated"
            )
            d = entity.task_forecasts[0].distribution
            assert bool(
                (d.cumulative_risk[1:] >= d.cumulative_risk[:-1] - 1e-12).all()
            )

    def test_uncalibrated_engine_reports_status(self, model, clip, request60):
        result = ForecastEngine(model).forecast(clip, request60)
        assert (
            result.entities[0].task_forecasts[0].calibration_status
            == "uncalibrated"
        )

    def test_omitted_stages_are_reported_not_faked(self, model, clip, request60):
        result = ForecastEngine(model).forecast(clip, request60)
        joined = " ".join(result.omitted)
        for stage in ("trust", "novelty", "evidence", "ledger", "publish"):
            assert stage in joined

    def test_nonfinite_input_raises_numeric_failure(self, model, request60):
        clip = build_clip(num_windows=5, seed=1)
        window = clip[-1]
        window.x[0, 0] = float("inf")
        engine = ForecastEngine(model)
        with pytest.raises((NonFiniteTensorError, ContractError)):
            engine.forecast(clip, request60)


class TestRequestValidation:
    def test_empty_clip_rejected(self, model, request60):
        with pytest.raises(ContractError):
            ForecastEngine(model).forecast([], request60)

    def test_bad_horizon_rejected(self, model, clip):
        request = ForecastRequest(
            horizon_bins=0,
            bin_seconds=30,
            task_mask=None,
            min_occurrence_probability=0.3,
            published_horizons_seconds=(300,),
        )
        with pytest.raises(ContractError):
            ForecastEngine(model).forecast(clip, request)

    def test_bad_task_mask_rejected(self, model, clip, request60):
        request = ForecastRequest(
            horizon_bins=60,
            bin_seconds=30,
            task_mask=torch.ones(3, dtype=torch.bool),
            min_occurrence_probability=0.3,
            published_horizons_seconds=(300,),
        )
        with pytest.raises(ContractError):
            ForecastEngine(model).forecast(clip, request)

    def test_display_threshold_default(self):
        assert DEFAULT_DISPLAY_ETA_THRESHOLD == 0.30
        assert DEFAULT_DISPLAY_ETA_THRESHOLD <= 0.496  # ADR-001 golden example


class TestEnsemble:
    @pytest.fixture()
    def engines(self, core_config):
        members = []
        for seed in (0, 1, 2):
            torch.manual_seed(seed)
            m = ForesightWorldModel.from_config(core_config, num_event_tasks=5)
            members.append(ForecastEngine(m))
        return members

    def test_mixture_averages_member_distributions(self, engines, clip, request60):
        members = [e.forecast(clip, request60) for e in engines]
        ens = EnsembleForecaster(engines)
        result = ens.forecast(clip, request60)
        entity = result.entities[0]
        tf = entity.task_forecasts[0]
        member_dists = [
            m.entities[0].task_forecasts[0].distribution for m in members
        ]
        expected_mass = torch.stack([d.event_mass for d in member_dists]).mean(dim=0)
        assert torch.allclose(tf.distribution.event_mass, expected_mass, atol=1e-12)
        total = float(tf.distribution.event_mass.sum()) + float(
            tf.distribution.no_event_mass
        )
        assert total == pytest.approx(1.0, abs=1e-9)

    def test_disagreement_labeled_not_evidence(self, engines, clip, request60):
        result = EnsembleForecaster(engines).forecast(clip, request60)
        assert result.model_disagreement is not None
        assert len(result.model_disagreement) == 20  # 4 entities x 5 tasks
        for value in result.model_disagreement.values():
            assert value >= 0.0

    def test_identical_members_have_zero_disagreement(self, core_config, clip, request60):
        torch.manual_seed(0)
        m = ForesightWorldModel.from_config(core_config, num_event_tasks=5)
        engines = [ForecastEngine(m), ForecastEngine(m), ForecastEngine(m)]
        result = EnsembleForecaster(engines).forecast(clip, request60)
        assert all(v == 0.0 for v in result.model_disagreement.values())
        single = engines[0].forecast(clip, request60)
        tf_mix = result.entities[0].task_forecasts[0].distribution
        tf_one = single.entities[0].task_forecasts[0].distribution
        assert torch.allclose(tf_mix.event_mass, tf_one.event_mass, atol=1e-12)
        assert torch.allclose(result.node_mean, single.node_mean, atol=1e-6)

    def test_ensemble_needs_two_members(self, model):
        with pytest.raises(ContractError):
            EnsembleForecaster([ForecastEngine(model)])
