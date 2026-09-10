"""GR01/GR02 (Appendix R.3): batching and padding.

GR01 — graphs processed in one batch produce the same states and forecasts as
graphs processed alone, and no graph's activations depend on another graph's
content in the same batch.
GR02 — forecasts do not change when the slot array is padded with absent slots.
"""

from __future__ import annotations

import pytest
import torch

from conftest import (
    build_candidates,
    build_clip,
    build_window,
    observed_state,
)

from foresight.models.types import GraphWindowBatch

TOL_ATOL = 1e-5
TOL_RTOL = 1e-5


def merge_windows(windows: list[GraphWindowBatch]) -> GraphWindowBatch:
    """Stack single-graph windows into one batched window (graph-major rows).

    Graphs with fewer slots are padded with absent slots (GR02 semantics)."""
    assert all(w.node_present.shape[0] == 1 for w in windows)
    num_graphs = len(windows)
    max_slots = max(w.num_slots for w in windows)
    present = torch.zeros(num_graphs, max_slots, dtype=torch.bool)
    obs_valid = torch.zeros(num_graphs, max_slots, dtype=torch.bool)
    for i, w in enumerate(windows):
        n = w.num_slots
        present[i, :n] = w.node_present[0]
        obs_valid[i, :n] = w.node_observation_valid[0]

    x = torch.cat([w.x for w in windows], dim=0)
    offset = 0
    edge_chunks = []
    for w in windows:
        edge_chunks.append(w.edge_index + offset)
        offset += w.num_nodes
    merged = GraphWindowBatch(
        x=x,
        edge_index=torch.cat(edge_chunks, dim=1),
        edge_attr=torch.cat([w.edge_attr for w in windows], dim=0),
        batch=torch.cat(
            [w.batch + i for i, w in enumerate(windows)], dim=0
        ),
        slot_index=torch.cat([w.slot_index for w in windows], dim=0),
        node_present=present,
        node_observation_valid=obs_valid,
        global_raw=torch.cat([w.global_raw for w in windows], dim=0),
    )
    merged.validate()
    return merged


def clips_for_batch(seeds: list[int], slots: list[int], length: int = 6):
    return [
        build_clip(
            num_windows=length,
            seed=seed,
            num_slots=n,
            edges=[[(0, 1), (1, min(2, n - 1)), (n - 1, 0)]],
        )
        for seed, n in zip(seeds, slots)
    ]


