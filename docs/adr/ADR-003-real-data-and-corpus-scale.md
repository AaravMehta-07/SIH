# ADR-003: Real-data profile and corpus scale

- **Status:** Accepted
- **Date:** 2026-09-11
- **Authority:** Build Spec Sections 6-11, 15, 20, 29; Appendices F, I, M, Q, T

## Context

The first trained profile used 72 synthetic episodes. It proved the sealed
forecast contract but did not establish performance on real traffic, and its
locked synthetic gates failed. CTU-13 supplies real capture-derived flows with
publisher labels for Botnet, Normal, and Background. Its public scenario PCAPs
contain botnet traffic only rather than the complete mixed capture.

## Decisions

1. The qualified CTU registry is `configs/datasets/ctu13.json`. Scenario 1 is
   training, scenario 6 is calibration, and scenario 12 is a locked test. The
   split unit is the entire scenario/campaign; windows and address partitions
   never cross partitions. With only three selected campaigns, there is no
   separate development scenario. Hyperparameters below are fixed before the
   locked run and statistical evidence is reported inconclusive where support
   is insufficient (Sections 6, M.1, T.1). (Correction 2026-09-11: the
   registry's scenario-6 SHA-256 originally carried a one-character
   transcription error; `foresight data qualify` caught it and the registry
   now records the verified digest of the intact on-disk file — 558,907
   accepted rows, 12 malformed, parse peak ~147 MB.)
2. CTU `binetflow` is a flow-only profile. Observed flow closure, addresses,
   ports, protocol, total packets and byte totals are retained. Packet timing,
   sizes, flags, TCP sequence/window, TTL, fragmentation, payload length and
   directional packet allocation remain invalid. Availability and ingestion
   are replay assumptions at flow closure because CTU has no independent
   collector receipt clock (Sections 6, 7, 9; D.4).
3. IP strings become address-scoped entities, never physical-device identity.
   The fixed `147.32.84.0/24` lab range is divided into two deterministic `/25`
   cohorts to respect the 128-node cap. External addresses remain aggregate
   context and do not receive endpoint forecasts (Section 8).
4. Only `From-Normal` enters verified benign risk sets. `Background`, `To-*`,
   unresolved, missing, and ambiguous labels are not benign. Generic
   `From-Botnet` is a weak proxy for task 0 (malicious endpoint contact). Task 3
   is supported only when the publisher label explicitly names CC, C&C, IRC,
   or command-and-control. Tasks 1, 2, and 4 and all tactic tags are
   `not_supported` on this profile (Sections 6, 11, T.4).
5. The CTU model is a target-domain fine-tune of three independently shaped
   synthetic members: reference seed 0, gate seed 0, and wide seed 0. The CTU
   scaler is fitted on scenario 1 only. Three natural-prevalence epochs at a
   fixed 10-bin rollout are used; scenario 6 alone fits calibrators and alert
   thresholds. No locked-test result changes these defaults (I.4, I.5, M.1).
6. The public scenario-6 PCAP runs in a separate `python -I` worker with fixed
   byte, packet, captured-length, time, and output bounds. It retains only an
   allowlisted header table. The UI identifies it as real but botnet-only; it
   does not imply Normal/Background packet coverage (F.1, Q).
7. The synthetic corpus expands to 300 episodes: 70 benign baseline, 50 benign
   drift, and 45 for each of four attack families. All six selected members
   (reference seeds 0-2, gate seeds 0-1, wide seed 0) are retrained because the
   corpus fingerprint invalidates old scalers, clip caches, checkpoints,
   calibrators and thresholds. The 40 percent benign share increases
   false-alert exposure while preserving every family (Sections 29, I.5).

## Consequences

- Synthetic and CTU reports are separate artifacts and make separate claims.
- CTU is primarily a transfer and ingestion stress test. A scenario whose
  first botnet/C2 observation precedes the required history cannot establish
  prospective event recall; the gate is inconclusive rather than re-labeling a
  later flow as a new attack onset.
- The real-flow console exposes unavailable packet groups. The real-PCAP
  console exposes packet-header capability but also the botnet-only scope.
- Trained artifacts remain gitignored and reproducible from registered hashes
  and scripts; source, registries, decisions, and reports remain reviewable.
