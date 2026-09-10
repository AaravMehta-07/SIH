"""Serve the FORESIGHT console API + built React console.

``python -m foresight.api.server`` requires the package to be importable
(editable install); this launcher works from a plain checkout by putting
``src/`` on ``sys.path`` first.

Usage (from the repository root)::

    python scripts/serve_console.py            # default port 8001
    set FORESIGHT_CONSOLE_PORT=8080 && python scripts/serve_console.py

Serves the API on http://127.0.0.1:8001 and, once ``apps/console/dist``
exists (``npm run build``), the built console at the same address.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from foresight.api.server import main  # noqa: E402

if __name__ == "__main__":
    os.environ.setdefault("FORESIGHT_CONSOLE_PORT", "8001")
    main()
