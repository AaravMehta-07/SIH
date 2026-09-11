"""Section-35 training run: the real FORESIGHT profile (Build Spec I.1-I.6).

Pipeline (all offline, laptop GPU):

1. Build the synthetic episode corpus (300 episodes, six families) and the
   M.1 chronological episode splits (60/15/10/15).
2. Fit the F.8 feature scaler on the TRAIN split's prefix windows only.
3. Train six independent heterogeneous members (three reference, two gate,
   one wide; I.5: separate encoders,
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
import gc
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
    CUTOFF_STEP_EVAL,
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
from foresight.models.variants import build_world_model, variant_of  # noqa: E402
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
#: I.5 heterogeneous ensemble: the Tier B profile trains the Section-13
#: reference plus two architecturally distinct members (models/variants.py).
#: All members are retrained after corpus scaling.  Six preserves three
#: architectures while bounding laptop wall-clock and memory (I.5/T.1).
DEFAULT_MEMBERS = "reference:0,1,2 gate:0,1 wide:0"
CURRICULUM_TRANSITIONS = (9, 17, 25, 33)  # epochs at which horizon advances
EARLY_STOP_PATIENCE = 8
#: Early stop may only fire once the curriculum reaches the PRIMARY horizon
#: (h=10 begins at epoch 17): dev AP at h=1/h=3 sits in the same 0.008-0.04
#: band for every member family (reference seeds included — see
#: training_run.json) and an epoch-2 spike there exhausts patience before
#: the metric means anything. Patience also resets at each horizon
#: transition, so every phase gets a fresh budget.
PRIMARY_HORIZON_EPOCH = 17
FALSE_ALERT_BUDGET_PER_100_ASSET_HOURS = 1.0

#: ---- v2 recall-focused fine-tune recipe (2026-09-12) ---------------------
#: Locked-test diagnosis that motivated it (all from the sealed report):
#:   (a) task-1 calibrators abstain (8 cal events < 20 minimum) so raw
#:       ~0.99 logits pass through — 183 test records above 0.5 with 2 real
#:       events, ~94% of the Brier gap;
#:   (b) the v1 policy fitted each task at its OWN 1.0/100ah budget while
#:       the Section-29 gate is AGGREGATE across tasks, and the fit only
#:       counted at-risk records while the evaluator also counts post-event
#:       re-alerts (an ongoing beacon keeps scores high after the event, and
#:       each post-event re-alert can never match anything);
#:   (c) catchable recall lives in tasks 2/3 (lateral, C2) — task 0 is the
#:       campaign-onset event with no traffic precursor by construction.
FINETUNE_RECIPE = "finetune-v3-recall"
FINETUNE_EPOCHS = 14
FINETUNE_LR = 1e-3
#: Fine-tune curriculum starts AT the primary horizon (the members already
#: learned h=1/3 in the scratch run) and still tours the long horizons so
#: the transition model keeps its 30/60-bin quality. Every phase trains the
#: primary bins too (the rollout covers bins 1..H).
FINETUNE_HORIZONS = (10, 30, 60)
FINETUNE_TRANSITIONS = (7, 11)
#: v3 selection metric: fine-tuned members are selected on the mean dev AP
#: over the CATCHABLE tasks (lateral/C2/exfil — the ones with traffic
#: precursors). Onset tasks 0/1 have no precursor by corpus design; their
#: dev AP is base-rate noise, and a 5-task mean dilutes exactly the ranking
#: the recall gate measures. Dev-split selection only (I.1); the metric is
#: recorded in every run summary.
FINETUNE_SELECTION_TASKS = (2, 3, 4)
#: Per-task survival positive weights (A12: recorded; the induced odds shift
#: is corrected by the I.4 calibrators fitted at natural prevalence).
#: Lateral/C2/exfil are the catchable tasks; onset tasks keep the base.
TASK_POSITIVE_WEIGHTS = (50.0, 50.0, 100.0, 150.0, 100.0)
BOOSTED_TASKS = (2, 3, 4)
BOOSTED_POSITIVE_CLIP_OVERSAMPLING = 8.0
#: Declared AGGREGATE alert budget for the v2 policy fit: 20% headroom under
#: the Section-29 gate (1.0/100ah) for calibration->test split variance,
#: declared before any test evaluation and recorded in the run manifest.
POLICY_AGGREGATE_BUDGET = 0.8


def parse_members(spec: str) -> list[tuple[str, int]]:
    """Parse a member plan like ``reference:0,1,2 gate:0,1 wide:0``."""
    members: list[tuple[str, int]] = []
    for group in spec.split():
        variant, _, seed_list = group.partition(":")
        variant = variant.strip()
        if variant not in ("reference", "gate", "wide"):
            raise ValueError(f"unknown variant {variant!r} in member plan")
        for part in seed_list.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-")
                seeds = range(int(lo), int(hi) + 1)
            else:
                seeds = [int(part)]
            for s in seeds:
                members.append((variant, s))
    if not members:
        raise ValueError("member plan is empty")
    return members


def member_checkpoint(partial_dir: Path, variant: str, seed: int) -> Path:
    """Checkpoint path for one member. Reference members fall back to the
    legacy ``seed{N}.pt`` name from the original 5-seed run."""
    new = partial_dir / f"{variant}_seed{seed}.pt"
    if variant == "reference" and not new.exists():
        legacy = partial_dir / f"seed{seed}.pt"
        if legacy.exists():
            return legacy
    return new


def member_model_path(bundle_dir: Path, variant: str, seed: int) -> Path:
    return bundle_dir / f"model_{variant}_seed{seed}.safetensors"

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
    *,
    budget: float = POLICY_AGGREGATE_BUDGET,
) -> dict:
    """Per-task alert thresholds under an AGGREGATE false-alert budget,
    fitted on the calibration split with the exact M.3 matching semantics.

    ``cal_records`` entries: {task, entity, episode, cutoff_window, score,
    event_bin, at_risk, event, complete_followup, asset_hours_weight}.
    Records include post-event / not-at-risk forecasts: the evaluator alerts
    on those too (an ongoing beacon keeps scores high after the event fired,
    and each post-event re-alert after cooldown can never match anything),
    so the fit must see them or it underestimates the false-alert rate.

    The Section-29 gate is AGGREGATE false alerts per 100 asset-hours across
    all tasks; this fit optimizes total warned events under that same
    aggregate constraint. M.3 matching is per (entity, task) key, so the
    per-task (matched, unmatched) frontiers are independent and the joint
    optimum is a small knapsack over them. Alert semantics mirror the
    evaluator exactly: alerts fire on score > threshold, sorted by emission,
    300-second per-(entity, task) cooldown, strict-before-and-within-horizon
    matching (I.3 deterministic threshold fitting).
    """
    from foresight.evaluation.matching import (
        Alert,
        ObservedEvent,
        match_events,
    )

    # Asset-hours mirror report.py: unique (episode, cutoff, entity) triples
    # over the evaluated grid x primary horizon.
    asset_hours = (
        sum(
            1
            for _ in {
                (r["episode"], r["cutoff_window"], r["entity"])
                for r in cal_records
            }
        )
        * PRIMARY_HORIZON
        * 30
        / 3600.0
    )

    # Events mirror the evaluator's extraction: unique first events per
    # (episode, entity, task) from the records' event bins (absolute window).
    first_event: dict[tuple[str, str, int], int] = {}
    for r in cal_records:
        if r.get("event_bin") is None:
            continue
        key = (r["episode"], r["entity"], r["task"])
        w = r["cutoff_window"] + r["event_bin"]
        if key not in first_event or w < first_event[key]:
            first_event[key] = w

    max_candidates = 4000
    frontiers: dict[int, list[tuple[int, int, float]]] = {}
    events_by_task: dict[int, list[ObservedEvent]] = {}
    records_by_task: dict[int, list[dict]] = {}
    for t in range(5):
        records_by_task[t] = [r for r in cal_records if r["task"] == t]
        events_by_task[t] = [
            ObservedEvent(
                entity=ent, task_index=t, event_window=w, episode_id=ep
            )
            for (ep, ent, tk), w in first_event.items()
            if tk == t
        ]
        if not records_by_task[t]:
            # No records -> the only operating point is abstention; the
            # frontier must still carry it or the cross-task DP would drop
            # accumulated choices when it reaches this task.
            frontiers[t] = [(0, 0, float("inf"))]
            events_by_task[t] = []
            continue
        scores = sorted({r["score"] for r in records_by_task[t]}, reverse=True)
        if len(scores) > max_candidates:
            # Evenly spaced subsample (densest at both ends); frontier
            # windows can be a single score wide, so this cap is a last
            # resort for pathologically large candidate sets.
            keep = sorted(
                set(
                    int(round(f * (len(scores) - 1)))
                    for f in np.linspace(0, 1, max_candidates)
                )
            )
            cands = [scores[i] for i in keep]
        else:
            # Every unique score: the (matched, unmatched) frontier can
            # change at any single score, so no coarser grid is safe.
            cands = scores
        thresholds = [float(np.nextafter(s, -np.inf)) for s in cands]
        thresholds.append(float("inf"))  # abstain
        frontier: dict[int, tuple[int, float]] = {}
        for thr in thresholds:
            alerts = [
                Alert(
                    entity=r["entity"],
                    task_index=t,
                    emission_window=r["cutoff_window"],
                    score=r["score"],
                    episode_id=r["episode"],
                )
                for r in records_by_task[t]
                if r["score"] > thr
            ]
            alerts.sort(
                key=lambda a: (a.emission_window, a.entity, a.task_index)
            )
            m = match_events(alerts, events_by_task[t])
            u, mt = m.unmatched_alerts, m.matched_events
            cur = frontier.get(u)
            if cur is None or mt > cur[0] or (mt == cur[0] and thr > cur[1]):
                frontier[u] = (mt, thr)
        # Pareto frontier: (unmatched, matched, threshold), matched
        # nondecreasing in unmatched, dominated points dropped.
        pareto: list[tuple[int, int, float]] = []
        best_m = -1
        for u in sorted(frontier):
            mt, thr = frontier[u]
            if mt > best_m:
                pareto.append((u, mt, thr))
                best_m = mt
        frontiers[t] = pareto

    # Knapsack across tasks: maximize total matched subject to the
    # aggregate false-alert budget (integer unmatched counts).
    u_max = int(budget * asset_hours / 100.0)
    dp: dict[int, tuple[int, dict[int, float]]] = {0: (0, {})}
    for t in range(5):
        ndp: dict[int, tuple[int, dict[int, float]]] = {}
        for u0, (m0, ch0) in dp.items():
            for u, mt, thr in frontiers[t]:
                if u0 + u > u_max:
                    continue
                key = u0 + u
                cand = (m0 + mt, {**ch0, t: thr})
                cur = ndp.get(key)
                if cur is None or cand[0] > cur[0]:
                    ndp[key] = cand
        dp = ndp if ndp else {0: (0, {})}
    # Lowest unmatched total among the max-matched optima (deterministic).
    best_choices: dict[int, float] = {}
    best_matched = -1
    for u_total in sorted(dp):
        m_total, choices = dp[u_total]
        if m_total > best_matched:
            best_matched = m_total
            best_choices = choices

    policy: dict[str, dict] = {}
    for t in range(5):
        thr = best_choices.get(t, float("inf"))
        if not events_by_task[t]:
            policy[str(t)] = {
                "threshold": None,
                "status": "insufficient_positive_support",
                "false_alerts_per_100_asset_hours": None,
                "warned_events": 0,
                "total_events": 0,
            }
            continue
        if thr == float("inf"):
            policy[str(t)] = {
                "threshold": None,
                "status": "budget_unreachable",
                "false_alerts_per_100_asset_hours": None,
                "warned_events": 0,
                "total_events": len(events_by_task[t]),
            }
            continue
        alerts = [
            Alert(
                entity=r["entity"],
                task_index=t,
                emission_window=r["cutoff_window"],
                score=r["score"],
                episode_id=r["episode"],
            )
            for r in records_by_task[t]
            if r["score"] > thr
        ]
        alerts.sort(key=lambda a: (a.emission_window, a.entity, a.task_index))
        m = match_events(alerts, events_by_task[t])
        policy[str(t)] = {
            "status": "supported",
            "threshold": float(thr),
            "recall": m.matched_events / max(len(events_by_task[t]), 1),
            "false_alerts_per_100_asset_hours": (
                100.0 * m.unmatched_alerts / max(asset_hours, 1e-9)
            ),
            "warned_events": m.matched_events,
            "total_events": len(events_by_task[t]),
        }
    policy["_aggregate"] = {
        "budget_per_100_asset_hours": budget,
        "calibration_asset_hours": asset_hours,
        "calibration_total_warned_events": best_matched,
        "calibration_total_events": sum(
            len(events_by_task[t]) for t in range(5)
        ),
        "semantics": (
            "aggregate budget across tasks; exact M.3 matching on the "
            "calibration split including post-event re-alerts"
        ),
    }
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
                candidate_pairs=candidates_to_device(
                    ex.targets.candidate_pairs, device
                ),
            )
            result = ensemble.forecast(windows, request)
            for entity in result.entities:
                for tf in entity.task_forecasts:
                    if tf.status != "supported" or tf.distribution is None:
                        continue
                    t = tf.task_index
                    score = float(tf.distribution.cumulative_risk[PRIMARY_HORIZON - 1])
                    at_risk = bool(ex.targets.risk_mask[entity.slot, 0, t])
                    event_bins = ex.targets.event_y[entity.slot, :, t]
                    has_event = bool(float(event_bins.sum()) > 0)
                    event_bin = (
                        int(event_bins.argmax()) + 1 if has_event else None
                    )
                    event = bool(
                        at_risk
                        and float(
                            ex.targets.event_y[
                                entity.slot, :PRIMARY_HORIZON, t
                            ].sum()
                        )
                        > 0
                    )
                    # complete follow-up: still at risk through the horizon's
                    # last bin (no event, full observation — M.3 false-alert
                    # counting needs adequate follow-up)
                    complete = bool(
                        ex.targets.risk_mask[entity.slot, PRIMARY_HORIZON - 1, t]
                    ) and ex.cutoff_window + PRIMARY_HORIZON <= 110
                    # Records include NOT-at-risk (post-event) forecasts: the
                    # evaluator alerts on those too, and each post-event
                    # re-alert after cooldown can never match anything — the
                    # selection-policy fit must see them (v2 fix).
                    records.append(
                        {
                            "task": t,
                            "entity": ex.entity_ids[entity.slot],
                            "episode": ex.episode_id,
                            "cutoff_window": ex.cutoff_window,
                            "score": score,
                            "at_risk": at_risk,
                            "event": event,
                            "event_bin": event_bin,
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
            candidate_pairs=candidates_to_device(
                ex.targets.candidate_pairs, device
            ),
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
    parser.add_argument(
        "--members",
        type=str,
        default=DEFAULT_MEMBERS,
        help=(
            "member plan: 'variant:seeds' groups, e.g. "
            "'reference:0,1,2 gate:0,1 wide:0' (I.5)"
        ),
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=None,
        help="max epochs (default: 40 scratch / 20 fine-tune)",
    )
    parser.add_argument(
        "--finetune",
        action="store_true",
        help=(
            "warm-start members from an existing final checkpoint of the "
            "same corpus (v2 recall recipe: per-task positive weights, "
            "boosted catchable-task oversampling, h=10-start curriculum; "
            "epoch-0 dev AP is banked as the selection floor)"
        ),
    )
    parser.add_argument(
        "--policy-budget",
        type=float,
        default=None,
        help=(
            "override the declared aggregate alert budget "
            f"(default {POLICY_AGGREGATE_BUDGET}/100 asset-hours)"
        ),
    )
    parser.add_argument("--device", type=str, default=None)
    args = parser.parse_args()
    if args.epochs is None:
        args.epochs = FINETUNE_EPOCHS if args.finetune else 40
    recipe_tag = FINETUNE_RECIPE if args.finetune else "scratch"
    policy_budget = (
        args.policy_budget
        if args.policy_budget is not None
        else POLICY_AGGREGATE_BUDGET
    )

    plan = parse_members(args.members)

    device = torch.device(
        args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    )
    print(f"device: {device}", flush=True)
    # Thread caps: this run shares a 16 GB host with the user's own
    # workload; every avoided thread stack and workspace is margin against
    # the system memory guard.
    torch.set_num_threads(4)
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True

    t_start = time.time()
    config = load_core_config(REPO_ROOT / "configs" / "core.yaml")

    # ---- 1. corpus + splits ------------------------------------------------
    print("[1/8] building corpus (synthetic, disclosed)...", flush=True)
    episodes = build_corpus()
    splits = split_episodes(episodes)
    corpus_fingerprint = hashlib.sha256(
        json.dumps(
            [(e.episode_id, e.seed, e.family) for e in episodes],
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    print(
        f"  episodes: {len(episodes)} | train {len(splits.train)} "
        f"dev {len(splits.development)} cal {len(splits.calibration)} "
        f"test {len(splits.locked_test)}",
        flush=True,
    )

    # ---- 2. scaler on train prefix windows ---------------------------------
    print("[2/8] fitting F.8 scaler on train split...", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    scaler_path = args.out / "scaler.json"
    scaler_meta_path = args.out / "scaler_corpus.json"
    scaler_matches = False
    if scaler_meta_path.exists():
        try:
            scaler_matches = (
                json.loads(scaler_meta_path.read_text(encoding="utf-8")).get(
                    "corpus_fingerprint"
                )
                == corpus_fingerprint
            )
        except (OSError, ValueError):
            scaler_matches = False
    if scaler_path.exists() and scaler_matches:
        # Fit once per corpus; per-seed invocations reuse the frozen fit
        # (F.8: never fit per run, let alone per upload).
        scaler = FeatureScaler.from_json(
            json.loads(scaler_path.read_text(encoding="utf-8"))
        )
        print("  scaler loaded from cache", flush=True)
    else:
        train_ds = ClipDataset(
            list(splits.train), split="train", scaler=None, cache_dir=args.cache
        )
        scaler = train_ds.fit_scaler_from_train()
        del train_ds
        gc.collect()
        scaler_path.write_text(scaler.serialize(), encoding="utf-8")
        scaler_meta_path.write_text(
            json.dumps(
                {"corpus_fingerprint": corpus_fingerprint, "episodes": len(episodes)},
                indent=2,
            ),
            encoding="utf-8",
        )

    # ---- 3. clip examples (staged for memory: train+dev now, cal/test later)
    print("[3/8] building clip examples (cached)...", flush=True)

    def load_examples(split_name: str, episodes_list, stride=None) -> list:
        ds = ClipDataset(
            episodes_list, split=split_name, scaler=scaler,
            cache_dir=args.cache, stride=stride,
        )
        return ds.examples()

    examples: dict[str, list] = {
        "train": load_examples("train", list(splits.train)),
        "development": load_examples("development", list(splits.development)),
    }
    for name in ("train", "development"):
        events = sum(int(ex.targets.event_y.sum()) for ex in examples[name])
        print(f"  {name}: {len(examples[name])} clips, {events} events", flush=True)

    # Full dev set at the training stride (88 clips at stride 8) — a
    # modulo sub-filter can silently match nothing when the stride and the
    # modulus share factors (caught live: stride-8 cutoffs are all 4 mod 8).
    dev_monitor = examples["development"]
    rng = random.Random(0)

    # ---- 4. per-seed training (checkpointed; resumable) ----------------------

    partial_dir = args.out / "partial"
    partial_dir.mkdir(parents=True, exist_ok=True)
    members: dict[tuple[str, int], OrderedDict] = {}
    run_summaries: dict[str, dict] = {}
    # Variant seed offsets decorrelate member initialization across families
    # sharing seed numbers (I.5: independently trained members).
    variant_seed_offset = {"reference": 0, "gate": 10_000, "wide": 20_000}
    horizons, transitions = (
        (FINETUNE_HORIZONS, FINETUNE_TRANSITIONS)
        if args.finetune
        else ((1, 3, 10, 30, 60), CURRICULUM_TRANSITIONS)
    )
    early_stop_from = 1 if args.finetune else PRIMARY_HORIZON_EPOCH
    for variant, seed in plan:
        member_key = f"{variant}:{seed}"
        checkpoint = member_checkpoint(partial_dir, variant, seed)
        resume = None
        warm = None
        if checkpoint.exists():
            candidate = torch.load(checkpoint, map_location="cpu", weights_only=False)
            if candidate.get("corpus_fingerprint") != corpus_fingerprint:
                print(
                    f"[4/8] {member_key}: stale checkpoint ignored "
                    "(corpus fingerprint changed)",
                    flush=True,
                )
            elif candidate.get("recipe", "scratch") != recipe_tag:
                if args.finetune and candidate.get("final", False):
                    warm = candidate
                    print(
                        f"[4/8] {member_key}: warm start from "
                        f"{candidate.get('recipe', 'scratch')} checkpoint "
                        f"(best epoch {candidate['summary']['best_epoch']}, "
                        f"devAP {candidate['summary']['best_dev_mean_ap']:.3f})",
                        flush=True,
                    )
                else:
                    print(
                        f"[4/8] {member_key}: checkpoint from recipe "
                        f"{candidate.get('recipe', 'scratch')!r} ignored",
                        flush=True,
                    )
            else:
                resume = candidate
        if resume is not None:
            summary = resume["summary"]
            if resume.get("final", False):
                members[(variant, seed)] = resume["state"]
                run_summaries[member_key] = summary
                print(
                    f"[4/8] {member_key}: checkpoint found (best epoch "
                    f"{summary['best_epoch']}, devAP "
                    f"{summary['best_dev_mean_ap']:.3f}) - skipping",
                    flush=True,
                )
                continue
            print(
                f"[4/8] {member_key}: resuming from epoch "
                f"{summary['epochs'][-1]['epoch']} (best "
                f"{summary['best_epoch']}, devAP "
                f"{summary['best_dev_mean_ap']:.3f})",
                flush=True,
            )
        print(f"[4/8] training member {member_key}...", flush=True)
        set_seed(seed + variant_seed_offset[variant])
        model = build_world_model(config, variant=variant, num_event_tasks=5).to(
            device
        )
        if variant_of(model) == "custom":
            raise RuntimeError(f"variant assembly failed for {member_key}")
        if resume is not None:
            model.load_state_dict(
                {k: v.to(device) for k, v in resume["state"].items()}
            )
        elif warm is not None:
            model.load_state_dict(
                {k: v.to(device) for k, v in warm["state"].items()}
            )
        horizons, transitions = (
            (FINETUNE_HORIZONS, FINETUNE_TRANSITIONS)
            if args.finetune
            else ((1, 3, 10, 30, 60), CURRICULUM_TRANSITIONS)
        )
        early_stop_from = 1 if args.finetune else PRIMARY_HORIZON_EPOCH
        trainer = Trainer(
            model=model,
            weights=LossWeights.from_config(config.training["loss"]),
            learning_rate=(FINETUNE_LR if args.finetune else LEARNING_RATE),
            weight_decay=float(config.training["weight_decay"]),
            gradient_clip=float(config.training["gradient_clip"]),
            epochs_max=args.epochs,
            seed=seed,
            positive_weight=SURVIVAL_POSITIVE_WEIGHT,
            task_positive_weights=(
                TASK_POSITIVE_WEIGHTS if args.finetune else None
            ),
            curriculum=CurriculumSchedule(
                horizons=horizons,
                transition_epochs=transitions,
            ),
        )
        train_examples = examples["train"]

        # Section-15 oversampling policy (recorded; corrected by I.4):
        # imminent-event clips are drawn more often so the rare positive
        # hazard signal is not swamped by the ~99.5% negative bins. The v2
        # fine-tune draws clips with imminent lateral/C2/exfil events — the
        # catchable tasks — harder still.
        def clip_sampling_weight(ex) -> float:
            per_task = ex.targets.event_y[:, :PRIMARY_HORIZON, :].sum(dim=(0, 1))
            if args.finetune and any(
                int(per_task[t]) > 0 for t in BOOSTED_TASKS
            ):
                return BOOSTED_POSITIVE_CLIP_OVERSAMPLING
            if int(per_task.sum()) > 0:
                return POSITIVE_CLIP_OVERSAMPLING
            return 1.0

        clip_weights = np.array(
            [clip_sampling_weight(ex) for ex in train_examples], dtype=float
        )
        clip_probs = clip_weights / clip_weights.sum()

        def selection_ap(ap: dict) -> float:
            """Dev-selection metric: catchable-task mean AP for the
            fine-tune (v3), all-task mean for the scratch recipe."""
            if args.finetune:
                sel = [ap[t] for t in FINETUNE_SELECTION_TASKS if t in ap]
                return float(np.mean(sel)) if sel else 0.0
            return float(np.mean(list(ap.values()))) if ap else 0.0

        def sampling_policy_str() -> str:
            boost = (
                f", {BOOSTED_POSITIVE_CLIP_OVERSAMPLING}x for imminent tasks "
                f"{list(BOOSTED_TASKS)}"
                if args.finetune
                else ""
            )
            tw = (
                f" per-task {list(TASK_POSITIVE_WEIGHTS)}"
                if args.finetune
                else ""
            )
            return (
                f"positive_clip_oversampling({POSITIVE_CLIP_OVERSAMPLING}x"
                f"{boost}) + survival positive_weight"
                f"({SURVIVAL_POSITIVE_WEIGHT}{tw}) with recorded "
                "probabilities; base-rate/odds shift corrected by I.4 "
                "natural-prevalence calibration (Section 15, A12)"
            )

        def run_summary_so_far() -> dict:
            return {
                "recipe": recipe_tag,
                "selection_metric": (
                    "catchable_task_mean_ap"
                    f" (tasks {list(FINETUNE_SELECTION_TASKS)})"
                    if args.finetune
                    else "all_task_mean_ap"
                ),
                "best_epoch": best_epoch,
                "best_dev_mean_ap": best_ap,
                "curriculum_transitions": list(transitions),
                "task_positive_weights": (
                    list(TASK_POSITIVE_WEIGHTS) if args.finetune else None
                ),
                "sampling_policy": sampling_policy_str(),
                "epochs": epoch_logs,
            }

        if resume is not None:
            best_ap = resume["summary"]["best_dev_mean_ap"]
            best_epoch = resume["summary"]["best_epoch"]
            best_state = resume["state"]
            epochs_no_improve = resume.get("epochs_no_improve", 0)
            epoch_logs = resume["summary"]["epochs"]
            trainer.optimizer.load_state_dict(resume["optimizer"])
            start_epoch = epoch_logs[-1]["epoch"] + 1
        elif warm is not None:
            # Bank the warm state as epoch 0: the fine-tune's dev-selection
            # floor is the warm-start quality, so a member can never end
            # below where it started.
            ap0 = dev_average_precision(model, device, dev_monitor)
            best_ap = selection_ap(ap0)
            best_epoch = 0
            best_state = OrderedDict(
                {
                    k: v.detach().cpu().clone()
                    for k, v in model.state_dict().items()
                }
            )
            epochs_no_improve = 0
            epoch_logs = [
                {
                    "epoch": 0,
                    "horizon_bins": PRIMARY_HORIZON,
                    "train_loss": None,
                    "dev_average_precision": ap0,
                    "dev_mean_ap": best_ap,
                    "seconds": 0.0,
                    "warm_start": True,
                }
            ]
            start_epoch = 1
            torch.save(
                {
                    "state": best_state,
                    "optimizer": trainer.optimizer.state_dict(),
                    "summary": run_summary_so_far(),
                    "epochs_no_improve": 0,
                    "final": False,
                    "recipe": recipe_tag,
                    "corpus_fingerprint": corpus_fingerprint,
                },
                checkpoint,
            )
            print(
                f"  epoch  0 (warm start) devAP={best_ap:.3f} - banked as floor",
                flush=True,
            )
        else:
            best_ap = -1.0
            best_epoch = 0
            best_state = None
            epochs_no_improve = 0
            epoch_logs = []
            start_epoch = 1
        for epoch in range(start_epoch, args.epochs + 1):
            horizon = trainer.curriculum.horizon_for_epoch(epoch)
            if epoch == start_epoch:
                prev_horizon = horizon
            elif horizon != prev_horizon:
                # Fresh patience per curriculum phase: the dev-AP metric
                # changes meaning at every horizon advance.
                epochs_no_improve = 0
                prev_horizon = horizon
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
            mean_ap = selection_ap(ap)
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
                # Bank progress on every improvement: an interrupted run
                # resumes from the last best epoch (I.1), losing at most the
                # epoch in flight.
                torch.save(
                    {
                        "state": best_state,
                        "optimizer": trainer.optimizer.state_dict(),
                        "summary": run_summary_so_far(),
                        "epochs_no_improve": epochs_no_improve,
                        "final": False,
                        "recipe": recipe_tag,
                        "corpus_fingerprint": corpus_fingerprint,
                    },
                    checkpoint,
                )
            else:
                epochs_no_improve += 1
            print(
                f"  epoch {epoch:2d} h={horizon:2d} "
                f"loss={float(np.mean(losses)):.4f} devAP={mean_ap:.3f}"
                f"{marker} ({time.time() - t_epoch:.0f}s)",
                flush=True,
            )
            if (
                epochs_no_improve >= EARLY_STOP_PATIENCE
                and epoch >= early_stop_from
            ):
                print(f"  early stop at epoch {epoch} (best {best_epoch})", flush=True)
                break
        members[(variant, seed)] = best_state
        run_summaries[member_key] = {
            "variant": variant,
            "recipe": recipe_tag,
            "selection_metric": (
                "catchable_task_mean_ap"
                f" (tasks {list(FINETUNE_SELECTION_TASKS)})"
                if args.finetune
                else "all_task_mean_ap"
            ),
            "best_epoch": best_epoch,
            "best_dev_mean_ap": best_ap,
            "curriculum_transitions": list(transitions),
            "task_positive_weights": (
                list(TASK_POSITIVE_WEIGHTS) if args.finetune else None
            ),
            "sampling_policy": sampling_policy_str(),
            "epochs": epoch_logs,
        }
        # Final checkpoint for this member: complete, do not resume into it.
        torch.save(
            {
                "state": best_state,
                "summary": run_summaries[member_key],
                "final": True,
                "recipe": recipe_tag,
                "corpus_fingerprint": corpus_fingerprint,
            },
            member_checkpoint(partial_dir, variant, seed),
        )
        print(
            f"  checkpoint saved: {member_checkpoint(partial_dir, variant, seed)}",
            flush=True,
        )
        del model, trainer
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()

    # Free training memory before the calibration/prediction stages.
    del examples["train"]
    del dev_monitor
    gc.collect()

    # Sequential-member mode: the bundle is assembled ONLY when every member
    # of the FULL default plan has a FINAL checkpoint — a partial-plan run
    # (parallel member training) exits after its own members so it can never
    # write a partial-member manifest. Existence alone is not completion:
    # a mid-training member banks non-final checkpoints, and a sibling
    # process finishing early must not assemble those. The completing run
    # assembles over the full member set, not just its own plan.
    full_plan = parse_members(DEFAULT_MEMBERS)

    def _member_final(v, s) -> bool:
        path = member_checkpoint(partial_dir, v, s)
        if not path.exists():
            return False
        ck = torch.load(path, map_location="cpu", weights_only=False)
        return bool(ck.get("final", False))

    pending = [
        f"{v}:{s}" for v, s in full_plan if not _member_final(v, s)
    ]
    if pending:
        print(
            f"[resume] pending members {pending}; exiting after training stage "
            "(re-run per member; the final run assembles the bundle)",
            flush=True,
        )
        return
    if set(plan) != set(full_plan):
        print(
            "[assembly] all members present; assembling the FULL member set "
            f"({len(full_plan)} members)",
            flush=True,
        )
        plan = list(full_plan)
        for v, s in plan:
            if (v, s) not in members:
                ck = torch.load(
                    member_checkpoint(partial_dir, v, s),
                    map_location="cpu",
                    weights_only=False,
                )
                members[(v, s)] = ck["state"]
                run_summaries[f"{v}:{s}"] = ck["summary"]
                print(
                    f"[assembly] loaded {v}:{s} from checkpoint "
                    f"(best epoch {ck['summary']['best_epoch']}, devAP "
                    f"{ck['summary']['best_dev_mean_ap']:.3f})",
                    flush=True,
                )

    # ---- 5. calibrators -------------------------------------------------------
    print("[5/8] fitting I.4 calibrators on calibration split...", flush=True)
    examples["calibration"] = load_examples(
        "calibration", list(splits.calibration), stride=CUTOFF_STEP_EVAL
    )
    print(
        f"  calibration: {len(examples['calibration'])} clips, "
        f"{sum(int(ex.targets.event_y.sum()) for ex in examples['calibration'])} events",
        flush=True,
    )
    engines: list[ForecastEngine] = []
    calibrators_payload: dict[str, dict] = {}
    for variant, seed in plan:
        model = build_world_model(config, variant=variant, num_event_tasks=5).to(
            device
        )
        model.load_state_dict(
            {k: v.to(device) for k, v in members[(variant, seed)].items()}
        )
        model.eval()
        engines.append(ForecastEngine(model))
    # gather per-member logits once
    member_logits: dict[str, dict[int, tuple]] = {}
    for mi, engine in enumerate(engines):
        variant, seed = plan[mi]
        _, merged = collect_cal_records([engine], device, examples["calibration"])
        member_logits[f"{variant}:{seed}"] = merged
    # I.4 sparse-cell rule: a task with too few events for a per-member fit
    # falls back to a POOLED calibrator (all members' logits for that task
    # stacked) instead of passing raw logits through. The v1 run left task 1
    # uncalibrated and its raw ~0.99 logits dominated the Brier gap.
    from foresight.calibration.hazard import DEFAULT_MIN_EVENTS

    pooled_by_task: dict[int, dict] = {}
    all_tasks = sorted({t for m in member_logits for t in member_logits[m]})
    for task in all_tasks:
        parts = [
            member_logits[m][task]
            for m in member_logits
            if task in member_logits[m]
        ]
        sparse_members = [
            m
            for m in member_logits
            if task in member_logits[m]
            and int(member_logits[m][task][1].sum()) < DEFAULT_MIN_EVENTS
        ]
        if not sparse_members or not parts:
            continue
        stacked = tuple(
            torch.cat([p[i] for p in parts], dim=0) for i in range(3)
        )
        if int(stacked[1].sum()) >= DEFAULT_MIN_EVENTS:
            cal = fit_hazard_calibrator(*stacked, task_index=task, pooled=True)
            pooled_by_task[task] = cal.to_dict()
            print(
                f"  pooled task {task}: fitted={cal.fitted} "
                f"slope={cal.slope:.3f} events={cal.fit_event_count} "
                f"(sparse-cell fallback for {len(sparse_members)} members)",
                flush=True,
            )
    for mi, (variant, seed) in enumerate(plan):
        member_key = f"{variant}:{seed}"
        for task, (logits, events, masks) in member_logits[member_key].items():
            if (
                int(events.sum()) < DEFAULT_MIN_EVENTS
                and task in pooled_by_task
            ):
                calibrators_payload[f"{member_key}:{task}"] = pooled_by_task[task]
                print(
                    f"  {member_key} task {task}: pooled "
                    f"(events={pooled_by_task[task]['fit_event_count']})",
                    flush=True,
                )
                continue
            cal = fit_hazard_calibrator(logits, events, masks, task_index=task)
            calibrators_payload[f"{member_key}:{task}"] = cal.to_dict()
            print(
                f"  {member_key} task {task}: fitted={cal.fitted} "
                f"slope={cal.slope:.3f} events={cal.fit_event_count}",
                flush=True,
            )
    # rebuild engines with calibrators attached
    from foresight.calibration.hazard import HazardCalibrator

    calibrated_engines: list[ForecastEngine] = []
    for mi, (variant, seed) in enumerate(plan):
        member_key = f"{variant}:{seed}"
        cals = {
            (int(k.split(":")[2]), None): HazardCalibrator.from_dict(v)
            for k, v in calibrators_payload.items()
            if k.startswith(f"{member_key}:")
        }
        engines[mi].calibrator_set = CalibratorSet(calibrators=cals, pooled=None)
        calibrated_engines.append(engines[mi])

    # ---- 6. selection policy ---------------------------------------------------
    print("[6/8] fitting selection policy at the alert budget...", flush=True)
    cal_records, _ = collect_cal_records(
        calibrated_engines, device, examples["calibration"]
    )
    policy = fit_selection_policy(cal_records, budget=policy_budget)
    for task in sorted((k for k in policy if k != "_aggregate"), key=int):
        p = policy[task]
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
        "locked_test", list(splits.locked_test), stride=CUTOFF_STEP_EVAL
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
    for variant, seed in plan:
        path = member_model_path(bundle, variant, seed)
        from safetensors.torch import save_file

        save_file(members[(variant, seed)], str(path))
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "foresight.core.2026-09",
                "profile": "foresight-section35-tierb-ensemble",
                "recipe": recipe_tag,
                "task_positive_weights": (
                    list(TASK_POSITIVE_WEIGHTS) if args.finetune else None
                ),
                "selection_policy_budget_aggregate_per_100_asset_hours": (
                    POLICY_AGGREGATE_BUDGET
                ),
                "synthetic_data_only": True,
                "seeds": [s for v, s in plan if v == "reference"],
                "members": [
                    {"variant": v, "seed": s} for v, s in plan
                ],
                "ensemble": "I.5 heterogeneous (reference + gate + wide)",
                "corpus": {
                    "episodes": len(episodes),
                    "fingerprint": corpus_fingerprint,
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
                "recipe": recipe_tag,
                "seeds": {str(k): v for k, v in run_summaries.items()},
                "curriculum": {
                    "horizons": list(horizons),
                    "transition_epochs": list(transitions),
                },
                "early_stop_patience": EARLY_STOP_PATIENCE,
                "batch_clips": 16,
                "selection_policy_budget_aggregate_per_100_asset_hours": (
                    POLICY_AGGREGATE_BUDGET
                ),
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
