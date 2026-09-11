"""Next-mark decoder (Build Spec Section 20, N.2).

A mark is ``(event_type, source, target, time_bin)``. The decoder conditions
on the observed world state (entity memories + global context from the
reference world model) and previously generated marks through a GRU:

    P(mark_l | H_d, mark_1..mark_{l-1})
      = softmax over [candidate marks] + [STOP] + [OUTSIDE]

The option score is a conditional factorization (pair | state, history) +
(type | pair, state, history) + (time bin | state, history) — each factor
sees the GRU hidden state, so the product stays a proper autoregressive
conditional per step. Teacher forcing trains the next observed mark; free
generation feeds predicted marks back (beam.py).

External endpoints (outside the internal scope slots) use a learned bucket
embedding; internal slots read their state-conditioned entity memory rows.
"""

from __future__ import annotations

import torch
from torch import Tensor, nn

from .candidates import BOS, OUTSIDE, PATH_TIME_BINS, STOP

NUM_TASKS = 5
TYPE_VOCAB = NUM_TASKS + 3  # tasks + BOS + STOP + OUTSIDE
EXT_BUCKETS = 16

class NextMarkDecoder(nn.Module):
    def __init__(
        self,
        *,
        entity_dim: int = 64,
        global_ctx_dim: int = 24,
        hidden: int = 128,
        embed: int = 32,
    ) -> None:
        super().__init__()
        self.entity_dim = entity_dim
        self.hidden = hidden
        self.ext_embed = nn.Embedding(EXT_BUCKETS, entity_dim)
        self.type_embed = nn.Embedding(TYPE_VOCAB, embed)
        self.bin_embed = nn.Embedding(PATH_TIME_BINS, embed)
        self.init_state = nn.Sequential(
            nn.Linear(entity_dim + global_ctx_dim, hidden), nn.Tanh()
        )
        # previous-mark input: type embedding + pair vectors + time bin
        self.mark_input = nn.Linear(embed + 2 * entity_dim + embed, hidden)
        self.cell = nn.GRUCell(hidden, hidden)
        # factor scorers
        self.pair_scorer = nn.Sequential(
            nn.Linear(hidden + entity_dim, 64), nn.ELU(), nn.Linear(64, 1)
        )
        self.type_scorer = nn.Sequential(
            nn.Linear(hidden + entity_dim + embed, 64), nn.ELU(), nn.Linear(64, 1)
        )
        self.bin_scorer = nn.Sequential(
            nn.Linear(2 * hidden, 32), nn.ELU(), nn.Linear(32, PATH_TIME_BINS)
        )
        self.stop_scorer = nn.Sequential(
            nn.Linear(hidden + embed, 32), nn.ELU(), nn.Linear(32, 1)
        )
        self.outside_scorer = nn.Sequential(
            nn.Linear(hidden + embed, 32), nn.ELU(), nn.Linear(32, 1)
        )

    # ------------------------------------------------------------------
    def initial_hidden(
        self, entity_memory: Tensor, global_context: Tensor
    ) -> Tensor:
        """[B, H] from mean-pooled entity memory + global context."""
        pooled = entity_memory.mean(dim=1)  # [B, 64]
        return self.init_state(torch.cat([pooled, global_context], dim=-1))

    def node_vectors(
        self, entity_memory: Tensor, ext_bucket: Tensor
    ) -> Tensor:
        """[B, N_total, 64]: state-conditioned internal rows + learned
        external bucket embeddings."""
        ext = self.ext_embed(ext_bucket)  # [E, 64]
        return torch.cat(
            [entity_memory, ext.unsqueeze(0).expand(entity_memory.shape[0], -1, -1)],
            dim=1,
        )

    def _gather(self, node_vecs: Tensor, idx: Tensor) -> Tensor:
        """Rows for node indices; -1 yields zeros (special marks)."""
        out = torch.zeros(
            (idx.shape[0], self.entity_dim), device=node_vecs.device,
            dtype=node_vecs.dtype,
        )
        valid = idx >= 0
        if bool(valid.any()):
            out[valid] = node_vecs[valid.nonzero(as_tuple=True)[0], idx[valid]]
        return out

    def mark_embedding(
        self,
        node_vecs: Tensor,
        type_idx: Tensor,
        src: Tensor,
        tgt: Tensor,
        bin_idx: Tensor,
    ) -> Tensor:
        """Input embedding for one previous mark ([B, H]). Negative node
        indices and time bins (special marks) contribute zero vectors."""
        src_v = self._gather(node_vecs, src)
        tgt_v = self._gather(node_vecs, tgt)
        t_e = self.type_embed(type_idx.clamp(min=0))
        b_e = self.bin_embed(bin_idx.clamp(min=0))
        b_e = torch.where(
            (bin_idx >= 0).unsqueeze(-1),
            b_e,
            torch.zeros_like(b_e),
        )
        return self.mark_input(torch.cat([t_e, src_v, tgt_v, b_e], dim=-1))

    # ------------------------------------------------------------------
    def score_options(
        self,
        h: Tensor,
        node_vecs: Tensor,
        pair_src: Tensor,
        pair_tgt: Tensor,
        prev_embedding: Tensor,
        *,
        pair_mask: Tensor | None = None,
        type_mask: Tensor | None = None,
    ) -> Tensor:
        """Joint log-probabilities over [P*T*Bins candidates, STOP, OUTSIDE].

        h: [B, H]; node_vecs: [B, N, 64]; pair_src/pair_tgt: [P] node indices;
        prev_embedding: [B, H] embedding of the previous mark (for the time
        factor). ``pair_mask`` [P] masks padded pairs; ``type_mask`` [T] is
        the allowed-type mask (Section 20).
        """
        bsz, pairs = h.shape[0], pair_src.shape[0]
        src_v = node_vecs[:, pair_src.clamp(min=0)]  # [B, P, 64]
        tgt_v = node_vecs[:, pair_tgt.clamp(min=0)]
        pair_vec = src_v + tgt_v                     # [B, P, 64]

        h_exp = h.unsqueeze(1).expand(bsz, pairs, h.shape[-1])
        pair_logits = self.pair_scorer(
            torch.cat([h_exp, pair_vec], dim=-1)
        ).squeeze(-1)                                # [B, P]

        types = torch.arange(NUM_TASKS, device=h.device)
        t_e = self.type_embed(types)                 # [T, E]
        type_in = torch.cat(
            [
                h_exp.unsqueeze(2).expand(bsz, pairs, NUM_TASKS, h.shape[-1]),
                pair_vec.unsqueeze(2).expand(bsz, pairs, NUM_TASKS, self.entity_dim),
                t_e.view(1, 1, NUM_TASKS, -1).expand(bsz, pairs, NUM_TASKS, -1),
            ],
            dim=-1,
        )                                            # [B, P, T, H+64+E]
        type_logits = self.type_scorer(type_in).squeeze(-1)  # [B, P, T]

        bin_logits = self.bin_scorer(torch.cat([h, prev_embedding], dim=-1))

        joint = (
            pair_logits[:, :, None, None]
            + type_logits[:, :, :, None]
            + bin_logits[:, None, None, :]
        )                                            # [B, P, T, Bins]
        flat = joint.reshape(bsz, pairs * NUM_TASKS * PATH_TIME_BINS)

        stop = self.stop_scorer(
            torch.cat([h, self.type_embed(
                torch.full((bsz,), NUM_TASKS + 1, device=h.device, dtype=torch.long)
            )], dim=-1)
        )
        outside = self.outside_scorer(
            torch.cat([h, self.type_embed(
                torch.full((bsz,), NUM_TASKS + 2, device=h.device, dtype=torch.long)
            )], dim=-1)
        )
        logits = torch.cat([flat, stop, outside], dim=-1)  # [B, C+2]

        if pair_mask is not None:
            invalid = ~pair_mask
            if bool(invalid.any()):
                pad = invalid[:, None, None, None].expand_as(joint)
                logits = logits.masked_fill(
                    pad.reshape(bsz, -1), float("-inf")
                )
        if type_mask is not None:
            t_invalid = ~type_mask  # [T]
            if bool(t_invalid.any()):
                joint_pad = t_invalid.view(1, 1, -1, 1).expand(
                    bsz, pairs, NUM_TASKS, PATH_TIME_BINS
                )
                logits = logits.masked_fill(
                    joint_pad.reshape(bsz, -1), float("-inf")
                )
        return torch.log_softmax(logits, dim=-1)

    # ------------------------------------------------------------------
    def forward_sequence(
        self,
        entity_memory: Tensor,
        global_context: Tensor,
        ext_bucket: Tensor,
        pair_src: Tensor,
        pair_tgt: Tensor,
        history: list[tuple[Tensor, Tensor, Tensor, Tensor]],
        *,
        pair_mask: Tensor | None = None,
    ) -> tuple[Tensor, list[Tensor]]:
        """Teacher-forced scoring.

        history: per step, (type_idx [B], src [B], tgt [B], bin [B]) of the
        mark fed as input. Returns (final hidden, per-step option log-probs).
        """
        node_vecs = self.node_vectors(entity_memory, ext_bucket)
        h = self.initial_hidden(entity_memory, global_context)
        step_logs: list[Tensor] = []
        for (t_idx, src, tgt, b_idx) in history:
            emb = self.mark_embedding(node_vecs, t_idx, src, tgt, b_idx)
            h = self.cell(emb, h)
            step_logs.append(
                self.score_options(
                    h, node_vecs, pair_src, pair_tgt, emb, pair_mask=pair_mask
                )
            )
        return h, step_logs

    @staticmethod
    def bos_batch(bsz: int, device) -> tuple[Tensor, Tensor, Tensor, Tensor]:
        t = torch.full((bsz,), NUM_TASKS, device=device, dtype=torch.long)
        neg = torch.full((bsz,), -1, device=device, dtype=torch.long)
        return t, neg, neg, neg


def special_type_index(kind: str) -> int:
    if kind == BOS:
        return NUM_TASKS
    if kind == STOP:
        return NUM_TASKS + 1
    if kind == OUTSIDE:
        return NUM_TASKS + 2
    raise ValueError(kind)
