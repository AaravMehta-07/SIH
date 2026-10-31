# FORESIGHT SaaS: Detailed Implementation Plan

Date: 2 October 2026. Status: proposed implementation specification, not a completion or production-readiness claim.

This document translates the inspected hackathon baseline, market assessment and subsequent differentiation discussion into an executable product program. It covers software companies, general product businesses and security service providers. It does not assume that one installation or one feature set fits all three.

Related documents:

- [Market Readiness Plan](FORESIGHT_MARKET_READINESS_PLAN.md): inspected baseline, competitor evidence, 70-feature inventory and commercial hypotheses.
- [Execution Backlog](FORESIGHT_EXECUTION_BACKLOG.md): packages B01-B32 and their original acceptance criteria.
- [Research Build Specification](../../FORESIGHT_Build_Spec.md) and [accepted ADRs](../adr/): authorities for existing model semantics and research qualification.

This is the controlling proposal for the commercial implementation, subject to founder approval. It does not silently replace accepted research ADRs. Changes to model inputs, training regimes, targets, graph limits or receipt semantics require a new ADR and new qualification evidence. Priorities here refine the earlier backlog; existing package IDs remain stable.

## 1. Product Objective and Boundaries

Build an evidence-led security operations SaaS that turns available network, identity and selected cloud observations into actionable investigations, routes work to the right owner, and records what was observed, decided and achieved. It should complement a customer's EDR, firewall or SIEM rather than require replacing them.

The product must answer six operational questions:

1. What suspicious activity is happening, and which observations support that conclusion?
2. Which assets, identities, workloads and business services are involved?
3. What is missing or unreliable in the available evidence?
4. What should an analyst investigate next, and who can resolve it?
5. Did the customer's action actually resolve the observed issue without unacceptable disruption?
6. Is this product reducing useful investigation time and operational risk enough to justify its cost?

### 1.1 Release Lines

| Release line | Included outcome | Not an implied claim |
|---|---|---|
| Design-partner pilot | Authorized telemetry, qualified small detection pack, durable cases, read-only recommendations, measured investigations | Public SaaS general availability or autonomous response |
| Core V1 | Tested SaaS isolation, dependable onboarding, cases, integrations, retention, billing, support and published operating limits | Universal threat coverage or successful attack prediction |
| Software/company profile | Qualified cloud/identity context and service ownership for selected environments | Full CNAPP, source-code security, application tracing or Kubernetes runtime protection |
| Provider edition | Explicit customer delegation, provider queue, customer-specific SLAs and usage accounting | A staffed MDR service or unrestricted provider access |
| Controlled response extension | One qualified adapter with approvals, bounded effects and reconciliation | Exactly-once remote effects or safe arbitrary automation |
| Forecast extension | Only individually qualified task/profile/horizon combinations | Forecasting arbitrary breaches or providing a guaranteed warning interval |
| Research track | Decision-guided evidence acquisition and counterfactual experiments | A market-first invention, causal proof or launch dependency |

### 1.2 Non-Goals

Do not build an EDR agent, antivirus engine, general packet decoder, vulnerability scanner, password vault, pentesting platform, compliance certification service or complete SIEM replacement. Do not add features merely because competitors list them. Do not promise 24/7 managed detection unless a real staffed service and operating agreement exist.

The differentiator to test is a coherent evidence-to-resolution workflow with explicit uncertainty, business context, receipt-based evaluation and low deployment burden. That combination may be commercially useful; competitive superiority must be demonstrated, not inferred from a long feature list.

### 1.3 Terms That Must Remain Separate

- Detection: a conclusion about observed activity, supported by available evidence.
- Hypothesis: a possible explanation or next event; not necessarily a calibrated probability.
- Forecast: a qualified prediction of a specified observable outcome within a specified future horizon.
- Explanation: sensitivity or supporting evidence; not automatically a causal explanation.
- Delivery: the platform or downstream recipient actually received a published output, distinct from decision cutoff.
- Resolution: a documented outcome, not merely closing a ticket or accepting a response request.
- Unknown: a legitimate result when evidence, visibility, labels or remote outcome are unavailable.

## 2. Customer Profiles and Supported Use Cases

### 2.1 Software Companies

Primary users: infrastructure/security engineer, SecOps analyst, platform lead and service owner. Start with one cloud provider and one identity provider. Network-only qualification does not establish cloud or identity qualification.

| Use case | Required context | Product output | Important benign controls |
|---|---|---|---|
| Suspicious sign-in followed by privileged cloud activity | Entra or supported IdP outcomes; CloudTrail; role/session bindings | Evidence-linked case and identity/session investigation | VPN egress, approved travel, service accounts, emergency access |
| Workload making unusual periodic outbound connections | Zeek/Suricata or supported network source; workload/service ownership | Suspected beaconing investigation, not proof of compromise | Health checks, telemetry agents, retry loops, scheduled jobs |
| Unusual outbound transfer from a sensitive service | Network counters; storage/cloud events where available; service criticality | Transfer investigation and owner confirmation request | Backups, releases, replication, customer exports |
| Unexpected identity-to-service access after deployment | Identity/network evidence; deployment and maintenance metadata | Timeline with change context, analyst decision | Autoscaling, blue/green releases, migrations |
| Security issue requiring engineering follow-up | Case evidence, ticket integration, owner map | Assigned remediation and read-only revalidation | Ticket state alone does not establish technical resolution |

Optional release/deployment context is metadata-only initially: service, environment, actor, time, change ID and approved scope. Do not ingest source code, secrets or build logs merely to correlate a deployment.

### 2.2 General Product Businesses

Primary users: IT administrator, small security team, security manager and business-system owner. Typical starting sources are firewall/network metadata plus AD or Entra.

Prioritize password spray followed by suspicious success, unusual administrative fan-out, possible command-and-control behavior, reconnaissance, sensitive-service outbound activity, sensor outages and repeated unresolved cases. Capture branch/site boundaries, critical applications, maintenance schedules, authorized scanners and backup windows. Manufacturing/OT use is observation-only unless independently qualified; do not infer industrial protocol or safety-control support.

### 2.3 Security Companies and MSSPs

Primary users: provider analyst, shift lead, customer relationship owner and customer administrator.

Deliver a customer-scoped work queue, assignment, handoff, escalation, evidence export, delegated policy administration and per-customer coverage/value reports. A provider cannot override a customer's data residency, retention or response policy. Customer opt-out and delegation revocation must invalidate further reads, jobs, exports and connector actions.

MSSP support is a distinct release gate, not a new filter on a globally accessible tenant table. A customer remains the authority over its own organization.

### 2.4 Profile Selection

During discovery, choose two initial environments with credible buyer access. Default hypothesis: one network-plus-AD product business and one AWS-plus-Entra software company. If buyer evidence favors another combination, change this before connector implementation. Do not build every connector before validating any workflow.

Shared foundations serve all profiles. Each profile needs its own source matrix, scenarios, benign controls, deployment guide, cost envelope and acceptance report. Support a profile only when those artifacts pass.

## 3. End-to-End Journeys

### J01. Organization to First Useful Investigation

1. Organization owner authenticates, accepts deployment/data scope and selects region and profile.
2. The setup wizard creates a site, owner map and expiring enrollment token.
3. Customer installs the approved collector or configures a supported existing sensor export.
4. Collector exchanges the token for a scoped certificate; reports source versions, capabilities and clock quality.
5. An authorized test batch verifies durable ingestion, field validity, identity mapping and downstream delivery.
6. Setup displays missing sources, unsupported fields and visibility gaps; it does not show a misleading global green state.
7. A labeled non-production fixture exercises the case workflow without being counted as a real threat or value outcome.
8. Customer confirms owners, notifications, retention and escalation. First genuine cases are adjudicated during the pilot.

Exit evidence: setup duration, required permissions, source-to-case latency, unresolved coverage gaps, support interventions and user-confirmed usefulness.

### J02. Detection to Resolution

Ingest -> validate -> persist -> normalize -> identity bind -> detect/correlate -> create or update case -> notify -> acknowledge -> investigate -> request context -> adjudicate -> assign remediation -> revalidate -> close or reopen.

Every arrow is represented by a durable record or independently verifiable external acknowledgment. If notification fails, the case still exists. If enrichment fails, the original evidence remains available. If an action times out, the case records unknown outcome rather than successful containment.

### J03. Provider Shift Handoff

The provider analyst selects only explicitly delegated customers; opens a severity/SLA queue; takes a case with optimistic concurrency; reviews observed and missing evidence; leaves a structured handoff; escalates through that customer's policy; exports only permitted evidence. Revocation while the case is open blocks subsequent protected requests and cancels unauthorized queued work.

### J04. Business Owner Feedback

An analyst requests bounded context from a service owner: approved change, expected transfer, maintenance or unauthorized activity. The owner sees only the relevant case subset. Their answer becomes attributed evidence, not ground truth automatically. Repeated benign patterns may propose a scoped, expiring suppression; an authorized analyst approves it.

### J05. Customer Exit or Data Deletion

Disable integrations and response authority; export authorized records; revoke sensor credentials and user grants; execute policy-specific deletion; remove search/cache copies; record backup expiry or key destruction; reconcile billing; issue a deletion report with remaining legal holds and backup limitations. No hidden continued model training or support access.

## 4. Baseline, Migration and Immediate Repairs

Inspected baseline commit: `51e1bbe450aa29bb2a13c3c1c900692162b6c7fc`. Revalidate before implementation. Prior local verification passed 324 Python tests and console type checking; those results are not a production acceptance test.

The saved synthetic evaluation had approximately 11.9% event recall and 1.465 false alerts per 100 asset-hours, failing its stated recall and alert-rate gates. Its reported lead time used decision cutoff, not actual delivery. A successful hash/release verification did not mean the statistical gates passed. These results prevent a sellable prediction claim today; they do not prevent building a useful separately qualified detection/case product.

### 4.1 Repair Sequence

| Repair | Current location | Required change | Acceptance evidence |
|---|---|---|---|
| Production authority | `src/foresight/api/server.py` | Distinct authenticated production application; demo remains local-only | Anonymous production requests rejected; demo credentials never accepted |
| Tenant scope | `src/foresight/storage/store.py` and API callers | Tenant-composite repository API and trusted tenant context | Two-tenant negative tests across reads, writes, workers, objects and exports |
| Data/model profile selection | `src/foresight/api/server.py` and bundle loading | Explicit qualified profile-to-bundle binding | Real-source profile cannot silently use synthetic/untrained bundle |
| Actual timing | `src/foresight/api/service.py`, evaluator matching | Record cutoff, inference, durable publication and transport separately | Controlled delay lowers measured useful lead and can make it nonpositive |
| Censoring | Evaluator matching/ranking | Follow-up coverage and supported outcome labels | Unobserved follow-up not counted as a verified negative |
| Release gating | CLI release verification and registry | Distinguish integrity, compatibility, statistical qualification and approval | Failed/missing qualification blocks production activation |
| Durable workflow | In-memory sessions/actions in demo API | Cases, jobs, receipts and policy state persisted in production store | Restart/multiworker tests preserve work and prevent duplicate local effects |
| Action authority | Demo action handling and audit | Remove automatic production signing; fail closed on security audit failure | Missing approval, stale target or unavailable audit blocks dispatch |
| Parser boundary | Capture/upload parsing | OS-enforced resource and network isolation | Malformed/decompression/fuzz fixtures cannot exhaust service or make network calls |
| Packaging and rights | Package metadata and release process | Supported runtimes, locks, license/notice inventory, reproducible builds | Clean-build SBOM and legal release approval |

Do not rewrite research tests to accept degraded behavior. Add regression fixtures for every repaired issue. Retain historical reports as historical reports.

### 4.2 Runtime Policy

