"""MO03/MO04 (Appendix R.3): rollouts consult no future telemetry and never
mutate or contaminate the observed state (Build Spec Sections 14, 26, H.4)."""

from __future__ import annotations

import inspect

import pytest
import torch

from conftest import build_candidates, build_clip, build_window, observed_state


class TestMO03NoFutureAccess:
    def test_rollout_signature_has_no_future_inputs(self, model):
        params = inspect.signature(model.roll_out).parameters
        assert set(params) == {
            "observed_state", "horizon_bins", "candidate_pairs", "task_mask"
        }, "roll_out must not accept future windows, labels or targets"

    def test_transition_prior_signature_has_no_future_inputs(self, model):
        params = inspect.signature(model.transition_prior).parameters
        assert set(params) == {"state"}

    def test_rollout_never_observes(self, model, monkeypatch):
        """A rollout must not absorb any window — observe_window is the only
        observation path and must stay untouched during imagination."""
        s = observed_state(model, build_clip(num_windows=4, seed=51))

        def _explode(*args, **kwargs):
            raise AssertionError("roll_out consulted observe_window (future access)")

        monkeypatch.setattr(model, "observe_window", _explode)
        outputs = model.roll_out(s, 5, build_candidates())
        assert len(outputs) == 5

    def test_rollout_depends_only_on_state(self, model):
        """Two states from different histories produce different rollouts; the
        same state always produces the same rollout."""
        s1 = observed_state(model, build_clip(num_windows=6, seed=52))
        s2 = observed_state(model, build_clip(num_windows=6, seed=53))
        r1 = model.roll_out(s1, 3)
        r2 = model.roll_out(s2, 3)
        assert not torch.allclose(r1[0].hazard_logits, r2[0].hazard_logits)

        r1b = model.roll_out(s1, 3)
        assert torch.equal(r1[0].hazard_logits, r1b[0].hazard_logits)
        assert torch.equal(r1[2].node_mean, r1b[2].node_mean)

    def test_longer_horizon_extends_prefix(self, model):
        """roll_out(s, H+1)[:H] == roll_out(s, H): the rollout is a deterministic
        state trajectory, not re-sampled per horizon."""
        s = observed_state(model, build_clip(num_windows=3, seed=54))
        short = model.roll_out(s, 4)
        long = model.roll_out(s, 7)
        for i in range(4):
            assert torch.equal(short[i].hazard_logits, long[i].hazard_logits)
            assert torch.equal(short[i].node_mean, long[i].node_mean)


class TestMO04ImaginedObservedIsolation:
    def test_rollout_does_not_mutate_observed_state(self, model):
        s = observed_state(model, build_clip(num_windows=5, seed=55))
        snap = {
            "entity_memory": s.entity_memory.clone(),
            "global_h": s.global_h.clone(),
            "global_c": s.global_c.clone(),
            "global_context": s.global_context.clone(),
        }
        _ = model.roll_out(s, 10, build_candidates())
        assert torch.equal(s.entity_memory, snap["entity_memory"])
        assert torch.equal(s.global_h, snap["global_h"])
        assert torch.equal(s.global_c, snap["global_c"])
        assert torch.equal(s.global_context, snap["global_context"])

    def test_observation_after_rollout_unaffected(self, model):
        """Imagined trajectories never leak into later observation: observing the
        same continuation yields the same state whether or not a rollout happened
        in between (imagined memory is not committed as observed live memory)."""
        prefix = build_clip(num_windows=4, seed=56)
        continuation = build_clip(num_windows=3, seed=57, num_slots=4)

        s_clean = observed_state(model, prefix)
        s_rolled = observed_state(model, prefix)
        _ = model.roll_out(s_rolled, 8)

        for w in continuation:
            s_clean = model.observe_window(s_clean, w)
            s_rolled = model.observe_window(s_rolled, w)
        assert torch.equal(s_clean.entity_memory, s_rolled.entity_memory)
        assert torch.equal(s_clean.global_h, s_rolled.global_h)
        assert torch.equal(s_clean.global_c, s_rolled.global_c)

    def test_bin_convention(self, model):
        """outputs[i] is bin i+1: outputs[0] decodes exactly the state produced by
        one transition from the observed state (Section 14: after transition j the
        state represents bin j)."""
        s = observed_state(model, build_clip(num_windows=4, seed=58))
        z1 = model.transition_prior(s)
        d_direct = model.decode_state(z1, build_candidates())
        outputs = model.roll_out(s, 3, build_candidates())
        assert torch.equal(outputs[0].hazard_logits, d_direct.hazard_logits)
        assert torch.equal(outputs[0].node_mean, d_direct.node_mean)
        assert torch.equal(outputs[0].edge_logits, d_direct.edge_logits)

        z2 = model.transition_prior(z1)
        d_direct2 = model.decode_state(z2, build_candidates())
        assert torch.equal(outputs[1].hazard_logits, d_direct2.hazard_logits)

    def test_rollout_fails_cleanly_on_nonfinite_state(self, model):
        from foresight.models.types import NonFiniteTensorError

        s = observed_state(model, build_clip(num_windows=3, seed=59))
        s = s.clone()
        with torch.no_grad():
            s.global_h[0, 0, 0] = float("nan")
        with pytest.raises(NonFiniteTensorError):
            model.roll_out(s, 3)
