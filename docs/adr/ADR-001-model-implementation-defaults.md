# ADR-001: World Model Implementation Defaults

Status: Accepted (2026-09-10, extended same day for training/calibration/runtime)
Scope: `src/foresight/models/`, `src/foresight/training/`, `src/foresight/calibration/`, `src/foresight/runtime/` (Aarav Mehta - Core World Model + Integration)
Authority: FORESIGHT_Build_Spec.md Sections 13-15, 25-26, 35; Appendices D.5, D.6, D.7, G, H, I, T.1

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

## Training objectives (§15, I.2), targets (D.6) and loop (I.1)

| Decision | Default | Spec basis |
|---|---|---|
| Survival NLL form | `-(y·logsigmoid(z) + (1-y)·logsigmoid(-z))` on raw logits — the numerically stable form of `log(q)`/`log1p(-q)`; no probability clamping; normalized by `max(1, count(valid_risk_bins))` pooled across entities and tasks | §15 |
| Task separation | Each event type is a separate risk process on the J axis, sharing one pooled normalization exactly as the §15 formula writes it | §15 |
| Observable NLL grouping | Node and global Gaussian NLL normalized separately then averaged equally over present groups; absent group recorded, available group used without invented count | §15 |
| Calibrator horizon groups | Bins 1-10 / 11-30 / 31-60; bins past 60 remain in the last group | I.4 |
| Calibrator objective | Total (un-normalized) survival likelihood + weak zero-mean L2 prior on the group intercepts; un-normalized so the prior's influence fades as calibration support grows and dominates only in sparse cells | I.4 ("regularized horizon-group intercepts") |
| Calibrator optimizer | L-BFGS with strong-Wolfe line search, max 100 iterations, 5 parameters (slope, intercept, 3 group intercepts) | I.4 (implementation choice) |
| Sparse-cell threshold | Fewer than 20 observed events for a task/regime cell → abstained calibrator with recorded reason; caller decides pooled backoff | I.4 ("a handful of events") |
| CalibratorSet lookup order | Exact (task, regime) cell → task-level calibrator → pooled backoff → explicit `uncalibrated`/`abstained` status; status travels with every forecast | App. S (`calibrate(logits, task, regime)`), D.7 |
| Display ETA threshold | 0.30 occurrence probability (must stay ≤ 0.496 so the §35 golden example reports its ETA) | §12, T.1 |
| Curriculum transitions | Not automatic: `CurriculumSchedule` starts at 1 bin and expands to [3, 10, 30, 60] only through explicit `transition_epochs` chosen from development behavior; every transition is recorded in the run summary | I.1 |
| Sampling/weighting policy | `natural_class_prevalence` by default; the policy string is recorded in every step log and run summary, never implicit | §15, TR03 |
| Split guard | `assert_trainable_split` refuses `test`/`locked_test` before any gradient work | TR02 |
| Batch handling | `ClipTargets` is per-clip `[N, H, J]` (D.6); the trainer processes one clip per step; multi-clip batching (batch_clips=16) awaits `graphs.collate`, which owns padding across clips | D.6, C.2, GR01/GR02 |
| Forecast engine omitted stages | Trust gating, novelty, evidence assembly, ledger commit and publishing are reported as `omitted` with reasons rather than faked; they activate when the runtime/storage/sentinel modules land | §26 |

Any change to a default in these tables requires a schema/config decision record per
Build Spec Section 35 and Appendix T.1, plus updated golden fixtures.