Python 3.10 reached end of support on 1 October 2026 according to the [Python version table](https://devguide.python.org/versions/). Preserve the existing Python 3.10 research reproduction environment where required, but do not choose it for the new internet-facing production service.

Candidate production runtime: Python 3.12, after testing the exact Torch/PyG/native dependency matrix; Python 3.13 is an alternative only after the same qualification. Pin one supported minor and patched releases. Compare feature extraction, serialization, model outputs, calibrators, deterministic replay and artifact loading between the baseline and production runtime before approving migration. Rebuild incompatible artifacts; never assume native/runtime changes preserve numerical behavior.

Use Node 24 LTS as a candidate build runtime, subject to application compatibility; verify support again at implementation. [Node release schedule](https://nodejs.org/en/about/previous-releases). Pin tested frontend dependencies and production Python dependencies with hashes; review security advisories and support dates quarterly. This plan does not authorize installing runtimes or changing the local baseline now.

## 5. System Architecture

### 5.1 Initial Topology

```text
Customer boundary
  Zeek / Suricata / AD forwarder / selected cloud APIs
  -> Collector: schema adapters, local privacy filter, bounded encrypted spool
  -> Outbound authenticated upload; no inbound shell

Regional SaaS cell
  API gateway -> Authenticated ingestion -> Encrypted batch object
                                      -> PostgreSQL manifest + outbox
  Outbox dispatcher -> Durable queue -> Normalization/identity workers
                                   -> Rules/correlation -> Cases/evidence index
                                   -> Qualified inference pool -> Forecast receipts
  Authenticated case API -> Console / notifications / tickets / SIEM

Separate authorities
  Control plane: membership, policies, credentials, entitlements, deployment
  Evaluator: consented labels, holdouts, experiments, later outcomes
  Response executor: separate grants, credentials, approvals and reconciliation
  Training/registry: consented snapshots, challenger validation, approval
```

### 5.2 Technology and Deployment Decisions

- Keep FastAPI/Python and React/TypeScript; use a modular monolith for business APIs with independent durable workers. Reuse qualified existing model code rather than rebuilding it.
- PostgreSQL is authoritative for organizations, grants, assets, cases, manifests, jobs, receipts, policies and usage references. SQLite remains for local research and optionally the collector spool.
- Encrypted S3-compatible objects hold immutable metadata batches, large evidence, exports, checkpoints and model artifacts. An object path or digest never substitutes for authorization.
- Use one managed durable queue with a transactional outbox. AWS Mumbai is a hosting hypothesis, not an approved purchase. If chosen, SQS standard queues require idempotent consumers and cannot provide universal exactly-once effects. [AWS delivery semantics](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues-at-least-once-delivery.html).
- Redis, if introduced, is non-authoritative cache/rate limiting only. The product must recover after cache loss.
- Start investigation queries with bounded PostgreSQL indexes and object partitions. Introduce a columnar/search store only after benchmarked needs justify its cost and isolation/deletion burden.
- Separate dev, staging and production accounts/projects, secrets, buckets, databases and identity clients. Do not run production using a developer's workstation credentials.
- Start without Kubernetes. Add orchestration only when measured scaling, rollout or isolation needs justify the additional operational surface.

### 5.3 Boundaries and Dependency Direction

Business modules depend on typed contracts and repository interfaces, not global demo sessions. Inference consumes committed observation prefixes and approved artifacts; it cannot read future labels. Response consumes signed policy-bound proposals, not arbitrary model commands. Evaluators cannot mutate published forecasts. Training cannot access customer telemetry without explicit purpose-bound consent.

The control plane stores cell placement and minimal organization metadata; it must not silently centralize raw telemetry across regions. Customer queries and background jobs are routed to the assigned cell. A cell failure does not grant another region permission to read data.

## 6. Proposed Repository Structure

Paths below are planned additions, not existing implementations. Reconcile naming with the repository before each package.

```text
src/foresight/
  contracts/                 Existing research contracts; version deliberately
  production/
    application.py           Production app composition and dependency injection
    context.py               Trusted actor, tenant, cell and request context
    organizations/           Membership, roles, delegation and placement
    ingestion/               Enrollment, upload manifests and capabilities
    normalization/           Source adapters and provenance validation
    identity/                Versioned asset/identity/address bindings
    detection/               Rule packs, baselines and signal generation
    cases/                   Correlation, lifecycle, adjudication and revalidation
    evidence/                Authorized search, object access and exports
    forecasting/             Profile binding, state leases and publication
    integrations/            Notification, ticket, SIEM and cloud connectors
    response/                Proposals, approvals, dispatch and readback
    privacy/                 Retention, holds, deletion and restore tombstones
    billing/                 Entitlements, usage events and reconciliation
    audit/                   Append-only security events and integrity roots
    repositories/            Tenant-qualified SQL implementations
    workers/                 Durable handlers and bounded work classes
    registry/                Artifact approval and serving compatibility
  evaluation/                Existing code plus prospective evaluator adapters
  collector/                 Thin enrollment/filter/spool/shipping package
migrations/                  Reviewed forward migrations and rollback procedures
configs/production/          Non-secret schemas, support profiles and defaults
deploy/                      IaC, image definitions and environment templates
tests/production/            Contracts, integration, tenancy, fault and E2E tests
tests/fixtures/              Synthetic and legally usable sanitized fixtures
docs/product/                Product authority, evidence index and release claims
docs/runbooks/               Recovery, incidents, connectors, support and upgrades
console/src/                 Existing console evolved into case-first workbench
```

Keep modules small enough to review. Avoid parallel demo and production copies of pure feature/model logic; share tested logic behind an explicit production adapter. Do not migrate SQLite research files in place. Import permitted historical data into a separate production staging pipeline only when rights and schemas are verified.

## 7. Domain Model and Database Contracts

### 7.1 Common Record Rules

All tenant-owned records carry `tenant_id`, stable opaque ID, creation time, schema version and provenance where applicable. API IDs are not secrets. Resource lookup always includes tenant. Use composite foreign keys for tenant-local relationships; do not rely on a UUID being difficult to guess.

UTC instants use indexed PostgreSQL timestamps where microsecond precision suffices. Preserve original source time/precision in evidence. API nanosecond epochs, where needed for existing contracts, are decimal strings rather than unsafe JavaScript integers. Duration fields have explicit units. Unknown values are nullable with a reason/validity mask, not numeric zero.

Sensitive data is encrypted at rest and in transit. Classify fields as operational metadata, customer-sensitive identifier, evidence, credential or label. Credentials go to a secret manager, not a generic JSON column. Customer identifiers never become high-cardinality unrestricted monitoring labels.

### 7.2 Core Tables

| Record/table | Important fields | Invariants and indexes |
|---|---|---|
| `organizations` | Region, cell, status, profile, policy version | Placement changes require migration workflow; disabled organizations cannot dispatch |
| `memberships` / `grants` | Actor, role, resource scope, expiry, grant version | No implicit tenant from user input; deny by default |
| `provider_delegations` | Customer tenant, provider organization, allowed actions/resources, expiry | Explicit customer approval; revocation version checked at execution |
| `sites` / `sensors` | Observation domain, certificate identity, capabilities, heartbeat | Source identity unique within tenant/site; revocation blocks new acceptance |
| `ingestion_batches` | Sensor epoch, sequence range, digest, object ref, durable receipt, status | Unique `(tenant, sensor, epoch, batch_id)`; conflicting retry quarantined |
| `outbox` / `jobs` | Tenant, event/job ID, handler version, attempt, lease, fence | Local effect uniqueness key; terminal records retained for dedup horizon |
| `assets` / `services` | Stable asset ID, kind, owners, criticality, environment | Ownership provenance; no IP-only global identity |
| `address_bindings` | Domain, address, validity interval, identity, source/confidence | Overlaps may be ambiguous; never resolve by last write silently |
| `identity_bindings` | Principal/workload/session, provider namespace, validity interval | Separate user, device, workload and session identities |
| `source_capabilities` | Modality, valid fields, delay, coverage intervals, clock quality | Versioned; job can use only capabilities valid at its cutoff |
| `signals` | Detector version, evidence refs, scope, first/last seen, reason | Deterministic observation/dependency fingerprints prevent replay inflation |
| `cases` / `case_events` | Status, owner, severity rationale, version, history | Optimistic concurrency; immutable attributed event history |
| `case_evidence` | Case, object/row locator, digest, source dependencies, visibility class | Same tenant FK; no dangling exports after retention without explicit unavailable marker |
| `forecast_publications` | Prefix commitment, task/horizon, hashes, support, publication clock | Published payload immutable; revisions refer to original |
| `delivery_receipts` | Output revision, transport, attempt, received/failed/unknown state | Do not equate transport acceptance with human reading |
| `suppressions` / `maintenance` | Scope, creator, approver, reason, expiry | Suppression impacts notification/correlation, not original retention evidence |
| `response_proposals` / `dispatches` | Exact target, policy/approval version, expiry, request key, outcome | Remote uncertainty explicit; no blind retry on unknown non-idempotent effects |
| `adjudications` | Actor, taxonomy, evidence, outcome time/coverage, confidence | Analyst opinion distinct from independently verified outcome |
| `audit_events` / `audit_roots` | Actor, purpose, action, resource, result, digest chain/root | Append-only runtime role; no secrets/raw telemetry in event body |
| `retention_jobs` / `deletion_tombstones` | Class, cutoff, hold, object/index targets, result | Restore applies tombstones before opening customer access |
| `usage_events` / `invoice_refs` | Meter, interval, quantity, idempotency key, tariff version | Append-only meter events; provider callbacks deduplicated |
| `artifact_registry` / `qualification_runs` | Hashes, schemas, profile, environment, evidence, reviewer | Integrity is separate from approved production status |

Do not put every packet or flow into PostgreSQL as an independent operational row. Persist raw normalized streams in bounded object microbatches; index summaries and locators required for bounded investigations. Database design must be benchmarked using the actual event mix.

### 7.3 Example Tenant-Composite Constraint

```sql
-- Illustrative migration contract; complete migrations need policies and indexes.
CREATE TABLE cases (
    tenant_id uuid NOT NULL,
    case_id uuid NOT NULL,
    version bigint NOT NULL,
    status text NOT NULL,
    PRIMARY KEY (tenant_id, case_id)
);
CREATE TABLE case_evidence (
    tenant_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    case_id uuid NOT NULL,
    digest text NOT NULL,
    PRIMARY KEY (tenant_id, evidence_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id)
);
```

Apply RLS with a non-owner, non-superuser runtime role without `BYPASSRLS`; consider `FORCE ROW LEVEL SECURITY` where appropriate. Set trusted tenant context transaction-locally and reset pooled connections. Migration/backup roles are separate, monitored and never used by APIs. Test actual runtime roles because owners and privileged roles can bypass ordinary RLS. [PostgreSQL RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).

## 8. Production API and Authorization

### 8.1 API Rules

Use a separate production API namespace such as `/api/v1`; keep current demo/replay routes separately composed and disabled on public production ingress. Version OpenAPI contracts and generate frontend types. Reject unexpected fields for security-sensitive operations.

Every request resolves actor, selected organization, action and resource through server-side authorization. Do not accept a payload `tenant_id` as authority. Scope API tokens by tenant, action, resources, expiry and optional source restrictions. Store only token hashes; display a new secret once. Interactive administrators use enterprise identity and MFA; machine sensors use certificate-bound identities.

Writes support `Idempotency-Key` and a bounded replay window. Mutations of existing resources require an expected version/ETag; stale updates return conflict. Use opaque cursor pagination, maximum page sizes, bounded query intervals and cancellable async jobs for expensive work. Error responses contain stable codes and trace IDs, not SQL, stack traces or protected resource details.

### 8.2 Endpoint Families

| Family | Representative operations | Authorization and contract |
|---|---|---|
| Organization | Membership, profile, region, policy | Owner/admin; sensitive changes audited and versioned |
| Sensors | Enrollment token, activation, renewal, revoke, health | Site-scoped admin or sensor identity; no general case access |
| Ingestion | Start upload, finalize manifest, receipt/status | Sensor-scoped; size/type/sequence/digest limits; trusted placement |
| Assets/services | List, detail, owner/criticality changes, binding review | Analyst reads; designated editor changes attributed context |
| Cases | Queue/detail, assign, transition, comment, adjudicate, merge/split | Scope-aware role; expected version; history retained |
| Evidence | Bounded search, detail, query job, export request/download | Evidence field policy and audit; object authorization on every access |
| Forecasts | Qualified outputs, support/abstention, immutable revisions | No future labels; capability gate checked server-side |
| Policies | Suppressions, maintenance, escalation, retention | Scoped editor/approver; expiry and policy version mandatory |
| Integrations | Register, credential rotate, test, health, disable | Admin; secrets never returned; outbound destination constraints |
| Response | Propose, preview, approve, dispatch, reconcile, emergency stop | Separate response grants and approvals; no generic execute endpoint |
| Provider | Delegation requests, granted customer queue, handoff | Customer-approved grants evaluated per result and per operation |
| Billing | Plan, meter summary, invoice references | Billing role; does not grant evidence access |
| Support | Access request, approval, bounded support bundle | Explicit customer scope/expiry; access audit visible to customer |
| Privacy | Hold, deletion, export, job report | Separate permission; legal/policy checks; high-risk confirmation |

### 8.3 Role Model

Start with organization owner, security admin, analyst, read-only investigator, service owner, billing admin and explicitly granted support operator. Do not make every admin a response approver automatically. Resource attributes include site, environment, service, evidence class and provider delegation.

Service owners can view limited assigned context, not unrestricted tenant telemetry. Support has no default evidence access. Provider membership alone grants no customer access. Long-lived jobs capture a grant version and revalidate it before accessing evidence, publishing results, exporting or dispatching.

SSO logout/session revocation and membership removal must invalidate protected work within a documented bound. Enterprise SAML/SCIM follows committed demand; OIDC plus correct offboarding is foundational. Require independent approval for high-risk role, credential, retention and response changes where policy specifies it.

## 9. Collector, Enrollment and Ingestion

### 9.1 Collector Responsibilities

Build a thin, signed collector around maintained source components. Responsibilities: enrollment, source/version discovery, privacy filtering, batch packaging, clocks, certificate renewal, bounded encrypted spool, compression, retry and health. Do not build another IDS or permit a generic remote shell.

Initial supported host: one documented Linux distribution/version, with a signed container or package, non-root service where possible, minimal filesystem access and outbound-only connectivity. AD event forwarding may use a separately documented customer-side Windows forwarding mechanism; do not pretend a Linux collector can obtain all Windows identity events without configuration.

Enrollment tokens are single-use, site-scoped and short-lived. Exchange over authenticated TLS for a renewable sensor certificate bound to tenant, site and sensor. Certificate renewal authenticates the old identity and current policy; lost/revoked credentials require re-enrollment. Rotation supports an overlap window without allowing indefinite old-certificate use.

### 9.2 Batch Envelope

```json
{
  "schema_version": "ingestion.batch.v1",
  "batch_id": "opaque-stable-id",
  "sensor_epoch": "new-id-after-sequence-reset",
  "sequence_first": "120001",
  "sequence_last": "120450",
  "source_type": "zeek.conn",
  "source_version": "qualified-version",
  "parser_version": "adapter-v1",
  "event_interval_utc": ["2026-10-02T10:00:00Z", "2026-10-02T10:00:05Z"],
  "source_available_at_utc": "2026-10-02T10:00:06Z",
  "clock_quality": {"estimated_offset_ms": 15, "uncertainty_ms": 30},
  "capability_ref": "capability-revision-id",
  "payload_digest": "sha256-of-precisely-defined-stored-bytes",
  "compression": "qualified-codec",
  "compressed_bytes": 42000,
  "uncompressed_bytes": 170000,
  "record_count": 450,
  "loss": {"dropped_records": 0, "coverage_gaps": []}
}
```

The server derives tenant/site/sensor from authenticated identity, verifies the envelope against that identity, and attaches authoritative receipt times. Report source time claims separately from server clocks. Sensor epochs cannot be used to evade quotas or replay retention. Validate declared sizes, counts and sequence monotonicity against actual content.

### 9.3 Durable Acceptance Protocol

1. Authenticate sensor, deployment placement, certificate status and allowed source.
2. Allocate a short-lived upload grant for one bounded object key, content type and size. No bucket listing or arbitrary path permission.
3. Receive and verify object size/digest/schema. Parsing of untrusted bytes runs in the restricted worker boundary.
4. Commit manifest and processing outbox in one PostgreSQL transaction after object durability is confirmed.
5. Return a durable receipt only after both required stores are durable. A transport/upload acknowledgment alone does not authorize dropping the local spool copy.
6. Collector removes acknowledged spool entries. Lost receipts cause retries using the same batch ID; an identical retry returns the original receipt, while different bytes under the same ID are quarantined.
7. Reconcile orphaned objects, orphaned manifests, stale uploads and undelivered outbox entries. Reconstruct work from committed manifests after queue loss.

Normal operation targets no loss of acknowledged batches inside the qualified regional failure model. Regional disaster recovery has separately declared RPO limits; do not claim global zero loss from a single-region deployment.

### 9.4 Backpressure and Offline Behavior

Spool limits are explicit in bytes and oldest age. On disconnection, preserve ordering within the source epoch and continue local health reporting when possible. On capacity exhaustion, apply customer-approved priority/drop policy, record loss counters and coverage intervals, and degrade dependent detections/forecasts. Never silently drop while displaying complete coverage.

Bound upload concurrency, batch size, decompression ratio and records per batch. Proposed starting batch interval: 1-5 seconds, subject to throughput/cost tests. Heartbeats include spool age, drops, source lag, collector version, certificate expiry and clock uncertainty, without sending raw evidence unnecessarily.

## 10. Connector Implementation Matrix

| Connector | Initial scope | Required engineering | Release boundary |
|---|---|---|---|
| Zeek | Connection/DNS/TLS metadata where configured | Qualified version fixtures, UID linkage, flow closure, field masks | Pilot network profile; no payload interpretation claim |
| Suricata EVE | Alerts/flows and qualified protocol metadata | Signature version/provenance, flow linkage, duplicate dependencies | Pilot; alert is a source signal, not independent corroboration of its own flow |
| AD | Selected logon outcomes and administration context | Customer forwarding, event version fixtures, SID/device/time binding | Pilot when product-business profile is selected |
| Entra | Selected sign-in/audit data | Least-privilege Graph grants, paging, cursor checkpoint, delay and entitlement checks | Software profile; provider licensing/permissions documented |
| Firewall/IPFIX | Selected vendor log or exporter | One actual vendor/version first; NAT/direction/counter semantics | V1; no universal syslog compatibility claim |
| AWS VPC Flow Logs | Qualified flow summaries | Account/region source, aggregation delay, record status and gaps | Software profile; not packet-level live visibility |
| AWS CloudTrail | Supported audit event types | Read-only role, cursor/object dedup, identity/session linkage, regional completeness | Software profile; missing trails reported |
| EDR read-only | One chosen vendor's entity/detection/context API | Scoped query, pagination, quotas, revoked grants, reason/purpose audit | Evidence-request extension before any response API |
| Deployment context | Signed webhook or supported provider metadata | Signature validation, service mapping, retention, replay protection | Optional software V1; no source-code ingestion |
| Kubernetes context | Read-only workload/service identity metadata | Supported versions, workload lifetime, namespace scope, RBAC minimization | Later profile; no runtime protection without separate source |

Reconcile this matrix with discovery before committing B10/B12/B30. The original backlog placed cloud work in V2; a software-company pilot may pull a minimal read-only AWS/Entra slice forward after B06-B09, while leaving broad multi-cloud expansion in V2. This is a sequencing refinement, not a claim of completed cloud support.

Each connector has an SDK/API version pin, permissions manifest, capability report, sanitized fixtures, contract tests, live authorized acceptance, health/runbook, error taxonomy and revocation test. API cursors and provider tokens are tenant-scoped. Expired licenses, rate limits and source lag produce visible degraded states.

Use maintained [Zeek](https://docs.zeek.org/en/current/about/what.html) and [Suricata EVE](https://docs.suricata.io/en/latest/output/eve/eve-json-output.html) schemas; implementation must pin versions rather than consume `latest` blindly. Preserve limitations of [AWS flow logs](https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs-limitations.html). Verify [Entra sign-in API](https://learn.microsoft.com/en-us/graph/api/resources/signin?view=graph-rest-1.0) permissions and available fields for the customer's actual subscription.

## 11. Normalization, Time and Coverage

### 11.1 Three Clocks and Actual Delivery

Preserve event time, source availability and platform ingestion time as separate quantities. Add durable publication and downstream receipt times for product outputs. Never reconstruct source availability from future flow closure or treat an inference timer as total publication time.

For delayed log sources, the product can investigate what it received, but cannot claim that it warned before an event using data available only afterward. Latency dashboards show source delay, collection delay, processing delay, publication delay and transport delay separately.

### 11.2 Validation and Provenance

Normalize through typed, versioned adapters. Preserve source record locators and transformation versions. Store observed/derived fields distinctly, retain validity masks, and expose ambiguity. A missing byte counter, user ID or failure outcome cannot become zero, anonymous or success by default.

Dedup uses source-native IDs when stable, otherwise documented composite fingerprints with collision handling. Evidence derived from the same observation carries dependency IDs. Multiple parsers or detectors consuming the same flow are not automatically multiple independent witnesses.

Map supported SIEM exports to a pinned [OCSF](https://ocsf.io/) version where appropriate. Keep internal timing/provenance extensions and publish loss-of-information rules; do not claim full conformance without schema tests.

### 11.3 Windowing and Lateness

Watermarks are per source/site and based on receipt behavior plus bounded declared lateness. A finalized window records contributing batch manifest IDs, capability revision, coverage, watermark and rule/model versions. A missing source does not indefinitely block every tenant; finalize with explicit incomplete status according to policy.

Late observations may produce a new case revision or retrospective analysis, but never change the original warning or its measured lead. Retain immutable input-prefix commitments and correction links. Do not backdate a revised case into an earlier delivered warning.

Define late/drop behavior for clock skew, out-of-order source data, reconnect bursts, missing sequences, duplicate windows, daylight-saving source timestamps and source schema changes. Test all of them with deterministic fixtures.

## 12. Asset, Identity and Business Context

Use stable IDs from source authorities where available. Namespace identities by tenant, site, observation domain and provider. Separate devices, users, service accounts, workloads, cloud roles and short-lived sessions. Address bindings are time intervals, not permanent identities.

NAT, DHCP reuse, shared proxies and load balancers create ambiguity. Store multiple plausible bindings and confidence/provenance rather than forcing a merge. Manual analyst edits append attributed binding revisions; they do not rewrite old published evidence silently.

Business context includes service ownership, environment, criticality class, approved administrators, maintenance/backup windows and protected assets. Default criticality is unknown, not critical. Customer assertions are distinguished from observed inventory. No invented monetary-loss estimate is required for useful priority.

Cloud/workload entities may need new typed channels. Do not insert them into the old 44-feature model input without a versioned feature/schema/model change. Rules and case timelines can consume broader entity types before predictive models qualify them.

Acceptance requires DHCP reuse, overlapping address spaces, VPN changes, ephemeral workloads, deleted/recreated cloud principals, shared service accounts and cross-site routing fixtures. A false entity merge must be repairable and propagated to case revisions without contaminating unrelated tenant state.

## 13. Durable Processing, Graph Scope and Inference

### 13.1 Job Semantics

Each work item records tenant, input manifest/window, handler version, idempotency key, deadline, resource class and attempt. A worker acquires a bounded lease with a monotonic fencing token. Local output commit requires the current fence; an expired worker cannot overwrite a newer result.

Use one transaction for dependent local projections and their outbox events where feasible. Retry transient failures with bounded backoff and jitter. Permanent schema or authorization failures go to quarantine, not infinite retries. Dead-letter tools respect the same tenant/grant boundaries and require an attributed replay reason.

Separate priority lanes for ingestion/cases, inference, explanations, search/export and training. A large export or expensive explanation cannot starve security case creation. Enforce per-tenant concurrency, weighted fairness and global headroom; record actual queue delay.

### 13.2 Existing Model Boundary

The existing qualified shape is a bounded 128-node scope with existing feature masks and model channels. That is not a qualification of a 500-asset or 100,000-asset graph. Deterministically partition by tenant/site and an approved scope policy; record boundary traffic and unsupported cross-scope predictions.

Cross-scope rule/case correlation may use observed events with explicit provenance. Cross-scope learned forecasting is a separate model experiment. Do not arbitrarily increase the cap and retain previous calibrators or performance claims.

Initially recompute the existing bounded history from committed windows. Persistent hidden state needs a separately trained/qualified regime, burn-in behavior, checkpoint compatibility and prospective comparison. The mere ability to serialize GRU/LSTM state is not evidence that long-running state is calibrated.

### 13.3 Checkpoints and Recovery

Checkpoint includes tenant/scope, source offsets, window sequence, capability/feature versions, artifact hashes, optional qualified hidden state, random-state requirements and fence. Store checkpoint object first, then commit its metadata pointer atomically with processing progress. A crash cannot advance offsets without a recoverable state/input reference.

On restart, obtain a new lease, validate compatibility, restore the last committed point and replay retained manifests idempotently. A stale checkpoint or incompatible model causes bounded replay or an explicit warm-up/abstention state. Never substitute an untrained bundle.

### 13.4 Artifact Registry

States: registered -> integrity checked -> compatibility checked -> evaluated -> security reviewed -> approved for explicit profiles -> canary -> active -> retired/revoked. A failed state cannot be skipped by a UI toggle.

Manifests bind features, scaler, model, calibrator, task definitions, input modalities, source regime, graph limits, runtime compatibility, data rights, evaluation report and signer. Production serving uses protected verification keys and approved digests, not mutable path names. Support revocation, canary rollback and reproducible activation history.

## 14. Detection and Correlation Content

### 14.1 Initial Detection Pack

| Detector | Core observations | Required controls and output |
|---|---|---|
| Maintained rule/IDS signal | Qualified source alert and contextual flow | Source rule/version, dependency linkage, severity rationale |
| Periodic outbound behavior | Valid timing/connection sequences to a destination | Minimum observation/coverage; retry/health-check controls; suspected behavior label |
| Password spray plus success | Identity failures across accounts with subsequent success | Outcome validity, source grouping, service-account exceptions, approved test controls |
| Administrative/lateral fan-out | Auth/device relationships plus network access | Approved administrators/scanners, asset roles, unknown identity handling |
| Low-and-slow reconnaissance | Qualified destination/port fan-out over longer windows | Authorized scan context, baseline resets, bounded memory |
| Unusual outbound volume | Valid direction/byte counters and historical context | Backup/export/replication controls; exfiltration remains unconfirmed |
| Cloud audit correlation | Selected role/session/action sequences | Approved automation, session binding and API lag; no universal compromise conclusion |

Choose a small subset for the first profile; expand only after measured usefulness. Version content packs and thresholds. A rule score is a priority/ranking value unless independently calibrated as a probability.

### 14.2 Detection Contract

Every detector declares required modalities/fields, window length, minimum coverage, source delay bound, supported asset roles, dependencies, score semantics, expected cost and abstention/degradation conditions. Outputs contain observation intervals, evidence references, detector version, reason codes and suggested read-only steps.

Tests include realistic benign controls and background volume, not only attack fixtures. Replay raw observations through the entire normalization path so parser bugs cannot be hidden by perfect synthetic feature arrays.

### 14.3 Correlation

Correlate by stable entity, temporal relation, service context and evidence dependency, not simply IP equality. Preserve parent signals and a reason for each linkage. Duplicate evidence strengthens chronology, not independent certainty.

Support merge/split with an attributed reason and versioned membership. Keep historical delivery/notification links after merges. Control case storms with deterministic grouping, rate limits and visible suppression reasons; never discard all evidence merely to meet an alert KPI.

## 15. Cases, Investigation and Evidence Integrity

### 15.1 Lifecycle

States: new -> triaged -> investigating -> awaiting context/action -> monitoring -> resolved -> closed. Benign, confirmed incident, authorized activity, unknown and insufficient evidence are adjudication outcomes, not an overloaded single closed flag. Reopening requires new evidence, failed revalidation or explicit analyst action and records why.

Assignment uses optimistic concurrency; enforce escalation ownership and acknowledgment deadlines. Comments are attributed and sanitized. Corrections append revisions with edit history. A case keeps evidence refs, impacted services, severity rationale, coverage limitations, outstanding questions, ticket links and remediation tasks.

### 15.2 Investigation Workbench

Default screen is a dense operational queue, not a marketing or model-demo landing page. Case detail provides summary, observed timeline, entity graph, evidence inspector, coverage/uncertainty, owner context, activity history and next-step checklist.

Observed, hypothesized and qualified predicted graph layers are visually and semantically distinct. Predicted edge labels include horizon/support; hypotheses never masquerade as observed connections. The inspector links to source records and explains missing fields and transformations.

### 15.3 Search and Exports

Use a typed filter AST with allowed fields/operators, tenant enforcement, bounded time ranges, query budgets and stable pagination. Do not expose arbitrary SQL or provider query languages to unprivileged callers. Saved queries are tenant-scoped and re-authorized at execution.

Large exports are async, cancelable and audited. Manifests contain case revision, selected evidence, digests, transformation versions, redaction rules, timestamps and support statements. Download grants are short-lived and resource-scoped. Reports distinguish retained/verifiable evidence from deleted, customer-local or unavailable evidence.

### 15.4 Integrity and Audit

Hashes demonstrate consistency with committed bytes; hashes alone do not prove resistance to a privileged administrator rewriting both data and hash. Add protected signing keys, append-only audit privileges, periodic signed roots and an independent verification procedure. Optional immutable object retention must be reconciled with privacy/deletion requirements before activation.

Audit sensitive reads, exports, permissions, support sessions, policy changes, artifact promotion and response operations. If the durable security audit cannot be committed, high-risk mutation/dispatch fails closed. Ordinary case reads may follow a documented degraded policy only with a durable fallback audit mechanism; do not silently swallow audit errors.

## 16. Notifications, Tickets and Revalidation

Implement authenticated email/webhook delivery first, then one buyer-selected Jira or ServiceNow integration and one SIEM export format. Webhooks use signed payloads, timestamp/replay protection and bounded retries. Outbound URLs require destination validation, redirect checks, egress constraints and protection against private-network/metadata-service access unless an explicitly configured connector requires it.

Delivery states: queued, attempted, accepted by transport, recipient acknowledgment where available, failed and unknown. Human acknowledgment is a separate actor event. Escalation uses customer calendars/timezones and severity policy, with an auditable path and deduplication key.

Bidirectional ticket updates use stable IDs, expected versions and reconciliation. Do not create notification loops or treat a ticket being closed as a verified security fix. Revalidation records its evidence window, source coverage and result: issue persists, observed condition absent under adequate coverage, insufficient evidence or not applicable.

Run connector acceptance against an authorized real sandbox/account before claiming support. Unit mocks are necessary but insufficient for permission, pagination, webhook and rate-limit behavior.

## 17. Forecasting and Evaluation Qualification

### 17.1 Qualified Outputs Only

Serving checks task, horizon, modality, source regime, feature version, graph scope, calibration, novelty and current visibility. Unsupported or insufficient evidence yields abstention with reasons. SENTINEL novelty remains a novelty signal, not an attack probability. Deletion attribution remains sensitivity, not causal responsibility. Existing next-mark path mass is a hypothesis until independently calibrated.

Forecast publication commits the exact legal input prefix, feature/artifact/policy hashes, cutoff, generation duration, durable publication time and actual delivery receipts. Outcomes and future labels belong to a separate evaluator authority. Late data or corrected labels cannot rewrite the original publication.

### 17.2 Required Baselines and Splits

Compare with rules-only detection, persistence/rate baselines, simpler calibrated classifiers/survival models and an available incumbent workflow where buyer access permits. Use chronological separation, source/site separation when possible, explicit burn-in and leakage checks. Report performance under base-rate and missing-source changes, not just an aggregate accuracy score.

Use the CTU-13 data only for its supported botnet/flow observations. It is a controlled 2011 dataset and does not establish modern cloud, initial-access, lateral-movement or exfiltration performance. Do not treat source `Background` as verified benign or infer unavailable receipt clocks. [CTU-13 dataset](https://www.stratosphereips.org/datasets-ctu13).

### 17.3 Metrics

- Detection: useful-case precision, scenario recall, nuisance cases per site/day, asset-hours with adequate coverage, time to triage and missed scenarios.
- Forecast: horizon-specific calibration, Brier/log loss versus predeclared baselines, precision/recall at operational budgets, abstention coverage, useful lead measured from actual delivery and censor-aware uncertainty.
- Product: paired investigation time, analyst interventions, owner response, revalidation success, setup burden, retention and resource cost.
- Reliability: durable ingestion loss/gaps, source lag, processing latency, notification delay, recovery and per-tenant fairness.

Define useful lead as outcome time minus actual qualified warning delivery time, with event-time uncertainty and follow-up coverage accounted for. Zero/negative lead gets no advance-warning credit. Label insufficiency is not a negative event. A low aggregate ECE over mostly low-risk bins cannot substitute for calibration of operationally important risks.

### 17.4 Candidate Gates

Before testing, fix task/profile-specific targets with partners. Starting hypotheses: at least 80% useful-case precision, no more than two nuisance cases per site/day for the chosen profile, at least 70% recall over a predeclared authorized scenario set, and at least 30% less paired investigation time than the current workflow. These are targets, not measured results or universal guarantees.

Forecast qualification additionally requires meaningful improvement over strong baselines at a fixed alert budget, sufficient samples/events, calibrated important-risk regions and useful delivered lead. A provisional 60-second minimum is meaningful only for selected low-delay sources; it is not applicable to every cloud/log modality. Set the sample requirement through power/uncertainty analysis before the final holdout, not after seeing results.

Low-sample or statistically inconclusive results stay experimental. Report uncertainty at meaningful site/incident units, not only thousands of correlated windows. A failure to outperform simpler rules keeps the core product operating without the predictive extension.

## 18. Decision-Guided Evidence Research

### 18.1 Honest Positioning

The discussion did not establish a completely new cybersecurity invention. AI investigation, detection coverage validation, active sensing, response cost modeling and optimal stopping have prior art. This experiment is a deeper implementation of scoped evidence requests, not a claim that nobody has done it.

Hypothesis: selecting the next authorized observation according to its decision value, delay and cost can improve correct containment/investigation decisions compared with fixed playbooks or collecting everything. The differentiating possibility is practical, time-aware operational usefulness with verifiable outcomes; it must earn inclusion.

### 18.2 Experiment Contract

Input: current case evidence and dependencies, explicit missing questions, allowed read-only connector queries, query latency/cost distributions, protected-service context, analyst-defined decision alternatives and an evidence-quality model.

Output: ranked bounded query suggestions with expected decision relevance, assumptions, estimated delay/cost, authorization requirements and a stop/insufficient-evidence option. The module has no response credentials and cannot execute containment. In production experimentation, an analyst approves each query or a separately authorized tightly bounded read-only policy applies.

Questions must be concrete: was there a successful authentication after the failures; is the device managed; is the cloud session the same identity; was this transfer an approved export; is the suspicious destination independently supported? Avoid generic unrestricted "investigate everything" tool use.

### 18.3 Objective and Limitations

Candidate objective: expected improvement in decision utility after a query, minus collection cost and expected harm from waiting. Utility incorporates unnecessary disruption, missed supported activity, analyst effort and time. Business owners must validate harm categories; do not fabricate financial losses or calibrated probabilities.

If belief/utility estimates are not calibrated, display ordinal or interval-valued relevance and uncertainty instead of precise expected dollars. Compare robust heuristic query ranking before implementing a complex planner. Use hard stopping constraints for query budget, unresolved authority, source staleness and analyst emergency escalation. The tool never instructs an analyst to delay urgent containment solely to optimize a score.

### 18.4 Build Steps and Kill Gate

1. Define a versioned decision/query schema and create replayable cases with observation release times, not omniscient evidence.
2. Implement fixed-playbook and collect-all baselines, plus experienced-analyst decisions where feasible.
3. Add bounded relevance/latency/cost ranking with provenance and sensitivity to uncertain assumptions.
4. Add an approved read-only query broker with grants, deadlines, caching by evidence revision and dependency tracking.
5. Run held-out paired scenarios with missing, delayed, stale and misleading evidence, including adversarial source content.
6. Measure correct decisions before relevant outcomes, unnecessary containment decisions, investigation time, query cost and worst-case degradation.
7. Promote only if predeclared meaningful improvement and safety/noninferiority constraints hold over adequate samples. Otherwise archive the experiment and retain the useful query broker without planner marketing.

This work is not on the Core V1 critical path. Even a successful lab experiment does not prove field performance or justify market-first language.

Prior-art anchors: [Dropzone investigation example](https://www.dropzone.ai/blog/teaching-ai-soc-agents-to-investigate-a-use-case-in-action), [Prophet agentic investigation](https://www.prophetsecurity.ai/blog/what-makes-an-ai-soc-solution-agentic), [SIFT active perception](https://www.sift.net/publications/active-perception-cyber-intrusion-detection-and-defense), [principled forensic investigation](https://arxiv.org/abs/2211.13345), [optimal stopping for intrusion prevention](https://arxiv.org/abs/2111.00289), and [response cost/impact work](https://link.springer.com/article/10.1186/s13635-017-0063-6). These do not establish that the proposed operational implementation exists or that it is absent elsewhere.

## 19. Controlled Response Extension

### 19.1 Start with Manual Playbooks

Core V1 produces evidence-backed investigation steps and exportable manual containment playbooks. A suggestion records what it might change, prerequisites, target ambiguity and operational risks. It cannot execute a firewall/EDR action merely because a model score is high.

### 19.2 Authority and State Machine

States: proposed -> previewed -> awaiting approvals -> approved -> preflight checked -> dispatched -> accepted -> effect verified / failed / outcome unknown -> monitored -> expired / rolled back / superseded. An approval is bound to exact target, action parameters, evidence revision, policy version, requester, expiry and approved blast radius.

Require separate requester/approver where configured. Protected assets, unsupported actions and ambiguous identities are denied. Revalidate grants, target identity, current evidence, current resource state and policy immediately before dispatch. Expired or materially changed proposals require new approval.

### 19.3 One Adapter Fully Qualified

Select one EDR or firewall with real customer demand, readback, bounded action scope and a viable expiry/rollback mechanism. Use separate least-privilege response credentials and a separate executor identity. No arbitrary script, shell command or generic API proxy.

Persist dispatch intent before contacting the provider. Use provider idempotency keys where supported; record request/response references and read back actual state. A timeout after dispatch is outcome unknown until reconciled. Do not automatically retry a non-idempotent unknown effect. Exactly-once local dispatch records do not imply exactly-once remote effects.

### 19.4 Safety During Failure

TTL must be enforced remotely or by a tested customer-side agent capable of reverting without cloud connectivity. If neither is available, the action is not sold as safely time-bounded. A cloud-only timer is insufficient when the cloud fails.

Rollback compares the current remote version/state with the state created by this action. Do not overwrite a later customer change. Capture health/coverage checks before and after; preserve emergency rollback and kill-switch authority. Test partial failure, credential expiry, provider outage, duplicated callbacks, stale approval, API schema change, concurrent administrator action and loss of cloud connectivity.

Only after independent safety review and authorized live adapter acceptance can the response capability be enabled per tenant. Counterfactual intervention estimates remain research and cannot provide a production causal-effect guarantee.

## 20. Console Implementation

Retain the existing React/TypeScript stack and reusable evidence/graph components, but replace session/demo-first navigation with Cases, Assets/Services, Coverage, Search, Integrations and Administration. Forecasts appear only when qualified and enabled. Provider navigation appears only for actors with actual delegations.

| Surface | Required behavior | Verification |
|---|---|---|
| Case queue | Severity/SLA/site/service filters, assignment, saved views, cursor pagination | Large queues, concurrent assignment, empty/degraded/error states |
| Case workbench | Evidence-linked timeline, graph layers, coverage, adjudication and revalidation | Missing fields, long identifiers, inaccessible/deleted evidence |
| Asset/service detail | Identity/binding history, owner, criticality, related cases | IP reuse, ambiguous identity, permission-limited service owner |
| Coverage | Source freshness, loss intervals, capability matrix, setup errors | Source disconnected, partial modality, high clock uncertainty |
| Search/export | Typed filters, bounded jobs, progress/cancel, permitted downloads | Query limits, authorization changes, expired export grant |
| Integration administration | Permission summary, connection test, rotation, health | Provider outage, rate limit, revoked credential, partial setup |
| Policy administration | Suppression/maintenance/retention review, scope and expiry | Stale edits, protected resources, separation of duties |
| Provider workspace | Delegated customer queue, handoff, customer policy context | Revocation during use and no hidden cross-customer data |
| Subscription/support | Usage, entitlements, invoice refs, approved support sessions | Billing-only role cannot view evidence |

Use dense but readable operational layouts, familiar icon controls, tooltips, accessible labels, keyboard focus and restrained styling. Virtualize large tables; render graphs with node/edge budgets and clear collapsed counts. Long service/user identifiers must wrap or truncate with an accessible full value, never overlap controls. Do not place predicted and observed data in an indistinguishable color scheme.

Use generated API types, a query cache with tenant-qualified keys and explicit invalidation on tenant/grant changes. Never reuse one tenant's cached data after switching organization. Validate error, loading, stale/offline and authorization-revoked states, not just the happy path.

End-to-end browser tests cover desktop and narrow/mobile layouts, accessibility checks, screenshots, long-content fixtures and actual authenticated routes. Provider analysts will primarily work on desktop, but setup, acknowledgments and owner feedback must remain usable on smaller screens.

## 21. Provider Edition and Enterprise Extensions

### 21.1 MSSP Domain

Represent provider organizations and customer organizations separately. A delegation grants specific actions/resources and an expiry; it does not transfer ownership. Customer settings define which evidence classes, sites and policies the provider may access, whether exports are allowed, and whether response approval may be delegated.

The cross-customer queue is assembled from individually authorized customer results. Do not solve it with a global privileged SQL connection that bypasses customer scopes. Maintain per-customer budgets and per-provider aggregate limits so one noisy account cannot starve the provider's other customers.

Handoffs record actor, shift, unresolved questions, next action, escalation deadlines and customer contacts. SLA calculation uses each customer's calendar and policy. Reports clearly separate platform support from any provider's managed-service obligation.

### 21.2 Enterprise Identity and Private Deployment

SAML/SCIM requires lifecycle tests for deprovisioning, group changes, conflicting mappings and break-glass policy. Private VPC/customer-hosted deployment requires a supported topology, upgrade process, telemetry restrictions, key ownership, recovery procedure and support-access model. It is not merely exporting a Docker Compose file.

Keep the same application contracts and release artifact; avoid forks per customer. Document which managed services are replaced and which features are unavailable offline. Qualify private deployments independently for capacity, updates, vulnerability management and model activation. Do not claim an air-gapped product until its complete dependency, licensing, update and recovery story works without network access.

## 22. Privacy, Retention and Data Lifecycle

### 22.1 Collection Defaults

Payload collection is off by default. Filter authentication headers, cookies, secrets, unnecessary URL parameters and unrelated personal content locally before transmission. Metadata such as IP addresses and user IDs can still be sensitive; pseudonymization is not anonymization.

Provide a versioned data inventory listing purpose, source, sensitivity, storage region, subprocessors, retention, access roles and deletion paths. Separate permission to investigate from permission to train models, perform support, export or retrieve customer-local raw evidence.

### 22.2 Retention Classes

Proposed product defaults, subject to contract/counsel and cost validation: short raw metadata retention, longer selected case evidence, policy-specific audit retention and limited operational logs. Do not hard-code one period across all classes. The setup wizard requires an explicit policy selection and shows storage implications.

Retention enforcement covers raw objects, normalized/indexed copies, caches, exports, query jobs, case attachments, labels and training snapshots. A case referencing expired evidence retains an unavailable marker and permitted summary, not a secret shadow copy. Legal holds are authorized, scoped, reviewed and auditable.

### 22.3 Deletion and Backup Restore

Deletion jobs enumerate all derived copies, issue tombstones, remove online data and produce a result manifest. Immutable audit entries must avoid containing the customer data that later needs deletion. Decide upfront whether permitted audit pseudonyms/digests can be retained under the applicable policy; hashes can themselves reveal information and are not automatically anonymous.

Backups have a declared retention/expiry policy. If tenant-level cryptographic erasure is offered, prove that the key hierarchy, escrow and backups cannot restore the erased key; sharing a single recoverable encryption key across tenants does not meet that promise. A restored database remains closed to customers until deletion tombstones, credential revocations and placement/policy changes are reapplied and checked.

Customer data used for training requires purpose-bound opt-in, dataset lineage, revocation handling and a documented policy for already-trained artifacts. Do not promise reliable machine unlearning unless verified; consent withdrawal may prevent future use without making past model removal trivial.

### 22.4 India and Other Jurisdictions

Have counsel determine applicable duties, roles, notification timelines, log classes and transitional provisions. Do not equate all customer telemetry with mandatory retention or claim compliance from regional hosting alone. Use official [CERT-In directions](https://www.cert-in.org.in/Directions70B.jsp) and [MeitY DPDP rules information](https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digit) as inputs, with implementation-date verification.

Security controls, data-processing agreements, subprocessors, customer deletion rights, incident response and contract representations need actual review. SOC 2/ISO certification is a separate professional process; this roadmap does not award certification.

## 23. Grounded AI, Feedback and Learning

AI summaries are optional and not on the initial critical path. They consume only authorized case evidence and return citations to actual evidence IDs. Unsupported assertions become unknown. An LLM never creates fake source records, changes adjudication, promotes a model or gains response credentials.

Treat logs, user comments, domain names, cloud tags and retrieved documents as untrusted data that may contain prompt injection. Separate instructions from evidence, enforce tool allowlists externally, redact secrets and test malicious content. Choose provider/region/retention terms consistent with customer policy; do not send data to external models under implied consent.

Capture analyst feedback as attributed labels with confidence and evidence. Quarantine labels before training, detect duplicate/dependent examples, split by time/site, and compare challenger models on held-out and prospective data. Promotion requires review; no silent self-training on unreviewed suspicious traffic.

Similar-case search stays tenant-local unless a separately consented, legally reviewed sanitized library is created. Cross-tenant embeddings or examples can leak sensitive information; isolation must include vector indexes and retrieval caches.

## 24. Scalability, Capacity and Cost

### 24.1 Scale by Measured Workload, Not Asset Count Alone

An asset count does not define event rate, evidence volume, inference load or query concurrency. Each supported tier declares active assets, sustained/burst EPS, average encoded record size, source mix, retention, graph scopes, ensemble size, inference frequency, analysts, export workload and connector rate limits.

The following are engineering benchmark targets, not current capabilities or customer guarantees:

| Tier | Active assets | Sustained normalized EPS | Burst | Concurrent analysts | Deployment intent |
|---|---|---|---|---|---|
| Qualification pilot | Up to 500 | 500 | 2x for 15 minutes | 5 | Dedicated early data boundary |
| Growth cell | 10,000 aggregate | 5,000 | 2x for 15 minutes | 50 | Shared regional cell after tenancy qualification |
| Enterprise/provider fleet | 100,000 aggregate | 25,000 aggregate | 2x across tested cells | 250 | Multiple independently sized cells, not one giant graph |

Asset/EPS caps must be revised after realistic customer measurements. One high-volume customer may require a dedicated cell or a different tier despite few assets. Profile qualification remains independent of fleet capacity.

### 24.2 Sizing Equations

```text
Raw bytes/day = sustained EPS * average encoded bytes/record * 86,400
Retained raw bytes = raw bytes/day * retention days * measured storage factor
Inference work/hour = active scopes * evaluations/hour * ensemble members
Required workers >= arrival work/sec / measured service work/sec / target utilization
Backlog drain time = backlog work / (service capacity - ongoing arrival rate)
Customer variable cost = ingestion + storage + compute + notifications
                        + connector/AI charges + attributable support + egress
Contribution margin = (subscription revenue - variable cost) / revenue
```

Example only: 500 EPS at 500 encoded bytes/record is 21.6 GB/day before compression/overheads; 30 days is 648 GB before replication/index/export effects. At 5,000 EPS it is 216 GB/day. Do not choose 90-day retention, packet-level PostgreSQL inserts or large free plans without measuring their economics.

For 500 assets, `ceil(500/128)` is a lower-bound scope count only if the qualified partitioning can fill scopes; site/service boundaries may create more scopes. With four scopes, six ensemble members and one evaluation/minute, there are 1,440 member evaluations/hour. Benchmark actual sequence lengths, explanations, memory and queue latency rather than deriving throughput from a GPU model name.

### 24.3 Scaling Strategy

1. Batch observations into bounded immutable objects; PostgreSQL indexes operational summaries/manifests instead of becoming a packet warehouse.
2. Scale stateless APIs and normalization/detection workers independently; use queue age and measured service time, not CPU alone.
3. Partition inference ownership by tenant/site/scope with fencing and safe state migration.
4. Isolate expensive exports/explanations; apply per-tenant and per-provider budgets.
5. Add cells with explicit tenant placement and regional boundaries. Migrate one tenant using paused acceptance or dual-read verification with a clear authoritative cutover, not uncontrolled dual writes.
6. Introduce a columnar event index when qualified search latency/volume cannot meet targets with the simpler layout; include tenant authorization, retention, replay and deletion before rollout.
7. Add orchestration or specialized services only when a specific measured constraint justifies them.

Benchmark tenant skew: one tenant generating 50% of traffic, many small tenants, reconnect storms and long export jobs. A 2x burst must not silently exceed retained buffer capacity. Admission controls preserve durable backlog/visibility reporting; billing limits must never produce invisible security data loss.

### 24.4 Cost Controls and Pricing

Record ingestion/storage/compute/explanation/query/AI use by tenant and workload class. Alert on budget approach, show source-specific costs and propose reduced retention or approved aggregation before costs explode. Restrict costly explanation jobs and AI calls without disabling core case visibility silently.

Use the earlier plan's pricing only as buyer-testing hypotheses, not competitor-derived facts. Start with paid design-partner pilots and a clear subscription covering a qualified workload envelope. Separate onboarding, provider, private-deployment and response support costs. Target sustainable contribution margin after measuring real support burden; a nominal software margin excluding support and external API costs is misleading.

Define billable asset identity and active interval explicitly, including ephemeral workloads, address reuse and excluded infrastructure. Usage reports allow customer reconciliation. Overage/grace/collection policies are disclosed and do not retroactively change a tariff.

## 25. Reliability, Observability and Recovery

### 25.1 Initial Operating Targets

Targets below require load/fault/soak evidence before becoming contractual commitments:

- Core API availability target: 99.5% monthly for the initial qualified service, with documented measurement and exclusions; improve only after observed operations.
- Finalized supported window to durable case publication: p95 below 60 seconds at the qualified load. This excludes neither unmeasured steps nor failures; source delay is reported separately.
- Source-to-delivery latency: reported by source class, with event/source clock uncertainty and missing receipts visible; no single universal promise.
- Regional metadata recovery target: RPO at most 15 minutes and RTO at most four hours, with a tested recovery drill. Ingestion manifests/checkpoints may require tighter recovery or replay from objects to preserve acknowledged batches under the declared failure model.
- Seven-day engineering soak and at least 30-day partner observation before broad operational claims. Synthetic load soak is not natural attack validation.

An RPO target must distinguish cases/policy metadata, batch objects, audit, billing and regional disaster. If a restored metadata backup loses acknowledgment/manifests, reconciliation from immutable receipt/object records is required before normal acceptance resumes. Publish what survives which failure, rather than saying "zero loss" and "15-minute RPO" interchangeably.

### 25.2 Metrics and Alerts

Monitor durable acceptance failures, manifest/object inconsistencies, queue age, quarantine counts, source freshness/loss, lease/fence conflicts, processing/publication latency, case creation rates, notification retries, model abstention/support, export time, database saturation, certificate expiry, deletion backlog and budget drift.

Use bounded cardinality: aggregate metrics by cell/workload/profile; retrieve tenant-specific details through authorized operational records. Logs redact secrets and unnecessary identifiers. Traces connect acceptance, job, case and delivery IDs without copying raw telemetry into monitoring services.

Alert on actionable symptoms with an owner/runbook. Maintain a status page and customer incident notification process. Define incident severity, on-call responsibilities, update cadence and postmortem requirements. Do not sell a 24/7 response SLA without staffed coverage.

### 25.3 Recovery and Upgrades

Use infrastructure as code, immutable signed images, health checks and staged rollout. Database changes follow expand/migrate/contract; rollback cannot depend on reversing destructive schema changes. Check model/checkpoint compatibility before switching serving versions.

Drills cover API/process crash, queue loss, database failover, object outage, expired certificates, cache loss, disk-full collector, failed migration, bad model activation, secret revocation and regional restore. Restore into an isolated environment; apply deletion/revocation tombstones; verify cross-store consistency; then authorize reopening.

Define collector support windows and signed upgrade verification. Older collectors report capability compatibility; incompatible schemas are quarantined with a customer-visible remediation path, not silently parsed as a newer schema.

## 26. Security Engineering and Abuse Resistance

Build a threat model for malicious tenants, compromised collectors, malicious uploads/log content, stolen credentials, provider overreach, support abuse, supply-chain compromise and attacker attempts to poison labels or suppress detections.

Required controls include OIDC/MFA, least-privilege service identities, short-lived object grants, secret rotation, encrypted transport/storage, tenant-composite constraints, application authorization, RLS defense in depth, signed artifacts, audit integrity and egress restrictions.

Parser/upload workers run non-root with bounded CPU/memory/time, limited filesystem, no unnecessary network and controlled decompression. `python -I` is import isolation, not an OS sandbox. Separate processing of hostile files from serving credentials. Fuzz parsers and test zip/decompression bombs, oversized JSON, nested structures, invalid encodings and path traversal.

CI requires dependency/secret scanning, reproducible locks, SBOM, license notices, container review and provenance. Use [OWASP ASVS](https://owasp.org/projects/asvs) and [NIST SSDF](https://csrc.nist.gov/pubs/sp/800/218/final) as verification frameworks with selected version/requirements; do not call a checklist an independent assessment.

Before GA, obtain an independent penetration test covering real production-like identity, tenancy, integrations, uploads, support and provider flows. Remediate release-blocking findings and retest them. Document residual accepted risks and the named approver. An agent-run scanner cannot replace this gate.

## 27. Billing, Support and Commercial Readiness

### 27.1 Subscription Implementation

Entitlements are versioned tenant policies, not frontend-only switches. Usage events have stable idempotency keys and tariff versions; webhook callbacks are authenticated and deduplicated. Reconcile metering with source summaries and retain adjustment history.

Plan changes, failed payments, credits, grace periods and cancellation follow explicit policy. A billing-only actor sees usage/invoices but not raw evidence. Service restrictions preserve exports and applicable retention obligations. Select a payment/invoicing provider only after jurisdiction, tax and buyer procurement needs are known; invoice/manual payment can be the initial commercial path.

### 27.2 Support and Trust Pack

Deliver setup guides, connector permission manifests, architecture/data-flow diagram, data inventory, security controls, support scope, incident policy, retention/deletion policy, subprocessor list, vulnerability disclosure contact, release notes and recovery statement. Procurement answers reference actual evidence and clearly identify incomplete controls.

Support bundles default to sanitized diagnostics and include a manifest of collected fields. Customer-approved evidence access is scoped and expires. Emergency access requires a documented break-glass procedure, independent authorization where applicable, immutable audit and prompt customer notification.

### 27.3 Pilot and Value Review

Pilot agreement fixes authorized scope, data/source rights, workload envelope, buyer success criteria, action restrictions, privacy/retention, incident contacts, support hours, pricing and exit process. It must not represent experimental predictions as certified protection.

Weekly reviews examine meaningful cases, false positives, missing scenarios, source failures, owner feedback, investigation time and cost. At the end, report both positive and negative evidence. Conversion depends on buyer-confirmed value and release gates, not a polished dashboard or generated case volume.

## 28. Verification Matrix

Each test produces a versioned report identifying code/artifact/config versions, environment, fixtures, execution time, result and remaining limitations. Local tests, live connector acceptance, statistical qualification and independent security assessment are separate evidence classes.

### 28.1 Required Acceptance Scenarios

| ID | Scenario | Required result |
|---|---|---|
| T01 | Anonymous/expired/revoked actor reaches production API | Protected access denied without resource leakage |
| T02 | Tenant A guesses B's case, object, job or export ID | Denied across API, repository and object access |
| T03 | Pooled DB connection previously served another tenant | Transaction-local scope prevents residual access |
| T04 | Worker receives forged tenant/resource payload | Trusted manifest/grant context wins; invalid job quarantined |
| T05 | Provider delegation revoked during open case/export | Subsequent reads/queued protected effects denied |
| T06 | Sensor sends different bytes under an accepted batch ID | Conflict quarantined; original receipt/evidence unchanged |
| T07 | Receipt lost after durable acceptance | Retry returns original receipt; one local processing effect |
| T08 | Crash between object upload and manifest transaction | Orphan reconciled; no premature durable acknowledgment |
| T09 | Queue lost or dispatcher restarted | Committed outbox/manifests reconstruct processing |
| T10 | Late, skewed or out-of-order events arrive | Coverage/revision explicit; original output not backdated |
| T11 | Missing/invalid source field | Validity preserved; detector/forecast degrades or abstains |
| T12 | DHCP/NAT/proxy/overlapping-site identity ambiguity | No unsupported merge; uncertainty available to analyst |
| T13 | Old worker finishes after lease expiry | Fence prevents stale commit |
| T14 | Crash after output commit before queue acknowledgment | Retry creates no duplicate local case/publication |
| T15 | Checkpoint incompatible with current artifact | Bounded replay/warm-up or fail closed, never silent fallback |
| T16 | Synthetic/untrained/wrong-profile bundle selected | Production activation blocked |
| T17 | Qualification gate missing/failed but hashes valid | Integrity passes separately; capability remains disabled |
| T18 | Transport delayed until after supported outcome | No positive delivered-lead credit |
| T19 | Future labels inserted into serving storage/input | Access/schema/leakage tests reject the path |
| T20 | Follow-up incomplete or labels ambiguous | Not treated as verified negative; uncertainty reported |
| T21 | Attack fixtures plus backup/scanner/deployment controls | Predeclared detector gates assessed without removing hard negatives |
| T22 | Same flow produces multiple derived alerts | Evidence dependencies prevent independent-count inflation |
| T23 | Two analysts assign/change same case | Expected-version conflict; attributed history preserved |
| T24 | Suppression expires or maintenance ends | Normal processing resumes; original evidence retained |
| T25 | Ticket/webhook loops, duplicate callback, provider outage | Bounded dedup/retry and visible delivery state |
| T26 | Webhook destination resolves to blocked/internal endpoint | SSRF/redirect/egress policy prevents unauthorized connection |
| T27 | Malicious upload/log/prompt content | Parser/tool boundaries hold; no secrets/network/control leakage |
| T28 | Support actor without customer approval | Evidence access denied and attempted access audited |
| T29 | Audit durability unavailable during sensitive mutation | Operation fails closed; no silent success |
| T30 | Evidence export after grant/retention change | Reauthorization/redaction/deletion policy enforced |
| T31 | Online deletion and later backup restoration | Tombstones applied before access; deletion not resurrected |
| T32 | Response missing/stale approval or protected target | Dispatch denied |
| T33 | Response provider times out after possible effect | Outcome unknown; reconciliation rather than blind repeat |
| T34 | Cloud outage during action TTL | Qualified local/remote expiry mechanism still limits effect |
| T35 | Customer changes remote state before rollback | Rollback does not clobber later customer change |
| T36 | Noisy tenant/burst/export saturates shared cell | Fairness, backlog durability and documented SLO limits assessed |
| T37 | Billing callback replay or duplicate meter interval | One accounting effect; adjustments auditable |
| T38 | Artifact/signing key revoked or bad rollout detected | Activation blocked/rolled back with compatible recovery |
| T39 | Restore/failover/collector disk full | Declared RPO/RTO/loss behavior verified, gaps visible |
| T40 | Large/long-content UI with tenant switch and stale cache | No overlap, data bleed or misleading stale authority |
| T41 | Decision-guided query policy under missing/misleading evidence | Safe bounded research comparison; no autonomous containment |
| T42 | Authorized live connector onboarding and revocation | Actual provider permissions/cursors/limits behave as documented |

### 28.2 CI and Release Layers

PR checks: formatting/type checks, focused domain/unit tests, contract/schema tests, tenant negative tests, dependency/secret checks and migration checks. Nightly: broader replay, fuzz/property tests, multiworker recovery and UI E2E. Candidate release: production-like load, seven-day soak, restore, connector acceptance, artifact qualification and independent security findings disposition.

Maintain regression tests for baseline measurement/profile/audit failures. Run production tests against PostgreSQL and the actual runtime role; SQLite-only tests cannot qualify SaaS isolation or database concurrency. Emulated queues/objects are useful locally, but acceptance includes the chosen managed services' behavior.

## 29. Delivery Sequence and Work Packages

### 29.1 Working Cadence

Use two-week engineering increments with a demonstration of an end-to-end workflow, updated evidence index, risk review and cost review. This is a planning cadence, not a promise that every package fits two weeks. Security/data foundations precede customer telemetry; response and research run only after their prerequisites.

Indicative Core V1 planning range: five to eight months with a small experienced team, accessible design partners and manageable connector scope. Provider edition, response, enterprise/private deployments and research are additional releases; implementing every extension well can exceed that range substantially. One coding agent can accelerate implementation but cannot supply buyer access, staffed operations, independent testing, counsel or prospective event samples.

### 29.2 Milestones

| Milestone | Indicative window | Scope | Exit evidence |
|---|---|---|---|
| M0: Baseline and buyer contract | Weeks 1-3 | B01-B05; rights, threat model, corrected measurement, chosen profiles | Signed scope/claims inventory; reproducible reports; committed design partners |
| M1: Secure telemetry vertical slice | Weeks 3-8 | B06-B10; supported runtime, tenant DB, CI, collector, network ingestion | Authenticated source -> durable manifest -> normalized evidence across restart |
| M2: Investigations that work | Weeks 7-13 | B11-B18; selected identity/cloud context, detectors, cases, console, notifications | Real authorized sources -> actionable case -> analyst disposition -> ticket/owner |
| M3: Partner observation and hardening | Weeks 12-22 | B19-B23; value, pentest, load/recovery, retention; B30 slice if software profile | Adequate pilot evidence; failure fixes; profile/capacity support matrix |
| M4: Paid Core V1 acceptance | Weeks 20-32 | B24-B27; metering, support/trust, GA evidence and renewal work | G0-G5 and G7 passed for declared scope; disabled unqualified extensions |
| M5: Provider and controlled extensions | After relevant gates | B28-B32; MSSP, response, more cloud, AI, private/research | Separate edition/adapter/profile qualification; no bundled readiness claim |

Work may overlap only after its dependencies and security boundary are available. Customer observation/sample acquisition can exceed engineering time. Milestones are revised after M0 and each completed capacity/connector experiment.

### 29.3 Package-to-Implementation Breakdown

The linked execution backlog retains each package's original dependencies/acceptance. The breakdown below adds implementation-level deliverables; any dependency refinement must be recorded before execution.

| Package | Concrete deliverables | Critical verification |
|---|---|---|
| B01 | Baseline/source/artifact inventory; claims register; fixture/data rights inventory | Reproducible current reports and explicit failed/missing gates |
| B02 | Receipt clock contracts; censor-aware matcher; publication latency accounting | T18-T20; introduced delay worsens lead correctly |
| B03 | Release states; qualification manifest; production enablement policy | T16-T17; integrity alone cannot enable a capability |
| B04 | Source/profile/artifact binding; strict production loader | Wrong profile/untrained bundle rejected; compatible rollback |
| B05 | Buyer interviews; two profile contracts; threat/data-flow model; architecture ADR | Required sources/permissions, success criteria and nonclaims agreed |
| B06 | OIDC integration; membership/grants; sensor identities; scoped API tokens | T01/T28; revocation, MFA policy and no demo authority |
| B07 | PostgreSQL migrations/repositories; composite FKs; RLS/runtime roles | T02-T04; actual worker/connection-pool isolation |
| B08 | Supported runtime matrix; locks; image/SBOM/signing; CI; environment IaC | Clean reproducible build, supply-chain/rights review, no secret coupling |
| B09 | Collector enrollment/spool; object upload; manifest/outbox; ingestion receipt | T06-T10; durable acceptance and restart/retry behavior |
| B10 | Qualified Zeek/Suricata adapters; capabilities; field masks; restricted parsing | Valid real-source fixtures, malformed data, source loss/lag |
| B11 | Entity/binding history; site domains; service owners/criticality | T12; no address-only false merge; repairable revisions |
| B12 | One real identity connector and permission/runbook pack | T11/T42; genuine outcomes, paging, delay and revocation |
| B13 | Durable jobs; leases/fencing; watermarks; checkpoint/replay; fair queues | T13-T15; no duplicate local effects or silent state reset |
| B14 | Versioned small detection pack; benign controls; correlation dependencies | T21-T22; actual evidence and useful case budget |
| B15 | Case lifecycle/history; dedup/merge/split; assignment/adjudication | T23-T24; durable coherent analyst workflow |
| B16 | Production console/routes; API types; queue/workbench/coverage/search | T40; authenticated E2E and responsive visual/accessibility QA |
| B17 | Signed notifications; one ticket connector; SIEM schema; escalation/revalidation | T25-T26/T42; failure reconciliation, no ticket=resolution shortcut |
| B18 | Profile wizard; source tests; capability coverage; enrollment/support guide | Customer can set up without founder-only manual intervention |
| B19 | Rules/simple-model baselines; chronological/profile evaluation; forecast gates | Prospective receipts, censoring, power/sample adequacy; report negatives |
| B20 | Pilot protocol; weekly adjudication; paired investigation study; value report | Buyer-confirmed usefulness and explicit uncertain metrics |
| B21 | Independent production-like security test; findings and retest evidence | Release-blocking findings closed; residual risks approved |
| B22 | Workload generator; skew/burst tests; cost dashboard; restore/soak drills | T36/T39; qualified capacity and achievable RPO/RTO |
| B23 | Retention classes; holds; deletion orchestration; tombstone restore gate | T30-T31; object/index/export/training/backup accounting |
| B24 | Entitlements; usage meter; invoice/payment adapter; grace/exit policies | T37; replay-safe accounting, auditable tariff changes |
| B25 | Support approvals/bundles; runbooks; status/incident process; trust pack | T28-T29; supported operating hours and truthful procurement answers |
| B26 | GA evidence manifest; supported profile/tier matrix; release checklist | G0-G5/G7; exact enabled scope independently reviewed |
| B27 | Renewal dashboard; customer outcomes; nuisance/coverage improvement | Value trend without removing hard negatives or inflating case counts |
| B28 | Proposal/approval state machine; one adapter; preflight/readback/TTL/rollback | T32-T35; G6 and authorized live effect acceptance |
| B29 | Provider/customer delegation; scoped queue; handoff/SLAs/provider usage | T05; explicit customer authority and fairness |
| B30 | Selected cloud/profile connectors; workload/session context; source-delay logic | T11/T12/T42; per-profile qualification, not broad cloud claims |
| B31 | Grounded summaries; tenant-local similar cases; feedback quarantine/promotion | Prompt-injection/citation/consent tests; no unsafe control authority |
| B32 | Qualified private topology; enterprise lifecycle; bounded research experiments | Separate deployment acceptance and held-out research reports |

### 29.4 Dependency Refinements

- Add supported-runtime and supply-chain qualification to B08 before any public production deployment.
- Require B06-B09 before authorized cloud ingestion. A minimal software-profile B30 connector slice may precede B19/B20; full B30 depends on identity/case foundations. Record the slice boundary and do not require it for the unrelated network profile.
- Complete minimal retention/access policy before first real customer telemetry; B23 expands and proves full deletion/restore behavior before GA. It is not permission to ignore privacy during pilot.
- Provider B29 requires production isolation, case/integration workflows, delegation threat tests and budgets; first provider sale requires its own acceptance, even if core GA is already complete.
- Response B28 depends on cases, audit, qualified connector, policies, recovery and protected-resource context. Forecast success is neither necessary nor sufficient for response authority.
- Decision-guided evidence research is a B32 experiment using the bounded B31/B30 query broker where appropriate; it does not hold up B26.

## 30. Feature Traceability

All 70 previously proposed capabilities are retained below with explicit implementation placement. Retention of an item in this plan does not make it mandatory for Core V1 or claim that it is novel. Each package links back to the original feature definition in the market plan.

| Feature IDs | Capability group | Primary packages | Planned release/gate |
|---|---|---|---|
| F01, F02 | Zeek and Suricata sources | B09-B10 | Pilot source qualification |
| F03, F04 | Source health and field capabilities | B09-B10, B18 | Pilot; prerequisite for honest detection |
| F05, F06 | Asset context and real identity evidence | B11-B12 | Selected pilot profile |
| F07 | Firewall/IPFIX selected source | B10, B30 | V1 after actual vendor acceptance |
| F08 | AWS flow/audit context | B30 | Selected software pilot slice or later V2 |
| F09 | IPv6/NAT/proxy/visibility semantics | B10-B11, B19 | V1 regime qualification; unsupported portions rejected |
| F10 | Payload-off/local evidence policy | B05, B09, B23 | Before customer data; verified lifecycle before GA |
| F11, F12, F13, F14 | Rules, beaconing, lateral and spray correlation | B14, B19-B20 | Pilot small qualified pack |
| F15, F16, F17 | Transfer, reconnaissance and expiring threat context | B14, B19 | V1 after benign-control testing |
| F18 | Role/peer baselines | B11, B14, B19 | V2; incremental measured usefulness |
| F19 | Business-criticality priority | B11, B15-B16 | V1; explainable ordinal rationale |
| F20 | Qualified progression forecasts | B02-B04, B13, B19 | Research until task/profile gates pass |
| F21, F22 | Case workbench and entity timeline | B15-B16 | Pilot core workflow |
| F23, F24, F25 | Graph layers, evidence search/export | B15-B16, B23 | V1; authorization/integrity gates |
| F26, F27 | Scoped evidence queries and similar cases | B30-B31 | V2; query broker before research planner |
| F28, F29 | Coverage/uncertainty and service ownership | B11, B15-B16 | Pilot coverage; V1 ownership |
| F30 | Grounded summaries | B31 | V2 optional; citation/privacy/injection gates |
| F31, F32 | Durable case lifecycle and dependencies | B14-B15 | Pilot |
| F33, F34 | Expiring suppressions/maintenance | B11, B15-B16 | V1 |
| F35, F36, F37, F38 | Notification, tickets, SIEM and escalation | B17 | Pilot notifications; V1 selected integrations |
| F39 | Adjudication/outcomes | B15, B19-B20 | Pilot with label provenance |
| F40 | MSSP delegation and customer queue | B29 | Provider edition gate |
| F41, F42 | Read-only recommendations/manual playbooks | B14-B17 | Pilot/V1; no dispatch |
| F43, F44, F45, F46, F47, F48 | Approvals, preview, adapter, expiry, reconciliation, checks | B28 | Controlled response extension; G6 |
| F49 | Remediation and revalidation | B17, B28 | Read-only V1 workflow; action-specific V2 checks |
| F50 | Counterfactual intervention research | B32 | Research only; causal qualification separate |
| F51, F52, F53 | Authentication, authorization and isolation | B06-B07, B13 | Before real customer data |
| F54, F55, F56 | Retention, encryption and durable audit | B06-B09, B23, B25 | Minimal before pilot; full proof before GA |
| F57, F58 | SAML/SCIM and private deployment | B32 | Buyer-driven enterprise extension |
| F59, F60 | Trust pack, scoped API and portability | B06, B16, B23, B25 | V1 |
| F61, F62, F63, F64 | Value, prospective evaluation, registry and drift | B02-B04, B19-B20, B27 | Pilot evaluation/registry; V1 scorecard/drift |
| F65, F66 | Budgets and recovery | B13, B22 | Pilot recovery; V1 qualified shared capacity |
| F67, F68, F69 | Billing, onboarding and support | B18, B24-B25 | Pilot setup; V1 commercial operations |
| F70 | Controlled feedback and promotion | B19, B31 | V2; consent and challenger gates |

New discussion item: time-aware decision-guided evidence acquisition is an experiment under F26/B32, not an unvalidated F71 that must be sold. Archive it if it does not improve the measured decision workflow.

## 31. Release Gates and Definition of Done

| Gate | Required proof | Responsible approval |
|---|---|---|
| G0: Rights and scope | Code/dependency/data/model rights, customer authority, deployment/purpose boundaries | Founder plus counsel/customer as applicable |
| G1: Measurement | Actual receipts, legal prefixes, follow-up coverage, leakage/censor checks, honest release states | Engineering and evaluation reviewer |
| G2: Security | Auth/tenancy/audit/secrets/upload/support controls; independent test disposition | Security owner and independent assessor |
| G3: Ingestion | Supported real source versions, durable receipt/replay, gap/clock reporting, source onboarding | Engineering plus customer administrator |
| G4: Buyer value | Useful-case and workload outcomes with adequate samples and explicit uncertainty | Customer buyer/analyst plus product owner |
| G5: Reliability and scale | Qualified workload, cost, soak, backup/restore, RPO/RTO, fairness and runbooks | Engineering/SRE owner |
| G6: Control safety | Exact authority, approvals, bounded effects, remote reconciliation, expiry/rollback and live acceptance | Customer response owner and safety reviewer |
| G7: Commercial operations | Contract scope, privacy/trust pack, billing, support/incident commitments and exit | Founder/customer procurement plus counsel |

Core GA requires G0-G5 and G7 for its declared profiles and capacity. G6 is required only to enable actual control effects, not to sell a read-only product. Forecasts have additional task/profile statistical gates; provider/private editions have additional boundary/operating gates.

Every package is done only when:

1. Implementation is reachable through its actual producer/consumer workflow, not just an unused interface.
2. Focused, contract and failure tests pass at the appropriate environment level.
3. Authorization, privacy, audit, budgets and recovery effects are addressed.
4. Documentation, migrations, rollback and operator guidance match shipped behavior.
5. A durable evidence report identifies version/environment and open limitations.
6. The designated owner accepts the evidence; unqualified claims remain disabled.

### 31.1 Release Evidence Bundle

Each release produces a signed manifest linking source revision, dependency locks/SBOM, images, migrations, configuration/policy schemas, source profiles, detector packs, optional model approvals, test reports, connector acceptance, load/cost/soak/restore reports, security findings, data/legal approvals, enabled features and known limitations.

Publish a customer-readable support matrix: connector/version, modality/valid fields, delay/visibility limitations, qualified workloads, availability/support commitments, enabled detection pack, optional forecast tasks, response actions and retention/deployment options. Do not compress all of this into a single "enterprise ready" badge.

## 32. Decision Register, Risks and Stop Conditions

### 32.1 Decisions to Resolve Before Committing Cost

| Decision | Default hypothesis | Evidence required to finalize |
|---|---|---|
| First two buyers/profiles | Network+AD business; AWS+Entra software company | Buyer access, real permissions, pain and willingness to pay |
| Hosting region/provider | India-region managed services | Customer residency, budget, operating skills and contracts |
| Production runtime | Qualified supported Python minor; Node LTS build | Native dependency compatibility and numerical parity |
| Identity/ticket/EDR vendor | One of each selected by actual demand | Authorized accounts, permissions, pricing and support burden |
| Search backend | PostgreSQL summary/index plus object partitions | Real query/cost benchmark before adding another datastore |
| Forecast launch | Disabled unless individual gates pass | Prospective supported-task advantage over strong baselines |
| Response launch | Manual playbooks first | One adapter with viable remote/local safety and G6 |
| MSSP launch | Separate provider edition | Explicit delegation acceptance and customer/provider buyer value |
| AI/research scope | Optional bounded modules | Measured decision/time improvement and privacy/safety gates |
| Private/air-gap offering | Later separately priced qualification | Committed buyer and complete operating dependency story |

### 32.2 Principal Risks

- Buyer wants an EDR replacement: qualify/disqualify early; do not expand into an endpoint platform casually.
- Prediction remains poor: keep forecast disabled and evaluate whether the investigation product has independent value.
- Telemetry too delayed or incomplete: report gaps, select suitable tasks and reject unsupported protection claims.
- Connector sprawl: stop expansion until one profile runs end to end with acceptable support cost.
- Multi-tenant leakage: block shared GA; dedicated deployments still require full actor/resource controls.
- Cases are noisy or duplicative: fix content/dependencies and test benign controls; do not hide misses through broad suppression.
- Unit costs exceed willingness to pay: reduce source/retention/query scope transparently or change segment; do not subsidize unlimited ingestion blindly.
- Response rollback cannot survive failure: offer manual response only for that adapter.
- Too few outcomes for claims: extend observation or label qualification inconclusive; never manufacture event prevalence.
- Founder-only onboarding/support: fail the scalable operating gate and build the required tooling/runbooks.
- Legal/source/license rights unclear: do not deploy or redistribute the affected component/data.

### 32.3 Stop Conditions

Pause a capability's promotion when a release-blocking isolation/security finding appears, source rights are unresolved, useful-case outcomes fail the predeclared gate, cost exceeds the agreed envelope without a credible remedy, or required safety mechanisms are unavailable. Continue unrelated safe foundational work where possible; do not hide failure by moving the threshold after testing.

If neither target segment demonstrates willingness to pay for measured core value after structured pilots, revisit the product positioning before building further extensions. If decision-guided evidence research is inconclusive or inferior, archive it without adding marketing fluff. If the complex forecast cannot outperform simpler alternatives, ship the simpler qualified component or no forecast.

## 33. First Implementation Increment

Start with B01-B05 and the interfaces required for B06-B09, not with additional dashboards or autonomous AI:

1. Revalidate current Git/artifacts and freeze an evidence inventory without altering historical reports.
2. Correct actual-publication/delivery timing and censoring; add regression tests for the existing false-readiness paths.
3. Introduce explicit integrity/qualification/approval states and strict profile loading.
4. Confirm the first two customer profiles, data rights, permissions, success measures and workload envelope.
5. Write accepted commercial ADRs for tenancy, timing, ingestion durability, supported runtime and profile-specific limits.
6. Build the secure vertical slice: real actor -> tenant-scoped API -> enrolled sensor -> durable batch -> normalized observation -> case -> receipt.

At the end of that increment, demonstrate one restart-safe, authorized workflow and its negative tests. That establishes the foundation for a product that works; it does not yet establish general availability, forecast quality or market leadership.

## Appendix A. Concrete Detection Implementation Contracts

These are initial engineering designs to test, not qualified thresholds or probability models. All thresholds live in versioned profile/content-pack configuration and are fixed before final evaluation.

### A.1 Periodic Outbound Behavior

Group valid connection-start observations by stable source entity, destination identity/address, transport and observation domain. Require minimum sample count, adequate observation span and source completeness. Compute inter-arrival distribution, robust spread, persistence across windows, destination novelty and available byte/duration consistency. Avoid a simple "same interval equals malware" rule; scheduled benign services are common.

Implement a transparent baseline first: median interval, median absolute deviation relative to interval, proportion of gaps near integer multiples, repeated-window persistence and documented minimum counts. Test against randomized jitter, connection retries, missing samples and multiple benign periodic services. Only add spectral/autocorrelation features if they improve held-out behavior enough to justify cost.

Output: observed periodic behavior score with component values, observation span, source coverage, destination context and example supporting records. Score does not mean probability of C2. Destination reputation is an expiring separate context signal. The same source alert/flow is not counted as independent confirmation.

### A.2 Password Spray and Suspicious Success

Consume only real qualified authentication outcomes. Maintain bounded sliding aggregates over actor/source, target principal set, failure categories and destination service, partitioned by tenant/domain. Track successful authentication following relevant failures within a configured horizon, preserving exact event relationships and ambiguous principal/source bindings.

Distinguish one mistyped account from multi-account patterns; incorporate distributed-source patterns only when source coverage supports them. Exclude or annotate approved password tests, known proxy egress, service retries and account lockout policies. A success following failures is a suspicious correlation, not proof that credentials were stolen.

Output includes number of distinct targets, qualified failure/success counts, involved principals/services, timing and evidence references. If failure outcomes are missing, disable the spray claim rather than count all sign-ins as failures.

### A.3 Administrative/Lateral Activity

Build observed temporal relations among authenticated principal, source device, destination device/service and permitted administrative protocol evidence. Compare new fan-out/role relationships with approved administration/scanner/maintenance context. Require minimum identity binding confidence for identity-specific claims.

Do not label a port scan as lateral compromise or assume any SMB/RDP connection is an attack. A correlated case can state unusual administrative fan-out and request owner confirmation. Confirmed compromise requires stronger independent evidence or attributed adjudication.

Cross-model-scope observed correlation is permitted with explicit records; it must not become a cross-scope calibrated forecast by accident.

### A.4 Unusual Transfer and Low-and-Slow Reconnaissance

For transfer, require valid byte direction, observation completeness and comparable baseline intervals. Use robust historical quantiles/median-deviation within appropriate asset role/time buckets; show cold-start and low-sample states. Incorporate backup/replication/export context. Explain observed volume and destination change; do not infer sensitive file content from encrypted flow counters.

For reconnaissance, track bounded unique target/port estimates and exact exemplar records across short and longer windows. If sketches are used, record estimation error and preserve verifiable sample evidence. Test approved scanners, service discovery, load balancers, failed health checks and low-volume hostile patterns. Bound state by tenant/source with documented eviction that produces coverage limitations.

### A.5 Content Pack Review

Each detector pack contains source/field requirements, algorithms/thresholds, resource limits, test fixtures, benign controls, expected case grouping, rationale text, false-positive guidance, support status and rollback compatibility. Review changes for reduced recall as well as improved alert counts. Threat-intelligence feeds carry origin, license, observation/expiry times and confidence; expired context cannot silently remain active.

## Appendix B. Processing and Policy Examples

### B.1 Idempotent Local Commit

```text
receive job reference
load committed manifest using trusted tenant context
validate current authorization, schema, handler version and deadline
acquire lease with new fencing token
compute bounded result from the committed input prefix
begin database transaction
  require lease/fence still current
  if effect key already committed: return its result
  insert output and input provenance
  update checkpoint/progress with the same commit boundary
  insert case/publication/delivery outbox events
commit
acknowledge queue message
```

Object/checkpoint payloads are written and verified before their committed pointers. Failed transactions leave removable orphan objects, not advanced progress. Remote notifications/response are dispatched from their own durable intents and have separate reconciliation semantics.

### B.2 Example Case API Output

```json
{
  "schema_version": "case.v1",
  "case_id": "opaque-case-id",
  "version": 7,
  "status": "investigating",
  "adjudication": "unknown",
  "severity": "high",
  "severity_reasons": ["sensitive-service", "suspicious-success-after-failures"],
  "evidence_refs": ["evidence-id-1", "evidence-id-2"],
  "coverage": {"identity": "adequate", "network": "partial"},
  "open_questions": ["Was this access approved?"],
  "owner_ref": "scoped-actor-id",
  "forecast": {"state": "disabled", "reason": "profile-not-qualified"},
  "delivery": {"transport": "webhook", "state": "accepted-by-transport"}
}
```

The actual response also includes permitted entity/service/timeline links and precise clocks. It never exposes another tenant's actor details, hidden evidence classes or an implied incident probability from ordinal severity.

### B.3 Policy Evaluation Order

```text
trusted actor/sensor identity
-> organization/cell placement and active status
-> resource tenant and current grant/delegation
-> action-specific role and field/evidence class restrictions
-> policy version, expiry and protected-resource constraints
-> resource budget and source/capability compatibility
-> durable audit requirements
-> execute or reject with a stable reason code
```

Resource budgets can defer expensive work but must not bypass authorization or falsely report missing observations as complete. Response adds approval, preflight, exact target and remote-effect constraints before dispatch.

### B.4 Suppression Contract

Every suppression carries creator/approver, purpose, tenant/site/entity/service scope, detector/content version match, start/expiry, review date and reason. It distinguishes notification suppression, case grouping and approved-context annotation. Retained observations remain searchable under authorized policy. Suppression hit counts and unexpected coverage effects are visible; blanket permanent tenant suppression is not a normal convenience feature.

## Appendix C. Evidence and Implementation Checklist

Keep a repository-owned implementation tracker with package ID, status, source revision, owner, dependencies, test report paths, environment, live acceptance, unresolved gates and approval date. Planned and partially implemented packages must not be labeled complete because code exists.

Before any model implementation, hash-compare the authoritative build-spec copies where the repository workflow requires it and stop on mismatch. Research torch/pytest reproduction uses the established Python 3.10/no-new-venv workflow until a separately approved migration; production runtime qualification is a separate activity.

Store new large corpora and generated artifacts on an explicitly selected data volume with adequate headroom; the prior inspected workspace had limited free space. Do not start full-volume telemetry load tests or downloads on that volume without checking capacity and retention. Record dataset rights and provenance before acquisition.

Customer-facing acceptance must include at least one complete authorized environment for each sold profile, not just sample files. A feature that is useful only in a synthetic demo remains a research/demo feature in the support matrix.

Final launch review asks: can a buyer install it, see supported evidence, investigate meaningful cases, integrate existing work, recover from failure, understand costs, revoke access, delete/export data and obtain the promised support? If any required answer is no, the corresponding market release is not complete.
