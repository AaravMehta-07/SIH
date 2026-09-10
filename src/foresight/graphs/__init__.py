"""Graph collation (Build Spec Appendix G.2, S).

``collate`` turns raw D.5 windows into the frozen ``GraphWindowBatch``
tensor contract: values-then-validity layouts (88/22/48), batch-global node
rows with ``(batch, slot_index)`` uniqueness, no cross-graph edges (GR01),
padding that never changes valid-node results (GR02).
"""

from .collate import (
    collate_batch,
    collate_windows,
    entity_union,
    stack_candidates,
    stack_windows,
)

__all__ = [
    "collate_batch",
    "collate_windows",
    "entity_union",
    "stack_candidates",
    "stack_windows",
]