class TestGR01BatchedEqualsIndividual:
    def test_states_and_outputs_match(self, model):
        seeds, slots = [11, 22, 33], [4, 6, 3]
        clips = clips_for_batch(seeds, slots)
        length = len(clips[0])

        # Individual runs.
        indiv_states = [observed_state(model, clip) for clip in clips]
        indiv_decodes = [
            model.decode_state(s, build_candidates(pairs=[(0, 0, 1)]))
            for s in indiv_states
        ]

        # Batched run: window t merges each graph's window t.
        s = model.zero_state(merge_windows([clip[0] for clip in clips]).node_present)
        for t in range(length):
            s = model.observe_window(s, merge_windows([clip[t] for clip in clips]))
        batched = s

        for b in range(len(clips)):
            n = clips[b][0].num_slots
            assert torch.allclose(
                batched.entity_memory[b, :n],
                indiv_states[b].entity_memory[0],
                atol=TOL_ATOL, rtol=TOL_RTOL,
            ), f"entity memory mismatch for graph {b}"
            assert torch.allclose(
                batched.global_h[:, b], indiv_states[b].global_h[:, 0],
                atol=TOL_ATOL, rtol=TOL_RTOL,
            )
            assert torch.allclose(
                batched.global_c[:, b], indiv_states[b].global_c[:, 0],
                atol=TOL_ATOL, rtol=TOL_RTOL,
            )
            assert torch.allclose(
                batched.global_context[b], indiv_states[b].global_context[0],
                atol=TOL_ATOL, rtol=TOL_RTOL,
            )

        pairs = build_candidates(
            pairs=[(0, 0, 1), (1, 2, 4), (2, 0, 2)]
        )
        d = model.decode_state(batched, pairs)
        for b in range(len(clips)):
            n = clips[b][0].num_slots
            assert torch.allclose(
                d.hazard_logits[b, :n], indiv_decodes[b].hazard_logits[0],
                atol=TOL_ATOL, rtol=TOL_RTOL,
            )
            assert torch.allclose(
                d.node_mean[b, :n], indiv_decodes[b].node_mean[0],
                atol=TOL_ATOL, rtol=TOL_RTOL,
            )
        # Edge logits: pair 0 belongs to graph 0 -> compare with its decode.
        assert torch.allclose(
            d.edge_logits[0], indiv_decodes[0].edge_logits[0],
            atol=TOL_ATOL, rtol=TOL_RTOL,
        )

    def test_rollout_batched_equals_individual(self, model):
        clips = clips_for_batch([44, 55], [4, 5], length=4)
        indiv = [observed_state(model, clip) for clip in clips]
        indiv_roll = [model.roll_out(s, 5) for s in indiv]

        s = model.zero_state(merge_windows([c[0] for c in clips]).node_present)
        for t in range(4):
            s = model.observe_window(s, merge_windows([c[t] for c in clips]))
        batched_roll = model.roll_out(s, 5)

        for b in range(2):
            n = clips[b][0].num_slots
            for i in range(5):
                assert torch.allclose(
                    batched_roll[i].hazard_logits[b, :n],
                    indiv_roll[b][i].hazard_logits[0],
                    atol=TOL_ATOL, rtol=TOL_RTOL,
                )


class TestGR01NoCrossGraphLeakage:
    def test_other_graphs_content_is_irrelevant(self, model):
        """Graph 0's forecasts must not change when graph 1's clip content
        changes inside the same batch."""
        clip_a = build_clip(num_windows=5, seed=61, num_slots=4)
        clip_b = build_clip(num_windows=5, seed=62, num_slots=5)
        clip_b2 = build_clip(num_windows=5, seed=99, num_slots=5)

        def graph0_outputs(other_clip):
            s = model.zero_state(merge_windows([clip_a[0], other_clip[0]]).node_present)
            for t in range(5):
                s = model.observe_window(
                    s, merge_windows([clip_a[t], other_clip[t]])
                )
            d = model.decode_state(s, build_candidates(pairs=[(0, 1, 2)]))
            return s, d

        s1, d1 = graph0_outputs(clip_b)
        s2, d2 = graph0_outputs(clip_b2)
        assert torch.allclose(
            s1.entity_memory[0], s2.entity_memory[0], atol=1e-6, rtol=1e-5
        )
        assert torch.allclose(
            s1.global_h[:, 0], s2.global_h[:, 0], atol=1e-6, rtol=1e-5
        )
        assert torch.allclose(
            s1.global_context[0], s2.global_context[0], atol=1e-6, rtol=1e-5
        )
        assert torch.allclose(
            d1.hazard_logits[0], d2.hazard_logits[0], atol=1e-6, rtol=1e-5
        )
        assert torch.allclose(
            d1.node_mean[0], d2.node_mean[0], atol=1e-6, rtol=1e-5
        )

    def test_cross_graph_edges_rejected(self):
        w = build_window(num_graphs=2, num_slots=3, seed=63)
        # Row 0 is graph 0's slot 0; the first row of graph 1 is after graph 0's
        # node count. An edge between them must be rejected (GR01).
        graph1_first_row = int((w.batch == 1).nonzero()[0, 0])
        from foresight.models.types import ContractError

        bad = GraphWindowBatch(
            x=w.x,
            edge_index=torch.tensor([[0], [graph1_first_row]]),
            edge_attr=w.edge_attr[:1].clone(),
            batch=w.batch,
            slot_index=w.slot_index,
            node_present=w.node_present,
            node_observation_valid=w.node_observation_valid,
            global_raw=w.global_raw,
        )
        with pytest.raises(ContractError):
            bad.validate()


