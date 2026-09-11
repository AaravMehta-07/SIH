# ADR-002: Tier B Implementation Defaults

Status: Accepted 2026-09-11
Scope: Build Spec Sections 20-23, Appendices N, O; Tier B delivery items.

Every default below is an elaboration of an open detail (T.1), frozen before
the Tier B training runs. None is an empirical claim.

## 1. I.5 Heterogeneous Ensemble (`models/variants.py`)

- Member plan: `reference:0-4 gate:0,1 wide:0,1` (9 members). Reference
  checkpoints from the original 5-seed run are reused unchanged; only the
  interface (H.1) and frozen §35 widths are shared across families.
- `gate`: two-layer GAT 88→96 (6×16 concat) → 64 (8 averaged 64-wide
  heads); GRUCell-gated entity transition `next = GRU(proj(endpoint),
  current)`; 32-wide heads; direct LayerNorm global map.
- `wide`: three-layer GAT 88→144 (6×24 concat) → 144 (4×36 concat) → 64
  (8 averaged heads); sigmoid-gated residual transition; 192→96→48 deep
  heads.
- Variant seed offsets (reference +0, gate +10000, wide +20000)
  decorrelate initialization across families sharing seed numbers.
- Early-stop policy (corrected after the first gate run): patience (8)
  resets at every curriculum horizon transition and may only fire from the
  first primary-horizon epoch (17). Dev AP at h=1/h=3 sits in the same
  0.008–0.04 band for EVERY member family — reference seeds included — so
  stopping there (as the first gate:0 run did at epoch 10) truncates members
  before the metric means anything. Reference seeds survived the old policy
  only by improvement-granularity luck.
- Checkpoints `partial/{variant}_seed{N}.pt` (legacy `seed{N}.pt` accepted
  for reference); bundle weights `model_{variant}_seed{N}.safetensors`;
  calibrators keyed `{variant}:{seed}:{task}` (legacy `{seed}:{task}`
  remapped for reference members — same weights, same calibration split,
  no refit).

## 2. Path Engine (§20, `paths/`)

- Candidate universe is CANONICAL per topology: every directed
  internal→internal pair (authorized inventory) plus external↔internal
  pairs for externals present in the capture. Corpus size: 260 pairs × 5
  tasks × 6 time bins = 7800 options + STOP + OUTSIDE. A canonical universe
  (not per-cutoff sets) makes batches share one option space; pair KINDS
  (active / external_active / inactive_seen / inventory) are still computed
  per cutoff for disclosure. Hard negatives are structural: every inventory
  pair competes in the softmax at every step.
- Next-mark decoder: GRU(128) over previous marks, initial hidden from
  mean-pooled entity memory + global context (reference member's observed
  state). Option score = pair factor + type factor + time-bin factor, each
  conditioned on the GRU state; joint log-softmax over all options + STOP +
  OUTSIDE. Externals use 16 stable hash-bucket embeddings (internal slots
  read state-conditioned memory rows).
- Time bins: 6 × 300 s over the 30-minute horizon (coarser than the
  30-second hazard grid; path time is tactical, hazard time is operational).
- Beam: width 8, depth 4 (§20 defaults). `no_event_mass` = P(STOP at step
  0); `outside_candidate_mass` = mass of paths terminating in OUTSIDE;
  `truncated_search_mass` = 1 − accounted (depth-exhausted beams + width
  pruning). All path probabilities stay `calibrated: false`.
- STOP targets are censored when the horizon extends past the recording
  (`cutoff + 60 > 110`): the absent tail is unknown, not benign.
- Training: teacher forcing on `ChainStep` labels; a true mark whose pair is
  outside the universe trains the OUTSIDE token and ends the sequence.

## 3. Identity Modality + Evidence Requests (§21, `ingest/identity.py`,
   `queries/`)

- The identity stream is generated deterministically per episode (seeded),
  aligned with chain/stage labels, and round-tripped through the real CSV
  adapter boundary (header validation, malformed-row accounting) into
  canonical `auth_observed` SecurityEvents with the three §7 clocks.
- Coverage: all internal hosts except `web-01.dmz.local` (no agent —
  honest `unavailable`); `dc-01.corp.local` requires elevated authorization
  (`denied` under the demo policy). Externals are never identity-covered.
- Query rule (transparent, §21-sanctioned): propose `identity_session_detail`
  for entities whose lateral-movement occurrence probability exceeds
  max(0.03, 1.5 × scope median) and is ≤ 0.85. The band is RELATIVE because
  calibrated lateral probabilities on this profile never exceed ≈0.08 — a
  fixed absolute band would never fire. Flat (benign) scopes propose
  nothing; confidently-alarming entities need a decision, not a query.
- Answers carry their own clocks, increment a forecast version, and never
  rewrite the committed seal. Identity records are analyst context only —
  the §35 feature registry is frozen; model scores do not change (disclosed
  in every answer).

## 4. Range Actions (§22-23, `actions/`)

- One action type: `block_edge`, scope = one observed internal↔external
  pair, reversible (temporary network restriction). Scope check uses
  packet-derived cross-boundary pairs (graph edges are internal-only, G.2).
- Approval: HMAC-SHA256 over the canonical proposal (action id, pair,
  forecast hash, expiry, idempotency key, policy version) with a DISCLOSED
  demo key. Production authorization is a separate service (§23).
- State machine per the §23 table; idempotency key checked before any state
  change; expiry enforced at authorize, execute and by the reconciler;
  audit log is the durable intent written before the connector call.
- Paired trials: both arms share the episode seed and byte-identical prefix.
  The action arm drops blocked-pair packets after the action time and
  suppresses chain steps causally downstream of a lost C2 channel (source
  host of a blocked C2 step cannot command later steps). Benign disruption
  is measured as collateral suppression of non-attack traffic; the
  postcondition (zero surviving blocked-pair packets post-action) is
  verified on the action-arm table.
- The scripted attacker has no backup channel; adaptive scenarios are Tier C
  (§22). Simulator success is not production proof (§2); all execution is
  disclosed synthetic-range only.

## 5. Console (K.2/K.3)

- New screens: Paths (ranked hypotheses, mass tiles, `calibrated: false`
  disclosure, distinct observed/predicted/hypothesized legends), Query
  (proposals, allowlist/cost/expiry, typed answer states), Action (propose →
  policy check → authorize → dry-run/execute paired trial).
- Motion system: duration/easing tokens; line draw-in via `pathLength=1`
  dashoffset (replays on data change through element keys); staggered
  reveals; rAF count-up (respects `prefers-reduced-motion`); focus-visible
  rings. Animations transform/opacity only — no layout-affecting motion
  (K.3 stable chart dimensions).

## Consequences

- The bundle manifest gains `members: [{variant, seed}, ...]` (legacy
  `seeds` list still honored for reference-only bundles).
- `/health` reports `action_mode: demo_range` and a `tier_b` capability map
  instead of the blanket `disabled`.
- `verify_console.py` walks all eight screens including the Tier B flows.
