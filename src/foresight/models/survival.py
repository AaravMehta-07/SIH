"""Discrete-time survival probability contract (Build Spec Section 12, I.5).

For endpoint e and event k, ``q[j]`` is the probability of the first qualifying
event in future bin j, conditional on no earlier occurrence in the episode and on
the eligible history at decision time. With 30-second bins:

    S[0] = 1
    event_mass[j] = S[j-1] * q[j]
    S[j] = S[j-1] * (1 - q[j])
    cumulative_risk[j] = 1 - S[j]        (nondecreasing, in [0, 1])
    no_event_mass = S[H]

Computation uses float64 log-survival sums with stable ``log1p`` (Section 12).
Cumulative risk is monotone by construction; different event types need not sum
to one. ETA is derived from event-time mass and is never an independent head
(Section 12, I.5). Golden values are pinned by tests from Section 35 golden
example 1 and Appendix R.2.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor

from .types import ContractError

DEFAULT_BIN_SECONDS = 30


@dataclass
class EventDistribution:
    """First-event distribution over ``H`` future bins."""

    hazards: Tensor  # float64 [H]
    event_mass: Tensor  # float64 [H]
    cumulative_risk: Tensor  # float64 [H]
    no_event_mass: Tensor  # float64 scalar
    bin_seconds: int

    @property
    def horizon_bins(self) -> int:
        return int(self.hazards.shape[0])


def hazards_from_logits(logits: Tensor) -> Tensor:
    """Sigmoid probability readout (Section 13): applied at readout only."""
    return torch.sigmoid(logits.to(torch.float64))


def distribution_from_hazards(
    hazards: Tensor, bin_seconds: int = DEFAULT_BIN_SECONDS
) -> EventDistribution:
    """Build the event-time distribution from per-bin hazards.

    Accepts float tensors of shape ``[...]`` (a leading batch/entity dimension is
    preserved). All outputs share the input's leading shape.
    """
    if bin_seconds <= 0:
        raise ContractError("bin_seconds must be positive")
    q = hazards.to(torch.float64)
    if bool((q < 0).any()) or bool((q > 1).any()):
        raise ContractError("hazards must lie in [0, 1]")

    # log S[j] = sum_{k<=j} log(1 - q[k]); log1p(-q) is stable for small q and
    # yields -inf exactly when q == 1 (event certain in that bin).
    log_survival = torch.cumsum(torch.log1p(-q), dim=-1)
    survival = torch.exp(log_survival)  # [H]
    ones = torch.ones_like(q[..., :1])
    survival_prev = torch.cat([ones, survival[..., :-1]], dim=-1)  # S[0..H-1]
    event_mass = survival_prev * q
    cumulative_risk = 1.0 - survival
    no_event_mass = survival[..., -1]
    return EventDistribution(
        hazards=q,
        event_mass=event_mass,
        cumulative_risk=cumulative_risk,
        no_event_mass=no_event_mass,
        bin_seconds=bin_seconds,
    )


@dataclass
class ConditionalETA:
    """Conditional event-time summary (Section 12, I.5).

    All values are conditioned on occurrence within the supported horizon and are
    reported together with that occurrence probability. Bin resolution is explicit:
    the median is a bin boundary, not a falsely precise timestamp (D.7).
    """

    median_bin: int  # 1-indexed future bin
    median_seconds: int  # end-of-bin boundary, seconds after cutoff
    occurrence_probability: float  # cumulative risk within the horizon
    bin_seconds: int
    lower_quantile_bin: int | None = None
    upper_quantile_bin: int | None = None


def conditional_eta(
    distribution: EventDistribution,
    *,
    min_occurrence_probability: float,
    lower_quantile: float | None = None,
    upper_quantile: float | None = None,
) -> ConditionalETA | None:
    """Conditional median (and optional quantiles) given occurrence within the
    horizon (I.5), or ``None`` when occurrence probability is insufficient under
    the frozen display policy — the countdown is then withheld, not invented."""
    if distribution.hazards.dim() != 1:
        raise ContractError("conditional_eta expects a single [H] distribution")
    occurrence = float(distribution.cumulative_risk[-1])
    if occurrence < min_occurrence_probability or occurrence <= 0.0:
        return None

    conditional_cumulative = (
        distribution.cumulative_risk / occurrence
    )  # F[j] / F[H]

    def _first_bin_reaching(p: float) -> int:
        # The last conditional value is exactly 1.0, so a crossing always exists.
        reached = (conditional_cumulative >= p).nonzero()
        return int(reached[0, 0]) + 1  # 1-indexed

    median_bin = _first_bin_reaching(0.5)
    lower_bin = _first_bin_reaching(lower_quantile) if lower_quantile else None
    upper_bin = _first_bin_reaching(upper_quantile) if upper_quantile else None
    return ConditionalETA(
        median_bin=median_bin,
        median_seconds=median_bin * distribution.bin_seconds,
        occurrence_probability=occurrence,
        bin_seconds=distribution.bin_seconds,
        lower_quantile_bin=lower_bin,
        upper_quantile_bin=upper_bin,
    )


def mixture_from_distributions(
    distributions: list[EventDistribution],
) -> EventDistribution:
    """Average member event-time distributions, then derive mixture hazards.

    I.5: average each member's cumulative distribution — do not multiply or
    average hazards and call it the same mixture (CA03). Mixture hazards are
    recovered as ``p_mix[j] / S_mix[j-1]`` where the denominator is positive.
    """
    if not distributions:
        raise ContractError("mixture needs at least one distribution")
    h = distributions[0].horizon_bins
    bin_seconds = distributions[0].bin_seconds
    if any(d.horizon_bins != h for d in distributions):
        raise ContractError("mixture members must share the horizon length")
    if any(d.bin_seconds != bin_seconds for d in distributions):
        raise ContractError("mixture members must share the bin size")

    event_mass = torch.stack([d.event_mass for d in distributions]).mean(dim=0)
    no_event_mass = torch.stack(
        [d.no_event_mass for d in distributions]
    ).mean(dim=0)

    # S_mix[j-1] = 1 - sum_{k<j} event_mass[k]
    cumulative_mass = torch.cumsum(event_mass, dim=-1)
    survival_prev = torch.cat(
        [torch.ones(1, dtype=event_mass.dtype), 1.0 - cumulative_mass[:-1]]
    )
    hazards = torch.where(
        survival_prev > 0,
        event_mass / survival_prev.clamp_min(torch.finfo(torch.float64).tiny),
        torch.zeros_like(event_mass),
    )
    # The mixture CDF is the averaged cumulative distribution by construction.
    cumulative_risk = torch.cumsum(event_mass, dim=-1)
    return EventDistribution(
        hazards=hazards,
        event_mass=event_mass,
        cumulative_risk=cumulative_risk,
        no_event_mass=no_event_mass,
        bin_seconds=bin_seconds,
    )
