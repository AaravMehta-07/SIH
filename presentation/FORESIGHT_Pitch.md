# FORESIGHT — The Pitch

*What to say, in what order, and how to win the room. Pair this with
`FORESIGHT_Complete_Guide.md` — this file is the speak, that file is the
know.*

---

## The 30-second opener (say this first)

> "Every security product on the market answers *'are we under attack right
> now?'* — and by the time the answer is yes, the attacker is already inside.
> FORESIGHT answers the question that actually matters: **what is about to
> happen, to which host, how likely, how soon — and what should we do about
> it while there's still time.** It's a network attack *forecaster*: it turns
> raw traffic into calibrated predictions of the next attack event —
> command-and-control, lateral movement, exfiltration — with the evidence
> behind every prediction and a sealed, tamper-proof evaluation to prove the
> numbers are real."

---

## The problem, framed to sting (1 minute)

- Detection is a **losing race**: the attacker needs one mistake, the
  defender needs to catch every move. Average breach dwell time is measured
  in weeks; detection finds attacks *after* persistence, *after* lateral
  movement, often *after* exfiltration.
- SOC analysts drown in alerts: industry false-positive rates are ~90%+.
  Each alert costs triage time; fatigue makes real ones slip through.
- SIH26153 asks for the actual answer: **forecasting** — predicting the
  attack while it is still forming, from network traffic alone.
- The three hard parts nobody solves casually: **rare events** (99%+ of
  traffic is benign), **no peeking at the future** (easy to fake, hard to
  enforce), and **probabilities you can actually trust** (a raw neural score
  is not a probability). FORESIGHT is engineered around all three.

---

## How it works — the spoken 90 seconds

> "Under the hood: every packet is stamped with three clocks — when it
> happened, when the sensor could know it, when we received it. A forecast at
> any moment uses only what was *knowable* then — that's the causal prefix,
> and it's why our evaluation can't cheat. On top of that we compute an exact
> feature registry — 44 measurements per host, 11 per connection, 24
> network-wide — and each feature carries a validity bit: if the data source
> can't measure something, we mark it unsupported. We never invent data.
>
> The core is a graph-temporal world model: a graph attention network reads
> the host-communication graph; every host carries its own recurrent memory
> of its history; a global LSTM holds network-wide context. Then the part
> that makes it a *forecaster* — a learned transition model rolls that state
> forward in imagination, step by step, and decoder heads ask, at every
> imagined step: would a C2 event fire here? Lateral movement? Exfiltration?
> Out comes a cumulative-risk curve per host per attack type, over a 30-minute
> horizon, with conditional ETAs.
>
> Six independently-trained model architectures vote, and their calibrated
> distributions are averaged — disagreement is surfaced, not hidden. Raw
> scores then pass through per-target calibration so that when the screen
> says 67%, it means 67%. And SENTINEL, a separate module, flags behavior
> unlike our benign reference — labeled as novelty, never as attack
> probability."

---

## What's UNIQUE about FORESIGHT (the moot — lead with these)

### 1. Sealed evaluation — we can prove we're not cheating
No competitor will show you this. Every forecast is **hash-committed to an
immutable ledger before the future is revealed**; a separate authority
releases ground truth; outcomes — hits with lead time, misses, false alarms —
are scored with nothing hidden. Judges can select a moment in the replay,
watch the commitment, then watch the reveal. **Any team can claim accuracy;
we can prove the measurement.**

### 2. Calibration as a first-class property
Our probabilities pass a strict calibration gate (ECE 0.004 vs 0.05 target)
on locked-out data, and the world model **beats the empirical-hazard
baseline on Brier score** — the learned dynamics demonstrably out-predict
the persistence floor. Security dashboards almost never measure either.
It's the difference between a scary-looking number and a
**decision-grade number**.

### 3. Evidence accountability, not "the AI said so"
Every prediction is **deletion-tested**: remove a piece of the traffic,
recompute, rerun — the risk drop is the evidence, checked against
matched-random controls. Every claim traces to real packet rows. We label it
sensitivity, not causation. **Explainability with a fidelity measurement —
not attention heatmaps dressed up as truth.**

### 4. Forecasting the *sequence*, not just the event
A typed-event decoder ranks whole attack paths — "C2 to this external
address, then lateral movement to the file server" — with complete
probability accounting (no-event mass, outside-candidate mass, truncated
search mass; it all sums to 1). Honest labels: ranked hypotheses, never
"calibrated attack path probability."

### 5. Intervention with paired causal evidence
Propose blocking a C2 channel; FORESIGHT runs the **same capture into two
futures** — with and without the block — and shows events averted, benign
disruption, and a verified postcondition. With explicit human authorization,
expiry, idempotency, and a full audit trail. **No other student project
treats the response side with this discipline.**

### 6. Novelty ≠ malicious, missing ≠ benign
SENTINEL reports unexpectedness against a benign reference — honestly
separated from risk. A system that converts "I don't recognize this" into
"80% attack" is lying; ours never does.

### 7. Real-data integration done properly
CTU-13 (real botnet captures): registry-verified files with SHA-256s and
license terms, scenario-level frozen splits, flow-only features honestly
masked as unsupported where the data can't measure them, `Background` never
counted as benign. **Real-data rigor, not a screenshot claim.**

