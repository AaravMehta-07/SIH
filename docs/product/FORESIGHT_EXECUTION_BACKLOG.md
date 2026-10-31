# FORESIGHT: Execution Backlog

Date: 2 October 2026. All packages below are **planned**, not completed.
Authority: proposed [Market Readiness Plan](FORESIGHT_MARKET_READINESS_PLAN.md).
Detailed implementation contracts and sequencing refinements: [SaaS Implementation Plan](FORESIGHT_SAAS_IMPLEMENTATION_PLAN.md).
Existing research authority: [Build Specification](../../FORESIGHT_Build_Spec.md) and accepted [ADRs](../adr/).

## Delivery Rules

- Preserve the offline research pipeline and its honesty contracts. Add a distinct production mode; never make demo credentials, synthetic labels or untrained fallback valid in production.
- Recheck current Git state before each package. Preserve unrelated changes and never overwrite existing evidence/artifacts to make a gate pass.
- Use focused tests plus contract/integration/security tests proportional to each package's blast radius.
- Each package must produce implementation, tests, documentation and a durable evidence report. A design or interface alone is not completion.
- Record versioned model/data/schema/policy changes explicitly; new feature channels invalidate old compatibility claims.
- Acceptance thresholds are fixed before final testing. An inconclusive capability stays disabled; passing software tests does not override it.
- Do not deploy paid cloud resources or connect customer systems without the necessary customer authority and approved budget.
- Keep consent, support access and response authority separate. No external memory storage for customer evidence without authorization.

## Roles and Dependencies

Coding agent: implementation, test harnesses, local verification, deployment definitions and evidence artifacts.
Founder/product owner: buyer access, scope, budget, priorities, contracts and sales.
Customer administrator/analyst: authorized integrations, operational context, outcomes and pilot feedback.
External specialists: independent security testing, commercial/privacy counsel, certification and any staffed MDR service.

Each dependency list uses package IDs. Work can overlap only where its stated prerequisites are met. Estimates are intentionally not per-ticket promises; apply the phase ranges in the market plan and update after discovery.

## Phase A: Baseline and Claims

### B01. Freeze the Baseline and Commercial Claims Inventory

Dependencies: none. Owners: coding agent + founder.
Scope: source/release/artifact inventory; supported target/profile matrix; deployment and rights inventory; clean reproducible developer setup.
Existing modules: `README.md`, `pyproject.toml`, `configs/release.json`, `api/bundle.py`, `cli`, `docs/adr`.
Acceptance: source-only installation works in a clean environment; hash manifest captures the unchanged reference; every public claim maps to real evidence or is marked experimental/unavailable; synthetic and real evidence remain separate.
Evidence: `reports/product/baseline/<run-id>/inventory.json`, commands/results, dependency and ownership review checklist. Human gate: commercial ownership and dataset/content permissions.

### B02. Independent Measurement Oracle and Evaluator Repair

Dependencies: B01. Owner: coding agent; methodology reviewed by a security/ML specialist.
Scope: actual source/availability/ingestion/publication/delivery clocks; follow-up completeness and censoring; event matching; case deduplication; supported exposure denominators; correct latency naming.
Existing modules: `evaluation/matching.py`, `evaluation/report.py`, `storage/store.py`, `api/service.py`, training prediction exporters.
Acceptance: hand-computed fixtures cover events before/during/after delivery, partial follow-up, unknown labels, zero exposure, repeated warnings, multiple episodes with reused entity IDs, cooldowns and multiple horizons. No double matching. Sampling/ranking tests cannot quietly label censored outcomes negative. Receipt lead uses an explicitly mapped replay clock or independently observed live timestamps.
Evidence: oracle fixtures, old/new metric comparison without overwriting old reports, versioned metric specification and regression tests. No new performance claim from this package alone.

### B03. Separate Integrity, Deployment and Claim Release States

Dependencies: B01, B02. Owner: coding agent.
Scope: make integrity verification explicit; add deployment qualification and per-capability promotion; fail-closed production bundle loading and approved manifests.
Existing modules: `cli`, `api/bundle.py`, `configs/release.json`, `contracts/quality.py`.
Acceptance: a bundle with failed recall or nuisance gates can be integrity-valid but cannot promote that forecast capability. Missing evaluation/hash coverage/signature/model approval is rejected in production. Optional absence is never advertised as supported. Regression fixture reproduces today's integrity-pass/performance-fail state.
Evidence: release-state schema, promotion receipts, artifact tampering/rollback tests, supported-claim manifest.

### B04. Fix Source/Profile Binding and Serving Contracts

