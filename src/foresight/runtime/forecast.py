"""Runtime forecast engine (Build Spec Section 26, Appendices D.7, I.5, S).

Implements the model-side core of the Section-26 inference algorithm:

    clip of observed windows -> zero state -> observe loop -> freeze
    -> copy state -> rollout loop -> per-bin hazards -> calibrate
    -> survival transform -> conditional ETA -> typed result.

The rollout only ever sees a copied state (MO04) and consults no future
telemetry (MO03). Trust gating, novelty, evidence assembly, ledger commit and
publishing are later pipeline stages owned by other modules; this engine
reports them as ``omitted`` rather than faking them.

Ensemble forecasts (I.5) average the member *calibrated event-time
distributions* — never the raw logits — and label member spread
``model_disagreement``, which is not evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor

from ..calibration.hazard import CalibratorSet
from ..models.survival import (
    ConditionalETA,
    EventDistribution,
    conditional_eta,
    distribution_from_hazards,
    hazards_from_logits,
    mixture_from_distributions,
)
from ..models.types import (
    CandidatePairs,
    ContractError,
    GraphWindowBatch,
)
from ..models.world_model import ForesightWorldModel

#: ADR-001: countdowns are displayed only when the calibrated occurrence
#: probability reaches this threshold (must stay <= 0.496 so the Section-35
#: golden example reports its ETA; Build Spec Appendix T.1).
DEFAULT_DISPLAY_ETA_THRESHOLD = 0.30

TASK_SUPPORTED = "supported"
TASK_NOT_SUPPORTED = "not_supported"

#: Engine-scope disclosure: these pipeline stages are owned by later modules
#: and attach their own typed fields in the same request (Section 26 steps
#: 9-14); the engine itself never fakes them.
OMITTED_STAGES = (
    "trust: TrustContract gating owned by the trust stage",
    "novelty: SENTINEL novelty owned by the sentinel stage",
    "evidence: evidence assembly and hashing owned by the evidence stage",
    "ledger: compute ledger commit owned by the storage stage",
    "publish: publication owned by the api stage",
)


def _validate_distribution(d: EventDistribution) -> None:
    """D.7: monotone cumulative risk and probability conservation are verified
    before a distribution leaves the model boundary."""
    cum = d.cumulative_risk.to(torch.float64)
    if bool((cum[1:] - cum[:-1] < -1e-12).any()):
        raise ContractError("cumulative risk must be nondecreasing")
    total = float(d.event_mass.to(torch.float64).sum()) + float(
        d.no_event_mass.to(torch.float64)
    )
    if abs(total - 1.0) > 1e-9:
        raise ContractError(
            f"probability mass must be conserved, got {total}"
        )
    if bool((cum < -1e-12).any()) or bool((cum > 1 + 1e-12).any()):
        raise ContractError("cumulative risk must stay within [0, 1]")


@dataclass(frozen=True)
class ForecastRequest:
    horizon_bins: int
    bin_seconds: int
    task_mask: Tensor | None
    min_occurrence_probability: float
    published_horizons_seconds: tuple[int, ...]
    candidate_pairs: CandidatePairs | None = None

    @classmethod
    def from_config(cls, config, candidate_pairs: CandidatePairs | None = None) -> "ForecastRequest":
        d = config.data
        bin_seconds = int(d["window_seconds"])
        return cls(
            horizon_bins=int(d["modeled_horizon_bins"]),
            bin_seconds=bin_seconds,
            task_mask=None,
            min_occurrence_probability=DEFAULT_DISPLAY_ETA_THRESHOLD,
            published_horizons_seconds=tuple(
                int(b) * bin_seconds for b in d["evaluated_horizon_bins"]
            ),
            candidate_pairs=candidate_pairs,
        )


@dataclass
class TaskForecast:
    """D.7 task output (model-side fields; evidence/ledger fields are added by
    the runtime record assembly stage)."""

    task_index: int
    status: str
    calibration_status: str
    distribution: EventDistribution | None = None
    conditional_eta: ConditionalETA | None = None
    eta_withheld_reason: str | None = None


@dataclass
class EntityForecast:
    slot: int
    task_forecasts: list[TaskForecast]


@dataclass
class ForecastResult:
    horizon_bins: int
    bin_seconds: int
    published_horizons_seconds: tuple[int, ...]
    entities: list[EntityForecast]
    node_mean: Tensor  # [H, N, 44]
    node_log_scale: Tensor  # [H, N, 44]
    global_mean: Tensor  # [H, 24]
    global_log_scale: Tensor  # [H, 24]
    tactic_logits: Tensor  # [H, N, 5]
    edge_logits: Tensor | None  # [H, E]
    model_disagreement: dict[tuple[int, int], float] | None = None
    omitted: tuple[str, ...] = OMITTED_STAGES


class ForecastEngine:
    """Single-model Section-26 inference core."""

    def __init__(
        self,
        model: ForesightWorldModel,
        calibrator_set: CalibratorSet | None = None,
    ) -> None:
        self.model = model
        self.calibrator_set = calibrator_set
        self.model.eval()

    @torch.no_grad()
    def forecast(
        self, windows: list[GraphWindowBatch], request: ForecastRequest
    ) -> ForecastResult:
        if not windows:
            raise ContractError("a forecast needs at least one observed window")
        if request.horizon_bins < 1:
            raise ContractError("horizon_bins must be >= 1")

        task_mask = request.task_mask
        if task_mask is None:
            task_mask = torch.ones(
                self.model.num_event_tasks, dtype=torch.bool
            )
        elif task_mask.shape != (self.model.num_event_tasks,) or (
            task_mask.dtype != torch.bool
        ):
            raise ContractError(
                f"task_mask must be bool [{self.model.num_event_tasks}]"
            )

        # Steps 2-4: zero state, observe loop, freeze.
        observed = self.model.observe_clip(windows)
        # Steps 5-6: rollout from a copied state only.
        outputs = self.model.roll_out(
            observed,
            request.horizon_bins,
            candidate_pairs=request.candidate_pairs,
            task_mask=task_mask,
        )

        n = observed.entity_memory.shape[1]
        entities: list[EntityForecast] = []
        for slot in range(n):
            if not bool(observed.node_present[0, slot]):
                continue  # padding slots carry no entity (G.2)
            task_forecasts: list[TaskForecast] = []
            for t in range(self.model.num_event_tasks):
                if not bool(task_mask[t]):
                    task_forecasts.append(
                        TaskForecast(
                            task_index=t,
                            status=TASK_NOT_SUPPORTED,
                            calibration_status="not_applicable",
                            eta_withheld_reason="task not qualified in manifest",
                        )
                    )
                    continue
                logits = torch.stack(
                    [outputs[j].hazard_logits[0, slot, t] for j in range(request.horizon_bins)]
                )
                # Steps 7-8: calibrate raw logits, then derive survival.
                if self.calibrator_set is not None:
                    calibrated, cal_status = self.calibrator_set.calibrate(
                        logits, t
                    )
                else:
                    calibrated, cal_status = logits, "uncalibrated"
                hazards = hazards_from_logits(
                    calibrated.to(torch.float64)
                )
                dist = distribution_from_hazards(
                    hazards, bin_seconds=request.bin_seconds
                )
                _validate_distribution(dist)
                eta = conditional_eta(
                    dist,
                    min_occurrence_probability=(
                        request.min_occurrence_probability
                    ),
                )
                if eta is None:
                    occurrence = float(dist.cumulative_risk[-1])
                    reason = (
                        "zero occurrence probability"
                        if occurrence == 0.0
                        else (
                            f"occurrence probability {occurrence:.3f} below "
                            f"display threshold "
                            f"{request.min_occurrence_probability}"
                        )
                    )
                else:
                    reason = None
                task_forecasts.append(
                    TaskForecast(
                        task_index=t,
                        status=TASK_SUPPORTED,
                        calibration_status=cal_status,
                        distribution=dist,
                        conditional_eta=eta,
                        eta_withheld_reason=reason,
                    )
                )
            entities.append(EntityForecast(slot=slot, task_forecasts=task_forecasts))

        first = outputs[0]
        return ForecastResult(
            horizon_bins=request.horizon_bins,
            bin_seconds=request.bin_seconds,
            published_horizons_seconds=request.published_horizons_seconds,
            entities=entities,
            node_mean=torch.stack([o.node_mean for o in outputs], dim=0)[:, 0],
            node_log_scale=torch.stack([o.node_log_scale for o in outputs], dim=0)[:, 0],
            global_mean=torch.stack([o.global_mean for o in outputs], dim=0)[:, 0],
            global_log_scale=torch.stack([o.global_log_scale for o in outputs], dim=0)[:, 0],
            tactic_logits=torch.stack([o.tactic_logits for o in outputs], dim=0)[:, 0],
            edge_logits=(
                torch.stack([o.edge_logits for o in outputs], dim=0)
                if first.edge_logits is not None
                else None
            ),
        )


class EnsembleForecaster:
    """I.5 ensemble: average member calibrated event-time distributions."""

    def __init__(self, engines: list[ForecastEngine]) -> None:
        if len(engines) < 2:
            raise ContractError("an ensemble needs at least two members")
        self.engines = engines

    @torch.no_grad()
    def forecast(
        self, windows: list[GraphWindowBatch], request: ForecastRequest
    ) -> ForecastResult:
        members = [e.forecast(windows, request) for e in self.engines]
        base = members[0]
        num_tasks = len(base.entities[0].task_forecasts)

        entities: list[EntityForecast] = []
        disagreement: dict[tuple[int, int], float] = {}
        for entity in base.entities:
            task_forecasts: list[TaskForecast] = []
            for tf in entity.task_forecasts:
                if tf.status != TASK_SUPPORTED:
                    task_forecasts.append(tf)
                    continue
                member_dists = [
                    m.entities[entity.slot].task_forecasts[tf.task_index].distribution
                    for m in members
                ]
                member_dists = [d for d in member_dists if d is not None]
                if not member_dists:
                    task_forecasts.append(tf)
                    continue
                # I.5: average the calibrated distributions, not the logits.
                mixture = mixture_from_distributions(member_dists)
                _validate_distribution(mixture)
                eta = conditional_eta(
                    mixture,
                    min_occurrence_probability=request.min_occurrence_probability,
                )
                occurrences = [
                    float(d.cumulative_risk[-1]) for d in member_dists
                ]
                if max(occurrences) == min(occurrences):
                    spread = 0.0  # exact-equality shortcut: the float mean of
                    # identical values differs by an ulp, which would fake a
                    # ~1e-16 disagreement for identical members
                else:
                    mean_occ = sum(occurrences) / len(occurrences)
                    spread = math.sqrt(
                        sum((o - mean_occ) ** 2 for o in occurrences)
                        / len(occurrences)
                    )
                disagreement[(entity.slot, tf.task_index)] = spread
                task_forecasts.append(
                    TaskForecast(
                        task_index=tf.task_index,
                        status=TASK_SUPPORTED,
                        calibration_status=tf.calibration_status,
                        distribution=mixture,
                        conditional_eta=eta,
                        eta_withheld_reason=(
                            None
                            if eta is not None
                            else "occurrence probability below display threshold"
                        ),
                    )
                )
            entities.append(EntityForecast(slot=entity.slot, task_forecasts=task_forecasts))

        # Moment-matched mixture of the member Gaussian observables: the
        # mixture mean is the average of member means; the mixture variance is
        # E[var] + Var[mean].
        def mix_gaussian(means: Tensor, log_scales: Tensor) -> tuple[Tensor, Tensor]:
            stacked_means = torch.stack(means, dim=0)  # [M, ...]
            stacked_vars = torch.exp(2.0 * torch.stack(log_scales, dim=0))
            mean_mix = stacked_means.mean(dim=0)
            var_mix = stacked_vars.mean(dim=0) + stacked_means.var(dim=0, unbiased=False)
            return mean_mix, 0.5 * torch.log(var_mix.clamp(min=1e-12))

        node_mean, node_log_scale = mix_gaussian(
            [m.node_mean for m in members], [m.node_log_scale for m in members]
        )
        global_mean, global_log_scale = mix_gaussian(
            [m.global_mean for m in members],
            [m.global_log_scale for m in members],
        )

        return ForecastResult(
            horizon_bins=base.horizon_bins,
            bin_seconds=base.bin_seconds,
            published_horizons_seconds=base.published_horizons_seconds,
            entities=entities,
            node_mean=node_mean,
            node_log_scale=node_log_scale,
            global_mean=global_mean,
            global_log_scale=global_log_scale,
            tactic_logits=torch.stack(
                [m.tactic_logits for m in members], dim=0
            ).mean(dim=0),
            edge_logits=(
                torch.stack([m.edge_logits for m in members], dim=0).mean(dim=0)
                if base.edge_logits is not None
                else None
            ),
            model_disagreement=disagreement,
        )