### 8. Production-grade engineering
324 automated tests, contract-first typed APIs, three Architecture Decision
Records, a 29-check end-to-end harness, offline-first with zero cloud
dependency, quota-hardened API, durable audit ledger. This isn't a notebook —
it's a system.

---

## What we did BEYOND the problem statement

The statement asks for attack forecasting from traffic. We delivered that —
plus the parts that make it *usable and provable*:

- **The sealed-verification framework** (commitment, reveal, scoring) — the
  statement doesn't ask for provable evaluation; without it, any accuracy
  claim is unverifiable.
- **The evidence & explanation layer** — forecasting without "why" is a
  black box no analyst would act on.
- **The alert-budget policy layer** — thresholds fitted at a declared
  false-alert budget per 100 asset-hours, because raw scores aren't
  deployable.
- **The identity/evidence-request modality** (Tier B) — requesting exactly
  the missing information that would change a decision.
- **The intervention trial framework** (Tier B) — moving from "predict" to
  "predict, then test the response."
- **A complete analyst product** — six-screen workspace, sealed-replay
  theater, honest evaluation screen — designed as an instrument a SOC
  analyst would actually use.
- **A full specification + ADR discipline** — 2,000-line build spec with
  numbered contracts; every default recorded and defensible.

---

## Why we're better than the other teams (say it confidently)

1. **They'll show dashboards; we show sealed proof.** Ask any competitor how
   they know their accuracy isn't leaked or cherry-picked. We hash-commit
   before reveal, on frozen splits.
2. **They'll show scores; we show calibrated probabilities.** Ask what their
   ECE is. Ours is 0.004 on locked-out data, and our Brier score beats the
   empirical-hazard baseline — measured, not asserted.
3. **They'll show detection; we show forecasting with lead time.** 90-second
   median advance warning on correct alerts — time to act, not time to
   investigate.
4. **They'll say "AI-powered"; we say which AI, why, and where it's honest
   about its limits.** Heterogeneous ensemble, per-target calibration,
   novelty separated from risk, unsupported ≠ zero.
5. **They'll demo happy paths; we demo the failure modes too.** Misses and
   false alerts scored on screen. Judges trust systems that don't hide.
6. **Engineering substance:** 324 tests, real datasets integrated with
   verified provenance, safe-intervention machinery with audit trails.

---

## Business value (for the "why does this matter" question)

- **Dwell time is money.** Every minute between foothold and detection is
  attacker freedom. Forecasting converts detection time into *preparation*
  time — block the C2 channel before it opens, isolate the host before
  lateral movement, watch the database before exfiltration begins.
- **Analyst economics.** With ~50% precision at a strict aggregate
  false-alert budget, each alert is worth triaging — versus industry ~10%
  precision where 9 of 10 alerts are noise. Calibrated probabilities let a
  SOC *rank* work by expected value.
- **Deployment reality: traffic-only, offline-first.** No agents to deploy on
  endpoints, no cloud dependency, works on mirrored/span traffic. The
  easiest possible deployment surface for a network team — and the only one
  viable for air-gapped or classified environments (this is an NTRO
  problem).
- **Evidence-grade output.** Every prediction cites its traffic evidence and
  is sealed with a hash — usable in incident reports, audits, and post-mortems.
- **Extensible platform.** Identity evidence requests and intervention
  trials are the foundation of closed-loop response; the architecture
  (tenant scoping, quotas, typed contracts, versioned models) is
  production-shaped.

**One line for the judges:** *"We didn't build a better alarm — we built the
instrument that tells you what happens next, why it believes that, and what
acting now is worth."*

---

## Numbers to quote (memorize these five)

1. **ECE 0.004** — calibration error on locked-out data (target ≤ 0.05): **PASS**
2. **Brier 0.0018 vs baseline 0.0021** — the world model beats the
   empirical-hazard floor: **PASS** (a gate the previous profile failed)
3. **Exfiltration AP 0.76, lateral movement AP 0.55** — 50×+ over base rate
4. **90 seconds** — median advance warning on correct forecasts
5. **324 tests passing** — contract tests plus a 29-check end-to-end
   sealed-workflow harness

And the honest two, said proudly: false alerts cut from 3.22 to **1.47 per
100 asset-hours** (gate 1.0 — 2.2× better, still above) at event recall
**0.119** — the steep frontier of a strict aggregate alert budget on a
30-episode calibration split, *published as-is, on sealed evaluation*. For
context on the recall ceiling: 13 of the 42 test events are campaign-onset
events with no traffic precursor by corpus construction — no traffic-only
forecaster can see them; the catchable ceiling on this test set is exactly
21/42 = 0.50, and the same model run at a looser budget reaches 0.214
recall at 3.2 false alerts. We report the strict-budget operating point.

---

## Closing line

> "FORESIGHT: calibrated forecasts of the next attack event, evidence behind
> every number, sealed before the future, honest after it. The question isn't
> whether you can detect an attack you're already suffering — it's whether
> you can see the next one coming. We can."