Dependencies: B01, B03. Owner: coding agent.
Scope: explicit source/capability-to-bundle selection; no CTU session loading the default synthetic model; request horizon behavior either supported or rejected.
Existing modules: `api/server.py`, `api/service.py`, `api/bundle.py`, CTU adapters and task manifests.
Acceptance: tests bind synthetic/flow/packet profiles to their own scaler, calibrator, task mask and report; missing/mismatched profiles fail explicitly; caller cannot request an unqualified horizon or change tenant/profile through arbitrary input. Real-source unavailable state is accurate.
Evidence: profile compatibility matrix and API integration tests. Real CTU training is a separate evaluation task, not silently triggered here.

### B05. Buyer Scope, Threat Model and Production ADR

Dependencies: B01; can overlap B02-B04. Owners: founder + coding agent.
Scope: discovery protocol, 3-5 initial scenarios, source access, dedicated pilot topology, regional data flow, abuse cases, privacy boundaries and proposed platform choices.
Acceptance: named user/buyer, specific deployment environment, lawful telemetry agreement, accepted nuisance workload, independent pilot protocol and clear no-response/no-MDR boundaries. Threat model includes compromised sensors, malicious files/logs, stolen connector credentials, cross-tenant data, support abuse and supply-chain compromise.
Evidence: discovery findings, design-partner scope sheets, threat model and a new production ADR that does not rewrite existing research ADRs. Human gates: partner commitments and authorized hosting budget.

## Phase B: Secure Product Foundation

### B06. Organizations, SSO and Actor/Resource Authorization

Dependencies: B05. Owner: coding agent.
Scope: OIDC integration, MFA policy, organization membership, RBAC, scoped API credentials, session/token revocation and support-access grants. Add a production API boundary separate from demo behavior.
Acceptance: unauthenticated and expired/revoked credentials denied; role/resource matrix exercised for every route; tenant never taken from client body; organization switching and support expiry do not leak cached data. Cookies/CSRF/CORS and API-token behavior match the chosen auth flow. Never implement a new password/crypto system unnecessarily.
Evidence: executable authorization matrix, two-tenant negative tests, auth integration results and documented privileged access.

### B07. Durable Tenant Storage, Migrations and Object Grants

Dependencies: B06. Owner: coding agent.
Scope: PostgreSQL schema for tenant-scoped entities/cases/jobs/receipts; transactional updates/outbox; object-store abstraction; migration path that leaves research SQLite intact.
Acceptance: composite constraints and scoped queries; actual runtime DB role cannot bypass intended tenant access; objects/exports/jobs/cache keys honor tenant; caller cannot supply a foreign tenant at write time. Transaction failure cannot leave inconsistent evidence/case/publication state. Restore and migration fixtures use real storage integrations, not only mocks.
Evidence: schema/migrations, data-boundary integration suite, storage recovery report and audit of privileged roles.

### B08. CI, Packaging and Reproducible Production Releases

Dependencies: B01, B05; production smoke tests require B06-B07.
Scope: tested dependency lock, production serving dependencies, container packaging, CI, secret/dependency checks, SBOM, signed release artifacts and staging deployment definitions.
Acceptance: source-only build/install/test works without laptop-specific `sys.path` fixes; non-root service; no trained private data/secrets embedded in images; verified artifact pull and rollback; offline demo still works. Use existing Python 3.10 locally until an explicit supported-runtime migration is tested; no unnecessary environment reinstall.
Evidence: clean-build manifest, SBOM, signatures, CI results and staging release/rollback transcript.

### B09. Sensor Enrollment and Secure Ingestion Gateway

Dependencies: B06-B08. Owner: coding agent + customer administrator.
Scope: per-sensor enrollment/certificate rotation, authenticated bounded batches, source identity, schema/sequence/hash validation, ingestion receipts, per-tenant quotas and payload-off policies.
Acceptance: forged tenant/sensor IDs, revoked credentials, conflicting replay, oversized input and decompression abuse rejected; duplicate batches idempotent; gap/drop accounting; durable acknowledgment before collector removes spool data; no raw secrets in logs or error messages. Enrollment tokens are expiring and single-use.
Evidence: ingestion contract fixtures, adversarial tests and end-to-end sensor lifecycle report.

### B10. Real Zeek and Suricata Connectors

Dependencies: B09. Owner: coding agent + customer administrator.
Scope: supported pinned source schemas, connection/DNS/TLS/EVE records, loss/capability reports, flow correlation, safe shipping and local buffering.
Acceptance: compare normalized output to independently inspected source logs; rotation/truncation/reconnect/schema changes and unsupported fields handled; no synthesized packet fields. Missing capture direction, IPv6 or payload visibility is explicit. Content/signature feeds have approved redistribution terms.
Evidence: golden real-source fixtures, version support matrix, throughput and accepted/rejected-record reconciliation.

