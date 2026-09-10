"""Local storage: SQLite metadata + immutable objects (Build Spec E.1-E.4).
"""

from .objects import ObjectStore
from .store import MetadataStore, Storage, StoreError

__all__ = ["ObjectStore", "MetadataStore", "Storage", "StoreError"]
