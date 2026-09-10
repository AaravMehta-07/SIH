# FORESIGHT Console

React analyst interface for the FORESIGHT offline attack-forecasting system
(SIH26153). Screens follow Build Spec Appendix K.2: Sessions, Forecast,
Evidence, Replay, Evaluation. The console displays API values only — it never
recalculates probabilities frontend-side.

## Run

1. Start the API (from the repository root, with the Python 3.10 interpreter
   that has PyTorch installed):

   ```
   python scripts/serve_console.py
   ```

   The server serves the API on `http://127.0.0.1:8001` (override with the
   `FORESIGHT_CONSOLE_PORT` environment variable) and, when
   `apps/console/dist` exists (after `npm run build`), serves the built
   console at the same address.

2. Either open `http://127.0.0.1:8001` (production build), or for frontend
   development:

   ```
   npm install
   npm run dev
   ```

   and open `http://localhost:5173` (Vite proxies `/v1` and `/health` to the
   API server).

## Demo profile

Until real data and trained weights exist, the server runs the **demo
profile**: ensemble members trained briefly on the scripted synthetic
scenarios in `src/foresight/api/scenarios.py` (`scripts/train_demo_profile.py`),
with I.4 hazard calibrators fitted on held-out synthetic episodes. Every API
response carries the `weights_profile` disclosure and the console shows the
amber banner. Interface semantics only — no measured performance is claimed.

## Structure

```
src/
  api.ts          typed API client (Appendix L subset)
  types.ts        payload types (D.7 semantics)
  App.tsx         shell: nav, status banner (Section 18 axes), disclosure
  components/     StatusBanner, RiskChart (SVG), GraphView (SVG)
  views/          the five K.2 screens
```

Hand-rolled SVG charts and graph — no chart dependencies. Keyboard-accessible
controls, textual status in addition to color, and distinct legends for
observed vs predicted vs late-observed edges (K.3).
