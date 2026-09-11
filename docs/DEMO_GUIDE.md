# FORESIGHT — Judge Demo Guide

**Morning-of checklist (10 min before):**

```
cd C:\Aarav\Code\SIH\SIH
python scripts\serve_console.py          # http://127.0.0.1:8001
```

- Open http://127.0.0.1:8001 in a full-screen browser (F11) at 1440×900 or 1920×1080.
- The header pill should read **Trained profile** (green dot). If it says Untrained, the
  artifacts folder isn't loaded — check the server console.
- Keyboard: **1–6** switch screens once a session is open (Sessions, Forecast,
  Evidence, Paths, Replay, Evaluation).
- Backup: the recorded video at `artifacts/demo/foresight-demo.mp4` (webm if ffmpeg
  was absent) plays the same flow offline.

---

## The 5-minute live walkthrough

### 1. Sessions — the entry (30s)

**Open "Web compromise to lateral movement" → Open session.**

Say: *"FORESIGHT forecasts network attacks before they unfold, from traffic
alone — no endpoint agents. Each session is a capture replayed through the
full pipeline. I'll use a scripted attack: an external exploit hits the DMZ
web server, C2 beaconing follows, then lateral movement into the app tier
and the database."*

Point at the catalog: synthetic captures are disclosed as such; the CTU-13
entries are real capture-derived flows (say "real-data transfer profile" if
the CTU bundle is built by demo time; otherwise "qualified real datasets,
registry-verified" — never claim real-data performance that isn't on screen).

### 2. Forecast — the analyst workspace (90s, the core)

The screen is one composition: **entities by risk | the observed network |
the selected entity.**

- *"On the left, every entity in scope, ranked by forecast risk. The web
  server is already elevated."* — click **web-01** in the list (or a node in
  the graph).
- *"The inspection panel: cumulative risk per target over the next 5, 15, 30
  minutes — this is a calibrated survival curve, not a score. Conditional
  ETA when the probability supports it. Sentinel novelty separately —
  unexpectedness is not attack probability. And the forecast is sealed:
  here's the SHA-256 of the committed record and the hash of the exact
  legal prefix it was computed from."* (point at the hash chips)
- Switch the horizon tabs (**5 min → 30 min**) — the curve extends.
- The graph: solid edges are **observed** communications, dashed are
  **predicted** future edges — *"we never draw a predicted edge as observed
  traffic."*

### 3. Evidence — why (60s)

**Screen 3 → Attribution tab.**

- *"Why does FORESIGHT think this? Deletion testing: we remove one window of
  the entity's traffic, recompute features, rerun the model — the risk delta
  is the evidence. Comprehensiveness 30% means removing the selected evidence
  drops risk by 30 points; the random-deletion control shows it's not noise.
  Every cited flow is a real packet row from the legal prefix."* (scroll the
  flows table)
- If asked about causality: *"deltas are sensitivity, not causal proof — the
  system says so."*

**Evidence requests tab** (30s): *"For uncertain credential use we can
request identity/session detail — a separate telemetry stream the forecaster
never sees. The rule is transparent, the request is costed and expiring, and
the answer arrives as a new observation with its own clock."* — click
**Request** on a proposal.

### 4. Paths — attack-path hypotheses (45s)

**Screen 4.**

- *"Beyond per-entity risk: a typed-event decoder ranks whole attack paths —
  'C2 from this host to that address in the next 5–10 minutes, then lateral
  movement to the file server.' Beam search with explicit mass accounting:
  no-event mass, outside-candidate mass, truncated-search mass — every bit
  of probability is accounted for. These are ranked hypotheses, not
  calibrated path probabilities — we never label them otherwise."*

### 5. Replay — the sealed forecast (90s, the differentiator)

**Screen 5.**

- *"This is the part that makes the evaluation honest. At this cutoff:
  everything left of the lock is what the model saw. Everything right was
  locked away — the forecast endpoint cannot read it. The forecast was
  committed with this hash before any reveal."* (point at the theater strip)
- Click **Reveal future**.
- *"Predicted: C2, 67% within 15 minutes. Actual: C2 observed — with 9
  minutes of advance warning. Matched. Misses and false alerts are scored
  with the same honesty — nothing is hidden."* (point at the outcome badges)
- Scrub the cutoff slider and repeat once to show it's live.

### 6. Evaluation — the science (45s)

**Screen 6.**

- *"Locked-test evaluation with predeclared gates. Some gates pass, some
  fail — we report both. Average precision on C2 detection is 50× the base
  rate; recall at the false-alert budget is the honest frontier we're
  pushing. The reliability diagram shows calibration. This is a scientific
  verification interface, not a scoreboard."*

### Close (15s)

*"Everything you saw — ingestion, causal prefixes, graph-temporal
forecasting, calibration, novelty, explanations, sealed evaluation, and
intervention trials — runs offline, from traffic alone, with every number
traceable to a hash."*

---

## Intervene (if time allows / judges ask about response)

Forecast workspace → **Intervene** at the bottom of the inspection panel.
Propose blocking the C2 pair → **Authorize** (explicit human approval) →
**Dry-run paired trial**: same capture, same seed, two futures — with the
block, the downstream lateral movement is averted at 0.0x% benign
disruption; the postcondition is verified. *"One authorized action, paired
causal evidence — and we never claim production control authority from a
simulation."*

---

## Hard-questions crib sheet (honest answers)

| Question | Answer |
|---|---|
| "Is this real data?" | The core profile is a disclosed synthetic range — engineered to carry real traffic signatures. The CTU-13 real-flow transfer profile is [trained/qualified] separately and reported separately; the two claims never mix. |
| "How accurate is it?" | On the locked synthetic test: C2 AP ~0.5 (50× base rate), median advance warning ~90s. Gates: we publish pass AND fail — see the Evaluation screen. |
| "Can it miss attacks?" | Yes — recall is the honest frontier; misses stay visible in the reveal scoring. We never turn unknown into benign. |
| "Is the path probability calibrated?" | No — ranked hypotheses, explicitly labeled uncalibrated. |
| "What's novel vs attack?" | Sentinel reports unexpectedness against a benign reference. Benign drift triggers it too. It is not an attack probability. |
| "Can this deploy in production?" | The architecture is production-shaped (tenant scoping, quotas, sealed ledger, typed contracts), but no real-world performance is claimed — that requires qualified deployment data. |
| "Why should we trust the eval?" | Forecasts are hash-committed before reveal; the reveal endpoint is a separate authority; the split is frozen in the registry; the report shows confidence intervals and failed gates. |

---

## What's real on screen (never overstate)

- Every forecast, risk curve, ETA, novelty score, evidence flow, path,
  query answer and trial outcome is computed live by the trained models —
  nothing is mocked.
- Captures are replayed (offline-first by design — that's the product, not
  a limitation to hide).
- Synthetic vs real sources are disclosed on every screen, per the build
  specification's honesty contract.
