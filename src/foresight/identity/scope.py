"""Cohort assignment policy (Build Spec Section 8, G.2).

Cohort assignment is based on inventory or past-only topology, never on
attack labels. A 32-host demo is a workload fixture, not a coverage
assertion.
"""

from __future__ import annotations

import hashlib


def cohort_assignment(entity_ids: list[str], *, num_cohorts: int = 4) -> dict[str, int]:
    """Deterministic, label-blind cohort assignment by name hash."""
    if num_cohorts < 1:
        raise ValueError("num_cohorts must be >= 1")
    out: dict[str, int] = {}
    for entity_id in entity_ids:
        digest = hashlib.sha256(entity_id.encode("utf-8")).hexdigest()
        out[entity_id] = int(digest[:8], 16) % num_cohorts
    return out