### B11. Asset Identity and Business Context

Dependencies: B07, B10. Owner: coding agent + customer administrator.
Scope: observed addresses, site/domain, DHCP/DNS/CMDB bindings, expiry, ambiguity, owner and service criticality.
Acceptance: duplicate RFC1918 addresses across tenants/sites isolated; address reuse does not merge independent histories; stale/conflicting/NAT bindings do not select an unsafe control target. Criticality is customer-supplied/versioned, not invented.
Evidence: binding fixtures, ambiguous-identity scenarios and asset lifecycle tests.

### B12. Real Identity Evidence Connector

Dependencies: B09, B11. Owner: coding agent + customer administrator.
Scope: read-only AD event forwarding for the initial partner; Entra sign-ins may substitute only if discovery selects that environment. Record collection delays, permissions and source licensing limits.
Acceptance: source IDs/outcomes/users/sessions normalized with provenance; auth failure and success semantics checked; service accounts and clock skew covered; no synthetic identity stream in production. Model inputs and evidence-only use remain distinct unless a new profile is qualified.
Evidence: authorized-source replay fixtures, permission review and support/capability matrix.

## Phase C: Useful Read-Only Product

### B13. Windowing, Queue Ownership and Restart Recovery

Dependencies: B07, B09-B12. Owner: coding agent.
Scope: bounded jobs/workers, deduplication, watermarks, lateness, offsets, per-tenant fairness and deterministic graph partitions with explicit boundaries.
Acceptance: stop/restart/duplicate messages reproduce identical lawful prefixes; late input creates linked revisions, not rewritten prior claims; overflow/dead-letter behavior observable; 128-node scopes remain qualified; partition boundaries cannot disappear as benign negatives. No universal exactly-once claim.
Evidence: fault-injection results, partition ownership/offset report and reference-vs-streaming parity tests.

### B14. Qualified Initial Detection and Correlation Pack

Dependencies: B02, B10-B13. Owners: coding agent + detection specialist + analysts.
Scope: maintained known-threat rules; beaconing, lateral activity and credential-spray correlation; separate observed signatures, heuristic suspicion and confirmed outcomes.
Acceptance: source-linked cases for authorized scenarios and challenging benign backups/scans/admin activity; duplicate evidence cannot inflate corroboration; frozen thresholds; unsupported modalities disabled; known misses and nuisance workload recorded. No exfiltration or compromise conclusion from byte volume/port numbers alone.
Evidence: detection content versions, scenario coverage map and independent benign/attack validation. Feature expansion requires its own qualified data.

### B15. Durable Cases, Feedback and Nuisance Controls

Dependencies: B06-B07, B14. Owner: coding agent.
Scope: case lifecycle, ownership/comments, deduplication, outcome states, suppressions, maintenance windows and auditable case revisions.
Acceptance: concurrent edits and restarts preserve history; suppression scoped/expiring/reasoned; confirmed/benign/unknown distinguishable; aggregate case counts cannot conceal event misses; role and tenant constraints exercised.
Evidence: workflow integration tests and analyst acceptance on representative cases.

### B16. Production Investigation Console

Dependencies: B11, B15. Owner: coding agent; analyst validation.
Scope: incident workbench, entity timelines, evidence search, coverage panel, ownership context and distinct graph layers. Reuse suitable existing React components; keep replay/demo as a separate mode.
Acceptance: desk/mobile/narrow and long-ID states; source gaps, no results, permission errors, canceled requests and large graphs handled. Evidence links resolve only authorized source records. Playwright end-to-end flows and fresh screenshots; no guess presented as observed fact.
Evidence: browser acceptance report, screenshots, accessibility checks and two-tenant export/link tests.

### B17. Notifications and Existing-Stack Integration

Dependencies: B15. Owner: coding agent.
Scope: signed webhook, email, one buyer-selected ticket connector, SIEM export, delivery retry and acknowledgment records.
Acceptance: customer-controlled endpoint validation prevents SSRF/internal-metadata access; secrets redacted; duplicate retry does not create duplicate tickets; revoked connectors fail visibly; event publication and destination receipt tracked separately. Offboarding revokes delivery access.
Evidence: real sandbox connector acceptance and duplicate/outage/secret-rotation tests. No paid integration availability claim from mocks alone.

### B18. Guided Onboarding and Data-Minimization Controls

