"""FORESIGHT entity-conditioned graph-temporal world model.

Implements the interface contract of Build Spec Appendix H.1:

    encode_graph(graph_batch) -> Tensor
    observe_window(state, graph_window) -> WorldState
    transition_prior(state) -> WorldState
    decode_state(state, candidate_pairs, task_mask) -> DecodedStep
    roll_out(observed_state, horizon_bins, candidates) -> list[DecodedStep]

Structure (Sections 13-14, H.2-H.4, ADR-001):
    node 88 / edge 22 -> directed GAT 88->128->128->64
    -> per-entity GRUCell(64, 64) identity-linked memory
    -> masked mean+max pool 128 || global adapter 24 -> global LSTM(152, 128, 2 layers)
    state z = (R, h, c, g); endpoint readout width 192; edge readout width 256.

Observation order per window (H.1): entity memories, global adapter, global
recurrent state. Rollout clones the observed state and consults no future
telemetry (Section 26; MO03/MO04). Non-finite states raise instead of producing
zero forecasts (H.5; MO05).
"""

from __future__ import annotations

import torch
from torch import Tensor, nn

from .config import CoreConfig, FeatureDimensions, ModelDimensions
from .decoders import GlobalObservationDecoder, NodeObservationDecoder
from .global_adapter import GlobalAdapter
from .graph_encoder import DirectedGraphEncoder
from .heads import EdgeHead, HazardHead, TacticHead
from .transition import TransitionPrior, masked_mean_max_pool
from .types import (
    CandidatePairs,
    ContractError,
    DecodedStep,
    GraphWindowBatch,
    WorldState,
)

#: Default J for the SIH five-target projection (first observed malicious endpoint
#: contact, initial access, lateral movement, C2, exfiltration — Section 11).
#: The qualified task manifest governs the real J at runtime.
DEFAULT_NUM_EVENT_TASKS = 5


