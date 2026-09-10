# FORESIGHT

Offline-first, evidence-accountable **network attack forecasting** system for
**SIH26153 — AI based Network Attack Forecasting from Network Traffic Data** (NTRO).
Team: Deja Vu T-1.

The authoritative engineering contract is [`FORESIGHT_Build_Spec.md`](FORESIGHT_Build_Spec.md)
(schema `foresight.core.2026-09`). The visual reference is
[`FORESIGHT_Final_Architecture.pdf`](FORESIGHT_Final_Architecture.pdf). Team work
distribution: [`docs/FORESIGHT_Team_Work_Distribution.pdf`](docs/FORESIGHT_Team_Work_Distribution.pdf).

**Status: Tier A build in progress.** No trained weights, measured performance or
completed software are claimed. Accuracy claims require the evaluation gates in
Build Spec Section 29.

## Repository layout

```
configs/            Frozen configuration (Section 35 is the only default profile)
docs/               Team work distribution, architecture decision records
src/foresight/
  models/           Core world model: GAT encoder, entity GRU, global LSTM,
                    transition prior, rollout, heads, decoders, survival transforms
tests/              Contract/unit tests (Appendix R catalogue IDs in docstrings)
```

Module areas owned by other teammates (ingest/, identity/, features/, graphs/,
labels/, data/, training/, calibration/, sentinel/, evaluation/, explain/,
runtime/, storage/, api/, apps/console/) are added as they are implemented; see
the work distribution PDF and Build Spec Appendix C.2 for the target layout.

## Environment

Python 3.10 with PyTorch (CUDA), PyTorch Geometric, NumPy, PyYAML.

```
python -m pip install -e ".[dev]"
```

## Tests

```
python -m pytest
```

Test IDs reference the automated test catalogue in Build Spec Appendix R.3
(MO01-MO05 model contracts, GR01-GR02 graph batching, ID02 identity
equivariance, CA01-CA03 calibration math, golden examples 1 and 3).

## Implementation decision records

- [ADR-001: World Model Implementation Defaults](docs/adr/ADR-001-model-implementation-defaults.md)