Dependencies: B09-B17. Owners: coding agent + customer administrator.
Scope: sensor/source setup, readiness checks, privacy/retention settings, credentials management and explicit first-use coverage.
Acceptance: a second administrator can enroll and produce a validated case from the documented procedure; missing sources never show healthy low risk; secret/payload redaction checked; source scopes and retention visible and enforced.
Evidence: independent onboarding transcript, measured time-to-first-evidence and privacy test fixtures.

## Phase D: Evidence and Pilot Qualification

### B19. Model Diagnosis, Baselines and Modality Profiles

Dependencies: B02-B04, B10-B14; lawful data from B05.
Scope: CTU hash requalification; lawful real-data registry; strongest comparable baselines; graph/memory/rollout/identity/ensemble ablations; new profile training and natural-prevalence calibration.
Acceptance: train/dev/calibration/test separation including campaign/site/time; no holdout-driven tuning; complete training provenance; independent event units and support documented; low recall investigated through controlled experiments. Preserve old reports/artifacts. Missing evidence remains inconclusive.
Evidence: experiment ledger, versioned model cards and unchanged-test comparison. Outcome can be "ship baseline detection, keep world model experimental."

### B20. Prospective Pilot and Buyer Value Scorecard

Dependencies: B14-B18 and G0-G3; forecasting publication additionally requires B19/B03.
Owners: founder + customer analysts + coding agent; independent scenario operator.
Scope: three authorized partners, shadow monitoring, benign operations, controlled scenarios, agreed workload/value/latency/cost metrics.
Acceptance: preregistered protocol and untouched final window; actual delivery lead; source coverage/misses/unknowns; nuisance cases, paired analyst time and costs; signed customer readout. Lack of natural attacks is not perfect recall. Customer decides whether value justifies paid continuation.
Evidence: partner-scoped reports and a claims matrix separating controlled/replay/shadow/live evidence. Human gate: continued data authority and actual buyer feedback.

### B21. Independent Security Review and Remediation

Dependencies: B06-B18. Owners: external security reviewer + coding agent.
Scope: tenant/role abuse, ingestion/parser isolation, credentials, log/LLM injection, dependencies, webhook SSRF, exports, support tools and deployment configuration.
Acceptance: independent review of deployed production-like boundary; critical/high exploitable issues fixed and retested; residual risks accepted by named owner. Source scanner counts alone cannot pass this package.
Evidence: external report, remediation/retest references and documented risk decisions.

### B22. Load, Soak, Recovery and Cost Qualification

Dependencies: B08-B18. Owner: coding agent; operator validation.
Scope: measured declared asset/event envelope, bursts/noisy tenants, bounded explanations, storage growth, seven-day soak, backup/restore, certificate rotation and migration rollback.
Acceptance: stated latency and resource targets met on named hardware/hosting; source-to-delivery and window-to-case reported separately; queues bounded; RPO/RTO verified through actual restoration; remote outages cause visible degradation. Quote capacity only within tested workload.
Evidence: reproducible workload generators, raw telemetry, restore transcript, cost model and supported deployment limits.

### B23. Retention, Deletion and Offboarding Verification

Dependencies: B07, B15-B18. Owners: coding agent + counsel/privacy owner.
Scope: legal retention classes, customer deletion, evidence/exports/indexes, training consent, backup expiry and connector revocation.
Acceptance: deletion reaches all documented stores within agreed windows; restored backup cannot silently resurrect deleted accessible records; legal holds handled explicitly; approved customer training data tracked separately; no access after offboarding.
Evidence: retention/deletion inventory, end-to-end deletion drill and counsel-approved policy mapping.

## Phase E: Supported Paid V1

### B24. Subscriptions, Entitlements and Invoicing

Dependencies: B05, B20, B22. Owner: coding agent + founder.
Scope: plan/contract limits, stable active-asset metering, usage visibility, onboarding charges and invoice/payment-provider references.
Acceptance: replay/DHCP duplicates do not inflate usage; entitled capacities enforced; downgrade/expiry has an explicit safe data-retention policy; invoice reconciliation idempotent; payment failures do not silently destroy evidence. No locally stored card data.
Evidence: billing fixtures, invoice reconciliation tests and agreed price/cost assumptions. Pilot manual invoices may precede full automation.

### B25. Support, Trust and Customer Operations

Dependencies: B20-B23. Owners: founder/operator + coding agent + counsel.
Scope: support runbooks, incident process/status page, authorized support bundle, architecture/data-flow pack, DPA/subprocessor list, SLA scope, commercial license and disclosure policy.
Acceptance: another operator can diagnose/restore without unrestricted customer access; escalation owner and business hours explicit; actual service availability observed before contractual promises; no unsupported SOC 2/ISO/MDR claim.
Evidence: runbook drill, procurement questionnaire pack, support-access audit and signed business/legal approvals.

