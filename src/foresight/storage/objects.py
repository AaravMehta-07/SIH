"""Immutable content-addressed object store (Build Spec E.1).

Object keys are server-generated (``objects/<sha-prefix>/<sha256>``), written
to a temporary sibling then atomically renamed, with content hash verified
after writing. Symlinks/reparse-point escapes are refused. A metadata
transaction never claims a durable object exists before the object is
flushed and verified.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

_NS_SAFE = frozenset("0123456789abcdef")


class StoreError(RuntimeError):
    """Raised on storage integrity or path-safety violations."""


class ObjectStore:
    """Content-addressed immutable object files under a configured root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_safe(self, key: str) -> Path:
        if not key.startswith("objects/"):
            raise StoreError(f"object keys must start with objects/: {key!r}")
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root)):
            raise StoreError(f"path escape refused: {key!r}")
        digest = key.rsplit("/", 1)[-1]
        if len(digest) != 64 or not set(digest) <= _NS_SAFE:
            raise StoreError(f"invalid object digest in key: {key!r}")
        return path

    def put(self, content: bytes) -> tuple[str, str]:
        """Store content; returns ``(key, sha256)`` after verification."""
        digest = hashlib.sha256(content).hexdigest()
        key = f"objects/{digest[:2]}/{digest}"
        path = self._resolve_safe(key)
        if path.exists():
            existing = hashlib.sha256(path.read_bytes()).hexdigest()
            if existing != digest:
                raise StoreError(f"object collision at {key}")
            return key, digest
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
        # Verify content hash after writing (E.1).
        written = hashlib.sha256(path.read_bytes()).hexdigest()
        if written != digest:
            path.unlink(missing_ok=True)
            raise StoreError("post-write hash verification failed")
        return key, digest

    def get(self, key: str) -> bytes:
        path = self._resolve_safe(key)
        if path.is_symlink():
            raise StoreError("symlink object refused")
        if not path.exists():
            raise StoreError(f"object not found: {key}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != key.rsplit("/", 1)[-1]:
            raise StoreError(f"object content hash mismatch: {key}")
        return content

    def has(self, key: str) -> bool:
        try:
            return self._resolve_safe(key).exists()
        except StoreError:
            return False
