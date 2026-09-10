"""Section-35 training run: the real FORESIGHT profile (Build Spec I.1-I.6).

Pipeline (all offline, laptop GPU):

1. Build the synthetic episode corpus (72 episodes, six families) and the
   M.1 chronological episode splits (60/15/10/15).
2. Fit the F.8 feature scaler on the TRAIN split's prefix windows only.
3. Train five independent members (seeds 0-4, I.5: separate encoders,
   transitions and heads) with the Section-15 objective, rollout curriculum
   [1,3,10,30,60] and effective batch 16 clips.
4. Early-stop each member on development average precision at the primary
   horizon (budget-free ranking proxy; the budgeted selection policy is
   fitted later on the calibration split, I.3).
5. Fit I.4 affine hazard calibrators per (member, task) on the calibration
   split.
6. Fit the selection policy (per-task alert thresholds at the 1-false-alert-
   per-100-asset-hours budget) on the calibration split.
7. Run the I.5 ensemble over the locked test split and store predictions
   for the evaluator.
8. Assemble and hash the I.6 artifact bundle.

Data is disclosed synthetic; the run manifest says so explicitly and no
measured-performance claim beyond these gates is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import OrderedDict
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from foresight.calibration.hazard import (  # noqa: E402
    CalibratorSet,
    fit_hazard_calibrator,
)
from foresight.data.clips import (  # noqa: E402
    ClipDataset,
    ClipExample,
)
from foresight.data.episodes import build_corpus  # noqa: E402
from foresight.data.splits import split_episodes  # noqa: E402
from foresight.features.registry import (  # noqa: E402
    EDGE_FEATURE_NAMES,
    GLOBAL_FEATURE_NAMES,
    NODE_FEATURE_NAMES,
    TRANSFORMS,
)
from foresight.features.transforms import FeatureScaler  # noqa: E402
from foresight.graphs.collate import stack_candidates, stack_windows  # noqa: E402
from foresight.labels.ontology import TASK_DEFINITIONS  # noqa: E402
from foresight.models.config import load_core_config  # noqa: E402
from foresight.models.survival import (  # noqa: E402
    distribution_from_hazards,
    hazards_from_logits,
)
from foresight.models.types import CandidatePairs, GraphWindowBatch  # noqa: E402
from foresight.models.world_model import ForesightWorldModel  # noqa: E402
from foresight.runtime.forecast import (  # noqa: E402
    EnsembleForecaster,
    ForecastEngine,
    ForecastRequest,
)
from foresight.training.losses import LossWeights  # noqa: E402
from foresight.training.targets import ClipTargets  # noqa: E402
from foresight.training.trainer import CurriculumSchedule, Trainer, set_seed  # noqa: E402

PRIMARY_HORIZON = 10
SEEDS = (0, 1, 2, 3, 4)
CURRICULUM_TRANSITIONS = (9, 17, 25, 33)  # epochs at which horizon advances
EARLY_STOP_PATIENCE = 8
FALSE_ALERT_BUDGET_PER_100_ASSET_HOURS = 1.0

#: Section-15 sanctioned oversampling: clips with imminent primary-horizon
#: events are sampled 4x more often; the sampling policy is recorded in the
#: run manifest and the base-rate shift is corrected by the I.4 calibrators,
#: which are fitted on the natural-prevalence calibration split.
POSITIVE_CLIP_OVERSAMPLING = 4.0

#: Section-15 positive-bin weight for the survival NLL (A12): rare events
#: (~0.1% of risk bins) otherwise contribute negligible gradient to the
#: hazard head. The induced odds shift is corrected by the I.4 affine
#: calibrators fitted on natural-prevalence calibration data.
SURVIVAL_POSITIVE_WEIGHT = 50.0

#: Learning rate: the Section-35 default is 0.001; this run uses 0.002 as a
#: documented development adjustment (I.1: defaults are adjustable
#: development choices, not optimality claims) — rare-event hazard learning
#: converged too slowly at 0.001 on the development split.
LEARNING_RATE = 0.002

_TARGET_FIELDS = (
    "event_y", "risk_mask", "stage_labels", "stage_mask",
    "node_values", "node_valid", "global_values", "global_valid",
    "edge_labels", "edge_mask", "task_mask",
)


def to_device(window: GraphWindowBatch, device) -> GraphWindowBatch:
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


def targets_to_device(targets: ClipTargets, device) -> ClipTargets:
    return replace(
        targets,
        candidate_pairs=CandidatePairs(
            batch_index=targets.candidate_pairs.batch_index.to(device),
            source=targets.candidate_pairs.source.to(device),
            target=targets.candidate_pairs.target.to(device),
        ),
        **{f: getattr(targets, f).to(device) for f in _TARGET_FIELDS},
    )


def candidates_to_device(c: CandidatePairs, device) -> CandidatePairs:
    return CandidatePairs(
        batch_index=c.batch_index.to(device),
        source=c.source.to(device),
        target=c.target.to(device),
    )


def average_precision(scores: list[float], labels: list[int]) -> float:
    """AP (area under precision-recall) without sklearn."""
    if not labels or sum(labels) == 0:
        return 0.0
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    hits = 0
    ap = 0.0
    prev_recall = 0.0
    for rank, i in enumerate(order, start=1):
        if labels[i]:
            hits += 1
            recall = hits / sum(labels)
            precision = hits / rank
            ap += precision * (recall - prev_recall)
            prev_recall = recall
    return ap


@torch.no_grad()
def dev_average_precision(
    model: ForesightWorldModel, device, dev_examples: list[ClipExample]
) -> dict:
    """Per-task AP at the primary horizon on raw logits (monotone under the
    affine calibrator, so ranking is preserved per task)."""
    model.eval()
    scores: dict[int, list[float]] = {t: [] for t in range(5)}
    labels: dict[int, list[int]] = {t: [] for t in range(5)}
    for ex in dev_examples:
        windows = [to_device(w, device) for w in ex.windows]
        observed = model.observe_clip(windows)
        outputs = model.roll_out(
            observed, PRIMARY_HORIZON,
            candidate_pairs=targets_to_device(ex.targets, device).candidate_pairs,
            task_mask=ex.targets.task_mask,
        )
        logits = (
            torch.stack([o.hazard_logits[0] for o in outputs], dim=0)
        )  # [H, N, J]
        cum = 1.0 - torch.cumprod(
            1.0 - torch.sigmoid(logits), dim=0
        )  # cumulative risk per bin [H, N, J]
        f_primary = cum[PRIMARY_HORIZON - 1]  # [N, J]
        for t in range(5):
            if not bool(ex.targets.task_mask[t]):
                continue
            # At-risk at the cutoff (no event of this task yet); positives
            # are first events inside the primary horizon (Section 11).
            at_risk = ex.targets.risk_mask[:, 0, t]
            if int(at_risk.sum()) == 0:
                continue
            event = (
                ex.targets.event_y[:, :PRIMARY_HORIZON, t].sum(dim=1) > 0
            )
            for slot in at_risk.nonzero(as_tuple=True)[0].tolist():
                scores[t].append(float(f_primary[slot, t]))
                labels[t].append(int(event[slot]))
    return {
        t: average_precision(scores[t], labels[t])
        for t in range(5)
        if scores[t]
    }


def fit_selection_policy(
    cal_records: list[dict],
) -> dict:
    """Per-task alert thresholds at the false-alert budget (calibration split).

    ``cal_records`` entries: {task, score (F at primary horizon), event (bool),
    complete_followup (bool), asset_hours_weight}. Alerts fire above the
    threshold; false alerts count only with adequate follow-up (M.3).
    """
    policy: dict[str, dict] = {}
    by_task: dict[int, list[dict]] = {}
    for r in cal_records:
        by_task.setdefault(r["task"], []).append(r)
    for task, records in by_task.items():
        asset_hours = sum(r["asset_hours_weight"] for r in records)
        events = [r for r in records if r["event"]]
        non_events = [r for r in records if not r["event"] and r["complete_followup"]]
        thresholds = sorted({r["score"] for r in records}, reverse=True)
        best = None
        for thr in thresholds:
            false_alerts = sum(1 for r in non_events if r["score"] > thr)
            per_100 = 100.0 * false_alerts / max(asset_hours, 1e-9)
            if per_100 > FALSE_ALERT_BUDGET_PER_100_ASSET_HOURS:
                continue
            warned = sum(1 for r in events if r["score"] > thr)
            recall = warned / max(len(events), 1)
            if best is None or recall > best["recall"]:
                best = {
                    "threshold": float(thr),
                    "recall": recall,
                    "false_alerts_per_100_asset_hours": per_100,
                    "warned_events": warned,
                    "total_events": len(events),
                }
        if best is None:
            # No threshold meets the budget: publish nothing for this task
            # (abstention is the honest state, not a zero threshold).
            policy[str(task)] = {
                "threshold": None,
                "status": "budget_unreachable",
                "false_alerts_per_100_asset_hours": None,
            }
        else:
            policy[str(task)] = {"status": "supported", **best}
    return policy


@torch.no_grad()
def collect_cal_records(
    engines: list[ForecastEngine], device, cal_examples: list[ClipExample]
) -> tuple[list[dict], dict[int, tuple[torch.Tensor, torch.Tensor, torch.Tensor]]]:
    """Ensemble-calibrated primary-horizon scores on the calibration split,
    plus per-member raw logits for the I.4 fits."""
    per_task_logits: dict[int, list[tuple]] = {t: [] for t in range(5)}
    records: list[dict] = []
    if len(engines) >= 2:
        ensemble = EnsembleForecaster(engines)
        for ex in cal_examples:
            if ex.cutoff_window % 10 != 0:
                continue  # non-overlapping horizons for alert accounting (M.3)
            windows = [to_device(w, device) for w in ex.windows]
            request = ForecastRequest(
                horizon_bins=PRIMARY_HORIZON,
                bin_seconds=30,
                task_mask=ex.targets.task_mask,
                min_occurrence_probability=0.30,
                published_horizons_seconds=(300,),
                candidate_pairs=ex.targets.candidate_pairs,
            )
            result = ensemble.forecast(windows, request)
            for entity in result.entities:
                for tf in entity.task_forecasts:
                    if tf.status != "supported" or tf.distribution is None:
                        continue
                    t = tf.task_index
                    score = float(tf.distribution.cumulative_risk[PRIMARY_HORIZON - 1])
                    at_risk = bool(ex.targets.risk_mask[entity.slot, 0, t])
                    if not at_risk:
                        continue
                    event = bool(
                        ex.targets.event_y[entity.slot, :PRIMARY_HORIZON, t].sum() > 0
                    )
                    # complete follow-up: still at risk through the horizon's
                    # last bin (no event, full observation — M.3 false-alert
                    # counting needs adequate follow-up)
                    complete = bool(
                        ex.targets.risk_mask[entity.slot, PRIMARY_HORIZON - 1, t]
                    ) and ex.cutoff_window + PRIMARY_HORIZON <= 110
                    records.append(
                        {
                            "task": t,
                            "entity": ex.entity_ids[entity.slot],
                            "episode": ex.episode_id,
                            "score": score,
                            "event": event,
                            "complete_followup": complete,
                            "asset_hours_weight": PRIMARY_HORIZON * 30 / 3600.0,
                        }
                    )
    # Per-member raw logits for the I.4 calibrator fits (all cal clips).
    for ex in cal_examples:
        windows = [to_device(w, device) for w in ex.windows]
        for engine in engines:
            observed = engine.model.observe_clip(windows)
            outputs = engine.model.roll_out(
                observed, 60,
                candidate_pairs=candidates_to_device(
                    ex.targets.candidate_pairs, device
                ),
                task_mask=ex.targets.task_mask,
            )
            logits = torch.stack([o.hazard_logits[0] for o in outputs], 0)
            for t in range(5):
                if bool(ex.targets.task_mask[t]):
                    per_task_logits[t].append(
                        (
                            logits[:, :, t].cpu(),        # [60, N]
                            ex.targets.event_y[:, :, t].cpu(),
                            ex.targets.risk_mask[:, :, t].cpu(),
                        )
                    )
    merged: dict[int, tuple[torch.Tensor, torch.Tensor, torch.Tensor]] = {}
    for t, parts in per_task_logits.items():
        if not parts:
            continue
        merged[t] = (
            torch.cat([p[0].permute(1, 0) for p in parts], dim=0),   # [K, 60]
            torch.cat([p[1] for p in parts], dim=0),                 # [K, 60]
            torch.cat([p[2] for p in parts], dim=0),                 # [K, 60]
        )
    return records, merged


@torch.no_grad()
def predict_locked_test(
    engines: list[ForecastEngine], device, test_examples: list[ClipExample]
) -> list[dict]:
    """Frozen-policy locked-test predictions for the evaluator (Section 29)."""
    ensemble = (
        EnsembleForecaster(engines) if len(engines) >= 2 else engines[0]
    )
    out: list[dict] = []
    for ex in test_examples:
        windows = [to_device(w, device) for w in ex.windows]
        request = ForecastRequest(
            horizon_bins=60,
            bin_seconds=30,
            task_mask=ex.targets.task_mask,
            min_occurrence_probability=0.30,
            published_horizons_seconds=(300, 900, 1800),
            candidate_pairs=ex.targets.candidate_pairs,
        )
        result = ensemble.forecast(windows, request)
        for entity in result.entities:
            for tf in entity.task_forecasts:
                if tf.status != "supported" or tf.distribution is None:
                    continue
                dist = tf.distribution
                out.append(
                    {
                        "episode_id": ex.episode_id,
                        "family": ex.family,
                        "cutoff_window": ex.cutoff_window,
                        "entity": ex.entity_ids[entity.slot],
                        "task": tf.task_index,
                        "cumulative_risk_300s": float(dist.cumulative_risk[9]),
                        "cumulative_risk_900s": float(dist.cumulative_risk[29]),
                        "cumulative_risk_1800s": float(dist.cumulative_risk[59]),
                        "event_bin": (
                            int(ex.targets.event_y[entity.slot, :, tf.task_index].argmax()) + 1
                            if float(ex.targets.event_y[entity.slot, :, tf.task_index].sum()) > 0
                            else None
                        ),
                        "risk_mask_bins": int(
                            ex.targets.risk_mask[entity.slot, :, tf.task_index].sum()
                        ),
                        "disagreement": (
                            result.model_disagreement.get(
                                (entity.slot, tf.task_index)
                            )
                            if result.model_disagreement is not None
                            else None
                        ),
                    }
                )
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts" / "profile")
    parser.add_argument("--cache", type=Path, default=REPO_ROOT / "artifacts" / "cache")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--device", type=str, default=None)
    args = parser.parse_args()

    device = torch.device(
        args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    )
    print(f"device: {device}", flush=True)
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True

    t_start = time.time()
    config = load_core_config(REPO_ROOT / "configs" / "core.yaml")

    # ---- 1. corpus + splits ------------------------------------------------
    print("[1/8] building corpus (synthetic, disclosed)...", flush=True)
    episodes = build_corpus()
    splits = split_episodes(episodes)
    print(
        f"  episodes: {len(episodes)} | train {len(splits.train)} "
        f"dev {len(splits.development)} cal {len(splits.calibration)} "
        f"test {len(splits.locked_test)}",
        flush=True,
    )

    # ---- 2. scaler on train prefix windows ---------------------------------
    print("[2/8] fitting F.8 scaler on train split...", flush=True)
    train_ds = ClipDataset(
        list(splits.train), split="train", scaler=None, cache_dir=args.cache
    )
    scaler = train_ds.fit_scaler_from_train()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "scaler.json").write_text(scaler.serialize(), encoding="utf-8")

    # ---- 3. clip examples (staged for memory: train+dev now, cal/test later)
    print("[3/8] building clip examples (cached)...", flush=True)

    def load_examples(split_name: str, episodes_list) -> list:
        ds = ClipDataset(
            episodes_list, split=split_name, scaler=scaler, cache_dir=args.cache
        )
        return ds.examples()

    examples: dict[str, list] = {
        "train": load_examples("train", list(splits.train)),
        "development": load_examples("development", list(splits.development)),
    }
    for name in ("train", "development"):
        events = sum(int(ex.targets.event_y.sum()) for ex in examples[name])
        print(f"  {name}: {len(examples[name])} clips, {events} events", flush=True)

    dev_monitor = [
        ex for ex in examples["development"] if ex.cutoff_window % 4 == 0
    ]
    rng = random.Random(0)

    # ---- 4. per-seed training (checkpointed; resumable) ----------------------
    import gc

    partial_dir = args.out / "partial"
    partial_dir.mkdir(parents=True, exist_ok=True)
    members: dict[int, OrderedDict] = {}
    run_summaries: dict[int, dict] = {}
    for seed in args.seeds:
        checkpoint = partial_dir / f"seed{seed}.pt"
        if checkpoint.exists():
            payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
            members[seed] = payload["state"]
            run_summaries[seed] = payload["summary"]
            print(
                f"[4/8] seed={seed}: checkpoint found (best epoch "
                f"{payload['summary']['best_epoch']}, devAP "
                f"{payload['summary']['best_dev_mean_ap']:.3f}) - skipping",
                flush=True,
            )
            continue
        print(f"[4/8] training member seed={seed}...", flush=True)
        set_seed(seed)
        model = ForesightWorldModel.from_config(config, num_event_tasks=5).to(device)
        trainer = Trainer(
            model=model,
            weights=LossWeights.from_config(config.training["loss"]),
            learning_rate=LEARNING_RATE,
            weight_decay=float(config.training["weight_decay"]),
            gradient_clip=float(config.training["gradient_clip"]),
            epochs_max=args.epochs,
            seed=seed,
            positive_weight=SURVIVAL_POSITIVE_WEIGHT,
            curriculum=CurriculumSchedule(
                horizons=(1, 3, 10, 30, 60),
                transition_epochs=CURRICULUM_TRANSITIONS,
            ),
        )
        train_examples = examples["train"]
        # Section-15 oversampling policy (recorded; corrected by I.4):
        # imminent-event clips are drawn more often so the rare positive
        # hazard signal is not swamped by the ~99.5% negative bins.
        clip_weights = np.array(
            [
                1.0
                if int(ex.targets.event_y[:, :PRIMARY_HORIZON, :].sum()) == 0
                else POSITIVE_CLIP_OVERSAMPLING
                for ex in train_examples
            ]
        )
        clip_probs = clip_weights / clip_weights.sum()
        best_ap = -1.0
        best_epoch = 0
        best_state = None
        epochs_no_improve = 0
        epoch_logs = []
        for epoch in range(1, args.epochs + 1):
            horizon = trainer.curriculum.horizon_for_epoch(epoch)
            order = list(
                np.random.default_rng(seed * 1000 + epoch).choice(
                    len(train_examples),
                    size=len(train_examples),
                    replace=True,
                    p=clip_probs,
                )
            )
            rng.shuffle(order)
            t_epoch = time.time()
            losses = []
            for i in range(0, len(order), 16):
                batch_ex = [train_examples[j] for j in order[i : i + 16]]
                num_t = len(batch_ex[0].windows)
                stacked = [
                    to_device(
                        stack_windows([ex.windows[t] for ex in batch_ex]), device
                    )
                    for t in range(num_t)
                ]
                candidates = candidates_to_device(
                    stack_candidates(
                        [ex.targets.candidate_pairs for ex in batch_ex]
                    ),
                    device,
                )
                clip_targets = [
                    targets_to_device(ex.targets, device) for ex in batch_ex
                ]
                log = trainer.batched_step(
                    stacked, clip_targets, candidates, epoch=epoch
                )
                losses.append(log.loss["total"])
            ap = dev_average_precision(model, device, dev_monitor)
            mean_ap = float(np.mean(list(ap.values()))) if ap else 0.0
            epoch_logs.append(
                {
                    "epoch": epoch,
                    "horizon_bins": horizon,
                    "train_loss": float(np.mean(losses)),
                    "dev_average_precision": ap,
                    "dev_mean_ap": mean_ap,
                    "seconds": round(time.time() - t_epoch, 1),
                }
            )
            marker = ""
            if mean_ap > best_ap + 1e-4:
                best_ap = mean_ap
                best_epoch = epoch
                best_state = OrderedDict(
                    {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                )
                epochs_no_improve = 0
                marker = " *"
            else:
                epochs_no_improve += 1
            print(
                f"  epoch {epoch:2d} h={horizon:2d} "
                f"loss={float(np.mean(losses)):.4f} devAP={mean_ap:.3f}"
                f"{marker} ({time.time() - t_epoch:.0f}s)",
                flush=True,
            )
            if epochs_no_improve >= EARLY_STOP_PATIENCE:
                print(f"  early stop at epoch {epoch} (best {best_epoch})", flush=True)
                break
        members[seed] = best_state
        run_summaries[seed] = {
            "best_epoch": best_epoch,
            "best_dev_mean_ap": best_ap,
            "curriculum_transitions": list(CURRICULUM_TRANSITIONS),
            "sampling_policy": (
                f"positive_clip_oversampling({POSITIVE_CLIP_OVERSAMPLING}x) "
                f"+ survival positive_weight({SURVIVAL_POSITIVE_WEIGHT}) "
                "with recorded probabilities; base-rate/odds shift corrected "
                "by I.4 natural-prevalence calibration (Section 15, A12)"
            ),
            "epochs": epoch_logs,
        }
        # Per-seed checkpoint: an interrupted run resumes here (I.1).
        torch.save(
            {"state": best_state, "summary": run_summaries[seed]},
            checkpoint,
        )
        print(f"  checkpoint saved: {checkpoint}", flush=True)
        del model, trainer
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()

    # Free training memory before the calibration/prediction stages.
    del examples["train"]
    del dev_monitor
    gc.collect()

    # Sequential-seed mode: when other seeds' checkpoints are still pending,
    # exit here — the final invocation (all checkpoints present) assembles
    # calibrators, policy, predictions and the bundle.
    pending = [
        s for s in SEEDS if not (partial_dir / f"seed{s}.pt").exists()
    ]
    if pending:
        print(
            f"[resume] pending seeds {pending}; exiting after training stage "
            "(re-run per seed; the final run assembles the bundle)",
            flush=True,
        )
        return

    # ---- 5. calibrators -------------------------------------------------------
    print("[5/8] fitting I.4 calibrators on calibration split...", flush=True)
    examples["calibration"] = load_examples(
        "calibration", list(splits.calibration)
    )
    print(
        f"  calibration: {len(examples['calibration'])} clips, "
        f"{sum(int(ex.targets.event_y.sum()) for ex in examples['calibration'])} events",
        flush=True,
    )
    engines: list[ForecastEngine] = []
    calibrators_payload: dict[str, dict] = {}
    for seed in args.seeds:
        model = ForesightWorldModel.from_config(config, num_event_tasks=5).to(device)
        model.load_state_dict({k: v.to(device) for k, v in members[seed].items()})
        model.eval()
        engines.append(ForecastEngine(model))
    # gather per-member logits once
    member_logits: dict[int, dict[int, tuple]] = {}
    for si, engine in enumerate(engines):
        _, merged = collect_cal_records([engine], device, examples["calibration"])
        member_logits[args.seeds[si]] = merged
    for seed, merged in member_logits.items():
        for task, (logits, events, masks) in merged.items():
            cal = fit_hazard_calibrator(logits, events, masks, task_index=task)
            calibrators_payload[f"{seed}:{task}"] = cal.to_dict()
            print(
                f"  seed {seed} task {task}: fitted={cal.fitted} "
                f"slope={cal.slope:.3f} events={cal.fit_event_count}",
                flush=True,
            )
    # rebuild engines with calibrators attached
    from foresight.calibration.hazard import HazardCalibrator

    calibrated_engines: list[ForecastEngine] = []
    for si, seed in enumerate(args.seeds):
        cals = {
            (int(k.split(":")[1]), None): HazardCalibrator.from_dict(v)
            for k, v in calibrators_payload.items()
            if int(k.split(":")[0]) == seed
        }
        engines[si].calibrator_set = CalibratorSet(calibrators=cals, pooled=None)
        calibrated_engines.append(engines[si])

    # ---- 6. selection policy ---------------------------------------------------
    print("[6/8] fitting selection policy at the alert budget...", flush=True)
    cal_records, _ = collect_cal_records(
        calibrated_engines, device, examples["calibration"]
    )
    policy = fit_selection_policy(cal_records)
    for task, p in sorted(policy.items(), key=lambda kv: int(kv[0])):
        print(
            f"  task {task}: {p['status']} "
            + (
                f"thr={p['threshold']:.3f} recall={p['recall']:.2f} "
                f"fa/100ah={p['false_alerts_per_100_asset_hours']:.2f}"
                if p["status"] == "supported"
                else ""
            ),
            flush=True,
        )

    # ---- 7. locked-test predictions --------------------------------------------
    print("[7/8] running I.5 ensemble over locked test...", flush=True)
    del examples["calibration"]
    gc.collect()
    examples["locked_test"] = load_examples(
        "locked_test", list(splits.locked_test)
    )
    print(
        f"  locked test: {len(examples['locked_test'])} clips, "
        f"{sum(int(ex.targets.event_y.sum()) for ex in examples['locked_test'])} events",
        flush=True,
    )
    predictions = predict_locked_test(
        calibrated_engines, device, examples["locked_test"]
    )
    print(f"  {len(predictions)} prediction records", flush=True)
    del examples["locked_test"]
    del examples["development"]
    gc.collect()

    # ---- 8. novelty reference (J.1) + bundle ---------------------------------
    print("[8/8] fitting novelty reference and assembling I.6 bundle...", flush=True)
    bundle = args.out
    from foresight.sentinel.reference import fit_novelty_reference

    benign_train = [
        ex
        for ex in load_examples("train", list(splits.train))
        if ex.family in ("benign", "benign-drift")
    ]
    if benign_train:
        novelty = fit_novelty_reference(
            calibrated_engines[0].model,
            next(calibrated_engines[0].model.parameters()).device,
            benign_train,
        )
        novelty.to_npz(bundle / "novelty_reference.npz")
        print(
            f"  novelty reference: {novelty.fit_episode_count} benign episodes, "
            f"{novelty.fit_residual_count} matured residuals",
            flush=True,
        )
    for seed in args.seeds:
        path = bundle / f"model_seed{seed}.safetensors"
        from safetensors.torch import save_file

        save_file(members[seed], str(path))
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "foresight.core.2026-09",
                "profile": "foresight-section35-run",
                "synthetic_data_only": True,
                "seeds": list(args.seeds),
                "corpus": {
                    "episodes": len(episodes),
                    "splits": splits.manifest(),
                },
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (bundle / "model_config.json").write_text(
        json.dumps({"num_event_tasks": 5, "config_source": "configs/core.yaml"}, indent=2),
        encoding="utf-8",
    )
    (bundle / "feature_registry.json").write_text(
        json.dumps(
            {
                "node": list(NODE_FEATURE_NAMES),
                "edge": list(EDGE_FEATURE_NAMES),
                "global": list(GLOBAL_FEATURE_NAMES),
                "transforms": TRANSFORMS,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (bundle / "task_manifest.json").write_text(
        json.dumps([asdict(t) for t in TASK_DEFINITIONS], indent=2),
        encoding="utf-8",
    )
    (bundle / "calibrators.json").write_text(
        json.dumps(calibrators_payload, indent=2), encoding="utf-8"
    )
    (bundle / "selection_policy.json").write_text(
        json.dumps(policy, indent=2), encoding="utf-8"
    )
    (bundle / "training_run.json").write_text(
        json.dumps(
            {
                "seeds": {str(k): v for k, v in run_summaries.items()},
                "curriculum": {
                    "horizons": [1, 3, 10, 30, 60],
                    "transition_epochs": list(CURRICULUM_TRANSITIONS),
                },
                "early_stop_patience": EARLY_STOP_PATIENCE,
                "batch_clips": 16,
                "elapsed_seconds": round(time.time() - t_start, 1),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (bundle / "test_predictions.json").write_text(
        json.dumps(predictions), encoding="utf-8"
    )
    hashes = {
        p.name: sha256_file(p)
        for p in sorted(bundle.iterdir())
        if p.is_file() and p.name != "artifact_hashes.json"
    }
    (bundle / "artifact_hashes.json").write_text(
        json.dumps(hashes, indent=2), encoding="utf-8"
    )
    print(
        f"done in {(time.time() - t_start) / 60:.1f} min -> {bundle}",
        flush=True,
    )


if __name__ == "__main__":
    main()
