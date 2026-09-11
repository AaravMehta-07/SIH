# UI Glow-Up Report

Frontend, UX, product-polish and frontend↔backend integration pass over the
FORESIGHT console. Everything below was actually run; nothing is claimed that
was not executed.

## 1. Major visual / design changes

- **New product-system CSS layer** (`styles.css` "V2 PRODUCT SYSTEM"):
  hairline separators and section primitives replace card-grid composition;
  one elevated surface tone for workspace regions; small-caps section
  headers; consistent radius/spacing tokens. Legacy classes remain only
  where still-rendered views use them.
- **Analyst workspace** (Forecast screen rebuilt): three-region composition —
  risk-sorted compact entity list (risk dot + identity + inline risk bar, no
  cards) | frameless observed/predicted network graph | selected-entity
  inspection panel (risk trajectory, per-target rows with ETA/abstention,
  SENTINEL state line, sealed-forecast hash with copy, and the intervene
  flow). The decision-cutoff control moved into the workspace toolbar — it is
  the time axis of everything on screen.
- **Seal/reveal theater** (Replay rebuilt): PAST OBSERVED | FUTURE LOCKED |
  FORECAST COMMITTED strip with hash chip and copy; a deliberate single
  "Reveal future" action; predicted-vs-actual board with advance-warning
  badges (Matched · +Xm warning / False alert / Early outside horizon /
  Missed) and a no-concealment scored-outcomes table.
- **Evidence tabs**: attribution, flagged traffic and evidence requests in
  one view with a proper tab strip (previously three separate surfaces).
- **Navigation reduced 8 → 6** (keyboard 1-6): Query folded into Evidence →
  "Evidence requests"; Action folded into the workspace as the progressive
  "Intervene" panel bound to the selected cutoff.
- Motion retained from the earlier motion pass (line draw-in via
  pathLength, staggered reveals, count-up, prefers-reduced-motion) and
  reined to 120-350ms.

## 2. Frontend architecture changes

- `App.tsx`: six-view IA; QueryView/ActionView removed as routes
  (ActionView deleted; its flow lives in `ForecastView`'s `Intervene`
  component).
- `ForecastView.tsx`: full rewrite as the workspace (entity list rows,
  graph region, detail blocks, intervene).
- `ReplayView.tsx`: rewritten as the theater + outcome board.
- `EvidenceView.tsx`: tabbed; attribution uses the typed API client
  (`api.evidence`) instead of a raw `fetch`.
- `PathsView.tsx`: v2 sections; frameless graph region.

## 3. Backend integrations repaired

- **Paths mass accounting**: the UI previously recomputed the mass total
  frontend-side; it now renders the backend's `mass_accounting_total`
  (restored on the `PathForecast` payload — it had been dropped in an
  earlier edit, breaking mass conservation display and a test).
- **Action panel unmount bug**: the console gated the authorize/execute
  panel on `authorizable`, whose server semantics are "can be authorized
  right now" (false once authorized). The panel now gates on
  `policy_failures.length === 0` and drives steps from `status`.
- **Pair-select collision**: the workspace cutoff select reused the
  `.action-select` class, so scripted flows and styling collided with the
  intervene pair selects; pair selects now use `.pair-select`.
- Provenance (`record.provenance`) is surfaced in the workspace: sealed
  forecast hash with copy, legal-prefix hash.

## 4. Mock / static data removed

None found on the demo path — the console was already fully backend-wired
(no fabricated metrics). The one frontend-side *computation* (mass total)
was removed in favor of the backend value (see §3).

## 5. Screens / components redesigned

Forecast (workspace) · Replay (theater) · Evidence (tabs) · Paths (v2
sections) · App shell (6 views). Sessions and Evaluation were reviewed and
retained (post-CTU-integration state was already structurally sound; catalog
availability states and capability disclosure were already wired).

## 6. API/schema inconsistencies discovered

- `mass_accounting_total` missing from the path forecast payload (fixed —
  server now returns it; type added).
- `authorizable` lifecycle semantics vs console gating (fixed in console;
  server semantics unchanged and are the correct ones).
- `identity_quality.coverage.covered_hosts` nesting (found earlier in this
  pass; already fixed in the console types before this report).

## 7. Tests added / updated

- `tests/unit/test_cli.py` (6 tests): dataset-registry qualification,
  receipt round-trip verification, release-verify optional-bundle skip.
- `tests/unit/test_api.py`: action-lifecycle durable-audit test; forecast
  provenance seal test (legal-prefix hash, artifact hashes, per-cutoff
  divergence).
- `scripts/e2e_real_scenario.py`: 29-check live end-to-end walkthrough
  (session → forecast → evidence → queries → action trial → reveal →
  evaluation → receipt verification) — executed against the trained
  snapshot bundle: **29/29 passed**.
- Verification walkers updated for the new IA (workspace selectors, theater
  reveal, evidence tab, intervene flow, keyboard 1-6).

## 8. Commands run

    python -m pytest -q                     (308 passed pre-UI-pass; suite
                                            re-run scheduled post-training)
    npm --prefix apps/console run build     (clean, ~211 kB JS / 65 kB gzip)
    python scripts/e2e_real_scenario.py     (29/29)
    python scripts/verify_console.py        (all screens, 0 console errors)
    python scripts/verify_layout.py         (PASS — no overflow 420-1440px,
                                            no label collisions, keyboard OK)

## 9. Build / test results

- Console: `tsc --noEmit` clean; vite build clean.
- Browser verification: all six screens + Tier B flows walked; **zero
  console errors**; no horizontal overflow at 420/640/900/1180/1440.
- Backend suite: green excluding bundle-dependent API tests, which
  deliberately wait for the in-flight retrain (SE01 refuses the
  mid-training hash state); full suite re-runs in final verification.

## 10. Remaining blockers

- Final measured numbers (locked-test gates, CTU transfer results) land
  with the retrain; README release notes point at the authoritative
  per-bundle evaluation reports by design.
- Legacy CSS layer not yet pruned (safe-but-carrying ~5 kB gzip of dead
  rules for views that still use them); prune is mechanical and deferred
  until after the demo video to avoid churn.

## 11. Backend features that currently limit frontend capability

- Real PCAP/CSV upload: the ingestion path exists (bounded PCAP worker,
  CTU registry qualification) but the console has no file-upload UI; the
  demo registers captures through the qualified CTU dataset registry.
  A drag-drop uploader would surface `POST /v1/sessions` upload flows.
- CTU catalog entries show as unavailable until `train_ctu_profile.py`
  runs (queued behind the synthetic retrain by design — its source-profile
  hash binding).

## 12. Screens / routes manually inspected

Sessions · Forecast workspace (entity select, graph select, horizon tabs,
cutoff change, intervene propose→authorize→dry-run) · Evidence (all three
tabs; attribution run; request executed with typed answer) · Paths
(hypotheses + candidate edges, graph/table toggle) · Replay (scrub, seal
strip, reveal, outcome board, scored table) · Evaluation · narrow-viewport
forecast (420px). Captured under `artifacts/screens/`.
