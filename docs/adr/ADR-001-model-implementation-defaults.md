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

## Full-pipeline build (2026-09-11): data, training, serving defaults

| Decision | Default | Spec basis |
|---|---|---|
| Transition prior | Residual: `next_memory = memory + MLP([memory ‖ h_top])`, `next_context = context + MLP(h_top)`. A direct regression contracts entity memories toward the pooled mean every rollout step (measured 0.39 → 0.065 std after one transition), erasing entity-specific hazards by bin ~5. Identity-plus-delta preserves discrimination through 60-step rollouts. Shapes unchanged (192→128→64, H.3) | §14, H.3 |
| Survival positive weight | 50.0 on observed-event bins (weighted mean normalization). Rare events (~0.1% of risk bins) otherwise contribute negligible gradient; the induced odds shift is corrected by the I.4 affine calibrators fitted on natural-prevalence calibration data | §15, A12 |
| Positive-clip oversampling | Clips with imminent primary-horizon events sampled 4×; probabilities recorded in the run manifest; corrected by I.4 calibration | §15 |
| Learning rate (this run) | 0.002 (Section-35 default 0.001; development adjustment — rare-event hazard learning converged too slowly at 0.001 on dev) | I.1 |
| Flag feature semantics | TCP flag counts count PACKETS carrying the bit (`(f & bit) != 0`), never the sum of bit values; applies to node counts 1-6, edge syn/rst counts and global flag fractions | F.6, F.7 |
| Healthy idle | A present, observation-valid host with no outgoing packets carries valid zeros for flag counts (1-7), unique-destination count and port count; entropy/contiguity/arrival-score stay masked (need ≥2 observations); the bidirectional byte ratio is a valid 1 | F.6 |
| Cutoff grid (training corpus) | Every second window from 20 to 80: full 60-bin targets for cutoffs ≤ 50, censored follow-up beyond; primary-horizon follow-up complete for every cutoff | G.4, §15 |
| Batched training | `Trainer.batched_step` stacks B=16 clips per timestep (`graphs.stack_windows`), one forward/backward through the shared batched graph, per-clip D.6 losses averaged (each already valid-count normalized); the frozen per-clip target contract is preserved by slicing the batched rollout outputs | §35 batch_clips, D.6, G.2 |
| Campaign timing | Attack campaigns start t0 ∈ [11, 17] min so first-contact/initial-access events fall inside the future of early cutoffs (earliest cutoff = window 20 = 10 min) | §11, G.4 |
| Serving path | `build_serving_windows` produces scaled windows + the frozen all-pairs candidate set WITHOUT the training target object; the serving loader never instantiates `ClipTargets` | C.2, G.4 |
| Ensemble disagreement | Exact-equality shortcut (`max == min → 0.0`): the float mean of identical occurrences differs by an ulp, which faked ~1e-16 disagreement for identical members | I.5 |
| Novelty reference | Robust per-feature-group median/MAD of matured residuals over benign train clips + diagonal embedding reference; residual thresholds 3.0 standardized units; benign change is change detection only | J.1, A09 |
| Sentinel input law | `MaturedResidual` enforces `observed_window > forecast_cutoff_window` at construction (NO01) | J.1, NO01 |
| Alert policy | Per-task thresholds fitted on the calibration split at the 1-false-alert-per-100-asset-hours budget over non-overlapping cutoffs (cutoff % 10 == 0); unreachable budget → `budget_unreachable` abstention (no threshold, no alerts) | §29, M.3, M.4 |
| Evaluation matching | 300 s per-(entity, task) cooldown on alert issuance; one alert matches at most one event; events beyond the horizon make an alert evaluable-false; no later event → outcome unknown unless follow-up complete | M.3, EV01, EV02 |
| Evidence attribution budget | 12 window-deletion groups + 6 matched random controls + top-4 selection per explanation; partial results flagged | K.1 |
| Episode corpus | 72 episodes / 6 families (16 benign-baseline, 10 benign-drift, 14 web-to-lateral, 12 c2-exfil, 10 slow-recon, 10 cred-spray); every 9th episode carries a 2-minute sensor gap; 1.2% late arrivals (3-8 min receipt delay) | §6, C.4, §18 |
| Splits | Family-balanced deterministic interleave, whole-episode units, 60/15/10/15 with the M.1 embargo recorded; never row-level | M.1 |
