"""Synthetic episode corpus (Build Spec Section 6, C.4, M.1).

Each episode is a ~55-minute synthetic capture (110 thirty-second windows:
20 history + 60 horizon + margin) with deterministic seeded background
traffic plus an optional scripted attack campaign. Ground truth follows the
Section-11 ontology: first-event times per (entity, task) with label tiers,
plus tactic activity windows for the stage tags.

Everything is disclosed synthetic (``privacy_class: synthetic``); no measured
performance is claimed. The corpus exists so the full pipeline — features,
world model, calibration, evaluation — runs on realistic traffic semantics
instead of random tensors.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ingest.synthetic import (
    CaptureBuilder,
    GroundTruth,
    Host,
    SyntheticCapture,
    generate_capture,
)

_NS = 1_000_000_000
MIN = 60 * _NS

EPISODE_WINDOWS = 110          # 55 minutes of 30-second windows
EPISODE_DURATION_NS = EPISODE_WINDOWS * 30 * _NS


@dataclass(frozen=True)
class StageWindow:
    """Tactic activity interval for stage tags (Section 11)."""

    entity: str
    tactic_index: int
    from_ns: int
    to_ns: int


@dataclass
class CampaignOutcome:
    ground_truth: list[GroundTruth] = field(default_factory=list)
    stages: list[StageWindow] = field(default_factory=list)


# --------------------------------------------------------------------------
# Shared network template
# --------------------------------------------------------------------------

def standard_hosts(seed_offset: int = 0) -> list[Host]:
    """The episode network: 13 internal hosts + 4 external endpoints."""
    hosts = [
        Host("ws-11.corp.local", "workstation", "10.10.1.11", ttl=128),
        Host("ws-12.corp.local", "workstation", "10.10.1.12", ttl=128),
        Host("ws-21.corp.local", "workstation", "10.10.1.21", ttl=128),
        Host("ws-41.corp.local", "workstation", "10.10.1.41", ttl=128),
        Host("srv-app-01.corp.local", "app-server", "10.10.2.10", ttl=64),
        Host("srv-app-02.corp.local", "app-server", "10.10.2.11", ttl=64),
        Host("db-01.corp.local", "database", "10.10.2.20", ttl=64),
        Host("dc-01.corp.local", "domain-controller", "10.10.2.30", ttl=128),
        Host("file-01.corp.local", "file-server", "10.10.2.40", ttl=64),
        Host("proxy-01.corp.local", "proxy", "10.10.2.50", ttl=64),
        Host("web-01.dmz.local", "web-server", "10.20.0.10", ttl=64),
        Host("backup-01.corp.local", "backup", "10.10.2.60", ttl=64),
        Host("siem-01.corp.local", "security", "10.10.2.70", ttl=64),
    ]
    externals = [
        Host("ext-cdn-01.net", "external", "203.0.113.10", ttl=52),
        Host("ext-mail-01.net", "external", "198.51.100.20", ttl=52),
        Host("ext-c2-01.net", "external", "192.0.2.100", ttl=52),
        Host("ext-attacker-01.net", "external", "192.0.2.66", ttl=52),
    ]
    return hosts + externals


INTERNAL_SUFFIXES = (".corp.local", ".dmz.local")


def is_internal(name: str) -> bool:
    return name.endswith(INTERNAL_SUFFIXES)


# --------------------------------------------------------------------------
# Benign background traffic (all episodes)
# --------------------------------------------------------------------------

def benign_background(b: CaptureBuilder, outcome: CampaignOutcome, *,
                      heavy: bool = False) -> None:
    """Deterministic-seed background: browsing, service calls, monitoring,
    one backup. ``heavy`` adds patch-rollout noise for drift episodes."""
    import numpy as np
    rng = b.rng

    # Workstations browse via proxy in random bursts.
    for ws in ("ws-11.corp.local", "ws-12.corp.local", "ws-21.corp.local"):
        n_bursts = int(rng.integers(6, 14))
        for _ in range(n_bursts):
            at = int(rng.integers(0, EPISODE_DURATION_NS - 10 * MIN))
            b.browse_burst(at, ws, "proxy-01.corp.local",
                           n_pages=int(rng.integers(3, 9)))
    # App tier talks to the database.
    b.periodic_service("srv-app-01.corp.local", "db-01.corp.local",
                       dport=1433, period_ns=int(90 * _NS),
                       jitter_ns=20 * _NS)
    # Workstations authenticate against the DC.
    for ws in ("ws-11.corp.local", "ws-12.corp.local", "ws-41.corp.local"):
        b.periodic_service(ws, "dc-01.corp.local", dport=88,
                           period_ns=int(240 * _NS))
    # SIEM polls everything.
    for target in ("srv-app-01.corp.local", "db-01.corp.local",
                   "proxy-01.corp.local", "web-01.dmz.local"):
        b.periodic_service("siem-01.corp.local", target, dport=514,
                           period_ns=int(70 * _NS), jitter_ns=15 * _NS)
    # Proxy fetches external content on behalf of users.
    b.periodic_service("proxy-01.corp.local", "ext-cdn-01.net",
                       dport=443, period_ns=int(45 * _NS),
                       request_bytes=int(rng.integers(500, 2000)),
                       response_bytes=int(rng.integers(4000, 30000)))
    # Mail relay.
    b.periodic_service("proxy-01.corp.local", "ext-mail-01.net",
                       dport=25, period_ns=int(300 * _NS))
    # File shares.
    b.periodic_service("ws-21.corp.local", "file-01.corp.local",
                       dport=445, period_ns=int(200 * _NS))
    # Nightly backup: one bulk transfer mid-episode.
    b.backup_job(int(rng.integers(18 * MIN, 26 * MIN)),
                 "backup-01.corp.local", "file-01.corp.local",
                 gib_bytes=int(rng.integers(120_000, 400_000)))

    if heavy:
        # Patch rollout: management pushes elevated-volume updates to every
        # workstation for ~8 minutes (benign drift, SENTINEL stress case).
        start = int(rng.integers(8 * MIN, 20 * MIN))
        for i, ws in enumerate(
            ("ws-11.corp.local", "ws-12.corp.local",
             "ws-21.corp.local", "ws-41.corp.local")
        ):
            b.backup_job(start + i * 45 * _NS, "backup-01.corp.local", ws,
                         gib_bytes=int(rng.integers(60_000, 120_000)))
        # Off-schedule second backup.
        b.backup_job(int(rng.integers(34 * MIN, 44 * MIN)),
                     "backup-01.corp.local", "db-01.corp.local",
                     gib_bytes=250_000)


# --------------------------------------------------------------------------
# Campaign scripts
# --------------------------------------------------------------------------

def campaign_benign_baseline(b: CaptureBuilder) -> CampaignOutcome:
    out = CampaignOutcome()
    benign_background(b, out)
    return out


def campaign_benign_drift(b: CaptureBuilder) -> CampaignOutcome:
    out = CampaignOutcome()
    benign_background(b, out, heavy=True)
    return out


def campaign_web_to_lateral(b: CaptureBuilder) -> CampaignOutcome:
    """External exploit -> C2 beacon -> internal scan -> two lateral hops."""
    import numpy as np
    out = CampaignOutcome()
    benign_background(b, out)
    rng = b.rng
    t0 = int(rng.integers(11 * MIN, 17 * MIN))

    # Stage 1: initial access — attacker exploits the DMZ web server.
    b.exploit_access(t0, "ext-attacker-01.net", "web-01.dmz.local", dport=8080)
    out.ground_truth.append(
        GroundTruth("web-01.dmz.local", 0, t0, "weak_proxy"))
    out.ground_truth.append(
        GroundTruth("web-01.dmz.local", 1, t0 + 30_000_000, "confirmed"))
    out.stages.append(StageWindow("web-01.dmz.local", 1, t0, t0 + 3 * MIN))

    # Stage 2: C2 beacon from the web server.
    b.beacon(t0 + 2 * MIN, "web-01.dmz.local", "ext-c2-01.net",
             duration_ns=EPISODE_DURATION_NS - (t0 + 2 * MIN) - 2 * MIN,
             interval_ns=30 * _NS, jitter_ns=120_000_000)
    out.ground_truth.append(
        GroundTruth("web-01.dmz.local", 3, t0 + 2 * MIN, "confirmed"))
    out.stages.append(
        StageWindow("web-01.dmz.local", 3, t0 + 2 * MIN, EPISODE_DURATION_NS))

    # Stage 3: reconnaissance — sequential port scan of the app tier.
    scan_t = t0 + 6 * MIN
    b.port_scan(scan_t, "web-01.dmz.local", "srv-app-01.corp.local",
                n_ports=140, rate_per_s=18.0, sequential=True)
    b.port_scan(scan_t + int(rng.integers(20 * _NS, 50 * _NS)),
                "web-01.dmz.local", "srv-app-02.corp.local",
                n_ports=140, rate_per_s=18.0, sequential=True)
    out.stages.append(
        StageWindow("web-01.dmz.local", 0, scan_t, scan_t + 2 * MIN))

    # Stage 4: lateral movement into the app tier.
    lat1 = t0 + 9 * MIN
    b.lateral_session(lat1, "web-01.dmz.local", "srv-app-02.corp.local")
    out.ground_truth.append(
        GroundTruth("srv-app-02.corp.local", 2, lat1 + 20_000_000, "confirmed"))
    out.stages.append(
        StageWindow("srv-app-02.corp.local", 2, lat1, lat1 + 4 * MIN))

    # Stage 5: second hop to the database.
    lat2 = t0 + 13 * MIN
    b.lateral_session(lat2, "srv-app-02.corp.local", "db-01.corp.local",
                      dport=1433)
    out.ground_truth.append(
        GroundTruth("db-01.corp.local", 2, lat2 + 20_000_000, "confirmed"))
    out.stages.append(
        StageWindow("db-01.corp.local", 2, lat2, lat2 + 4 * MIN))

    # Stage 6: second C2 channel from the app server.
    c2b = t0 + 16 * MIN
    b.beacon(c2b, "srv-app-02.corp.local", "ext-c2-01.net",
             duration_ns=EPISODE_DURATION_NS - c2b - 2 * MIN,
             interval_ns=45 * _NS, payload=96)
    out.ground_truth.append(
        GroundTruth("srv-app-02.corp.local", 3, c2b, "confirmed"))
    out.stages.append(
        StageWindow("srv-app-02.corp.local", 3, c2b, EPISODE_DURATION_NS))
    return out


def campaign_c2_exfil(b: CaptureBuilder) -> CampaignOutcome:
    """Compromised workstation -> lateral to file server -> staged bulk
    exfiltration from the database."""
    import numpy as np
    out = CampaignOutcome()
    benign_background(b, out)
    rng = b.rng
    t0 = int(rng.integers(11 * MIN, 17 * MIN))

    b.beacon(t0, "ws-41.corp.local", "ext-c2-01.net",
             duration_ns=EPISODE_DURATION_NS - t0 - 2 * MIN,
             interval_ns=30 * _NS, jitter_ns=300_000_000, payload=160)
    out.ground_truth.append(
        GroundTruth("ws-41.corp.local", 0, t0, "weak_proxy"))
    out.ground_truth.append(
        GroundTruth("ws-41.corp.local", 3, t0 + 60_000_000, "confirmed"))
    out.stages.append(
        StageWindow("ws-41.corp.local", 3, t0, EPISODE_DURATION_NS))

    lat = t0 + 5 * MIN
    b.lateral_session(lat, "ws-41.corp.local", "file-01.corp.local")
    out.ground_truth.append(
        GroundTruth("file-01.corp.local", 2, lat + 20_000_000, "confirmed"))
    out.stages.append(
        StageWindow("file-01.corp.local", 2, lat, lat + 4 * MIN))

    # Staging: archives copied from the file server into the database.
    stage_t = t0 + 8 * MIN
    b.backup_job(stage_t, "file-01.corp.local", "db-01.corp.local",
                 gib_bytes=int(rng.integers(500_000, 900_000)))

    # Exfiltration: bulk transfer from the database to attacker
    # infrastructure.
    exfil_t = t0 + 14 * MIN
    b.exfil_transfer(exfil_t, "db-01.corp.local", "ext-c2-01.net",
                     total_bytes=int(rng.integers(1_800_000, 3_200_000)))
    out.ground_truth.append(
        GroundTruth("db-01.corp.local", 4, exfil_t + 60_000_000, "confirmed"))
    out.stages.append(
        StageWindow("db-01.corp.local", 4, exfil_t, exfil_t + 8 * MIN))
    return out


def campaign_slow_recon(b: CaptureBuilder) -> CampaignOutcome:
    """Low-and-slow: quiet beacon, 2-port/s scan over 15 minutes, one hop."""
    import numpy as np
    out = CampaignOutcome()
    benign_background(b, out)
    rng = b.rng
    t0 = int(rng.integers(11 * MIN, 17 * MIN))

    b.beacon(t0, "ws-12.corp.local", "ext-c2-01.net",
             duration_ns=EPISODE_DURATION_NS - t0 - 2 * MIN,
             interval_ns=60 * _NS, jitter_ns=900_000_000, payload=64)
    out.ground_truth.append(
        GroundTruth("ws-12.corp.local", 0, t0, "weak_proxy"))
    out.ground_truth.append(
        GroundTruth("ws-12.corp.local", 3, t0 + 60_000_000, "confirmed"))
    out.stages.append(
        StageWindow("ws-12.corp.local", 3, t0, EPISODE_DURATION_NS))

    scan_t = t0 + 4 * MIN
    b.port_scan(scan_t, "ws-12.corp.local", "srv-app-01.corp.local",
                n_ports=180, rate_per_s=0.2, sequential=True)
    out.stages.append(
        StageWindow("ws-12.corp.local", 0, scan_t, scan_t + 15 * MIN))

    lat = t0 + 20 * MIN
    b.lateral_session(lat, "ws-12.corp.local", "srv-app-01.corp.local")
    out.ground_truth.append(
        GroundTruth("srv-app-01.corp.local", 2, lat + 20_000_000, "confirmed"))
    out.stages.append(
        StageWindow("srv-app-01.corp.local", 2, lat, lat + 4 * MIN))
    return out


def campaign_cred_spray(b: CaptureBuilder) -> CampaignOutcome:
    """Beacon foothold -> credential spray against the DC (failed SMB burst)
    -> lateral movement to the file server."""
    import numpy as np
    out = CampaignOutcome()
    benign_background(b, out)
    rng = b.rng
    t0 = int(rng.integers(11 * MIN, 17 * MIN))

    b.beacon(t0, "ws-21.corp.local", "ext-c2-01.net",
             duration_ns=EPISODE_DURATION_NS - t0 - 2 * MIN,
             interval_ns=45 * _NS, payload=112)
    out.ground_truth.append(
        GroundTruth("ws-21.corp.local", 0, t0, "weak_proxy"))
    out.ground_truth.append(
        GroundTruth("ws-21.corp.local", 3, t0 + 60_000_000, "confirmed"))
    out.stages.append(
        StageWindow("ws-21.corp.local", 3, t0, EPISODE_DURATION_NS))

    # Credential spray: many short SMB attempts, mostly denied.
    spray_t = t0 + 3 * MIN
    s = b.idx("ws-21.corp.local")
    d = b.idx("dc-01.corp.local")
    for attempt in range(44):
        at = spray_t + attempt * int(6.5 * _NS)
        sport = int(b.rng.integers(32768, 60999))
        b.emit(at, s, d, dport=445, sport=sport, flag_mask=1)      # SYN
        if b.rng.random() < 0.8:
            b.emit(at + int(b.rng.integers(3_000_000, 8_000_000)), d, s,
                   sport=445, dport=sport, flag_mask=8 | 2)        # RST+ACK
    out.stages.append(
        StageWindow("ws-21.corp.local", 0, spray_t, spray_t + 5 * MIN))

    lat = t0 + 9 * MIN
    b.lateral_session(lat, "ws-21.corp.local", "file-01.corp.local")
    out.ground_truth.append(
        GroundTruth("file-01.corp.local", 2, lat + 20_000_000, "confirmed"))
    out.stages.append(
        StageWindow("file-01.corp.local", 2, lat, lat + 4 * MIN))
    return out


CAMPAIGNS: dict[str, callable] = {
    "benign-baseline": (campaign_benign_baseline, "benign"),
    "benign-drift": (campaign_benign_drift, "benign-drift"),
    "web-to-lateral": (campaign_web_to_lateral, "web-lateral"),
    "c2-exfil": (campaign_c2_exfil, "c2-exfil"),
    "slow-recon": (campaign_slow_recon, "slow-recon"),
    "cred-spray": (campaign_cred_spray, "cred-spray"),
}

#: Corpus composition (72 episodes). Benign families get extra weight so the
#: false-alert metric has real negative exposure (Section 29).
CORPUS_PLAN: tuple[tuple[str, int], ...] = (
    ("benign-baseline", 16),
    ("benign-drift", 10),
    ("web-to-lateral", 14),
    ("c2-exfil", 12),
    ("slow-recon", 10),
    ("cred-spray", 10),
)


@dataclass
class Episode:
    """One corpus episode: capture plus labels and campaign metadata."""

    episode_id: str
    campaign: str
    family: str
    seed: int
    capture: SyntheticCapture
    stages: tuple[StageWindow, ...]
    start_ns: int
    end_ns: int
    duration_ns: int

    @property
    def ground_truth(self) -> tuple[GroundTruth, ...]:
        return self.capture.ground_truth

    def internal_entity_ids(self) -> tuple[str, ...]:
        """Stable ordered internal entity union (G.2: scope order, sorted)."""
        return tuple(sorted(h.name for h in self.capture.hosts if is_internal(h.name)))

    def external_hosts(self) -> tuple[str, ...]:
        return tuple(h.name for h in self.capture.hosts if not is_internal(h.name))


def build_episode(campaign: str, index: int, *, seed: int | None = None,
                  sensor_gaps: list[tuple[str, int, int]] | None = None) -> Episode:
    """Generate one episode deterministically from (campaign, index)."""
    if campaign not in CAMPAIGNS:
        raise ValueError(f"unknown campaign {campaign!r}")
    script, family = CAMPAIGNS[campaign]
    ep_seed = seed if seed is not None else (hash_fnv(campaign) * 7919 + index * 104729) % (2**31)
    hosts = standard_hosts()
    outcome_holder: dict[str, CampaignOutcome] = {}

    def wrapped(builder: CaptureBuilder) -> list[GroundTruth]:
        outcome = script(builder)
        outcome_holder["out"] = outcome
        return outcome.ground_truth

    capture = generate_capture(
        capture_id=f"{campaign}-{index:03d}",
        campaign=campaign,
        family=family,
        seed=ep_seed,
        duration_ns=EPISODE_DURATION_NS,
        script=wrapped,
        hosts=hosts,
        sensor_gaps=sensor_gaps,
        late_arrival_rate=0.012,
    )
    outcome = outcome_holder["out"]
    return Episode(
        episode_id=capture.capture_id,
        campaign=campaign,
        family=family,
        seed=ep_seed,
        capture=capture,
        stages=tuple(outcome.stages),
        start_ns=0,
        end_ns=EPISODE_DURATION_NS,
        duration_ns=EPISODE_DURATION_NS,
    )


def hash_fnv(text: str) -> int:
    h = 2166136261
    for ch in text:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def build_corpus(plan: tuple[tuple[str, int], ...] = CORPUS_PLAN,
                 *, seed_base: int = 0) -> list[Episode]:
    """Build the full corpus. A few episodes carry sensor gaps so degradation
    paths see realistic missingness (Section 18)."""
    episodes: list[Episode] = []
    counter = 0
    for campaign, count in plan:
        for i in range(count):
            gaps = None
            # every 9th episode gets a 2-minute observation gap on one host
            if counter % 9 == 4:
                gap_host = ("ws-21.corp.local", "srv-app-02.corp.local",
                            "ws-12.corp.local")[counter % 3]
                at = 17 * MIN + (counter % 5) * MIN
                gaps = [(gap_host, at, at + 2 * MIN)]
            episodes.append(
                build_episode(campaign, i, seed=seed_base + counter * 977,
                              sensor_gaps=gaps)
            )
            counter += 1
    return episodes
