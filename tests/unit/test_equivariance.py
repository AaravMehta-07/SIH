"""ID02 (Appendix R.3): identity-free permutation equivariance, plus the
Section 35 golden example 3 two-entity swap.

Entity identities enter only through per-entity memory slots: relabeling the
slots of a scope relabels the forecasts and leaves global quantities unchanged
(Build Spec Section 13; Work Distribution "identity-free features").
"""

from __future__ import annotations

import torch

from conftest import build_candidates, build_window

from foresight.models.types import GraphWindowBatch

ATOL = 1e-5
RTOL = 1e-5


def permute_window(window: GraphWindowBatch, perm: list[int]) -> GraphWindowBatch:
    """Relabel slots so new slot j holds old slot perm[j] (single-graph windows)."""
    assert window.node_present.shape[0] == 1
    n = window.node_present.shape[1]
    assert sorted(perm) == list(range(n))
    old_row_of = {int(s): i for i, s in enumerate(window.slot_index.tolist())}
    inv = [0] * n
    for new_s, old_s in enumerate(perm):
        inv[old_s] = new_s

    new_rows: list[int] = []
    new_row_of_old: dict[int, int] = {}
    new_slots: list[int] = []
    for new_s in range(n):
        old_s = perm[new_s]
        if bool(window.node_present[0, old_s]):
            new_row_of_old[old_s] = len(new_rows)
            new_rows.append(old_row_of[old_s])
            new_slots.append(new_s)

    edge_index = torch.zeros(2, window.edge_index.shape[1], dtype=torch.int64)
    for i in range(window.edge_index.shape[1]):
        u = int(window.slot_index[int(window.edge_index[0, i])])
        v = int(window.slot_index[int(window.edge_index[1, i])])
        edge_index[0, i] = new_row_of_old[u]
        edge_index[1, i] = new_row_of_old[v]

    out = GraphWindowBatch(
        x=window.x[new_rows],
        edge_index=edge_index,
        edge_attr=window.edge_attr,
        batch=torch.zeros(len(new_rows), dtype=torch.int64),
        slot_index=torch.tensor(new_slots, dtype=torch.int64),
        node_present=window.node_present[:, perm],
        node_observation_valid=window.node_observation_valid[:, perm],
        global_raw=window.global_raw,
    )
    out.validate()
    return out


def assert_state_equivariant(model, w, wp, perm):
    """new slot j holds old slot perm[j], so the permuted run's slot j equals the
    original run's slot perm[j] (and global quantities are invariant)."""
    s0 = model.observe_window(model.zero_state(w.node_present), w)
    s1 = model.observe_window(model.zero_state(wp.node_present), wp)
    perm_t = torch.tensor(perm)
    assert torch.allclose(
        s1.entity_memory, s0.entity_memory[:, perm_t], atol=ATOL, rtol=RTOL
    ), "entity memories must follow relabeled slots"
    assert torch.allclose(s1.global_h, s0.global_h, atol=ATOL, rtol=RTOL)
    assert torch.allclose(s1.global_c, s0.global_c, atol=ATOL, rtol=RTOL)
    assert torch.allclose(s1.global_context, s0.global_context, atol=ATOL, rtol=RTOL)
    return s0, s1


