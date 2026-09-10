"""Core world model and integration (Build Spec Sections 13-15, 25-26, 35;
Appendices H, I, S, T).

Public interface (Appendix H.1):
    ForesightWorldModel.observe_window / transition_prior / decode_state / roll_out
    WorldState, GraphWindowBatch, CandidatePairs, DecodedStep

Probability contract (Section 12, Appendix I.5):
    distribution_from_hazards, conditional_eta, mixture_from_distributions
"""

from .config import (
    ConfigError,
    CoreConfig,
    FeatureDimensions,
    ModelDimensions,
    load_core_config,
)
from .decoders import GlobalObservationDecoder, NodeObservationDecoder
from .global_adapter import GlobalAdapter
from .graph_encoder import DirectedGraphEncoder
from .heads import EdgeHead, HazardHead, TacticHead
from .survival import (
    ConditionalETA,
    EventDistribution,
    conditional_eta,
    distribution_from_hazards,
    hazards_from_logits,
    mixture_from_distributions,
)
from .transition import TransitionPrior, masked_mean_max_pool
from .types import (
    CandidatePairs,
    ContractError,
    DecodedStep,
    GraphWindowBatch,
    NonFiniteTensorError,
    WorldState,
)
from .world_model import DEFAULT_NUM_EVENT_TASKS, ForesightWorldModel

__all__ = [
    "ConfigError",
    "CoreConfig",
    "FeatureDimensions",
    "ModelDimensions",
    "load_core_config",
    "DirectedGraphEncoder",
    "GlobalAdapter",
    "HazardHead",
    "TacticHead",
    "EdgeHead",
    "NodeObservationDecoder",
    "GlobalObservationDecoder",
    "TransitionPrior",
    "masked_mean_max_pool",
    "ForesightWorldModel",
    "DEFAULT_NUM_EVENT_TASKS",
    "WorldState",
    "GraphWindowBatch",
    "CandidatePairs",
    "DecodedStep",
    "ContractError",
    "NonFiniteTensorError",
    "EventDistribution",
    "ConditionalETA",
    "distribution_from_hazards",
    "hazards_from_logits",
    "conditional_eta",
    "mixture_from_distributions",
]