class TestGR02PaddingInvariance:
    def _padded_pair(self, seed: int):
        base = build_window(seed=seed, num_slots=4, edges=[[(0, 1), (1, 2)]])
        present7 = torch.zeros(1, 7, dtype=torch.bool)
        present7[0, :4] = True
        padded = build_window(
            seed=seed, num_slots=7, present=present7, edges=[[(0, 1), (1, 2)]]
        )
        return base, padded

    def test_padding_preserves_window_content(self):
        """Sanity: the padded window carries identical content on real slots."""
        base, padded = self._padded_pair(seed=71)
        assert torch.equal(base.x, padded.x)
        assert torch.equal(base.edge_index, padded.edge_index)
        assert torch.equal(base.edge_attr, padded.edge_attr)
        assert torch.equal(base.global_raw, padded.global_raw)
        assert torch.equal(base.node_present, padded.node_present[:, :4])

    def test_padded_state_matches(self, model):
        base, padded = self._padded_pair(seed=72)
        s4 = model.observe_window(model.zero_state(base.node_present), base)
        s7 = model.observe_window(model.zero_state(padded.node_present), padded)
        assert torch.allclose(
            s7.entity_memory[0, :4], s4.entity_memory[0], atol=1e-7, rtol=1e-6
        )
        assert torch.count_nonzero(s7.entity_memory[0, 4:]) == 0
        assert torch.allclose(s7.global_h, s4.global_h, atol=1e-7, rtol=1e-6)
        assert torch.allclose(s7.global_c, s4.global_c, atol=1e-7, rtol=1e-6)
        assert torch.allclose(s7.global_context, s4.global_context, atol=1e-7)

    def test_padded_decode_matches(self, model):
        base, padded = self._padded_pair(seed=73)
        s4 = model.observe_window(model.zero_state(base.node_present), base)
        s7 = model.observe_window(model.zero_state(padded.node_present), padded)
        pairs = build_candidates(pairs=[(0, 0, 1), (0, 2, 3)])
        d4 = model.decode_state(s4, pairs)
        d7 = model.decode_state(s7, pairs)
        assert torch.allclose(
            d7.node_mean[0, :4], d4.node_mean[0], atol=TOL_ATOL, rtol=TOL_RTOL
        )
        assert torch.allclose(
            d7.hazard_logits[0, :4], d4.hazard_logits[0],
            atol=TOL_ATOL, rtol=TOL_RTOL,
        )
        assert torch.allclose(
            d7.global_mean, d4.global_mean, atol=TOL_ATOL, rtol=TOL_RTOL
        )
        assert torch.allclose(
            d7.edge_logits, d4.edge_logits, atol=TOL_ATOL, rtol=TOL_RTOL
        )

    def test_padding_invariance_over_full_clip(self, model):
        present7 = torch.zeros(1, 7, dtype=torch.bool)
        present7[0, :4] = True
        clip4 = build_clip(
            num_windows=10, seed=74, num_slots=4, edges=[[(0, 1), (1, 2)]]
        )
        clip7 = build_clip(
            num_windows=10, seed=74, num_slots=7, present=present7,
            edges=[[(0, 1), (1, 2)]],
        )
        s4 = observed_state(model, clip4)
        s7 = observed_state(model, clip7)
        assert torch.allclose(
            s7.entity_memory[0, :4], s4.entity_memory[0],
            atol=TOL_ATOL, rtol=TOL_RTOL,
        )
        assert torch.allclose(s7.global_h, s4.global_h, atol=TOL_ATOL, rtol=TOL_RTOL)
        r4 = model.roll_out(s4, 3)
        r7 = model.roll_out(s7, 3)
        for i in range(3):
            assert torch.allclose(
                r7[i].hazard_logits[0, :4], r4[i].hazard_logits[0],
                atol=TOL_ATOL, rtol=TOL_RTOL,
            )
