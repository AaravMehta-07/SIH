# FORESIGHT

Offline-first, evidence-accountable **network attack forecasting** system for
**SIH26153 — AI based Network Attack Forecasting from Network Traffic Data** (NTRO).
Team: Deja Vu T-1.

The authoritative engineering contract is [`FORESIGHT_Build_Spec.md`](FORESIGHT_Build_Spec.md)
(schema `foresight.core.2026-09`). The visual reference is
[`FORESIGHT_Final_Architecture.pdf`](FORESIGHT_Final_Architecture.pdf). Team work
distribution: [`docs/FORESIGHT_Team_Work_Distribution.pdf`](docs/FORESIGHT_Team_Work_Distribution.pdf).

**Status: Tier A + Tier B complete, real-data (CTU-13) integration included.**
I.5 heterogeneous ensemble, typed-event attack-path engine, identity adapter +
evidence requests, paired range-action trials, and a qualified CTU-13
real-flow transfer profile (ADR-003). The synthetic pipeline runs end-to-end
on disclosed synthetic captures; the CTU-13 profile runs on real
capture-derived flows under disclosed flow-only limitations. Accuracy claims
are bounded by the evaluation gates in Build Spec Section 29 and are reported
per profile — synthetic evidence and real-flow evidence are never mixed.

## Repository layout

```
configs/            Frozen configuration (Section 35 is the only default profile)
scripts/            Reproducible entry points (train_profile, train_paths,
                    evaluate_profile, serve_console, verify_console/layout)
src/foresight/
  contracts/        Typed records, canonical JSON, capability/quality reports (D)
  ingest/           Flow segmentation, TCP attempt semantics, synthetic capture
                    generator, versioned CSV profiles (F), identity auth-log
                    adapter (Tier B)
  identity/         Address/entity resolution with binding intervals, scope (G)
  features/         The exact 44/11/24 registry, 30s prefix windows, F.8 transforms
  graphs/           Collation into the frozen GraphWindowBatch contract (G.2)
  labels/           Section-11 ontology, D.6 target construction (training-only)
  data/             Episode corpus, M.1 splits, clip datasets, typed chain
                    labels for path training (G.4, N.2)
  models/           GAT encoder, entity GRU, global LSTM, residual transition,
                    heads, decoders, survival transforms (H), I.5 heterogeneous
                    member variants (reference/gate/wide)
  training/         Section-15 objectives (censored survival NLL with the A12
                    positive-weight correction), curriculum trainer (I.1)
  calibration/      I.4 affine hazard calibrators (natural-prevalence fit)
  runtime/          Section-26 inference core + I.5 ensemble
  sentinel/         J.1 residual/embedding novelty reference and scoring
  explain/          K.1 grouped-deletion attribution + Tier A candidate edges
  paths/            Tier B next-mark decoder, canonical candidates, beam search
                    with explicit mass accounting (Section 20, N.2)
  queries/          Tier B evidence requests: transparent rule, allowlist,
                    typed answer states (Section 21, N.3)
  actions/          Tier B action proposals, Section-23 state machine, paired
                    synthetic-range trials (Sections 22-23, O)
  evaluation/       M.3 event matching, M.4 metrics, gates, bootstrap (M)
  storage/          SQLite metadata + immutable content-addressed objects (E)
  api/              FastAPI service: bundle loading (I.6 verified), episode
                    sessions, sealed forecasts, evidence, reveal, queries,
                    actions (L)
  cli/              L.4 command surface (doctor, train, evaluate, serve, replay)
apps/console/       React analyst console — the eight K.2 screens
tests/              Contract/unit tests (Appendix R catalogue IDs in docstrings)
docs/adr/           ADR-001 model defaults, ADR-002 Tier B defaults
```

## Quick start

Python 3.10 with PyTorch (CUDA), PyTorch Geometric, NumPy, PyYAML; the console
needs Node for building. Run everything with the Python 3.10 interpreter.

```
# 0. qualify registered real datasets (Section 6) — CTU-13 scenarios 1/6/12
python -m foresight.cli data qualify --manifest configs/datasets/ctu13.json

# 1. train the Section-35 profile: reference seeds 0-2, gate seeds 0-1,
#    wide seed 0 — six heterogeneous I.5 members on the 300-episode corpus
#    (~4-6 h on an RTX 4060 laptop; per-epoch checkpointed, safe to re-run
#    and resume; stale checkpoints are fingerprint-rejected automatically)
python scripts/train_profile.py

# 2. locked-test evaluation of the synthetic profile (M.1-M.5)
python scripts/evaluate_profile.py

# 3. train the Tier B next-mark path decoder over the chain labels (N.2)
python scripts/train_paths.py

# 4. fine-tune + evaluate the CTU-13 real-flow transfer profile (ADR-003;
#    runs only after step 1 — it binds the synthetic profile's manifest hash)
python scripts/train_ctu_profile.py

# 5. build the console (once)
cd apps/console && npm install && npm run build && cd ../..

# 6. serve API + console
python scripts/serve_console.py        # http://127.0.0.1:8001
```

