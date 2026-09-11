"""Tier B path-model training (Build Spec Section 20, N.2).

Trains the next-mark decoder by teacher forcing on the disclosed chain
labels (``data/episodes.ChainStep``): at each cutoff the decoder sees the
reference member's observed world state and the ground-truth marks so far,
and predicts the next mark as a softmax over [candidate marks] + [STOP] +
[OUTSIDE].

Honesty: candidate recall is measured before any ranker judgment; metrics
are reported per split with the predeclared typed-event equivalence rule
(same task + same directed pair + time bin within +-1). Path probabilities
stay uncalibrated (``calibrated: false``).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from foresight.api.bundle import load_bundle  # noqa: E402
from foresight.data.clips import (  # noqa: E402
    CUTOFF_STEP,
    CUTOFF_STEP_EVAL,
    build_serving_windows,
    precompute_episode,
)
from foresight.data.episodes import build_corpus  # noqa: E402
from foresight.data.splits import split_episodes  # noqa: E402
from foresight.paths.beam import beam_search  # noqa: E402
from foresight.paths.candidates import (  # noqa: E402
    STOP,
    build_candidate_set,
    candidate_recall,
    chain_marks_after_cutoff,
    external_buckets,
)
from foresight.paths.engine import PathEngine  # noqa: E402
from foresight.paths.model import NextMarkDecoder  # noqa: E402

HORIZON_WINDOWS = 60
EPISODE_WINDOWS = 110
EPOCHS = 40
BATCH = 16
LR = 1.5e-3
EARLY_STOP = 6


def _window_to_device(window, device):
    from foresight.models.types import GraphWindowBatch

    return GraphWindowBatch(
        x=window.x.to(device),
        edge_index=window.edge_index.to(device),
        edge_attr=window.edge_attr.to(device),
        batch=window.batch.to(device),
        slot_index=window.slot_index.to(device),
        node_present=window.node_present.to(device),
        node_observation_valid=window.node_observation_valid.to(device),
        global_raw=window.global_raw.to(device),
    )


def build_split_examples(
    episodes, world_model, scaler, device, *, stride, state_cache: Path
) -> list[dict]:
    """One example per (episode, cutoff): state, candidates, targets."""
    state_cache.mkdir(parents=True, exist_ok=True)
    examples: list[dict] = []
    for episode in episodes:
        cache_file = state_cache / f"{episode.episode_id}.pt"
        if cache_file.exists():
            states = torch.load(cache_file, map_location="cpu", weights_only=False)
        else:
            # Prefix windows must exist on this split's stride grid (the
            # stride-8 and stride-10 grids share only cutoffs 20 and 60).
            pre = precompute_episode(episode, stride=stride)
            states = {}
            with torch.no_grad():
                for cutoff in range(20, 81, stride):
                    windows, _ = build_serving_windows(pre, scaler, cutoff)
                    state = world_model.observe_clip(
                        [_window_to_device(w, device) for w in windows]
                    )
                    states[cutoff] = (
                        state.entity_memory[0].cpu(),
                        state.global_context[0].cpu(),
                    )
            torch.save(states, cache_file)
        for cutoff in range(20, 81, stride):
            if cutoff not in states:
                continue
            cands = build_candidate_set(episode, cutoff)
            marks = chain_marks_after_cutoff(
                episode, cutoff, horizon_windows=HORIZON_WINDOWS
            )
            targets: list[int] = []
            valid_stop = cutoff + HORIZON_WINDOWS <= EPISODE_WINDOWS
            for m in marks:
                idx = cands.option_index(
                    m["task_index"], m["source"], m["target"], m["time_bin"]
                )
                if idx < 0:
                    targets.append(cands.outside_index)
                    break  # cannot supervise past an out-of-candidate mark
                targets.append(idx)
            if valid_stop:
                targets.append(cands.stop_index)
            else:
                targets.append(-1)  # censored horizon (past recording end)
            mem, ctx = states[cutoff]
            examples.append(
                {
                    "episode_id": episode.episode_id,
                    "family": episode.family,
                    "cutoff": cutoff,
                    "candidates": cands,
                    "targets": targets,
                    "entity_memory": mem,
                    "global_context": ctx,
                }
            )
    return examples


def collate(batch: list[dict], device):
    """Stack one batch. The corpus shares one canonical candidate universe
    (same hosts), so pair tensors come from the first example; node
    vocabularies are asserted equal."""
    node_names = batch[0]["candidates"].node_names
    for ex in batch:
        assert (
            ex["candidates"].node_names == node_names
            and ex["candidates"].pairs == batch[0]["candidates"].pairs
        ), "path batches require a shared candidate universe"
    cands = batch[0]["candidates"]
    pair_src = torch.tensor(
        [node_names.index(s) for (s, _t) in cands.pairs], dtype=torch.long
    )
    pair_tgt = torch.tensor(
        [node_names.index(t) for (_s, t) in cands.pairs], dtype=torch.long
    )
    pair_mask = torch.ones(len(cands.pairs), dtype=torch.bool)
    ext = torch.tensor(external_buckets(node_names, cands.internal_count))
    steps_max = max(len(ex["targets"]) for ex in batch)
    bsz = len(batch)
    mem = torch.stack([ex["entity_memory"] for ex in batch])          # [B, N, 64]
    ctx = torch.stack([ex["global_context"] for ex in batch])         # [B, 24]
    targets = torch.full((bsz, steps_max), -1, dtype=torch.long)
    for bi, ex in enumerate(batch):
        targets[bi, : len(ex["targets"])] = torch.tensor(ex["targets"])
    return (
        mem.to(device), ctx.to(device), ext.to(device),
        pair_src.to(device), pair_tgt.to(device), pair_mask.to(device),
        targets.to(device),
    )


def history_from_targets(
    batch: list[dict], steps_max: int, device
) -> list[tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]]:
    """Teacher-forced inputs: step k feeds target mark k-1 (BOS at step 0)."""
    bsz = len(batch)
    node_names = batch[0]["candidates"].node_names

    def node_index(name: str) -> int:
        try:
            return node_names.index(name)
        except ValueError:
            return -1

    history = []
    for step in range(steps_max):
        t_idx = torch.zeros(bsz, dtype=torch.long)
        src = torch.full((bsz,), -1, dtype=torch.long)
        tgt = torch.full((bsz,), -1, dtype=torch.long)
        bin_ = torch.full((bsz,), -1, dtype=torch.long)
        for bi, ex in enumerate(batch):
            if step == 0:
                t_idx[bi] = 5  # BOS
                continue
            prev = (
                ex["targets"][step - 1]
                if step - 1 < len(ex["targets"])
                else -1
            )
            if prev < 0:
                continue  # sequence ended; the target is masked (-1) anyway
            cands = ex["candidates"]
            if prev == cands.stop_index:
                t_idx[bi] = 6
            elif prev == cands.outside_index:
                t_idx[bi] = 7
            else:
                opt = cands.options[prev]
                t_idx[bi] = opt.task_index
                src[bi] = node_index(opt.source)
                tgt[bi] = node_index(opt.target)
                bin_[bi] = opt.time_bin
        history.append(
            (t_idx.to(device), src.to(device), tgt.to(device), bin_.to(device))
        )
    return history


def train(
    decoder: NextMarkDecoder,
    examples: list[dict],
    dev_examples: list[dict],
    device,
    *,
    epochs: int = EPOCHS,
) -> dict:
    opt = torch.optim.Adam(decoder.parameters(), lr=LR)
    rng = np.random.default_rng(0)
    best_loss = float("inf")
    best_epoch = 0
    best_state = None
    epochs_log = []
    for epoch in range(1, epochs + 1):
        decoder.train()
        order = rng.permutation(len(examples))
        losses = []
        for i in range(0, len(order), BATCH):
            batch = [examples[j] for j in order[i : i + BATCH]]
            mem, ctx, ext, psrc, ptgt, pmask, targets = collate(batch, device)
            history = history_from_targets(batch, targets.shape[1], device)
            _, step_logs = decoder.forward_sequence(
                mem, ctx, ext, psrc, ptgt, history, pair_mask=pmask
            )
            loss = 0.0
            count = 0
            for step, log_probs in enumerate(step_logs):
                tgt = targets[:, step]
                mask = tgt >= 0
                if bool(mask.any()):
                    loss = loss + nn.functional.nll_loss(
                        log_probs[mask], tgt[mask]
                    )
                    count += 1
            if count == 0:
                continue
            loss = loss / count
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(decoder.parameters(), 5.0)
            opt.step()
            losses.append(float(loss))
        train_loss = float(np.mean(losses)) if losses else float("nan")
        dev_loss = evaluate_loss(decoder, dev_examples, device)
        epochs_log.append(
            {"epoch": epoch, "train_loss": train_loss, "dev_loss": dev_loss}
        )
        marker = ""
        if dev_loss < best_loss - 1e-4:
            best_loss = dev_loss
            best_epoch = epoch
            best_state = {
                k: v.detach().cpu().clone()
                for k, v in decoder.state_dict().items()
            }
            marker = " *"
        print(
            f"  epoch {epoch:2d} train={train_loss:.4f} dev={dev_loss:.4f}{marker}",
            flush=True,
        )
        if epoch - best_epoch >= EARLY_STOP:
            break
    if best_state is not None:
        decoder.load_state_dict(best_state)
    return {"best_dev_loss": best_loss, "best_epoch": best_epoch, "epochs": epochs_log}


@torch.no_grad()
def evaluate_loss(decoder, examples: list[dict], device) -> float:
    decoder.eval()
    losses = []
    for i in range(0, len(examples), BATCH):
        batch = examples[i : i + BATCH]
        mem, ctx, ext, psrc, ptgt, pmask, targets = collate(batch, device)
        history = history_from_targets(batch, targets.shape[1], device)
        _, step_logs = decoder.forward_sequence(
            mem, ctx, ext, psrc, ptgt, history, pair_mask=pmask
        )
        for step, log_probs in enumerate(step_logs):
            tgt = targets[:, step]
            mask = tgt >= 0
            if bool(mask.any()):
                losses.append(
                    float(nn.functional.nll_loss(log_probs[mask], tgt[mask]))
                )
    return float(np.mean(losses)) if losses else float("nan")


def equivalent_mark(predicted: dict, truth: dict) -> bool:
    """Predeclared typed-event equivalence (N.2): same task, same directed
    pair, time bin within +-1."""
    return (
        predicted["task_index"] == truth["task_index"]
        and predicted["source"] == truth["source"]
        and predicted["target"] == truth["target"]
        and abs(predicted["time_bin"] - truth["time_bin"]) <= 1
    )


@torch.no_grad()
def evaluate(
    decoder: NextMarkDecoder,
    world_model,
    episodes_by_id: dict,
    examples: list[dict],
    device,
) -> dict:
    """Teacher-forced next-mark accuracy + beam top-4 first-mark recall +
    candidate recall (N.2 gates)."""
    decoder.eval()
    engine = PathEngine(decoder)
    mark_hits = mark_total = 0
    stop_hits = stop_total = 0
    first_hits = first_total = 0
    recalls = []
    for ex in examples:
        cands = ex["candidates"]
        mem = ex["entity_memory"].unsqueeze(0).to(device)
        ctx = ex["global_context"].unsqueeze(0).to(device)
        # teacher-forced accuracy
        s_mem, s_ctx, s_ext, s_psrc, s_ptgt, s_pmask, _ = collate([ex], device)
        history = history_from_targets([ex], len(ex["targets"]), device)
        _, step_logs = decoder.forward_sequence(
            s_mem, s_ctx, s_ext, s_psrc, s_ptgt, history, pair_mask=s_pmask
        )
        for step, log_probs in enumerate(step_logs):
            tgt = ex["targets"][step]
            if tgt < 0:
                continue
            pred = int(log_probs[0].argmax())
            if tgt == cands.stop_index:
                stop_total += 1
                stop_hits += int(pred == tgt)
            else:
                mark_total += 1
                mark_hits += int(pred == tgt)
        # beam top-4 first-mark recall + candidate recall
        marks = chain_marks_after_cutoff(
            episodes_by_id[ex["episode_id"]], ex["cutoff"],
            horizon_windows=HORIZON_WINDOWS,
        )
        recalls.append(candidate_recall(
            episodes_by_id[ex["episode_id"]], ex["cutoff"], cands
        )["recall"])
        if marks:
            first_total += 1
            forecast = engine.forecast(
                episodes_by_id[ex["episode_id"]],
                mem, ctx, ex["cutoff"], candidates=cands,
            )
            for path in forecast.ranked_paths[:4]:
                if path["marks"] and equivalent_mark(path["marks"][0], marks[0]):
                    first_hits += 1
                    break
    return {
        "clips": len(examples),
        "next_mark_accuracy": (
            round(mark_hits / mark_total, 4) if mark_total else None
        ),
        "stop_accuracy": (
            round(stop_hits / stop_total, 4) if stop_total else None
        ),
        "beam_top4_first_mark_recall": (
            round(first_hits / first_total, 4) if first_total else None
        ),
        "mean_candidate_recall": (
            round(float(np.mean([r for r in recalls if r is not None])), 4)
            if any(r is not None for r in recalls)
            else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts" / "paths")
    parser.add_argument("--profile", type=Path, default=REPO_ROOT / "artifacts" / "profile")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--device", type=str, default=None)
    args = parser.parse_args()

    epochs = args.epochs

    device = torch.device(
        args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    )
    torch.set_num_threads(4)
    print(f"device: {device}", flush=True)
    t0 = time.time()

    print("[1/5] loading reference world model from the profile...", flush=True)
    bundle = load_bundle(args.profile, config_path=REPO_ROOT / "configs" / "core.yaml")
    reference = bundle.engines[0].model.to(device)
    reference.eval()

    print("[2/5] building corpus, splits and world states...", flush=True)
    episodes = build_corpus()
    splits = split_episodes(episodes)
    episodes_by_id = {e.episode_id: e for e in episodes}
    state_cache = args.out / "states"
    train_examples = build_split_examples(
        list(splits.train), reference, bundle.scaler, device,
        stride=CUTOFF_STEP, state_cache=state_cache,
    )
    dev_examples = build_split_examples(
        list(splits.development), reference, bundle.scaler, device,
        stride=CUTOFF_STEP_EVAL, state_cache=state_cache,
    )
    test_examples = build_split_examples(
        list(splits.locked_test), reference, bundle.scaler, device,
        stride=CUTOFF_STEP_EVAL, state_cache=state_cache,
    )
    print(
        f"  examples: train {len(train_examples)} dev {len(dev_examples)} "
        f"test {len(test_examples)}",
        flush=True,
    )

    print("[3/5] training next-mark decoder (teacher forcing)...", flush=True)
    decoder = NextMarkDecoder().to(device)
    run = train(decoder, train_examples, dev_examples, device, epochs=epochs)

    print("[4/5] evaluating dev + locked test...", flush=True)
    dev_metrics = evaluate(decoder, reference, episodes_by_id, dev_examples, device)
    test_metrics = evaluate(decoder, reference, episodes_by_id, test_examples, device)
    print(f"  dev : {dev_metrics}", flush=True)
    print(f"  test: {test_metrics}", flush=True)

    print("[5/5] assembling path bundle...", flush=True)
    from safetensors.torch import save_file

    args.out.mkdir(parents=True, exist_ok=True)
    save_file(
        {k: v.cpu() for k, v in decoder.state_dict().items()},
        str(args.out / "model.safetensors"),
    )
    import hashlib

    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    (args.out / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "foresight.paths.2026-09",
                "synthetic_data_only": True,
                "beam_width": 8,
                "beam_depth": 4,
                "time_bins": 6,
                "bin_seconds": 300,
                "dev_metrics": dev_metrics,
                "test_metrics": test_metrics,
                "weights_profile": (
                    "Tier B next-mark decoder, teacher-forced on disclosed "
                    "synthetic chain labels; path products uncalibrated "
                    "(Section 20)"
                ),
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = json.loads((args.out / "manifest.json").read_text(encoding="utf-8"))
    manifest["hashes"] = {"model.safetensors": sha(args.out / "model.safetensors")}
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (args.out / "training_run.json").write_text(
        json.dumps(run, indent=2), encoding="utf-8"
    )
    print(
        f"done in {(time.time() - t0) / 60:.1f} min -> {args.out}",
        flush=True,
    )


if __name__ == "__main__":
    main()
