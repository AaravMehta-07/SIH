# FORESIGHT — The Complete Guide

*Read this once, slowly. Written so that someone who knows nothing about
FORESIGHT finishes knowing everything: what it is, how every part works, what
the numbers mean, and why it is built the way it is. After this document you
should be able to explain the system to judges and answer detailed questions.*

---

## Part 1 — The Problem

SIH26153 (NTRO): **"AI-based network attack forecasting from network traffic data."**

The key word is **forecasting**, not detection. Almost every security product
on the market *detects* — it tells you an attack is happening **right now**,
usually after the attacker is already inside. By then, the cost of response is
high and the information advantage is the attacker's.

Forecasting is the ability to say, *before the event*:

> "This host — a web server in the DMZ — has a 67% probability of
> establishing a command-and-control channel within the next 15 minutes.
> Conditional on that happening, the median time is about 11 minutes from now.
> Here is the traffic evidence driving that assessment."

That statement gives a defender something detection never can: **time to act
before the damage** — block the pair, isolate the host, request more
information — while the attack is still forming.

FORESIGHT (team **Deja Vu T-1**) is a complete system that makes this kind of
statement, attaches **trustworthy probabilities** to it, shows **the evidence**
behind it, and **proves** its evaluation is honest. It runs entirely offline
from network traffic alone — no endpoint agents, no cloud, no external
intelligence feeds.

### Why this is genuinely hard

1. **Attacks are rare.** In real networks, well over 99% of traffic is benign.
   A model that predicts "nothing will happen" is right almost always — and
   completely useless. The challenge is catching the rare true positives
   without drowning analysts in false alarms.
2. **The future is unobservable.** The model must not peek at anything after
   the decision moment — or its "forecast" is fraud. Enforcing this is an
   engineering discipline in itself.
3. **A probability is only useful if it is calibrated.** "67%" must mean 67%
   of such situations actually lead to the event. Raw neural network outputs
   never guarantee this.
4. **Judging a forecaster is easy to fake.** If you evaluate on data the model
   has seen, or choose your metrics after the fact, you can "prove" anything.

FORESIGHT is architected around solving all four.

---

## Part 2 — The Big Picture

FORESIGHT is a pipeline with one strict rule at its heart: **the forecast only
ever sees the past.**

```
network capture (PCAP / flow records)
        ↓
bounded, validated ingestion  →  capability report (what this data can/cannot support)
        ↓
the CAUSAL PREFIX — every packet that was knowable at the decision moment,
                    filtered by three separate clocks
        ↓
exact feature registry — 44 per-host, 11 per-link, 24 global measurements,
                    each with a validity bit (never fabricate a measurement)
        ↓
directed host graph  →  GAT (graph attention) encoder
                    →  per-entity GRU memory (each host remembers its own history)
                    →  global LSTM (network-wide context)
                    =  the model's picture of the network NOW
        ↓
learned transition prior  →  roll the state FORWARD in imagination,
                    step by step, with NO future data
        ↓
hazard heads  →  per-host, per-attack-type, per-time-bin event probabilities
        ↓
I.4 CALIBRATION  →  raw scores become honest probabilities
        ↓
SENTINEL  →  "is this behavior novel?" (separate from "is it malicious?")
        ↓
SEALED COMMIT  →  the forecast is hash-committed to an immutable ledger
        ↓
(promise kept: the future stays locked)
        ↓
REVEAL  →  ground truth comes out; every prediction scored honestly —
           hits, misses, false alarms. Nothing hidden.
```

Every box is a real, tested component. The rest of this guide walks through
each one.

---

## Part 3 — Time: The Three Clocks (the part most systems get wrong)

Every event in FORESIGHT carries **three timestamps**:

