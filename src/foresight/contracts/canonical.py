"""Canonical JSON encoding and hashing (Build Spec Appendix E.2, D.1).

Canonical form: UTF-8, ``json.dumps`` with ``sort_keys=True`` and compact
separators, int64 nanosecond timestamps rendered as decimal strings, all
numbers finite. ``forecast_hash`` fields are excluded from their own hash
input by the callers (E.2), never by this module.

Source ordering for seal material is ``(ingested_at_ns, sensor_id,
source_sequence_or_ingest_sequence, event_id)`` (E.2).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

_NS_RE = re.compile(r"^-?(0|[1-9][0-9]{0,18})$")

_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,254}$")


class CanonicalJSONError(ValueError):
    """Raised when a value cannot be canonically encoded (nonfinite number,
    unordered mapping where order matters, or invalid timestamp)."""


def _check_finite(value: float, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise CanonicalJSONError(f"nonfinite number at {path}: {value!r}")


def _walk(value: Any, path: str = "$") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        _check_finite(value, path)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJSONError(
                    f"canonical JSON keys must be strings, got {key!r} at {path}"
                )
            _walk(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _walk(item, f"{path}[{i}]")
        return
    raise CanonicalJSONError(f"cannot canonically encode {type(value)} at {path}")


def canonical_json(value: Any) -> str:
    """Deterministic compact JSON with sorted keys (E.2).

    Rejects NaN/Infinity anywhere in the tree, non-string keys and unbounded
    objects. A ``-0.0`` float is normalized to ``0.0`` (E.2: normalize
    negative zero in hash material).
    """

    def normalize(node: Any) -> Any:
        if isinstance(node, float):
            if not math.isfinite(node):
                raise CanonicalJSONError(f"nonfinite number: {node!r}")
            return 0.0 if node == 0.0 else node
        if isinstance(node, dict):
            return {k: normalize(v) for k, v in sorted(node.items())}
        if isinstance(node, (list, tuple)):
            return [normalize(v) for v in node]
        if isinstance(node, bool) or node is None or isinstance(node, (str, int)):
            return node
        raise CanonicalJSONError(f"cannot canonically encode {type(node)}")

    _walk(value)
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False)


def sha256_hex(data: str | bytes) -> str:
    """Lowercase hex SHA-256 of canonical material."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def decimal_ns(value: int) -> str:
    """Nanoseconds as a JSON-safe decimal string (D.1: avoid JS precision loss)."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise CanonicalJSONError(f"timestamp must be an int, got {type(value)}")
    if not (-(2**63) <= value < 2**63):
        raise CanonicalJSONError(f"timestamp out of int64 range: {value}")
    return str(value)


def parse_decimal_ns(value: Any) -> int:
    """Parse a decimal-string (or int) nanosecond timestamp from the wire."""
    if isinstance(value, bool):
        raise CanonicalJSONError("boolean is not a timestamp")
    if isinstance(value, int):
        if not (-(2**63) <= value < 2**63):
            raise CanonicalJSONError(f"timestamp out of int64 range: {value}")
        return value
    if isinstance(value, str):
        if not _NS_RE.match(value):
            raise CanonicalJSONError(f"invalid decimal-ns timestamp: {value!r}")
        parsed = int(value)
        if not (-(2**63) <= parsed < 2**63):
            raise CanonicalJSONError(f"timestamp out of int64 range: {value}")
        return parsed
    raise CanonicalJSONError(f"invalid timestamp type: {type(value)}")


def validate_opaque_id(value: Any, *, field: str = "id") -> str:
    """D.1: opaque IDs are nonempty strings with no path traversal components."""
    if not isinstance(value, str) or not _OPAQUE_ID_RE.match(value):
        raise CanonicalJSONError(f"invalid opaque {field}: {value!r}")
    if "/" in value or "\\" in value or ".." in value:
        raise CanonicalJSONError(f"{field} must not contain path components: {value!r}")
    return value


def source_sort_key(event) -> tuple:
    """E.2 canonical source ordering for seal material."""
    sequence = (
        event.source_sequence
        if event.source_sequence is not None
        else event.ingest_sequence
    )
    return (
        event.ingested_at_ns,
        event.sensor_id,
        sequence if sequence is not None else -1,
        event.event_id,
    )
