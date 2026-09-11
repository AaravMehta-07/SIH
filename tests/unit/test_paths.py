"""Tier B path engine tests (Build Spec Section 20, N.2)."""

from __future__ import annotations

import pytest
import torch

from foresight.data.episodes import build_episode
from foresight.paths.beam import beam_search
from foresight.paths.candidates import (
    PATH_TIME_BINS,
    STOP,
    build_candidate_set,
    candidate_recall,
    chain_marks_after_cutoff,
    external_buckets,
)
from foresight.paths.engine import PathEngine
from foresight.paths.model import NextMarkDecoder


@pytest.fixture(scope="module")
def web_episode():
    return build_episode("web-to-lateral", 0, seed=7000)


@pytest.fixture(scope="module")
def benign_episode():
    return build_episode("benign-baseline", 3, seed=7000)


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

def test_canonical_universe_covers_chain_pairs(web_episode) -> None:
    """Authorized inventory + observed externals must contain every chain
    pair (candidate recall before any ranker judgment, N.2)."""
    for cutoff in (20, 40, 60):
        cands = build_candidate_set(web_episode, cutoff)
        recall = candidate_recall(web_episode, cutoff, cands)
        if recall["marks"]:
            assert recall["recall"] == 1.0
        for step in web_episode.chain:
            if step.time_ns > cutoff * 30_000_000_000:
                assert (step.source, step.target) in cands.pair_kinds


def test_pair_kinds_disclose_activity(web_episode) -> None:
    cands = build_candidate_set(web_episode, 60)
    kinds = {k for k in cands.pair_kinds.values()}
    assert "inventory" in kinds
    # the C2 beacon pair is active at a mid-episode cutoff
    assert cands.pair_kinds.get(("web-01.dmz.local", "ext-c2-01.net")) in (
        "active", "external_active", "inactive_seen"
    )


def test_option_index_roundtrip(web_episode) -> None:
    cands = build_candidate_set(web_episode, 40)
    idx = cands.option_index(2, "web-01.dmz.local", "srv-app-02.corp.local", 3)
    assert idx >= 0
    opt = cands.options[idx]
    assert (opt.task_index, opt.source, opt.target, opt.time_bin) == (
        2, "web-01.dmz.local", "srv-app-02.corp.local", 3
    )
    assert cands.stop_index == len(cands.options) - 2
    assert cands.outside_index == len(cands.options) - 1
    assert cands.option_index(0, "not-a-host", "alsonot", 0) == -1


def test_chain_marks_after_cutoff(web_episode) -> None:
    marks = chain_marks_after_cutoff(web_episode, 20, horizon_windows=60)
    assert marks, "early cutoff must see the campaign inside the horizon"
    assert all(0 <= m["time_bin"] < PATH_TIME_BINS for m in marks)
    times = [m["time_ns"] for m in marks]
    assert times == sorted(times)
    later = chain_marks_after_cutoff(web_episode, 80, horizon_windows=60)
    assert later == [] or all(
        m["time_ns"] > 80 * 30_000_000_000 for m in later
    )


# ---------------------------------------------------------------------------
# Decoder + beam
# ---------------------------------------------------------------------------

def _decoder_inputs(web_episode, cutoff: int):
    cands = build_candidate_set(web_episode, cutoff)
    ext = torch.tensor(external_buckets(cands.node_names, cands.internal_count))
    pair_src = torch.tensor(
        [cands.node_names.index(s) for (s, _t) in cands.pairs]
    )
    pair_tgt = torch.tensor(
        [cands.node_names.index(t) for (_s, t) in cands.pairs]
    )
    n_internal = cands.internal_count
    mem = torch.randn(1, n_internal, 64)
    ctx = torch.randn(1, 24)
    return cands, ext, pair_src, pair_tgt, mem, ctx


def test_score_options_is_normalized(web_episode) -> None:
    torch.manual_seed(0)
    decoder = NextMarkDecoder()
    cands, ext, pair_src, pair_tgt, mem, ctx = _decoder_inputs(web_episode, 40)
    node_vecs = decoder.node_vectors(mem, ext)
    h = decoder.initial_hidden(mem, ctx)
    t_idx, src, tgt, b_idx = NextMarkDecoder.bos_batch(1, mem.device)
    emb = decoder.mark_embedding(node_vecs, t_idx, src, tgt, b_idx)
    log_probs = decoder.score_options(h, node_vecs, pair_src, pair_tgt, emb)
    expected = len(cands.pairs) * 5 * PATH_TIME_BINS + 2
    assert log_probs.shape == (1, expected)
    probs = log_probs.detach().exp()
    assert abs(float(probs.sum()) - 1.0) < 1e-5
    assert bool((log_probs > float("-inf")).all())


