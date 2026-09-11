"""Identity/auth-log adapter (Build Spec Tier B item 1, Sections 8, 21).

Two halves:

1. A disclosed synthetic identity-log generator aligned with each episode's
   scripted campaign: benign domain logons plus attack-correlated auth
   events (remote logons for lateral movement, a new local account at
   initial access, NTLM failure bursts for credential spray). The identity
   stream is a SEPARATE telemetry modality: the forecasting pipeline never
   reads it; it exists to answer Tier B evidence requests (Section 21) with
   genuinely paired data.
2. ``IdentityAdapter``: parses auth-log CSV text (a real adapter boundary —
   rows, header validation, malformed-row accounting) into typed
   ``IdentityRecord`` rows and canonical ``auth_observed`` SecurityEvents
   with the three Section-7 clocks.

Identity coverage is explicit: most internal hosts run the identity sensor;
the DMZ web server does not (the honest ``unavailable`` answer state), and
external endpoints are never identity-covered.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from ..data.episodes import is_internal
from .synthetic import Host

_NS = 1_000_000_000
MIN = 60 * _NS

IDENTITY_COLUMNS = (
    "time_ns", "user", "source_host", "dest_host",
    "auth_type", "result", "session_id",
)

AUTH_TYPES = ("kerberos", "ntlm", "network", "interactive", "remote", "batch")
RESULTS = ("success", "failure")

#: Hosts WITHOUT identity telemetry: queries on them return ``unavailable``.
IDENTITY_UNCOVERED = ("web-01.dmz.local",)

#: The domain controller requires elevated authorization to query: answers
#: there return ``denied`` under the default demo policy (Section 21).
IDENTITY_ELEVATED = ("dc-01.corp.local",)


def identity_covered(host: str) -> bool:
    return is_internal(host) and host not in IDENTITY_UNCOVERED


@dataclass(frozen=True)
class IdentityRecord:
    """One parsed auth-log row."""

    time_ns: int
    user: str
    source_host: str
    dest_host: str
    auth_type: str
    result: str
    session_id: str

    def to_json(self) -> dict:
        return {
            "time_ns": str(self.time_ns),
            "user": self.user,
            "source_host": self.source_host,
            "dest_host": self.dest_host,
            "auth_type": self.auth_type,
            "result": self.result,
            "session_id": self.session_id,
        }


# ---------------------------------------------------------------------------
# Synthetic identity-log generation (disclosed, deterministic per episode)
# ---------------------------------------------------------------------------

def _short(host: str) -> str:
    return host.split(".")[0]


def generate_identity_log(episode) -> list[IdentityRecord]:
    """Auth events aligned with the episode's campaign.

    Deterministic from the episode seed; benign logons mirror the background
    traffic pattern and attack-correlated logons are derived from the
    disclosed chain/stage labels (label-side, replay-only modality).
    """
    import numpy as np

    rng = np.random.default_rng((episode.seed * 31 + 17) % (2**31))
    rows: list[IdentityRecord] = []
    duration = episode.duration_ns

    def add(t, user, src, dst, auth, result):
        rows.append(
            IdentityRecord(
                time_ns=int(t),
                user=user,
                source_host=src,
                dest_host=dst,
                auth_type=auth,
                result=result,
                session_id=f"s-{int(t)//1_000_000:08d}-{int(rng.integers(1000, 9999))}",
            )
        )

    # Benign: workstations authenticate to the DC on a period.
    for ws in ("ws-11.corp.local", "ws-12.corp.local", "ws-21.corp.local",
               "ws-41.corp.local"):
        t = int(rng.integers(0, 90 * _NS))
        while t < duration:
            add(
                t, f"{_short(ws)}", ws, "dc-01.corp.local",
                "kerberos", "success",
            )
            t += int(rng.integers(200 * _NS, 400 * _NS))
    # Backup service batch logons.
    t = int(rng.integers(16 * MIN, 22 * MIN))
    while t < duration:
        add(t, "svc-backup", "backup-01.corp.local",
            "file-01.corp.local", "batch", "success")
        t += int(rng.integers(20 * MIN, 30 * MIN))
    # SIEM service account polling.
    t = int(rng.integers(0, 60 * _NS))
    while t < duration:
        add(t, "svc-siem", "siem-01.corp.local", "dc-01.corp.local",
            "network", "success")
        t += int(rng.integers(90 * _NS, 150 * _NS))

    # Attack-correlated logons from the disclosed labels.
    for step in episode.chain:
        if step.task_index == 1:  # initial access: new local account
            add(
                step.time_ns + 5 * _NS, f"iusr-{_short(step.target)}",
                step.source if is_internal(step.source) else step.target,
                step.target, "interactive", "success",
            )
        elif step.task_index == 2:  # lateral movement: remote logon
            add(
                step.time_ns - 8 * _NS, f"{_short(step.source)}",
                step.source, step.target, "remote", "failure",
            )
            add(
                step.time_ns, f"{_short(step.source)}",
                step.source, step.target, "remote", "success",
            )
    # Credential spray: NTLM failure burst in the recon stage window.
    if episode.family == "cred-spray":
        for stage in episode.stages:
            if stage.tactic_index != 0:
                continue
            for i in range(44):
                at = stage.from_ns + i * int(6.5 * _NS)
                if at >= duration:
                    break
                user = f"u{int(rng.integers(100, 999))}.{rng.choice(list('jrmask'))}"
                add(
                    at, user, stage.entity, "dc-01.corp.local",
                    "ntlm", "failure",
                )

    rows.sort(key=lambda r: r.time_ns)
    return rows


def identity_log_csv(records: list[IdentityRecord]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(IDENTITY_COLUMNS)
    for r in records:
        writer.writerow(
            [r.time_ns, r.user, r.source_host, r.dest_host,
             r.auth_type, r.result, r.session_id]
        )
    return out.getvalue()


# ---------------------------------------------------------------------------
# Adapter: CSV text -> typed records + canonical SecurityEvents
# ---------------------------------------------------------------------------

@dataclass
class IdentityParseResult:
    records: list[IdentityRecord]
    malformed_rows: int
    total_rows: int

    @property
    def quality_report(self) -> dict:
        return {
            "adapter": "identity-auth-csv",
            "columns": list(IDENTITY_COLUMNS),
            "total_rows": self.total_rows,
            "parsed_rows": len(self.records),
            "malformed_rows": self.malformed_rows,
            "event_kind": "auth_observed",
            "coverage": {
                "covered_hosts": sorted(
                    {r.dest_host for r in self.records if identity_covered(r.dest_host)}
                ),
                "note": (
                    "identity telemetry is a separate replay-only modality "
                    "(Section 21); it is analyst context and query answers, "
                    "not a model feature (the Section-35 feature registry is "
                    "frozen)"
                ),
            },
        }


class IdentityAdapter:
    """Auth-log CSV adapter (Tier B item 1).

    Header must match ``IDENTITY_COLUMNS``; rows with wrong field counts,
    non-integer times or unknown auth types are counted as malformed, never
    silently coerced.
    """

    def parse(self, csv_text: str) -> IdentityParseResult:
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        if not rows or tuple(rows[0]) != IDENTITY_COLUMNS:
            raise ValueError(
                f"identity log header must be {IDENTITY_COLUMNS}, got "
                f"{rows[0] if rows else None!r}"
            )
        records: list[IdentityRecord] = []
        malformed = 0
        for row in rows[1:]:
            if len(row) != len(IDENTITY_COLUMNS):
                malformed += 1
                continue
            try:
                rec = IdentityRecord(
                    time_ns=int(row[0]),
                    user=row[1],
                    source_host=row[2],
                    dest_host=row[3],
                    auth_type=row[4],
                    result=row[5],
                    session_id=row[6],
                )
                if rec.auth_type not in AUTH_TYPES or rec.result not in RESULTS:
                    malformed += 1
                    continue
            except ValueError:
                malformed += 1
                continue
            records.append(rec)
        return IdentityParseResult(
            records=records,
            malformed_rows=malformed,
            total_rows=len(rows) - 1,
        )

    def to_security_events(
        self, result: IdentityParseResult, *, sensor_id: str = "identity-sensor-01"
    ) -> list:
        """Canonical ``auth_observed`` SecurityEvents (D.3) with the three
        Section-7 clocks (small sensor latency, immediate ingestion)."""
        from ..contracts.events import EntityRef, build_event

        events = []
        for i, r in enumerate(result.records):
            subjects = (
                EntityRef("local", r.source_host, "host"),
                EntityRef("local", r.user, "process", link_confidence=0.9),
            )
            objects = (EntityRef("local", r.dest_host, "host"),)
            ev = build_event(
                tenant_id="local",
                event_id=f"auth-{i:06d}",
                sensor_id=sensor_id,
                event_kind="auth_observed",
                observables={
                    "user": r.user,
                    "auth_type": r.auth_type,
                    "result": r.result,
                    "session_id": r.session_id,
                    "source_host": r.source_host,
                    "dest_host": r.dest_host,
                },
                event_time_ns=r.time_ns,
                available_delay_ns=int(1.5 * _NS),
                ingest_delay_ns=int(2.0 * _NS),
                subjects=subjects,
                objects=objects,
                source_type="synthetic",
            )
            events.append(ev)
        return events


def host_of(record: IdentityRecord, host_map: dict[str, Host]) -> str | None:
    """Resolve a record's primary internal host (destination first)."""
    for name in (record.dest_host, record.source_host):
        if name in host_map:
            return name
    return None