### B26. V1 Commercial Acceptance

Dependencies: B03, B20-B25. Owners: founder + coding agent + external reviewers.
Scope: release review combining G0-G5 and G7; no real response unless G6 separately passes.
Acceptance: repeatable onboarding, useful qualified cases, permitted data handling, secure boundary, independent retest, recovery and support, measured cost and buyer willingness to pay. Disabled features remain disabled. Publish exact sources, tasks, limits and experimental capabilities.
Evidence: signed release dossier and buyer-specific acceptance. An agent test result cannot replace commercial approval.

### B27. Retention and Repeatability Improvements

Dependencies: B26. Owners: founder + coding agent.
Scope: renewal measurement, onboarding automation, one additional demanded connector, better suppression/search, cost optimization and qualified detection updates.
Acceptance: expansion selected from actual usage/support evidence; source adapters maintained; changes preserve tenant/case/detection regressions; support hours and deployment effort decrease without coverage loss.
Evidence: cohort usage/renewal findings, support-cost trend and each new connector's acceptance report.

## Phase F: Gated Expansion

### B28. Real Response Authority and One Adapter

Dependencies: B06-B07, B11, B21-B22, B26; customer change authority.
Scope: separate credentials/service, actor-bound signed approvals, protected targets, expiration, preview, TTL, kill switch, durable audit, one EDR/firewall adapter and remote readback.
Acceptance: tampered/stale/replayed approvals denied; duplicate requests and crashes before/after remote acknowledgment reconcile safely; partial failures and `outcome_unknown` do not imply success or blind retry; rollback and service-impact checks exercised. Audit/control failure fails closed. No claim of exactly-once remote effects.
Evidence: adapter-specific controlled acceptance, kill-switch/recovery drills and G6 approval. Synthetic paired trials are not sufficient.

### B29. MSSP Delegation and Portfolio Operations

Dependencies: B26; committed partner with defined operations.
Scope: delegated organization access, pooled queue, per-customer policy/entitlements, partner onboarding and reporting.
Acceptance: reseller permissions do not create global data access; cross-customer summaries contain only authorized data; customer exit revokes delegation; invoices and resource quotas remain scoped. White labeling follows actual purchasing need.
Evidence: multi-customer authorization suite, real partner workflow trial and partner contract.

### B30. Cloud Context and Additional Qualified Profiles

Dependencies: B19, B26; buyer demand.
Scope: one cloud environment, documented flow-log/control-plane delays, workload identity, permitted sign-in/cloud audit APIs, modality-specific training.
Acceptance: cloud flow logs never fabricated into packet telemetry; rate limits/permissions/delays visible; short-horizon support conditioned on actual availability; capability claims have their own holdout evaluation.
Evidence: cloud-specific source contracts, integration acceptance and model/support manifests.

### B31. Grounded AI Assistance and Controlled Learning

Dependencies: B15-B16, B21, B23, B26.
Scope: cited case summaries/query assistance; optional consented feedback quarantine, reviewed labels, challengers and human promotion.
Acceptance: malicious logs cannot inject privileged instructions; retrieval and citations tenant-scoped; no invented facts/probabilities or autonomous response; external model processing is consented/redacted; poisoned/unreviewed labels do not trigger retraining or promotion.
Evidence: adversarial evaluation, privacy tests, citation correctness and challenger/rollback records. AI assistance is not a substitute for core investigations.

### B32. Private Deployment and Research Extensions

Dependencies: B26; committed buyer/funding and explicit revised contracts.
Scope: private VPC/customer-hosted or air-gapped packaging; persistent memory, advanced active sensing and counterfactual research as independent modules.
Acceptance: deployment-specific upgrades, restore, secrets, licensing, support and resource limits proved. Persistent memory gets separate burn-in/prequential tests. Intervention outputs stay hypotheses until causally validated. Never bundle unqualified research into enterprise support claims.
Evidence: deployment qualification dossier and separate research reports; outcome can remain research-only.

## Definition of a Complete Package

A package is complete only when the actual behavior is implemented, its failure/abuse states are tested, its interfaces are documented, its evidence report is reproducible, and its owners accept the applicable gates. Record what is locally tested versus live accepted. Commit explicit scoped paths only after validation and never include private customer data or secrets.

## First Implementation Milestone

Start B01-B05 rather than a large UI rewrite. The first milestone should leave us with a trustworthy baseline, correct evaluator, honest release states, correct profile binding and an approved narrow production design. It should not deploy an insecure pilot or claim that repaired metrics prove predictive effectiveness.