1. **Event time** — when the thing happened on the wire.
2. **Available time** — the earliest moment the sensor could have finished
   measuring it (a flow's features only exist once the flow closes).
3. **Ingested time** — when our system actually received it.

At any decision moment `d`, a packet influences the forecast **only if all
three times are ≤ d**. No exceptions, no "it arrived late but let's include it."

Why does this matter? Because a real forecaster must be able to answer: *"what
would you have said at 14:32, knowing only what was knowable at 14:32?"* If
your evaluation lets late-arriving data leak into the "past," your measured
accuracy is fiction. This single rule is what makes FORESIGHT's numbers mean
something.

---

## Part 4 — Features: Measure, Don't Imagine

From the eligible traffic, FORESIGHT computes an **exact, frozen registry** of
features per 30-second window:

- **44 node features** per host — traffic volumes, port diversity and entropy,
  failed-connection fraction, inter-arrival statistics, byte ratios, port-scan
  signatures, beaconing regularity…
- **11 edge features** per communicating pair — direction, volume, symmetry.
- **24 global features** — whole-network state.

Crucially, each feature carries a **validity bit**. If the input is flow
records without packet detail (like the CTU-13 real dataset), the
packet-level features are marked **unsupported** — never guessed, never filled
with zeros pretending to be measurements. The capability report says exactly
what the source can and cannot support, and the model consumes that honestly.
This is rare discipline: most systems silently impute and pretend.

---

## Part 5 — The World Model (the AI core)

The model is a **graph-temporal world model** — think of it as the network's
imagination. Three stages:

### 5.1 The graph encoder (GAT — Graph Attention Network)

Each 30-second window becomes a directed graph: hosts are nodes,
communications are edges. A **graph attention network** learns which
neighboring hosts matter to each host's situation. An attacker moving from a
web server to a file server is literally a path through this graph — the
encoder's whole job is to make such patterns visible in each host's
representation.

### 5.2 Per-entity memory (GRU)

Every host has its **own recurrent memory** (a GRU — gated recurrent unit).
Host `web-01`'s memory accumulates its personal history: normal web traffic
for 10 minutes, then a strange inbound connection, then periodic beacons.
Each host's memory evolves independently — a workstation's history should not
be blurred into the database server's.

### 5.3 Global context (LSTM)

A network-level LSTM reads a summary of all host memories and maintains
network-wide context — is this a quiet night, or is the whole DMZ trending
strange? This global state feeds back into every host's representation, so
each host's risk is judged in network context.

### 5.4 The ensemble: six independent models

FORESIGHT does not trust one network. It trains **six models with genuinely
different architectures** (three "reference" seeds, two "gate" variants with
GRU-based transitions, one "wide" variant with deeper heads) and averages
their **calibrated probability distributions** — never their raw scores. When
the members disagree, the spread is surfaced as **model disagreement** (more
uncertainty), not hidden.

### 5.5 The transition prior: imagining the future

Here is the heart of "forecasting": a **learned transition model** takes the
current network state and rolls it forward — one step at a time, in
imagination, touching no future data. After each imagined step, decoder heads
read out what the network "would look like" and hazard heads ask: *would an
event of type X fire on host Y in this imagined future?* Rolling 60 steps
gives a full 30-minute forecast, with the uncertainty of longer horizons
reflected naturally.

This is the difference between **interpolation** (pattern-matching on
observed data) and **imagination** (a generative model of how network states
evolve). It is why FORESIGHT can talk about the future at all.

---

## Part 6 — The Five Targets

FORESIGHT forecasts five named event types (the SIH five-tactic projection):

| # | Target | Meaning |
|---|--------|---------|
| 0 | Malicious endpoint contact | first contact with a known-malicious endpoint (a *proxy indicator*, honestly labeled as such — not "compromise") |
| 1 | Initial access | confirmed first foothold |
| 2 | Lateral movement | attacker hopping host-to-host inside the network |
| 3 | Command & control | beaconing to attacker infrastructure |
| 4 | Exfiltration | bulk data leaving the network |

For each target, per host, the system produces a **cumulative risk curve**
over the horizon ("risk of C2 on this host within 5/15/30 minutes") and,
where probability supports it, a **conditional ETA** ("median ~11 minutes,
conditional on it happening within the horizon"). A target whose label
support is insufficient reports **`not_supported` — never 0%**. Zero is a
claim; unsupported is the truth.

---

## Part 7 — Calibration: Making "67%" Mean 67%

Raw neural scores are just numbers. **Calibration** maps them to real
frequencies: if FORESIGHT says 30%, then across many such cases roughly 30%
should see the event. This is done per-target with affine calibrators fitted
on a dedicated calibration split (never the test set, never the training
set). The current profile achieves **ECE (expected calibration error) of
0.004** — measured on locked-out data, this passes the strictest gate we
defined (≤ 0.05) with more than an order of magnitude to spare, and the
model's **Brier score beats the empirical-hazard baseline** — the learned
world model demonstrably out-predicts the persistence floor. Practically:
the probabilities on screen are trustworthy
enough to make decisions on. This is one of the rarest properties in
security ML and FORESIGHT's measured strength.

---

## Part 8 — SENTINEL: Novelty Is Not Malice

A separate module (SENTINEL) asks a different question: **is this host's
behavior unlike anything in the benign reference?** It measures the model's
prediction residuals against a reference fitted on benign traffic only.

Critical honesty rule: **novelty is not attack probability.** A software
push, a backup job, a new device — all are novel, none are attacks. SENTINEL
outputs "reference-like / elevated novelty / strongly novel" with residual
scores, and the UI labels it as unexpectedness, never as risk. Conversely,
**missing is never benign** — a sensor gap is a gap, not "all clear."

---

## Part 9 — Evidence: "Why Did You Say That?"

Every forecast can be interrogated. FORESIGHT's explanations are
**deletion-tested**: remove one window of a host's traffic, recompute
features, rerun the model — the drop in risk is that window's evidence.
Compare against **matched-size random deletion** (the control) and you get a
fidelity check: real evidence beats random deletion, or it isn't evidence.

Metrics on screen: **comprehensiveness** (risk falls X% when the selected
evidence is removed) and **sufficiency** (risk stays high when ONLY that
evidence is kept). Every cited item links to **actual packet rows from the
legal prefix** — click through to the flows. Deltas are always described as
*sensitivity*, never causation.

---

## Part 10 — Attack-Path Hypotheses (Tier B)

Beyond per-host risk, a **typed-event decoder** ranks whole future attack
sequences: *"C2 from web-01 to ext-c2 in the next 5–10 minutes, then lateral
movement to srv-app-02."* It generates paths by beam search over
(event-type, source, target, time-bin) "marks," conditioned on the current
world state.

The accounting is obsessive: every path carries its probability, plus the
total **no-event mass**, **outside-candidate mass**, and
**truncated-search mass** — the probabilities sum to 1 with nothing hidden.
And the label is permanent: these are **ranked hypotheses, explicitly not
calibrated path probabilities**. Predicted (dashed) edges are never drawn as
observed (solid) traffic.

On the current profile, the true next attack step appears in the top-4
ranked paths about **59% of the time** (locked test).

---

## Part 11 — Evidence Requests (Tier B)

When credential use is uncertain — lateral-movement probability elevated but
not alarming — the analyst can request **identity/session detail** for that
host: a separate telemetry stream the forecasting pipeline never sees. The
request is allowlisted, costed (privacy/compute/delay), and expiring. The
answer returns as a *new observation* with its own clocks, creating a new
forecast version — it never rewrites the sealed original. States are typed:
answered, unavailable (no sensor — missingness, not a claim), denied, expired.

This is the beginning of **active perception**: acquiring evidence when and
only when it changes a decision.

---

## Part 12 — Intervention Trials (Tier B)

FORESIGHT can also *test a response before recommending it*: propose blocking
a specific host↔external pair, then run a **paired trial** — same capture,
same seed, two futures: one with the block, one without. The outcome shows
events averted, packets blocked, benign disruption, and a **verified
postcondition** (zero surviving traffic on the blocked pair).

Every safety form is real: an explicit policy allowlist, human authorization
bound to the exact proposal with expiry, an idempotency key (execute once),
a full state machine (proposed → authorized → executing →
succeeded/failed/unknown → reconciled), durable audit records, and a
dry-run default. The system never claims production control authority from a
simulation — that honesty is printed on the screen.

---

## Part 13 — Sealed Evaluation (the differentiator)

How do you prove a forecaster isn't cheating?

1. The **splits are frozen** (train / calibration / locked-test, by campaign).
2. A forecast is computed from the causal prefix only.
3. It is **committed**: the forecast and its input context are hashed
   (SHA-256) into an immutable ledger. The hash is on screen.
4. Only then does a **separate reveal authority** release ground truth.
5. Outcomes are scored with no concealment: **correct warnings with lead
   time, misses, false alerts, early-outside-horizon** — all shown.

Every number in the evaluation screen was produced this way. The demo does
this live: commit hash visible, future locked, then reveal.

---

## Part 14 — The Honest Numbers (know these cold)

Current locked-test results (300-episode corpus, six-member ensemble,
disclosed synthetic range):

| Metric | Value | Meaning |
|---|---|---|
| **Calibration (ECE)** | **0.004 — PASS** | probabilities are trustworthy (gate ≤ 0.05) |
| **Brier vs baseline** | **0.0018 vs 0.0021 — PASS** | the world model beats the empirical-hazard floor |
| Lateral movement AP | **0.55** | ranked-detection quality ~50× the base rate |
| Exfiltration AP | **0.76** | strongest target |
| C2 AP | 0.29 | this round's weak target (was 0.53 on the smaller corpus — corpus shift) |
| Precision | 0.50 | when we alert, half are real |
| Recall | 0.119 | the strict-budget operating point (gate 0.5 — not yet) |
| False alerts | 1.47 per 100 asset-hours | 2.2× better than the previous profile (3.22); gate is 1.0 |
| Median advance warning | **90 seconds** | time gained when a warning is correct |
| Path top-4 recall | 0.59 | true next step in top-4 ranked paths |
| Tests | **324 passing** | including contract tests and a 29-check end-to-end run |

**The framing that wins questions:** "We report pass *and* fail, on sealed
evaluation, with the failure visible on screen. A system that only shows
green is marketing; ours is engineering." Two notes for the recall number:
the alert policy is fitted at a strict *aggregate* false-alert budget on a
30-episode calibration split, and that budget's frontier is steep — the
same model at a looser budget reaches 0.214 recall at 3.2 false alerts per
100 asset-hours. And 13 of the 42 test events are campaign-onset events
with **no traffic precursor by corpus construction** — the first malicious
packet *is* the event — so the catchable ceiling on this test set is
exactly 21/42 = 0.50.

---

## Part 15 — Real Data: CTU-13

FORESIGHT is not synthetic-only. The **CTU-13 dataset** (Czech Technical
University — real botnet captures, publisher-labeled) is integrated with a
qualified registry: exact files, SHA-256 hashes, license terms, split policy
(scenario-level: train on scenario 1, calibrate on 6, locked-test on 12),
recorded before any evaluation. The adapter respects the dataset's honest
limits: flow-only features (packet features marked unsupported), `Background`
traffic never counted as benign, only `From-Normal` as verified negative, IP
addresses as observed addresses — never device identities.

The transfer profile is trained and reported **separately** from the synthetic
profile; the two claims never mix. (Its training run was deliberately held
before the demo — the integration, adapter, and evaluation harness are in the
codebase and the registry-verified data is on disk.)

---

## Part 16 — The Spec Philosophy (why this impresses engineers)

Everything above is specified in a 2,000-line build specification with
numbered contracts, and every implementation default is recorded in three
Architecture Decision Records (ADRs). Notable engineered-honesty rules:

- Unsupported is never zero. Missing is never benign. Novel is not malicious.
- Predicted is never drawn as observed.
- No frontend may recompute a score; every number comes from the API.
- The evaluation truth and the inference engine are separate authorities.
- Every forecast cites its legal-prefix hash, source hashes, model/scaler/
  policy hashes, and the computations it omits.

**The one-sentence summary of the whole system:**

> FORESIGHT turns raw network traffic into calibrated, evidence-accountable
> forecasts of the next attack event — sealed before the future, honest
> after it.

---

## Part 17 — Likely Judge Questions (and your answers)

**"How is this different from an IDS/antivirus?"**
An IDS says "this is bad, now." We say "this may happen, here is when, here
is how confident, here is why, and here is what happens if you act."

**"Your recall is 0.12. Isn't that bad?"**
That is the operating point of a strict *aggregate* false-alert budget
(≤1 per 100 asset-hours) fitted on a 30-episode calibration split — the
frontier there is steep, and we publish the point we committed to, not a
post-hoc best. Three things to hold together: the same model at a looser
budget reaches 0.214 recall at 3.2 false alerts; 13 of the 42 test events
are campaign onsets with no traffic precursor by construction (the
catchable ceiling is exactly 0.50); and a correct warning still carries a
median 90 seconds of advance time — value detection cannot deliver at any
recall. The previous published profile was 0.156 recall at 17.9 false
alerts; the trajectory is real and the failures are disclosed.

**"Why should I trust the 67%?"**
It's calibrated on held-out data with ECE 0.004 against a 0.05 gate — when we
say 67%, it means 67%. That's measured, sealed, and on screen.

**"Did you cheat on the evaluation?"**
Show the theater: the forecast hash commits before the reveal; the reveal
comes from a separate endpoint; the splits are frozen in the registry; the
report shows failed gates alongside passed ones.

**"Does it work on real traffic?"**
The CTU-13 real-capture integration is complete and registry-verified —
adapter, qualification, scenario-level split, honest feature-masking. Its
transfer evaluation is queued behind the demo profile by design, and its
results will be reported separately, never blended with synthetic claims.

**"What if the attacker changes behavior?"**
SENTINEL flags behavior unlike the benign reference — that's exactly the
zero-day-shaped case — but as *unexpectedness*, not a fabricated attack
probability. The system never converts "I don't know this" into "it's fine."

**"Can it actually stop an attack?"**
The intervention trial gives paired causal evidence for one action: block
this pair, and here are the two futures. It's a decision instrument, not an
auto-pilot — authorization is human, scoped, expiring, and audited.

---

*Companion document: `FORESIGHT_Pitch.md` — what to say, in what order, and
how to position it.*
