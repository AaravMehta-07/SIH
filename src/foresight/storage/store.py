"""SQLite metadata store and the Storage facade (Build Spec E.1-E.3).

Minimum tables (E.1): raw_objects, sessions, jobs, dataset_manifests,
scope_versions, artifact_bundles, forecasts, forecast_publications,
evidence_refs, query_records, action_records, adjudications, evaluations,
audit_events. Every business key is tenant-scoped; JSON payloads are
schema-validated by callers before storage and remain immutable after commit.

Forecasts commit BEFORE publication; the publication receipt records the
actual emission time (E.3) used for lead-time scoring.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from ..contracts.canonical import canonical_json, sha256_hex
from .objects import ObjectStore, StoreError

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_objects (
  object_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, sha256 TEXT NOT NULL,
  byte_length INTEGER NOT NULL, format TEXT NOT NULL, storage_key TEXT NOT NULL,
  privacy_class TEXT NOT NULL, parser_status TEXT NOT NULL, created_at_ns TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, object_id TEXT,
  source_kind TEXT NOT NULL, status TEXT NOT NULL, capability_json TEXT,
  quality_json TEXT, created_at_ns TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, kind TEXT NOT NULL,
  status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
  error TEXT, created_at_ns TEXT NOT NULL, updated_at_ns TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_manifests (
  dataset_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scope_versions (
  scope_id TEXT NOT NULL, membership_version INTEGER NOT NULL,
  tenant_id TEXT NOT NULL, payload_json TEXT NOT NULL,
  PRIMARY KEY (scope_id, membership_version)
);
CREATE TABLE IF NOT EXISTS artifact_bundles (
  bundle_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecasts (
  forecast_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, session_id TEXT,
  scope_id TEXT, decision_cutoff_ns TEXT NOT NULL, forecast_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL, committed_at_ns TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecast_publications (
  forecast_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
  first_published_at_ns TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_refs (
  evidence_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
  forecast_id TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS query_records (
  query_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_records (
  action_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adjudications (
  adjudication_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluations (
  evaluation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL,
  kind TEXT NOT NULL, payload_json TEXT NOT NULL, at_ns TEXT NOT NULL
);
"""


class MetadataStore:
    """Tenant-scoped SQLite metadata (E.1). Foreign keys on; writes
    serialized through one connection lock."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query_one(self, sql: str, params: tuple = ()) -> dict | None:
        with self._lock:
            cur = self._conn.execute(sql, params)
            row = cur.fetchone()
        if row is None:
            return None
        columns = [d[0] for d in cur.description]
        return dict(zip(columns, row))

    def query_all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in rows]

    def audit(self, tenant_id: str, kind: str, payload: dict) -> None:
        self.execute(
            "INSERT INTO audit_events (tenant_id, kind, payload_json, at_ns) "
            "VALUES (?, ?, ?, ?)",
            (tenant_id, kind, canonical_json(payload), str(time.time_ns())),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class Storage:
    """Facade over the metadata store and the object store (Appendix S)."""

    def __init__(self, root: Path, *, tenant_id: str = "local") -> None:
        self.tenant_id = tenant_id
        self.root = Path(root)
        self.objects = ObjectStore(self.root / "objects")
        self.meta = MetadataStore(self.root / "metadata.sqlite3")

    # -- forecasts (E.2, E.3) -------------------------------------------------
    def commit_forecast(self, record: dict) -> str:
        """Commit an immutable forecast; the payload's own hash is excluded
        from its hash input (E.2)."""
        payload = dict(record)
        payload.pop("forecast_hash", None)
        forecast_hash = sha256_hex(canonical_json(payload))
        stored = dict(record)
        stored["forecast_hash"] = forecast_hash
        try:
            self.meta.execute(
                "INSERT INTO forecasts "
                "(forecast_id, tenant_id, session_id, scope_id, decision_cutoff_ns, "
                " forecast_hash, payload_json, committed_at_ns) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"],
                    record.get("tenant_id", self.tenant_id),
                    record.get("session_id"),
                    record.get("scope_id"),
                    str(record["decision_cutoff_ns"]),
                    forecast_hash,
                    canonical_json(stored),
                    str(time.time_ns()),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"forecast id is immutable: {record['id']}") from exc
        return forecast_hash

    def get_forecast(self, forecast_id: str, tenant_id: str | None = None):
        row = self.meta.query_one(
            "SELECT * FROM forecasts WHERE forecast_id = ? AND tenant_id = ?",
            (forecast_id, tenant_id or self.tenant_id),
        )
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def verify_forecast(self, record: dict) -> bool:
        """SE01: modified prefix/artifact/forecast bytes are rejected."""
        payload = dict(record)
        claimed = payload.pop("forecast_hash", None)
        if claimed is None:
            return False
        return sha256_hex(canonical_json(payload)) == claimed

    def publish_forecast(self, forecast_id: str) -> int:
        """Record the first external publication; the receipt time is the
        lead-time reference (E.3, SE03)."""
        existing = self.meta.query_one(
            "SELECT first_published_at_ns FROM forecast_publications "
            "WHERE forecast_id = ?",
            (forecast_id,),
        )
        if existing is not None:
            return int(existing["first_published_at_ns"])
        now = time.time_ns()
        self.meta.execute(
            "INSERT INTO forecast_publications "
            "(forecast_id, tenant_id, first_published_at_ns) VALUES (?, ?, ?)",
            (forecast_id, self.tenant_id, str(now)),
        )
        return now

    def publication_receipt(self, forecast_id: str) -> int | None:
        row = self.meta.query_one(
            "SELECT first_published_at_ns FROM forecast_publications "
            "WHERE forecast_id = ?",
            (forecast_id,),
        )
        return int(row["first_published_at_ns"]) if row else None

    # -- sessions and jobs -----------------------------------------------------
    def create_session(self, session: dict) -> None:
        self.meta.execute(
            "INSERT OR REPLACE INTO sessions "
            "(session_id, tenant_id, object_id, source_kind, status, "
            " capability_json, quality_json, created_at_ns) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session["session_id"],
                session.get("tenant_id", self.tenant_id),
                session.get("object_id"),
                session.get("source_kind", "synthetic"),
                session.get("status", "qualified"),
                canonical_json(session.get("capability", {})),
                canonical_json(session.get("quality", {})),
                str(time.time_ns()),
            ),
        )

    def get_session(self, session_id: str, tenant_id: str | None = None):
        row = self.meta.query_one(
            "SELECT * FROM sessions WHERE session_id = ? AND tenant_id = ?",
            (session_id, tenant_id or self.tenant_id),
        )
        return row

    def upsert_job(self, job: dict) -> None:
        now = str(time.time_ns())
        self.meta.execute(
            "INSERT OR REPLACE INTO jobs "
            "(job_id, tenant_id, kind, status, progress, error, created_at_ns, updated_at_ns) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job["job_id"],
                job.get("tenant_id", self.tenant_id),
                job.get("kind", "unknown"),
                job.get("status", "queued"),
                float(job.get("progress", 0.0)),
                job.get("error"),
                str(job.get("created_at_ns", now)),
                now,
            ),
        )

    def close(self) -> None:
        self.meta.close()
