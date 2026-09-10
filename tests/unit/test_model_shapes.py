"""MO01 (Appendix R.3): frozen tensor shapes through every model stage."""

from __future__ import annotations

import pytest
import torch

from conftest import build_candidates, build_clip, build_window, observed_state

TOL = 1e-6


class TestMO01Encoder:
    def test_encoder_output_shape(self, model):
        w = build_window(num_slots=5, seed=1, edges=[[(0, 1), (1, 2), (2, 3), (4, 0)]])
        u = model.graph_encoder(w.x, w.edge_index, w.edge_attr, w.batch)
        assert u.shape == (w.num_nodes, 64)
        assert u.dtype == torch.float32

    def test_encoder_batched_shape(self, model):
        w = build_window(num_graphs=3, num_slots=4, seed=2)
        u = model.graph_encoder(w.x, w.edge_index, w.edge_attr, w.batch)
        assert u.shape == (w.num_nodes, 64)


class TestMO01StateShapes:
    def test_observed_state_shapes(self, model):
        clip = build_clip(num_windows=20, seed=7)
        s = observed_state(model, clip)
        assert s.entity_memory.shape == (1, 4, 64)
        assert s.global_h.shape == (2, 1, 128)
        assert s.global_c.shape == (2, 1, 128)
        assert s.global_context.shape == (1, 24)
        assert s.node_present.shape == (1, 4)

    def test_zero_state_shapes(self, model):
        s = model.zero_state(torch.ones(3, 6, dtype=torch.bool))
        assert s.entity_memory.shape == (3, 6, 64)
        assert s.global_h.shape == (2, 3, 128)
        assert s.global_c.shape == (2, 3, 128)
        assert s.global_context.shape == (3, 24)
        assert torch.count_nonzero(s.entity_memory) == 0
        assert torch.count_nonzero(s.global_h) == 0
        assert torch.count_nonzero(s.global_c) == 0
        assert torch.count_nonzero(s.global_context) == 0


class TestMO01DecodeShapes:
    def test_decode_shapes(self, model):
        s = observed_state(model, build_clip(num_windows=5, seed=11))
        d = model.decode_state(s, build_candidates(pairs=[(0, 0, 1), (0, 2, 3)]))
        assert d.node_mean.shape == (1, 4, 44)
        assert d.node_log_scale.shape == (1, 4, 44)
        assert d.global_mean.shape == (1, 24)
        assert d.global_log_scale.shape == (1, 24)
        assert d.hazard_logits.shape == (1, 4, 5)
        assert d.tactic_logits.shape == (1, 4, 5)
        assert d.edge_logits.shape == (2,)

    def test_decode_without_candidates(self, model):
        s = observed_state(model, build_clip(num_windows=3, seed=12))
        d = model.decode_state(s)
        assert d.edge_logits is None
        assert d.hazard_task_mask is None

    def test_decode_task_mask_carried(self, model):
        s = observed_state(model, build_clip(num_windows=3, seed=13))
        mask = torch.tensor([True, True, False, False, True])
        d = model.decode_state(s, task_mask=mask)
        assert torch.equal(d.hazard_task_mask, mask)

    def test_heads_emit_raw_logits(self, model):
        """No sigmoid/softmax inside the heads (Section 13: probabilities are
        derived at readout only, so loss layers stay in logit space)."""
        big = torch.randn(4, 192) * 100.0
        for head in (model.hazard_head, model.tactic_head):
            out = head(big)
            assert out.abs().max() > 1.0
        edge_out = model.edge_head(torch.randn(4, 256) * 100.0)
        assert edge_out.abs().max() > 1.0

    def test_log_scale_clamped(self, model):
        """Decoded log-scales lie within the ADR-001 clamp [-5, 3]."""
        s = observed_state(model, build_clip(num_windows=3, seed=15))
        d = model.decode_state(s)
        assert (d.node_log_scale >= -5.0 - TOL).all()
        assert (d.node_log_scale <= 3.0 + TOL).all()
        assert (d.global_log_scale >= -5.0 - TOL).all()
        assert (d.global_log_scale <= 3.0 + TOL).all()


class TestMO01Rollout:
    def test_rollout_shapes_and_count(self, model):
        s = observed_state(model, build_clip(num_windows=5, seed=21))
        horizon = 10
        outputs = model.roll_out(s, horizon, build_candidates())
        assert len(outputs) == horizon
        for d in outputs:
            assert d.node_mean.shape == (1, 4, 44)
            assert d.hazard_logits.shape == (1, 4, 5)
            assert d.edge_logits.shape == (3,)

    def test_rollout_full_modeled_horizon(self, model):
        s = observed_state(model, build_clip(num_windows=2, seed=22))
        outputs = model.roll_out(s, 60)
        assert len(outputs) == 60

    def test_rollout_rejects_nonpositive_horizon(self, model):
        s = observed_state(model, build_clip(num_windows=2, seed=23))
        with pytest.raises(Exception):
            model.roll_out(s, 0)


class TestMO01HazardTaskCount:
    @pytest.mark.parametrize("j", [3, 5, 7, 12])
    def test_hazard_width_follows_task_count(self, core_config, j):
        from foresight.models.world_model import ForesightWorldModel

        torch.manual_seed(0)
        m = ForesightWorldModel.from_config(core_config, num_event_tasks=j)
        m.eval()
        s = observed_state(m, build_clip(num_windows=2, seed=31))
        d = m.decode_state(s)
        assert d.hazard_logits.shape == (1, 4, j)

    def test_invalid_task_count_rejected(self, core_config):
        from foresight.models.types import ContractError
        from foresight.models.world_model import ForesightWorldModel

        with pytest.raises(ContractError):
            ForesightWorldModel.from_config(core_config, num_event_tasks=0)
