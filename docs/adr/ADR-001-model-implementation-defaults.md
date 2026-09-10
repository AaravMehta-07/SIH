# ADR-001: World Model Implementation Defaults

Status: Accepted (2026-09-10)
Scope: `src/foresight/models/` (Aarav Mehta - Core World Model + Integration)
Authority: FORESIGHT_Build_Spec.md Sections 13-15, 25-26, 35; Appendices D.5, G, H, I, T.1

The Build Spec fixes all tensor dimensions and the transition/decoder structure. Where the
spec leaves an implementation choice open, Section T.1 requires an explicit recorded
default. This ADR is that record for the world model. Each default cites its spec basis.

| Decision | Default | Spec basis |
|---|---|---|
| GAT variant | `GATConv` (not GATv2), three directed layers 88→128→128→64, heads 4×32 concat / 4×32 concat / 4×64 averaged | §13, G.3, citation [6] |
| Edge attributes in GAT | Raw 22-dim edge features (`edge_dim=22`) at all three layers; edges influence attention only | §13, G.3 |
| Computational self-loops | Constructed deliberately by the encoder with explicit zero edge attributes; `GATConv(add_self_loops=False)`, observed self-loops removed first, one zero-attr self-loop appended per real node | §10, G.3 ("explicit zero edge attributes ... or construct these loops deliberately") |
| Reverse edges | Never fabricated; only observed reverse communication creates a reverse edge | G.3 |
| Normalization | `torch_geometric.nn.GraphNorm` after each GAT layer, per graph over real nodes only, eps = 1e-5 | G.3 ("per-graph normalization ... records the actual normalization class and epsilon") |
| Attention dropout | 0.1, training only (disabled in eval) | §13 |
| Activations | ELU between all linear layers in heads, decoders, adapter, transition MLPs | §13, H.2 |
| GRU update mask | `node_present AND node_observation_valid`: present healthy idle entities (valid zero features) receive the observed idle embedding update; temporarily unobserved entities preserve their memory for that window | G.2 |
| Entity-slot contract | One stable entity union per 20-window clip; slot order is fixed for the clip; padding rows have `node_present=False` and never enter the GAT batch | G.2, D.5 |
| Pooling | Masked mean + masked max over `node_present` entities (empty scope rejected upstream per D.5; pooling guards zero-present with zeros) | §13, H.1 |
| Global state | `nn.LSTM(152, 128, num_layers=2)`; full `(h, c)` pair retained; `global_h_top` = top-layer hidden `h[-1]` | §13, H.1, H.3 |
| Endpoint representation | `[entity_memory ‖ global_h_top]` = 192; transition-prior entity MLP uses the same 192 input (128-wide top hidden, NOT the 24-wide adapter output) | H.2, H.3 |
| Observation decoder log-scales | Clamped to [-5, 3] at the decoder output | H.2, H.5 |
| Hazard/tactic/edge readouts | Heads emit raw logits; sigmoid is applied only at probability readout, never inside BCE-with-logits | §13, H.2 |
| Number of hazard tasks J | Constructor argument (`num_event_tasks`); default 5 = SIH five-target projection; final J always from the qualified task manifest at runtime | §11, H.2 |
| Rollout bin convention | `state after transition j represents bin j`; `roll_out(...)[i]` (0-indexed) is bin i+1; bins are `(d+(j-1)·30s, d+j·30s]` | §14, §15 |
| Rollout isolation | `roll_out` clones the observed state; imagined entity memory is never committed as observed live memory; no in-place state mutation | §26, H.4, MO04 |
| Numerical failure | Any non-finite state/input tensor raises `NonFiniteTensorError`; runtime translates it to an explicit `numeric_failure` health status, never a zero-valued forecast | H.5, MO05 |
| Survival math | float64 log-survival accumulation via `log1p(-q)`; cumulative risk derived as `1 - S`; ETA derived from the same distribution, never an independent head | §12, I.5 |
| Ensemble mixture | Average member event-time/no-event distributions, then derive mixture hazards as `p_mix_j / S_mix_(j-1)` | I.5, CA03 |

Any change to a default in this table requires a schema/config decision record per
Build Spec Section 35 and Appendix T.1, plus updated golden fixtures.