class TestID02PermutationEquivariance:
    def test_observe_full_permutation(self, model):
        perm = [2, 0, 3, 1]
        w = build_window(num_slots=4, seed=81, edges=[[(0, 1), (1, 2), (2, 0), (3, 1)]])
        wp = permute_window(w, perm)
        assert_state_equivariant(model, w, wp, perm)

    def test_observe_with_unobserved_entity(self, model):
        """A present-but-unobserved entity keeps its memory; that behavior must
        travel with the entity under relabeling."""
        perm = [1, 2, 0, 3]
        obs = torch.tensor([[True, False, True, True]])
        w = build_window(
            num_slots=4, seed=82, observation_valid=obs,
            edges=[[(0, 1), (1, 2), (2, 0), (3, 0)]],
        )
        wp = permute_window(w, perm)
        assert_state_equivariant(model, w, wp, perm)

    def test_observe_with_absent_slot(self, model):
        perm = [1, 2, 0, 3]
        present = torch.tensor([[True, True, True, False]])
        w = build_window(
            num_slots=4, seed=83, present=present, edges=[[(0, 1), (1, 2), (2, 0)]]
        )
        wp = permute_window(w, perm)
        assert_state_equivariant(model, w, wp, perm)

    def test_decode_permutes(self, model):
        perm = [3, 1, 0, 2]
        w = build_window(num_slots=4, seed=84, edges=[[(0, 1), (1, 2), (2, 3), (3, 0)]])
        wp = permute_window(w, perm)
        s0, s1 = assert_state_equivariant(model, w, wp, perm)

        d0 = model.decode_state(s0)
        d1 = model.decode_state(s1)
        perm_t = torch.tensor(perm)
        for field in ("node_mean", "node_log_scale", "hazard_logits", "tactic_logits"):
            assert torch.allclose(
                getattr(d1, field), getattr(d0, field)[:, perm_t],
                atol=ATOL, rtol=RTOL,
            ), f"{field} must follow relabeled slots"
        for field in ("global_mean", "global_log_scale"):
            assert torch.allclose(
                getattr(d1, field), getattr(d0, field), atol=ATOL, rtol=RTOL
            ), f"{field} must be permutation invariant"

    def test_edge_logits_follow_endpoints(self, model):
        perm = [2, 3, 0, 1]
        w = build_window(num_slots=4, seed=85, edges=[[(0, 1), (1, 2), (2, 3), (3, 0)]])
        wp = permute_window(w, perm)
        s0, s1 = assert_state_equivariant(model, w, wp, perm)
        inv = [0] * 4
        for new_s, old_s in enumerate(perm):
            inv[old_s] = new_s

        pairs_old = [(0, 0, 1), (0, 2, 3), (0, 1, 3)]
        pairs_new = [(0, inv[u], inv[v]) for (_, u, v) in pairs_old]
        d0 = model.decode_state(s0, build_candidates(pairs=pairs_old))
        d1 = model.decode_state(s1, build_candidates(pairs=pairs_new))
        assert torch.allclose(d1.edge_logits, d0.edge_logits, atol=ATOL, rtol=RTOL)

    def test_rollout_permutes(self, model):
        perm = [1, 3, 0, 2]
        w = build_window(num_slots=4, seed=86, edges=[[(0, 1), (1, 2), (2, 3), (3, 0)]])
        wp = permute_window(w, perm)
        s0, s1 = assert_state_equivariant(model, w, wp, perm)
        r0 = model.roll_out(s0, 4)
        r1 = model.roll_out(s1, 4)
        perm_t = torch.tensor(perm)
        for i in range(4):
            assert torch.allclose(
                r1[i].hazard_logits, r0[i].hazard_logits[:, perm_t],
                atol=ATOL, rtol=RTOL,
            )
            assert torch.allclose(
                r1[i].global_mean, r0[i].global_mean, atol=ATOL, rtol=RTOL
            )

    def test_permutation_over_clip(self, model):
        perm = [2, 1, 3, 0]
        edges = [[(0, 1), (1, 2), (2, 3), (3, 0)]]
        clip = [build_window(num_slots=4, seed=90 + i, edges=edges) for i in range(5)]
        clip_p = [permute_window(w, perm) for w in clip]

        s0 = model.zero_state(clip[0].node_present)
        s1 = model.zero_state(clip_p[0].node_present)
        for w, wp in zip(clip, clip_p):
            s0 = model.observe_window(s0, w)
            s1 = model.observe_window(s1, wp)
        perm_t = torch.tensor(perm)
        assert torch.allclose(
            s1.entity_memory, s0.entity_memory[:, perm_t], atol=ATOL, rtol=RTOL
        )
        assert torch.allclose(s1.global_h, s0.global_h, atol=ATOL, rtol=RTOL)


class TestGoldenExample3TwoEntitySwap:
    """Section 35 golden example 3: swapping two entities' identities swaps their
    forecasts and leaves global forecasts unchanged."""

    def test_swap(self, model):
        perm = [1, 0, 2, 3]  # swap entities 0 and 1
        edges = [[(0, 1), (1, 2), (2, 3), (3, 0), (0, 2)]]
        clip = [build_window(num_slots=4, seed=95 + i, edges=edges) for i in range(4)]
        clip_swapped = [permute_window(w, perm) for w in clip]

        s = model.zero_state(clip[0].node_present)
        t = model.zero_state(clip_swapped[0].node_present)
        for w, ws in zip(clip, clip_swapped):
            s = model.observe_window(s, w)
            t = model.observe_window(t, ws)

        # Entity memories swap: swapped slot 0 holds original slot 1's memory.
        assert torch.allclose(
            t.entity_memory[:, [1, 0, 2, 3]], s.entity_memory, atol=ATOL, rtol=RTOL
        )
        # Global state is untouched by the identity swap.
        assert torch.allclose(t.global_h, s.global_h, atol=ATOL, rtol=RTOL)
        assert torch.allclose(t.global_c, s.global_c, atol=ATOL, rtol=RTOL)

        d = model.decode_state(s)
        d_swapped = model.decode_state(t)
        swap = torch.tensor([1, 0, 2, 3])
        assert torch.allclose(
            d_swapped.hazard_logits[:, swap], d.hazard_logits, atol=ATOL, rtol=RTOL
        )
        assert torch.allclose(
            d_swapped.tactic_logits[:, swap], d.tactic_logits, atol=ATOL, rtol=RTOL
        )
        assert torch.allclose(
            d_swapped.global_mean, d.global_mean, atol=ATOL, rtol=RTOL
        )

        # Rollouts swap too: bin-1 hazard for original entity 0 equals bin-1
        # hazard for swapped entity 1.
        r = model.roll_out(s, 3)
        r_swapped = model.roll_out(t, 3)
        assert torch.allclose(
            r_swapped[0].hazard_logits[:, swap], r[0].hazard_logits,
            atol=ATOL, rtol=RTOL,
        )