class ForesightWorldModel(nn.Module):
    def __init__(
        self,
        features: FeatureDimensions,
        model: ModelDimensions,
        *,
        num_event_tasks: int = DEFAULT_NUM_EVENT_TASKS,
    ) -> None:
        super().__init__()
        if num_event_tasks < 1:
            raise ContractError("num_event_tasks must be >= 1")
        self.features = features
        self.model = model
        self.num_event_tasks = num_event_tasks

        self.graph_encoder = DirectedGraphEncoder(
            features.node_input,
            features.edge_input,
            attention_dropout=model.attention_dropout,
            graph_norm_eps=model.graph_norm_eps,
        )
        self.entity_gru = nn.GRUCell(
            input_size=model.entity_gru_hidden,
            hidden_size=model.entity_gru_hidden,
        )
        self.global_adapter = GlobalAdapter(
            features.global_input, features.global_adapter_output
        )
        self.global_lstm = nn.LSTM(
            input_size=model.global_lstm_input,
            hidden_size=model.global_lstm_hidden,
            num_layers=model.global_lstm_layers,
        )
        self.prior = TransitionPrior(
            entity_dim=model.entity_embedding,
            global_hidden=model.global_lstm_hidden,
            global_context_dim=features.global_adapter_output,
        )
        self.hazard_head = HazardHead(
            model.endpoint_head_input, 64, num_event_tasks
        )
        self.tactic_head = TacticHead(
            model.endpoint_head_input, 64, model.num_tactic_tags
        )
        self.edge_head = EdgeHead(model.edge_head_input, 64)
        self.node_decoder = NodeObservationDecoder(
            model.endpoint_head_input,
            128,
            features.node_values,
            log_scale_min=model.log_scale_min,
            log_scale_max=model.log_scale_max,
        )
        self.global_decoder = GlobalObservationDecoder(
            model.global_lstm_hidden,
            64,
            features.global_values,
            log_scale_min=model.log_scale_min,
            log_scale_max=model.log_scale_max,
        )

    @classmethod
    def from_config(
        cls,
        config: CoreConfig,
        *,
        num_event_tasks: int = DEFAULT_NUM_EVENT_TASKS,
    ) -> "ForesightWorldModel":
        return cls(config.features, config.model, num_event_tasks=num_event_tasks)

    # ------------------------------------------------------------------
    # H.1 interface
    # ------------------------------------------------------------------

    def zero_state(self, node_present: Tensor) -> WorldState:
        """Documented zero state for a scope (Section 26)."""
        return WorldState.zeros(
            node_present,
            entity_embedding=self.model.entity_embedding,
            lstm_hidden=self.model.global_lstm_hidden,
            lstm_layers=self.model.global_lstm_layers,
            global_adapter_output=self.features.global_adapter_output,
        )

    def observe_window(self, state: WorldState, window: GraphWindowBatch) -> WorldState:
        """Absorb one observed window into the state (H.1 order: entity memories,
        global adapter, global recurrent state)."""
        window.validate()
        if not torch.equal(state.node_present, window.node_present):
            raise ContractError(
                "node_present must be the stable clip entity union in every window "
                "(G.2); observe_window received an inconsistent scope"
            )
        state.validate_finite()

        b, n = window.node_present.shape
        d = self.model.entity_embedding

        # 1. Entity memories: encode real nodes, scatter to padded slots, GRU update.
        u = self.graph_encoder(
            window.x, window.edge_index, window.edge_attr, window.batch
        )  # [T, 64]
        u_padded = u.new_zeros(b, n, d)
        u_padded[window.batch, window.slot_index] = u
        r_flat = state.entity_memory.reshape(b * n, d)
        u_flat = u_padded.reshape(b * n, d)
        r_updated = self.entity_gru(u_flat, r_flat)
        # ADR-001: present healthy idle entities update; unobserved entities keep
        # their memory for this window (G.2).
        update_mask = (window.node_present & window.node_observation_valid).reshape(
            b * n, 1
        )
        r_new = torch.where(update_mask, r_updated, r_flat).reshape(b, n, d)

        # 2. Global adapter.
        g_new = self.global_adapter(window.global_raw)  # [B, 24]

        # 3. Global recurrent state from pooled entity memories + adapted context.
        pooled = masked_mean_max_pool(r_new, window.node_present)  # [B, 128]
        lstm_input = torch.cat([pooled, g_new], dim=-1)  # [B, 152]
        _, (h_new, c_new) = self.global_lstm(
            lstm_input.unsqueeze(0), (state.global_h, state.global_c)
        )

        return WorldState(r_new, h_new, c_new, g_new, window.node_present)

    def transition_prior(self, state: WorldState) -> WorldState:
        """One imagined latent transition; no future telemetry is consulted (MO03)."""
        state.validate_finite()
        entity_next, global_next, lstm_input = self.prior(state)
        _, (h_next, c_next) = self.global_lstm(
            lstm_input.unsqueeze(0), (state.global_h, state.global_c)
        )
        return WorldState(
            entity_next, h_next, c_next, global_next, state.node_present
        )

    def decode_state(
        self,
        state: WorldState,
        candidate_pairs: CandidatePairs | None = None,
        task_mask: Tensor | None = None,
    ) -> DecodedStep:
        """Read observables, hazards, tactic tags and candidate edges from a state.

        ``task_mask`` (bool ``[J]``) marks manifest-supported event tasks; it is
        carried on the output so unsupported dimensions stay masked at loss and
        publication (H.2), while raw logits remain available as diagnostics.
        """
        state.validate_finite()
        if task_mask is not None and (
            task_mask.dtype != torch.bool
            or task_mask.shape != (self.num_event_tasks,)
        ):
            raise ContractError(
                f"task_mask must be bool [{self.num_event_tasks}]"
            )

        b, n, _ = state.entity_memory.shape
        h_top = state.global_h[-1]  # [B, 128]
        endpoint = torch.cat(
            [
                state.entity_memory,
                h_top.unsqueeze(1).expand(b, n, self.model.global_lstm_hidden),
            ],
            dim=-1,
        )  # [B, N, 192]

        node_mean, node_log_scale = self.node_decoder(endpoint)
        hazard_logits = self.hazard_head(endpoint)
        tactic_logits = self.tactic_head(endpoint)
        global_mean, global_log_scale = self.global_decoder(h_top)

        edge_logits = None
        if candidate_pairs is not None:
            candidate_pairs.validate(
                batch_size=b, num_slots=n
            )
            src = state.entity_memory[
                candidate_pairs.batch_index, candidate_pairs.source
            ]
            tgt = state.entity_memory[
                candidate_pairs.batch_index, candidate_pairs.target
            ]
            gh = h_top[candidate_pairs.batch_index]
            edge_logits = self.edge_head(torch.cat([src, tgt, gh], dim=-1))

        return DecodedStep(
            node_mean=node_mean,
            node_log_scale=node_log_scale,
            global_mean=global_mean,
            global_log_scale=global_log_scale,
            hazard_logits=hazard_logits,
            tactic_logits=tactic_logits,
            edge_logits=edge_logits,
            hazard_task_mask=task_mask,
        )

    def roll_out(
        self,
        observed_state: WorldState,
        horizon_bins: int,
        candidate_pairs: CandidatePairs | None = None,
        task_mask: Tensor | None = None,
    ) -> list[DecodedStep]:
        """Free rollout from a copied state (Section 26, H.4).

        The observed state is cloned and never mutated (MO04); imagined memory is
        never committed as observed live memory. ``outputs[i]`` (0-indexed) is bin
        ``i+1``: the state after transition ``j`` represents bin ``j`` (Section 14).
        """
        if horizon_bins < 1:
            raise ContractError("horizon_bins must be >= 1")
        z = observed_state.clone()
        outputs: list[DecodedStep] = []
        for _ in range(horizon_bins):
            z = self.transition_prior(z)
            outputs.append(self.decode_state(z, candidate_pairs, task_mask))
        return outputs

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def observe_clip(
        self, windows: list[GraphWindowBatch]
    ) -> WorldState:
        """Recompute the observed state from a bounded clip starting at the zero
        state (H.4) — training and serving share this exact context rule."""
        if not windows:
            raise ContractError("a clip needs at least one window")
        state = self.zero_state(windows[0].node_present)
        for window in windows:
            state = self.observe_window(state, window)
        return state
