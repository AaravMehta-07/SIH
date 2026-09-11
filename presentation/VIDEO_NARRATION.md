# Demo Video — Scene-by-Scene Narration Script

**The video:** `artifacts/demo/foresight-demo.mp4` (1080p, ~1 min 40 s).
The `.webm` next to it is the raw recording the mp4 was converted from —
**the mp4 is the one to use.**

**How to use this:** play the video and speak the script. Each scene holds
long enough for its lines. Timestamps are approximate — the "you'll see"
cues are exact. If you prefer to drive the live system instead, this same
script works click-for-click on http://127.0.0.1:8001 (see
`docs/DEMO_GUIDE.md`).

**Total speaking time if you say everything: ~2 minutes.** For a 1-minute
slot, use only the **bold** lines.

---

## Scene 1 — Sessions screen (0:00 – 0:08)

*You'll see: the FORESIGHT catalog — capture cards, each labeled synthetic
(disclosed) or real, with a summary of the attack scenario it contains.*

Say:

> **"This is FORESIGHT — a network attack forecasting system. It predicts
> attacks before they unfold, from traffic alone.**
> Each card here is a capture we can replay through the full pipeline. I'll
> use this one — an external exploit hits a DMZ web server, then
> command-and-control, then lateral movement into the internal network."

---

## Scene 2 — The analyst workspace loads (0:08 – 0:20)

*You'll see: a three-panel screen appears — a ranked host list on the left,
a network graph in the middle, an inspection panel on the right. Rows fill
in with risk percentages and small risk bars.*

Say:

> **"The capture opens into the analyst workspace. On the left, every host
> in scope, ranked by forecast risk — the web server is already elevated.**
> In the center, the actual observed communication graph — who is talking
> to whom. Solid lines are observed traffic; dashed lines later will be
> *predicted* future communications — we never draw a prediction as an
> observed fact."

---

## Scene 3 — Selecting the compromised host (0:20 – 0:29)

*You'll see: the web-01 row clicked; the right panel fills — a colored risk
curve, a list of the five attack targets with percentages, ETA, a novelty
line, and a hash chip.*

Say:

> **"Clicking the web server: this is the forecast. Cumulative risk per
> attack type — command-and-control, lateral movement, exfiltration — as
> calibrated probability curves over time, not a single scary score.**
> Where probability supports it, a conditional ETA — 'median eleven minutes,
> given it happens in the horizon.' Sentinel, separately, tells us this
> behavior is unlike our benign reference — novelty is not an attack
> probability, and we never label it as one. And this forecast is already
> sealed — that's its SHA-256 hash, committed to an immutable ledger."

---

## Scene 4 — Horizon switch to 30 minutes (0:29 – 0:36)

*You'll see: the "30 min" tab clicked; the risk curve extends across a
longer time axis.*

Say:

> "The horizon is a first-class choice — five, fifteen, thirty minutes.
> The model rolls the network state forward in imagination, step by step,
> and asks at every step: would an event fire here? Longer horizons carry
> their uncertainty honestly."

---

## Scene 5 — Evidence (0:36 – 0:50)

*You'll see: the Evidence screen — four metric tiles, a diverging bar chart
of attribution deltas by time window, and a table of actual packet flows.*

Say:

> **"Why does it believe that? Every prediction is deletion-tested. Remove
> one window of this host's traffic, recompute the features, rerun the
> model — the risk drop is the evidence.**
> The comprehensiveness figure shows how much risk the selected evidence
> explains; the random-deletion control proves it's signal, not noise. And
> every claim traces to real packet rows from the legal prefix —
> nothing is invented."

---

## Scene 6 — Sealed replay + REVEAL (0:50 – 1:08) — **the climax, slow down here**

*You'll see: the Replay screen — a strip reading "Past · observed | FUTURE
LOCKED | Forecast committed" with the hash, a scrub slider, and a large
"Reveal future" button. The button is clicked; a two-column board appears:
Predicted vs Actual, with a green "Matched" badge showing the advance
warning.*

Say:

> **"This is what makes our evaluation provable. Everything left of the
> lock is what the model saw. Everything right was locked away — the
> forecast endpoint cannot read it. The forecast was committed, with this
> hash, before any reveal.**
> Now we reveal the actual future: predicted C2 at high risk — actual C2
> observed — with advance warning measured in minutes. Matched.
> Misses and false alerts are scored on this same screen with nothing
> hidden. **No other system shows you its failures. We seal before, and
> we're honest after.**"

---

## Scene 7 — Evaluation (1:08 – 1:17)

*You'll see: the Evaluation screen — gate rows (some PASS in green, some
FAIL in red), metrics, a reliability diagram.*

Say:

> "The locked-test evaluation: predeclared gates, sealed before the reveal.
> Calibration passes at 0.004 error — when FORESIGHT says 67%, it means
> 67%. And the Brier score now beats the empirical-hazard baseline — the
> learned world model out-predicts the persistence floor; that gate failed
> on our previous profile. False alerts: cut from 3.2 to 1.5 per hundred
> asset-hours. The recall gate we report at its measured frontier — a
> third of these test events are campaign onsets with no traffic precursor
> at all, and the catchable ceiling is disclosed. This is a scientific
> verification interface, not a scoreboard."

---

## Scene 8 — Attack-path hypotheses (1:17 – 1:26)

*You'll see: the Paths screen — ranked rows, each a chain of colored
event → host → host steps with probabilities, plus mass tiles.*

Say:

> "Beyond single events — whole attack paths: C2 from this host to that
> address, then lateral movement to the file server. Beam search with
> complete probability accounting; every bit of mass is accounted for. The
> true next step appears in our top-four ranked paths about 59% of the
> time — labeled what it is: ranked hypotheses, never 'calibrated attack
> path probability.'"

---

## Scene 9 — Close on the workspace (1:26 – end)

*You'll see: back on the forecast workspace.*

Say:

> **"FORESIGHT: calibrated forecasts of the next attack event — evidence
> behind every number, sealed before the future, honest after it. The
> question isn't whether you can detect the attack you're already
> suffering. It's whether you can see the next one coming. We can."**

---

## If judges ask while the video plays

- **"Is this real data?"** → The captures here are a disclosed synthetic
  range engineered with real traffic signatures; the CTU-13 real-botnet
  integration is registry-verified on disk and reported separately — the
  two claims never mix.
- **"How accurate?"** → Calibration error 0.004 on locked-out data; Brier
  beats the empirical-hazard baseline (0.0018 vs 0.0021); lateral movement
  AP 0.55, exfiltration 0.76 — 50×+ over base rate; 90 seconds median
  advance warning. Recall at the strict aggregate false-alert budget is
  0.12 — published as a failing gate, with the onset-event ceiling
  disclosed (13 of 42 test events have no traffic precursor by
  construction).
- **"What's the model?"** → Graph attention network over the host
  communication graph, per-host recurrent memory, a global LSTM, and a
  learned transition that rolls the state forward in imagination — six
  independently trained architectures voting.
- **"Can it act?"** → Yes — paired intervention trials: block a channel and
  watch two futures, with human authorization, expiry, and audit. Happy to
  show it live.