Without step 1 the console falls back to untrained reference weights with an
explicit disclosure on every screen — interface semantics, not performance.
Without step 3 the Paths screen reports `not_supported` (typed paths are a
separate model; the Tier A candidate-edge projection still renders). Without
step 4 the two real-capture catalog entries are listed as unavailable.

## Command surface (L.4)

```
python -m foresight.cli doctor                      # deps, hashes, golden fixture
python -m foresight.cli data qualify --manifest …   # verify a dataset registry
python -m foresight.cli train / evaluate            # Section-35 pipeline
python -m foresight.cli bundle verify --bundle …    # hash-verified bundle load
python -m foresight.cli replay predict --episode campaign:index
python -m foresight.cli replay verify --receipt …   # E.2/E.3 receipt check
python -m foresight.cli release verify --manifest configs/release.json
python -m foresight.cli serve
```

Exit codes: 0 success, 2 invalid input, 3 missing dependency, 4 failed gate,
5 inconclusive evaluation. The remaining proposed L.4 pipeline-step commands
(`data extract/split`, `features build`, `labels build`, `baseline train`) are
provided by the scripts and library modules above; `baseline` runs inside
`evaluate` (M.2).

## Real data (CTU-13)

`configs/datasets/ctu13.json` is the qualified registry: scenario 1 trains,
scenario 6 calibrates, scenario 12 is the locked test; the split unit is the
whole scenario (M.1). The profile is a flow-only transfer (ADR-003): packet
features carry validity false, `Background` is never benign, only
`From-Normal` is a verified negative, and only task 0 plus explicitly
CC/C&C-labeled task 3 are supported. The public scenario-6 PCAP is botnet-only
and is disclosed as such — it is a parser/ingestion demonstration, not a
mixed-capture claim.

## What the demo shows

- **Sessions** — six curated captures (benign baseline, benign drift, and four
  attack families) through the real pipeline.
- **Forecast** — cumulative-risk timelines per target with frozen alert
  thresholds, conditional ETAs with their conditions, entity × target matrix,
  tactic tags, SENTINEL novelty, sealed record hash.
- **Evidence** — grouped-deletion attribution with comprehensiveness /
  sufficiency fidelity against matched random controls; every cited flow is a
  legal-prefix packet.
- **Replay** — advance the decision cutoff, forecast, then reveal the withheld
  ground truth: correct warnings with lead times, misses, false alerts.
- **Paths** (Tier B) — typed-event next-mark hypotheses with beam search and
  explicit mass accounting: ranked paths, no-event mass, outside-candidate
  mass, truncated search mass — ranked hypotheses, never labeled calibrated
  attack-path probabilities.
- **Query** (Tier B) — one targeted evidence request: identity/session detail
  for uncertain credential use, proposed by a transparent rule, answered from
  the separate identity modality with typed unavailable/denied/expired states.
- **Action** (Tier B) — propose a `block_edge` action bound to the committed
  forecast, pass the scope allowlist and explicit human authorization, then
  run the paired no-action/action trial in the disclosed synthetic range:
  events averted, packets blocked, benign disruption, verified postcondition.
- **Evaluation** — locked-test gates (pass/fail/inconclusive), reliability
  diagram, per-target average precision, baselines.

## Honesty contract

The corpus is synthetic and disclosed as such. Unsupported targets return
`not_supported`, never zero. Benign drift triggers novelty without becoming an
alert. Novelty is unexpectedness, not an attack probability. Deltas from
deletion are sensitivity, not causal effects. Statistical gates on the
synthetic corpus are evidence about the corpus, not real-world performance.
The CTU-13 profile adds real-flow evidence under its own disclosed limits
(flow-only features, scenario-level splits, botnet-only public PCAP); its
gates are reported independently and may be inconclusive where the public
labels provide no forecastable onset.

## Release notes (T.3)

Supported per profile (authoritative source: the `evaluation_report.json`
inside each verified bundle — `foresight release verify` checks them):

- **Synthetic profile** (`artifacts/profile`): 300-episode disclosed corpus,
  six heterogeneous members. Supported targets/horizons, gates and metrics:
  see the bundle's evaluation report.
- **CTU-13 transfer profile** (`artifacts/ctu13/profile`, optional): tasks 0
  and CC-labeled task 3 only; scenario-split evidence; packet features
  unsupported (validity false); background excluded from benign.
- Known blind spots: tasks without fitted calibrators abstain honestly;
  alert thresholds are fitted on small calibration splits and generalize
  imperfectly (documented per report); the paired range is synthetic and its
  attacker has no backup channel (Tier C).
- Required sensors: full-packet PCAP or the synthetic generator for the core
  profile; binetflow flows for the CTU profile.
- Disabled extensions: actions are unavailable on fixed real captures;
  endpoint/identity telemetry is synthetic-only; Tier C research items
  (active sensing, causal action models, adaptive attackers, controlled
  learning) remain out of scope.

## Environment

```
python -m pip install -e ".[dev]"
```

Run tests with the torch-enabled interpreter (Python 3.10):

```
python -m pytest tests -q
```