def test_teacher_forced_loss_runs(web_episode) -> None:
    torch.manual_seed(0)
    decoder = NextMarkDecoder()
    cands, ext, pair_src, pair_tgt, mem, ctx = _decoder_inputs(web_episode, 40)
    marks = chain_marks_after_cutoff(web_episode, 40, horizon_windows=60)
    targets = [
        cands.option_index(m["task_index"], m["source"], m["target"], m["time_bin"])
        for m in marks
    ] + [cands.stop_index]
    history = [NextMarkDecoder.bos_batch(1, mem.device)]
    for m in marks[:-1]:
        history.append(
            (
                torch.tensor([m["task_index"]]),
                torch.tensor([cands.node_names.index(m["source"])]),
                torch.tensor([cands.node_names.index(m["target"])]),
                torch.tensor([m["time_bin"]]),
            )
        )
    # history length must cover targets[:-1]; pad with zeros when needed
    while len(history) < len(targets):
        history.append(
            (
                torch.tensor([5]), torch.tensor([-1]),
                torch.tensor([-1]), torch.tensor([-1]),
            )
        )
    _, step_logs = decoder.forward_sequence(mem, ctx, ext, pair_src, pair_tgt, history)
    assert len(step_logs) == len(history)
    loss = torch.nn.functional.nll_loss(
        torch.cat(step_logs), torch.tensor(targets)
    )
    assert loss.item() > 0
    loss.backward()
    assert decoder.pair_scorer[0].weight.grad is not None


def test_beam_mass_accounting(web_episode) -> None:
    """Path + no-event + outside + truncated mass must account for all
    probability (Section 20 explicit truncated mass)."""
    torch.manual_seed(0)
    decoder = NextMarkDecoder()
    cands, ext, pair_src, pair_tgt, mem, ctx = _decoder_inputs(web_episode, 40)
    result = beam_search(decoder, mem, ctx, ext, pair_src, pair_tgt, cands)
    payload = result.to_json()
    total = payload["mass_accounting_total"]
    assert 0.0 <= total <= 1.0 + 1e-4
    assert 0.0 <= payload["no_event_mass"] <= 1.0
    assert payload["truncated_search_mass"] >= 0.0
    # beams: at most width paths survive pruning per step
    assert len(result.paths) <= 8 * 4
    for path in payload["ranked_paths"]:
        assert 0.0 <= path["probability"] <= 1.0
        assert path["terminal"] in ("stop", "outside", "depth")


def test_engine_forecast_payload(web_episode) -> None:
    torch.manual_seed(0)
    decoder = NextMarkDecoder()
    engine = PathEngine(decoder)
    cands, ext, pair_src, pair_tgt, mem, ctx = _decoder_inputs(web_episode, 40)
    forecast = engine.forecast(
        web_episode, mem, ctx, 40, candidates=cands
    )
    payload = forecast.to_json()
    assert payload["status"] == "supported"
    assert payload["calibrated"] is False
    assert payload["beam"] == {"width": 8, "depth": 4}
    assert "ranked_paths" in payload
    assert "truncated_search_mass" in payload


def test_benign_episode_still_searches(benign_episode) -> None:
    """A benign scope runs the same machinery; STOP mass is reported."""
    torch.manual_seed(0)
    decoder = NextMarkDecoder()
    engine = PathEngine(decoder)
    cands = build_candidate_set(benign_episode, 40)
    ext = torch.tensor(external_buckets(cands.node_names, cands.internal_count))
    pair_src = torch.tensor(
        [cands.node_names.index(s) for (s, _t) in cands.pairs]
    )
    pair_tgt = torch.tensor(
        [cands.node_names.index(t) for (_s, t) in cands.pairs]
    )
    mem = torch.randn(1, cands.internal_count, 64)
    ctx = torch.randn(1, 24)
    forecast = engine.forecast(
        benign_episode, mem, ctx, 40, candidates=cands
    )
    payload = forecast.to_json()
    assert payload["no_event_mass"] >= 0.0
    assert payload["candidate_pairs"]["pair_count"] > 0
