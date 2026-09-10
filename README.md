# FORESIGHT

Offline-first, evidence-accountable **network attack forecasting** system for
**SIH26153 — AI based Network Attack Forecasting from Network Traffic Data** (NTRO).
Team: Deja Vu T-1.

The authoritative engineering contract is [`FORESIGHT_Build_Spec.md`](FORESIGHT_Build_Spec.md)
(schema `foresight.core.2026-09`). The visual reference is
[`FORESIGHT_Final_Architecture.pdf`](FORESIGHT_Final_Architecture.pdf). Team work
distribution: [`docs/FORESIGHT_Team_Work_Distribution.pdf`](docs/FORESIGHT_Team_Work_Distribution.pdf).

**Status: Tier A build in progress.** The pipeline runs end-to-end on disclosed
synthetic captures. No real-network measured performance is claimed; accuracy
claims require the evaluation gates in Build Spec Section 29.

## Repository layout

```
configs/            Frozen configuration (Section 35 is the only default profile)
scripts/            Reproducible entry points (train_profile, evaluate_profile, serve_console)
src/foresight/
  contracts/        Typed records, canonical JSON, capability/quality reports (D)
  ingest/           Flow segmentation, TCP attempt semantics, synthetic capture
                    generator, versioned CSV profiles (F)
  identity/         Address/entity resolution with binding intervals, scope (G)
  features/         The exact 44/11/24 registry, 30s prefix windows, F.8 transforms
  graphs/           Collation into the frozen GraphWindowBatch contract (G.2)
  labels/           Section-11 ontology, D.6 target construction (training-only)
  data/             Episode corpus, M.1 splits, clip datasets (G.4)
  models/           GAT encoder, entity GRU, global LSTM, residual transition,
                    heads, decoders, survival transforms (H)
  training/         Section-15 objectives (censored survival NLL with the A12
                    positive-weight correction), curriculum trainer (I.1)
  calibration/      I.4 affine hazard calibrators (natural-prevalence fit)
  runtime/          Section-26 inference core + I.5 ensemble
  sentinel/         J.1 residual/embedding novelty reference and scoring
  explain/          K.1 grouped-deletion attribution + Tier A candidate edges
  evaluation/       M.3 event matching, M.4 metrics, gates, bootstrap (M)
  storage/          SQLite metadata + immutable content-addressed objects (E)
  api/              FastAPI service: bundle loading (I.6 verified), episode
                    sessions, sealed forecasts, evidence, reveal (L)
  cli/              L.4 command surface (doctor, train, evaluate, serve, replay)
apps/console/       React analyst console — the five K.2 screens
tests/              Contract/unit tests (Appendix R catalogue IDs in docstrings)
```

## Quick start

Python 3.10 with PyTorch (CUDA), PyTorch Geometric, NumPy, PyYAML; the console
needs Node for building.

```
# 1. train the Section-35 profile (synthetic corpus, ~1-3 h on an RTX 4060)
python scripts/train_profile.py

# 2. produce the locked-test evaluation report (M.1-M.5)
python scripts/evaluate_profile.py

# 3. build the console (once)
cd apps/console && npm install && npm run build && cd ../..

# 4. serve API + console
python scripts/serve_console.py        # http://127.0.0.1:8001
```

Without step 1 the console falls back to untrained reference weights with an
explicit disclosure on every screen — interface semantics, not performance.
With it, five independently trained ensemble members (seeds 0-4) run the full
pipeline: packet telemetry → eligibility-gated windows → the 44/11/24 feature
registry → calibrated cumulative-risk forecasts with conditional ETAs, sealed
records with publication receipts, SENTINEL novelty and deletion-tested
evidence.

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
- **Evaluation** — locked-test gates (pass/fail/inconclusive), reliability
  diagram, per-target average precision, baselines.

## Honesty contract

The corpus is synthetic and disclosed as such. Unsupported targets return
`not_supported`, never zero. Benign drift triggers novelty without becoming an
alert. Novelty is unexpectedness, not an attack probability. Deltas from
deletion are sensitivity, not causal effects. Statistical gates on the
synthetic corpus are evidence about the corpus, not real-world performance.

## Environment

```
python -m pip install -e ".[dev]"
```

Run tests with the torch-enabled interpreter (Python 3.10):

```
python -m pytest tests -q
```
