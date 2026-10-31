# FORESIGHT: Market Readiness and SaaS Product Plan

Date: 2 October 2026. Status: proposed commercialization plan, not an implemented release.

Working repository: `C:\Aarav\Code\SIH\SIH`.
Inspected baseline: `51e1bbe450aa29bb2a13c3c1c900692162b6c7fc` on `main`.
Implementation companion: [Execution Backlog](FORESIGHT_EXECUTION_BACKLOG.md).
Detailed commercial build specification: [SaaS Implementation Plan](FORESIGHT_SAAS_IMPLEMENTATION_PLAN.md), including profile-specific sequencing refinements and the gated evidence-acquisition experiment.

## 1. Executive Decision

FORESIGHT is a substantive offline research prototype with a working graph-temporal forecasting pipeline and analyst console. It is not presently a production cybersecurity SaaS. The best path is to preserve its research strengths, build a secure continuous-monitoring product around them, and earn narrowly scoped performance claims through customer pilots.

Do not attempt to replace CrowdStrike, Microsoft Sentinel, Darktrace, Wiz, and an entire SOC simultaneously. Start as an additional network-and-identity investigation layer for a specific customer segment. Win one repeatable buying decision before expanding the platform.

Recommended initial positioning:

> FORESIGHT connects network and identity evidence into clear attack-progression investigations, shows where visibility is missing, and measures which warnings actually helped your security team.

The forecasting extension becomes a paid differentiator only after prospective evidence supports it. Until then, detection, correlation, evidence navigation, and investigation efficiency must deliver value independently of the learned world model.

Recommended commercial sequence:

1. Validate the buyer and obtain authorized design-partner telemetry.
2. Repair measurement and release qualification before optimizing the model.
3. Build a secure, dedicated-tenant, read-only pilot with real connectors.
4. Prove useful investigations and acceptable operational cost on real traffic.
5. Launch a bounded paid product with onboarding, support, contracts, and explicit coverage.
6. Add calibrated forecasting, safe response, and MSSP operations behind their own gates.

This is a route to competing effectively, not a guarantee of beating established vendors. Product-market fit, production security, forecasting effectiveness, and sales must each be proved separately.

## 2. What Exists Today

### 2.1 Architecture and Assets Worth Preserving

The implemented path is:

```text
Synthetic packets / bounded PCAP / versioned flow files
  -> normalization, source clocks, capability and quality reports
  -> scoped address/entity graph, legal-prefix windows, validity masks
  -> directed graph encoder, per-entity GRU, global LSTM
  -> learned latent rollout, observable decoders and event hazards
  -> hazard calibration, ensemble disagreement, selective publication
  -> sealed forecast records, novelty diagnostics and evidence attribution
  -> paths, targeted evidence requests, replay and synthetic action trials
  -> FastAPI offline API and React analyst console
```

Strong existing foundations:

- Typed contracts separate observed evidence, predictions, unsupported tasks, and unknown outcomes.
- Features distinguish unavailable information from observed zero values.
- Eligibility checks account for event, availability, and ingestion clocks.
- The model has real temporal state and learned transitions, not just an AI-themed dashboard.
- Hazard-derived survival and event-time distributions preserve probability semantics.
- Training, calibration, data qualification, source hashes, and artifact manifests exist.
- Explanations recompute features after grouped deletion and disclose sensitivity rather than causality.
- Immutable forecast hashes and publication receipts provide a useful provenance starting point.
- Paths disclose that hypotheses are not calibrated attack-path probabilities.
- The action plane is explicitly synthetic, with a state machine and policy checks.
- The console already exposes sessions, forecasts, evidence, paths, replay, evaluation, and query/action interactions.

Relevant implementations include [world_model.py](../../src/foresight/models/world_model.py), [forecast.py](../../src/foresight/runtime/forecast.py), [events.py](../../src/foresight/contracts/events.py), [windows.py](../../src/foresight/features/windows.py), [attribution.py](../../src/foresight/explain/attribution.py), and [App.tsx](../../apps/console/src/App.tsx).

### 2.2 Current Evidence, Not Marketing Status

| Check | Result observed in this assessment | What it does not establish |
|---|---|---|
| Git working tree before assessment | Clean | Commercial ownership or release approval |
| Python 3.10 unit/contract suite | 324 passed, one Starlette/httpx deprecation warning | Live connector correctness, tenant isolation, customer detection effectiveness |
| `doctor` using the source tree | Passed; trained synthetic bundle and trained path decoder loaded | Statistical gates passing or production suitability |
| Console TypeScript check | `tsc --noEmit` passed | Fresh browser acceptance or deployment security |
| Existing release verifier | Exit 0; synthetic bundle consistent; CTU bundle skipped | Performance qualification; it does not enforce statistical gate status |
| CTU-13 local files | Three binetflow files and scenario-6 botnet-only PCAP present | A trained or evaluated real-flow serving profile |
| CTU model profile | `artifacts/ctu13/profile/manifest.json` absent | Real-world effectiveness cannot be inferred from parser support |
| Local environment | Doctor reported approximately 5.3 GiB free on the repository volume | Enough capacity for production telemetry or further large data work |

The plain CLI invocation initially failed because the project is not importable without a source-path setup in this shell. Re-running with `src` inserted into `sys.path` succeeded. This is a packaging/onboarding issue, not a failed model load. No dependencies were installed, datasets downloaded, models retrained, or application source files changed for this assessment.

Build specification SHA-256: `39C24B1578FDD24F071D7E9B781E6C6406A594820B50FC047B7CFDC52ECA43D5`. This plan does not replace the existing research specification or accepted ADRs.

### 2.3 Saved Synthetic Evaluation

These are values in the currently hash-verified saved [evaluation report](../../artifacts/profile/evaluation_report.json), not a new training run or a customer benchmark:

| Measure | Reported result | Interpretation |
|---|---:|---|
| Event recall | 11.90% | 5 matched events and 37 missed; below the existing 50% gate |
| Alert precision | 50.00% | 5 matched and 5 unmatched alerts; small sample |
| False alerts / 100 observed asset-hours | 1.465 | Above the existing maximum of 1.0 |
| Observed asset-hours | 341.25 | Too limited to extrapolate an enterprise false-alert burden |
| Median warning lead | 90 seconds | Among matched synthetic events; cutoff-based evaluator, not proven delivery lead |
| Primary average precision | 0.323 | Ranking diagnostic, not customer recall at a usable alert budget |
| ECE at 300 seconds | 0.00407 | Passes the saved gate but is dominated by low-risk cases |
| Brier at 300 seconds | 0.001803 | Better than the saved empirical-hazard floor of 0.002094 |
| Recall bootstrap units | 11 | Reported interval approximately 3.03%-21.21%; synthetic episodes, not independent customer organizations |
| Primary utility | -45 | Negative under the implemented utility function |

20,173 of 20,223 reliability samples lie in the lowest probability bucket. A small global ECE is therefore not enough to demonstrate useful calibration of high-risk alerts. Calibration must be inspected by task, support regime, selection policy, and risk range.

At the configured gate of one false alert per 100 asset-hours, even 500 fully observed assets would permit 120 false alerts per day before incident aggregation. This is arithmetic illustrating the scale problem, not a projection of the current model. A commercial product needs an analyst-facing nuisance-case budget as well as asset-hour metrics.

The current evidence does not justify claims of reliable breach prediction, ransomware prevention, enterprise accuracy, or superiority over another vendor.

## 3. Concrete Blockers Found in the Code

This is a repository assessment and critical-path review, not a complete penetration test or line-by-line formal audit. The following findings are sufficient to block exposing the current demo as a customer SaaS.

| ID | Evidence | Commercial consequence | Required change |
|---|---|---|---|
| R01 | [server.py](../../src/foresight/api/server.py): session routes have no authenticated actor or authorization dependency; global dictionaries at line 57 | Current API is intentionally a local demo, not an internet-facing customer boundary | New authenticated production API; authorization matrix; tenant ownership checks on every resource |
| R02 | [store.py](../../src/foresight/storage/store.py): several keys exclude tenant; publication queries at lines 186-209 omit tenant; record writes accept caller tenant values | Tenant fields and a filtered read test do not constitute end-to-end isolation | Trusted tenant context, composite constraints, scoped object access, transaction boundaries, negative isolation tests |
| R03 | [server.py](../../src/foresight/api/server.py): `create_session` at line 320 always selects `get_bundle()`; `get_ctu_bundle()` is defined but not selected there | Once CTU artifacts exist, real-capture sessions can still use the wrong profile | Select a qualified bundle by source/capability; reject mismatches; test model/scaler/calibrator provenance |
| R04 | [matching.py](../../src/foresight/evaluation/matching.py): line 86 sets emission to decision cutoff; [service.py](../../src/foresight/api/service.py): lines 343-349 record receipt but report inference-only duration as compute-to-ledger | Saved lead and latency names do not establish actual end-to-end advance warning | Separate source time, watermark, compute, commit, publish, and destination receipt; score actual delivery in live evaluation |
| R05 | [matching.py](../../src/foresight/evaluation/matching.py): `Alert`/`ObservedEvent` carry no follow-up coverage; no-later-event branch counts false alerts; [report.py](../../src/foresight/evaluation/report.py): AP includes any positive risk-mask support | Censored data cannot be interpreted safely as fully observed negatives | Explicit follow-up intervals and censoring; unknown outcomes; independent oracle fixtures; requalify metrics |
| R06 | [cli/__init__.py](../../src/foresight/cli/__init__.py): `cmd_release_verify`, lines 318-366, checks artifacts/report presence and consistency, not statistical gate status | A successful release command can accompany failed recall and false-alert gates, as it does now | Separate integrity verification from deployment qualification and claims approval |
| R07 | [server.py](../../src/foresight/api/server.py): global sessions/actions, quotas of 32/256, synchronous expensive routes | Restart loses operational state; multiple workers disagree; no production admission/fairness or recovery | Durable jobs, persisted investigations, bounded workers, quotas, idempotency, graceful restart |
| R08 | [server.py](../../src/foresight/api/server.py): line 711 signs missing approval on the server; `_audit_event` at line 584 swallows audit failures | Demo authorization and best-effort audit are not production control authority | Separate response service; actor-bound approvals; durable fail-closed control audit; remote reconciliation |
| R09 | [bundle.py](../../src/foresight/api/bundle.py): missing required files permit disclosed untrained fallback; hash map may be absent | Demo convenience must not permit customer forecasts from incomplete/unapproved artifacts | Production fail-closed loading, complete signed manifests, approved model registry, rollback and expiry policies |
| R10 | [core.yaml](../../configs/core.yaml): 128-node graph cap; [pcap_worker.py](../../src/foresight/ingest/pcap_worker.py): narrow classic-PCAP/IPv4 parser | Enterprise scope, IPv6, encrypted protocols, cross-partition movement, and live data are not qualified | Production sensor integrations, bounded partitions with explicit boundary coverage, qualified feature profiles |
| R11 | [pyproject.toml](../../pyproject.toml): license `TBD`; broad Python version ranges; serving packages in dev extras; no tracked CI/deployment workflow found | Rebuilds, procurement, commercial rights, and updates are not ready | Legal ownership review, production extras/lock, SBOM, signed releases, CI, deployment and upgrade tests |

The existing [Build Specification](../../FORESIGHT_Build_Spec.md) already requires many of these controls in Appendices L-Q. Written requirements should not be confused with implemented and qualified behavior.

## 4. Competitive Landscape

Sources below are official product descriptions inspected on the assessment date. They describe vendor-advertised capabilities, not independently verified performance or a complete feature/pricing audit. Contract scope, editions, deployment, and integration availability must be verified during competitive evaluations.

| Competitor/category | Established offering relevant to us | Implication for FORESIGHT |
|---|---|---|
| Vectra AI / NDR | Behavioral threat detection and prioritization across network, identity, and cloud; investigation and response integrations. [Platform](https://www.vectra.ai/platform) | Network-plus-identity correlation and AI prioritization are not unique claims |
| Darktrace / hybrid network | Environment-specific behavioral modeling, cross-domain investigations, configurable autonomous response. [Network](https://www.darktrace.com/products/network) | Baseline learning, anomaly AI, and automated containment are competitive table stakes |
| ExtraHop / RevealX | Network detection, protocol visibility, investigation, and secure decryption capabilities. [Platform](https://www.extrahop.com/platform), [Decryption](https://www.extrahop.com/resources/security/secure-decryption) | Packet depth and encrypted-traffic investigation require mature engineering; do not promise equivalent visibility |
| Corelight / Open NDR | Zeek/Suricata-based evidence, signatures, behavioral/AI detections, open data and SOC integrations. [Open NDR](https://corelight.com/solutions/why-open-ndr) | Evidence-first positioning and open telemetry are not unique by themselves |
| Microsoft Defender XDR + Sentinel | Cross-domain detections, SIEM, SOAR, investigation, and automated remediation in an integrated security workflow. [Architecture](https://learn.microsoft.com/en-us/security/operations/siem-xdr-overview) | Integrate into Microsoft customers' existing workflow rather than demand replacement |
| CrowdStrike Falcon / Next-Gen SIEM | Cross-domain data, AI detection and triage, incident management, and governed automation. [SIEM](https://www.crowdstrike.com/en-us/platform/next-gen-siem/), [Cases](https://www.crowdstrike.com/en-us/platform/next-gen-siem/incident-management/) | A chatbot or AI case summary is not a defensible USP |
| Wiz / cloud security graph | Relationships among cloud assets, identities, exposures, and attack paths with impact/ownership context. [Security Graph](https://www.wiz.io/lp/wiz-security-graph) | A graph visualization or blast-radius map alone is not differentiation |
| Pentera / exposure validation | Authorized adversarial validation, attack-path prioritization, remediation and retesting. [Platform](https://pentera.io/pentera-platform/) | Do not label our passive prediction or synthetic intervention as verified exploitability |
| Wazuh / open-source SIEM-XDR | Endpoint/cloud monitoring, vulnerability/configuration assessment, response and hosted options. [Overview](https://wazuh.com/platform/overview/) | A generic low-cost security dashboard faces a strong free/open-source alternative |
| Security Onion / network security monitoring | Integrated network monitoring and investigation stack. [Documentation](https://docs.securityonion.net/en/2.4/introduction.html) | Buyers can assemble mature detection tools; we must deliver maintained outcomes, not merely integrate logos |

### Competitive Conclusion

We cannot honestly claim competitors lack forecasting, explanations, privacy controls, paths, or evidence. This research does not prove a vacant category. The promising differentiation is a tightly delivered combination with measurable outcomes for an underserved buyer, not a checklist of features competitors supposedly do not have.

For each serious deal, create a buyer-specific comparison with their actual incumbent: source coverage, time to onboard, analyst minutes per case, nuisance cases, delivery latency, support effort, total deployment cost, and contract constraints. Run a consented side-by-side pilot. Never compare our synthetic metrics to a vendor's marketing figures.

## 5. Initial Customer and Buying Problem

These are hypotheses to test, not findings from customer interviews.

### Recommended First Segment

Indian mid-market organizations with approximately 100-500 monitored assets, one or a few network sites, an existing firewall/EDR, AD or Entra identity, and a small security or IT team able to investigate alerts. Candidate design partners: B2B technology/services companies and IT environments in non-safety-critical businesses.

Economic buyer: head of IT/security, security manager, or CISO. Daily user: analyst or IT security engineer. Required stakeholder: administrator who can approve sensor placement and read-only log access.

The pain to validate is not "we need AI." It is:

- Network and identity context are spread across tools.
- Suspicious events take too long to investigate and produce too many nuisance cases.
- Unmanaged assets and east-west traffic have visibility gaps.
- Buyers cannot readily verify why an alert fired or whether a new tool added value.
- Small teams cannot maintain a custom telemetry and correlation stack indefinitely.

MSSPs are an attractive subsequent channel: multi-customer views, repeated deployments, and domain expertise can improve distribution. However, first find a willing MSSP and verify its workflow; do not build delegated tenancy, white labeling, and reseller billing before a real partner commits.

Avoid first launches into large banks, critical OT, hospitals' clinical systems, or customers expecting fully managed 24/7 incident response. They add procurement, liability, safety, and support requirements that this team has not yet demonstrated. A campus or hackathon lab can validate engineering but is not proof of a commercial buyer.

### Discovery Sprint

Conduct 12-15 conversations with qualified buyers and operators before committing the full platform scope. Ask for recent investigation examples, current stack, available telemetry, tolerated workload, existing spend, procurement gates, ownership of remediation, and measurable purchase criteria. Obtain written permission and data-processing terms before accessing telemetry.

Exit condition: three design partners with an administrator sponsor, useful sources, an agreed evaluation protocol, and at least two buyers willing to discuss a paid continuation if outcomes are met. Letters of interest alone do not validate revenue.

If customer evidence instead points to cloud-only teams or MSSPs, change the initial connector and workflow plan rather than force an on-prem sensor product onto them.

## 6. Proposed Differentiators and How to Earn Them

### D1. Verifiable Forecast Receipts

For every published warning, preserve the lawful input prefix, source availability, artifact/policy versions, horizon, delivery time, support status, and later adjudication. Make customer-scoped verification/export usable without our dashboard. Show misses and unresolved outcomes as well as successes.

Buyer value: an analyst and security leader can inspect what the product knew and when, rather than trust a retrospective narrative. Existing hashes are a starting point, not proof against an administrator who can replace both data and hashes. Add signed manifests, protected signing keys, append-only audit roots, and independently verifiable receipts.

Proof required: independently timed prospective tests; no warning credit after event onset; tampering tests; export verification; consistent evidence after restart and upgrade.

### D2. Coverage-Aware Investigations

Show source health, delay, capture asymmetry, missing protocol visibility, identity ambiguity, and model support beside each case. Missing data must not become "low risk." Recommend the next evidence source that would resolve an uncertainty, then query it with permission.

Buyer value: fewer misleading conclusions and faster targeted investigation. Coverage reporting itself is not unique; its value must be demonstrated through better investigations.

Proof required: sensor loss and sparse-modality drills; controlled evidence requests; reduced time to correct conclusion versus existing workflow.

### D3. Low-Noise Threat Progression

Correlate signals into a versioned case showing observed steps, suspected next steps, affected business assets, and a concise investigation action. Retain independent sources and their dependencies; duplicate telemetry cannot inflate confidence. Manage an explicit nuisance-case budget per customer.

Buyer value: a manageable queue, not another stream of anomaly scores. Correlation scores are not automatically calibrated attack probabilities.

Proof required: case-level precision and workload improvement at comparable threat coverage, measured against the customer's incumbent. Do not obtain quietness simply by suppressing all uncertain findings.

### D4. Measured Value, Not an Accuracy Badge

Provide a tenant-specific scorecard: observation coverage, known misses, advance warnings, nuisance cases, unresolved outcomes, investigation time, and incremental discoveries. Separate lab, replay, shadow-production, and live-production evidence.

Buyer value: easier renewal and procurement because value is measured honestly. Rare-event environments may not supply enough attacks for a recall claim; report unavailable evidence rather than manufacture accuracy.

### D5. Data-Minimizing Hybrid Deployment

Use customer-side metadata collection and optional local evidence retention, with a region-pinned SaaS workflow. Raw packet payload is off by default; support access is explicit and time limited. Offer predictable asset/site pricing with metered capacity bands.

Buyer value: practical adoption with privacy and budget controls. Neither residency nor low price is unique by itself. Full private-VPC and air-gapped deployment are later supported products, not promises inherited from an offline demo.

### What Builds a Defensible Advantage

The durable advantage would be consented multi-environment outcome data, well-maintained source adapters and detection content, a rigorous evaluation harness, embedded analyst workflow, and repeatable deployment/support economics. A new neural architecture or larger feature count alone is not a moat.

## 7. Feature Portfolio

Priority definitions: **Pilot** is required before the relevant real-telemetry pilot; **V1** is required for the first supported general commercial release; **V2** follows validated adoption; **Research** stays experimental until separately qualified. This is a portfolio, not an instruction to implement all 70 capabilities before talking to customers.

### Sources and Visibility

| ID | Capability | Priority | Practical value / boundary |
|---|---|---|---|
| F01 | Zeek connection, DNS and TLS metadata ingestion | Pilot | Real network context with versioned source capabilities |
| F02 | Suricata EVE alerts and flow correlation | Pilot | Known-threat evidence independent of the world model |
| F03 | Sensor enrollment, heartbeat and ingestion lag | Pilot | Detect blind spots rather than silently showing a quiet network |
| F04 | Source schema, quality and loss accounting | Pilot | Accepted/rejected/duplicate/dropped records are visible |
| F05 | Asset inventory with DHCP/DNS/CMDB bindings | Pilot | Link evidence to assets without equating IP with device |
| F06 | Real AD authentication telemetry | Pilot | Qualify credential-abuse and lateral-investigation cases |
| F07 | One design-partner firewall or flow connector | V1 | Support actual customer infrastructure, not every vendor at once |
| F08 | AWS VPC Flow Logs plus CloudTrail context | V2 | Cloud visibility with delay-aware semantics |
| F09 | IPv6, NAT, proxy and asymmetric-visibility handling | V1 | Explicitly reject unsupported regimes until qualified |
| F10 | Payload-off collection and local evidence controls | Pilot | Minimize secrets and personal data entering SaaS |

### Detection and Progression

| ID | Capability | Priority | Practical value / boundary |
|---|---|---|---|
| F11 | Maintained signature/rule detections | Pilot | Useful security findings before predictive ML succeeds |
| F12 | Periodic outbound/C2 behavior detector | Pilot | Suspected beaconing with measured benign controls |
| F13 | Multi-source lateral activity correlation | Pilot | Combine auth and network evidence; do not infer compromise from ports alone |
| F14 | Password-spray and suspicious success correlation | Pilot | Real authentication outcomes, service-account exceptions |
| F15 | Unusual outbound transfer investigations | V1 | Flag activity; verify exfiltration only with adequate evidence |
| F16 | Low-and-slow reconnaissance detector | V1 | Windowed behavioral context tested against authorized scans |
| F17 | Threat-intelligence enrichment with expiry | V1 | Context and provenance, not proof that an entity is malicious |
| F18 | Role/peer-group behavior baselines | V2 | Reduce backup, patching and administrator noise |
| F19 | Business-asset criticality prioritization | V1 | Promote impact without inventing monetary-loss probabilities |
| F20 | Qualified attack-progression forecasts | Research | Task/horizon-specific probabilities only after prospective gates |

### Investigation Experience

| ID | Capability | Priority | Practical value / boundary |
|---|---|---|---|
| F21 | Incident workbench replacing demo-first navigation | Pilot | Queue -> case -> evidence -> disposition -> follow-up |
| F22 | Entity timeline across network and identity | Pilot | Source-linked observed chronology and clock uncertainty |
| F23 | Distinct observed, predicted and hypothesized graph layers | V1 | No visual laundering of guesses into observations |
| F24 | Filterable evidence search and saved queries | V1 | Bounded, authorized investigation without exporting everything |
| F25 | Evidence verification/export package | V1 | Reproducible incident handoff with deletion/redaction policy |
| F26 | Scoped contextual identity/EDR evidence request | V2 | Resolve uncertainty through a real permissioned connector |
| F27 | Similar-case search and investigation templates | V2 | Reuse analyst knowledge without cross-tenant leakage |
| F28 | Capability and uncertainty panel per case | Pilot | Show data gaps, staleness, support and confidence reasons |
| F29 | Asset ownership and critical-service context | V1 | Route investigation to the person who can resolve it |
| F30 | Grounded AI investigation summaries | V2 | Citations and abstention; no unsupervised control authority |

### Daily Workflow

| ID | Capability | Priority | Practical value / boundary |
|---|---|---|---|
| F31 | Case ownership, status, comments and history | Pilot | A durable workflow instead of ephemeral sessions |
| F32 | Signal deduplication and evidence dependency tracking | Pilot | Replayed alerts cannot become independent corroboration |
| F33 | Scoped suppressions with owner, reason and expiry | V1 | Control nuisance cases without permanent blind spots |
| F34 | Maintenance windows and approved scanner context | V1 | Explain benign change without deleting evidence |
| F35 | Authenticated webhook plus email notification | Pilot | Deliver cases into the customer's actual work queue |
| F36 | Jira or ServiceNow connector, selected by buyer | V1 | Ownership and bidirectional status reconciliation |
| F37 | SIEM export with stable schema and delivery health | V1 | Complement Sentinel/Splunk/other existing systems |
| F38 | Escalation policies and acknowledgment tracking | V1 | Distinguish delivery, reading, investigation and resolution |
| F39 | Analyst adjudication and outcome taxonomy | Pilot | Confirmed/benign/unknown/insufficient evidence, with provenance |
| F40 | MSSP delegated workspace and cross-customer queue | V2 | Explicit delegation with per-customer policy boundaries |

### Safe Response and Risk Reduction

| ID | Capability | Priority | Practical value / boundary |
|---|---|---|---|
| F41 | Evidence-backed recommended investigation actions | Pilot | Read-only suggestions with requirements and uncertainty |
| F42 | Exportable manual containment playbooks | V1 | Support customer-controlled response without executing it |
| F43 | Approval policies and separation of duties | V2 | Required before any real automated control effect |
| F44 | Response preview, target validation and blast-radius limits | V2 | Evaluate scope and operational harm before execution |
| F45 | One EDR or firewall response adapter | V2 | One fully tested connector rather than ten shallow ones |
| F46 | TTL, rollback, kill switch and protected-asset policies | V2 | Safety mechanisms remain effective during cloud/network failure |
| F47 | Remote outcome reconciliation and readback | V2 | Distinguish accepted, effected, failed and outcome unknown |
| F48 | Post-action coverage/service-health checks | V2 | Containment cannot simply destroy visibility or business service |
| F49 | Remediation ownership and revalidation workflow | V2 | Track whether a customer-approved fix resolved the observed issue |
| F50 | Counterfactual intervention simulation | Research | Synthetic scenario estimates, not production causal-effect claims |

### SaaS, Privacy and Trust

| ID | Capability | Priority | Practical value / boundary |
|---|---|---|---|
| F51 | Organization membership, OIDC SSO and MFA | Pilot | Real actor identity; no shared demo approval key |
| F52 | Role and resource authorization | Pilot | Admin, analyst, read-only, billing and explicit support roles |
| F53 | Isolated tenant data, caches, jobs and object access | Pilot | Dedicated pilot boundary first; proven shared tenancy later |
| F54 | Regional retention and verified deletion | Pilot | Address production, exports, indexes and backup lifecycle |
| F55 | Encryption, KMS/secret rotation and sensor certificates | Pilot | Protect telemetry and control credentials |
| F56 | Durable security audit and support-access approvals | Pilot | Trace sensitive reads, changes and investigations |
| F57 | SAML/SCIM and enterprise identity lifecycle | V2 | Build when a committed buyer requires these protocols |
| F58 | Private VPC / customer-hosted data plane | V2 | Separate qualification, upgrade and support package |
| F59 | Trust documentation and security questionnaire pack | V1 | Sell through procurement with evidence rather than badges |
| F60 | Open API, scoped keys and portable data export | V1 | Integrate and exit without unsafe broad credentials |

### Quality, Operations and Commercial Management

| ID | Capability | Priority | Practical value / boundary |
|---|---|---|---|
| F61 | Customer-specific value/coverage scorecard | V1 | Demonstrate investigations and outcomes, including unavailable metrics |
| F62 | Prospective receipt-based evaluation | Pilot | No credit for warnings that arrived after the event |
| F63 | Approved model registry and release rollback | Pilot | A valid hash is not automatic deployment approval |
| F64 | Drift, calibration and support-regime monitoring | V1 | Degrade safely; do not silently retrain on suspect traffic |
| F65 | Per-tenant resource budgets and ingestion cost views | V1 | Bound noisy neighbors, bills and expensive explanation jobs |
| F66 | Backup/restore, recovery and update verification | Pilot | Continued evidence and workflow after failure |
| F67 | Billing, entitlements, invoices and measured usage | V1 | Paid onboarding without ambiguous asset counts |
| F68 | Guided setup and connectivity/coverage validation | Pilot | Time to first useful case without founder-only deployment |
| F69 | Support bundle, runbooks and status/incident process | V1 | Maintain the product without unrestricted access to customer evidence |
| F70 | Controlled customer feedback/model promotion | V2 | Quarantine labels; consented training; challenger evaluation and approval |

### Initial Commercial Scope

The first sellable edition includes real network plus AD evidence, a small qualified detection pack, durable cases, source-linked investigations, visibility health, ticket/SIEM integration, secure onboarding, retention, subscription administration, support, and a measured value report. Forecasts remain absent or clearly experimental unless their particular task/profile passes its gate.

Do not make general availability depend on every V2 item. Conversely, do not remove foundational security, privacy, recovery, or support to meet an arbitrary launch date.

## 8. End-to-End Product Architecture

### 8.1 Deployment Model

Start with a Linux customer-side collector or existing Zeek/Suricata deployment feeding metadata to an India-region SaaS. Use a dedicated data boundary for each early pilot. Keep shared enterprise multi-tenancy as a separately tested evolution. Customer IT still needs to authorize SPAN/TAP placement or log exports; "agentless" does not mean zero infrastructure access or universal visibility.

```text
CUSTOMER ENVIRONMENT
  Existing Zeek / Suricata / firewall / AD event forwarding
       -> packaged collector: enrollment, filtering, redaction, bounded spool
       -> outbound authenticated connection, no inbound remote shell
       -> optional customer-retained raw evidence with approved retrieval

SAAS TRUST BOUNDARY
  authenticated ingestion -> durable batch manifest + transactional outbox
       -> bounded queue -> normalize / deduplicate / identity / feature workers
       -> rule detections and correlation -> durable cases and evidence index
       -> qualified ML worker -> sealed forecasts / abstention
       -> case API -> analyst console -> notifications / SIEM / ticketing

SEPARATE AUTHORITIES
  control plane: organizations, users, sensors, policies, entitlements
  evaluator: outcome labels, holdouts, receipts, experiments
  response service (later): policy + actor approval + connector + readback
  training pipeline: consented datasets -> challenger -> review -> registry
```

### 8.2 Technology Choices

- Retain Python/FastAPI and the existing model modules; retain React/TypeScript and existing console components where they fit the production workflow.
- Implement a modular production service plus separate ingestion/inference workers. Do not begin with a large microservice fleet or require Kubernetes for the first pilot.
- Use PostgreSQL for organizations, assets, policies, cases, jobs, receipts, and billing references; migrations and tenant-composite constraints are mandatory. SQLite remains suitable for local replay/edge state, not the shared cloud authority.
- Use S3-compatible encrypted object storage for immutable metadata batches, evidence and signed model artifacts; keep retention and tenancy enforcement outside merely guessing object IDs.
- Use one durable managed queue and transactional outbox rather than several brokers. Pilot hosting provider and budget determine the concrete service; a managed AWS deployment in Mumbai is a reasonable default hypothesis, not an already authorized deployment.
- Start bounded indexed investigation queries in PostgreSQL plus object-backed partitions. Introduce ClickHouse/OpenSearch only after measured query/storage requirements justify the operational cost.
- Prefer maintained sensor/shipping components over building a new packet engine. A custom collector should only implement enrollment, source policies, capability reports, receipt clocks, buffering and packaging that existing components cannot provide safely.
- Use infrastructure as code, separate dev/staging/prod, immutable releases, managed secrets and database backups. Lock tested versions during implementation; documentation's `latest` pages are not dependency pins.

Zeek produces structured network observations; Suricata EVE emits alerts and protocol metadata and supports flow-correlation identifiers. Reuse their established sensor logic rather than hand-roll a production IDS. [Zeek](https://docs.zeek.org/en/current/about/what.html), [Suricata EVE](https://docs.suricata.io/en/latest/output/eve/eve-json-output.html)

Map supported exports to [OCSF](https://ocsf.io/) where practical, while preserving the richer internal timing and provenance contracts. Do not rewrite all internal objects merely to claim standards compliance.

### 8.3 Contracts to Add

Each accepted batch needs server-derived tenant, sensor/certificate identity, schema/parser version, source ID, sequence range, content digest, observation interval, availability and ingestion receipts, and loss/clock-quality information. Customer-supplied `tenant_id` is never authoritative.

Each asset binding needs observation domain, stable identifier when available, address interval, binding provenance, confidence, and ambiguity state. Unknown identity remains unknown; reused private IPs across customers/sites never share state.

Each case needs version, immutable evidence refs, source dependencies, observed facts, rule/model outputs, qualified prediction status, severity rationale, impacted services, owner, investigation status, delivery records, and adjudication history. Case revisions append evidence; they do not retroactively change what a warning contained.

Each forecast needs legal-prefix commitment, model/scaler/calibrator/policy hashes, task/profile support, actual publication/transport times, horizon semantics and later evaluation linkage. Future labels belong to a separate evaluator authority, never to serving credentials or forecast input objects.

### 8.4 Tenant Isolation

Apply trusted authorization at the API and worker boundaries, composite `(tenant_id, resource_id)` constraints, tenant-qualified cache/job keys, scoped object grants and quotas. Use PostgreSQL RLS as defense in depth, not the only control. Database owners and privileged roles can bypass ordinary RLS; tests must exercise the real runtime role, background jobs and support tooling. [PostgreSQL RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

Dedicated early pilots reduce blast radius but still require authenticated actors, organization ownership, tenant-bound jobs and support permissions. Dedicated deployments do not excuse missing authorization.

### 8.5 Streaming and Recovery

Start by recomputing the existing bounded history over finalized windows. Persistent learned state changes model semantics and must have separate burn-in/training/evaluation evidence.

Implement source-sequence deduplication, explicit watermarks, bounded lateness, completeness reports, restart-safe offsets, and dead-letter quarantine. Late data can create a versioned revision but must not alter the original delivered forecast or its measured lead. Use at-least-once delivery with idempotent local effects, not an unsupported universal exactly-once claim.

Partition graphs deterministically by tenant/site/scope. Record boundary traffic and unavailable cross-partition forecasts. A fleet total of 500 assets is not a 500-node-qualified model. Qualify movement across the 128-node boundary separately; do not arbitrarily increase the cap and keep the old calibration claim.

### 8.6 Privacy and Secure Operations

Raw payload, credentials, HTTP authorization headers and unnecessary personal identifiers must be filtered before SaaS transmission. Pseudonymization is not anonymization; retained IP/user identifiers can still be sensitive. Scope local evidence retrieval, signed URLs, exports, support sessions, and training consent independently.

`python -I` is import isolation, not an operating-system security sandbox. Parser workers handling uploads need non-root execution, read-only filesystem where possible, network denial, CPU/memory/time quotas, bounded decompression, fuzzing and minimal dependencies.

Security development should follow a documented verification baseline such as [OWASP ASVS](https://owasp.org/projects/asvs) and secure release practices such as [NIST SSDF](https://csrc.nist.gov/pubs/sp/800/218/final). Use independent security testing before general availability; do not present a checklist or scan as a certification.

## 9. Detection and Forecasting Qualification

### 9.1 Separate Four Claims

1. **Observed detection:** evidence supports activity that has already occurred.
2. **Progression hypothesis:** a ranked possibility derived from context; not a probability unless calibrated.
3. **Forecast:** a particular observable event within a qualified future horizon under stated support conditions.
4. **Intervention effect:** outcome caused by a control change; requires an appropriate causal experiment, not deletion attribution.

Network traffic cannot establish every initial-access event, identity action, encrypted payload, or exfiltration outcome. Some attacks have no observable precursor at the available sensors. No model can forecast information absent from its input. Keep supported target/horizon/modality manifests and abstain explicitly.

### 9.2 Real-Data Program

- Reverify the existing CTU files against the registry; qualify the profile independently. CTU-13 is a 2011 controlled botnet dataset; it is useful regression/transfer evidence, not a modern enterprise acceptance test. Public PCAPs are botnet-only, while mixed flow labels include Normal and Background. [Publisher](https://www.stratosphereips.org/datasets-ctu13)
- Obtain consented benign operational telemetry covering backups, patching, VPNs, service accounts, admin work, scanners, DNS changes and seasonal variation.
- Run written-scope benign attack emulations in an isolated range or approved customer test environment. Record independent onset, successful/failed actions, sensors and collection clocks; never run unauthorized attacks against production.
- Freeze separate training, development, calibration and final holdout partitions by environment/campaign and time. Include leave-one-organization-out and unseen-family tests. Windows from one scenario are not independent incidents.
- Train modality-specific profiles. Zeek-only, packet-plus-metadata, flow-only and identity-augmented models have different input support. Extending the 88/22/48 feature contract requires versioned artifacts and fresh qualification.
- Keep production tenant data out of shared training unless contracts and explicit consent permit it. Review labels and feedback before they reach the training pipeline.

AWS flow logs have documented visibility limitations and aggregation behavior. They are not a drop-in low-latency packet sensor. Account for publication lag before offering short-horizon forecasts. [AWS limitations](https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs-limitations.html)

### 9.3 Baselines and Experiments

Compare on the same lawful information and the same alert budget: maintained signatures/rules, simple time-series or peer anomalies, logistic/gradient-boosted event risk, empirical hazards, and a temporal model without imagined rollout. Compare to the customer's incumbent when access and evaluation terms permit.

Run ablations for graph structure, entity memory, learned transition, identity context, observables loss, calibration, ensemble size and alert/case policy. Prefer the simpler model if the world model does not add usable recall, warning lead or workflow value at acceptable cost.

Research tasks should diagnose failure, not just increase epochs: inspect event/negative sampling, target alignment, source support, loss scaling, natural-prevalence calibration, per-task threshold stability, censored denominators, and held-out-family behavior. Saved low recall is a reason for controlled experiments, not proof that adding a larger model fixes the product.

### 9.4 Pilot Evaluation Protocol

Proposed protocol: 4-6 weeks with at least three design partners and 30 days of continuous shadow operation per partner where feasible. These are learning targets, not a sample-size guarantee. Real attacks may be absent, so evaluate controlled scenarios separately from natural operational traffic.

Measure event/case precision and recall, false cases per analyst-day, asset-hour exposure, abstention/support coverage, time to investigate, delivery lead, sensor lag, service impact, CPU/memory and infrastructure/support cost. Maintain unknown outcomes and confidence intervals clustered by genuinely independent environment/campaign units.

Initial candidate pilot thresholds, to freeze with design partners before testing:

- A useful-case precision target of at least 80%, and no more than two nuisance cases per site/day for the agreed scope; preserve a recall/coverage guard to prevent silence-by-suppression.
- At least 30% lower median investigation time on a paired, randomized-order case exercise against the customer's current workflow; disclose case count and learning effects.
- At least 70% recall on the explicitly scoped controlled progression scenarios, with every missed scenario disclosed. This does not establish natural production attack recall.
- For an advertised forecast task: better recall or operational utility than the strongest comparable baseline at the fixed nuisance budget, a preregistered confidence criterion, and useful actual delivery lead. Freeze the minimum lead per source/use case; a provisional packet/identity target is 60 seconds, not a blanket promise.
- No unsupported probabilities; no data-gap-as-low-risk behavior; source loss and clock manipulation cause safe degradation.

If there are too few independently observed events, the forecasting gate is inconclusive. Do not promote it merely because other pilot outcomes pass. Sell the qualified investigation/detection capabilities only if buyers value them independently.

## 10. Delivery Phases and Dependencies

Calendar estimates are planning ranges for a small experienced team working with coding-agent assistance. They are not guarantees, and customer data access, evaluation support and security remediation can extend them. A single founder should plan longer; agent speed does not replace partner response time or evidence collection.

| Phase | Indicative duration | Deliverable | Exit gate |
|---|---|---|---|
| A: Buyer and baseline | 2-3 weeks | Discovery, claims inventory, reproducible baseline, source/ownership review | Credible partners and agreed scope; no performance overclaims |
| B: Measurement and secure foundation | 3-5 weeks | Correct evaluator, qualified release states, actor/tenant architecture, secure packaging | Measurement oracle and security boundary tests pass |
| C: Read-only live pilot product | 5-8 weeks | Real connectors, durable cases, rule/correlation pack, visibility health, notifications | End-to-end onboarding/recovery/evidence tests and approved security review |
| D: Customer evidence and model decisions | 4-8 weeks | Shadow pilots, independent scenarios, cost/value reports, model ablations | Each shipped capability has adequate evidence and buyers accept its value |
| E: Paid V1 | 4-6 weeks | Repeatable deployment, invoices/entitlements, support, procurement pack, supported integrations | Commercial, operational and independent security gates pass |
| F: Expansion | Ongoing | More qualified profiles, forecasting, response, MSSP workflows | Feature-specific adoption and qualification gates |

Some workstreams overlap, but the dependency chain is real: measurement precedes claims; authorization precedes customer data; connectors precede customer validation; qualified pilots precede general availability; safe response follows durable authority and recovery.

A reasonable planning envelope is approximately 5-8 months to a supported first commercial edition with a small team and cooperative partners. A limited paid design partnership may start sooner after safe pilot gates. Do not confuse either date with comprehensive enterprise-platform completion.

The companion backlog defines individually executable packages, dependencies, acceptance tests and evidence artifacts. Implementation should proceed package by package, preserving the offline research reference.

## 11. Commercialization and Unit Economics

### 11.1 Pilot Offer

Offer a bounded design partnership, not a security guarantee: agreed assets/sites and sources, read-only shadow monitoring, initial configuration, weekly investigation review, measured outcome report and a clear end date. Customer remains responsible for response unless a separately staffed managed-service agreement says otherwise.

Possible pricing experiment: INR 50,000-150,000 for a 4-6 week supported pilot, credited against the first annual contract. These are proposed willingness-to-pay tests, not market research or competitor quotations. Charge only when the pilot is securely deliverable and its service scope is honest; consider a small number of strategic subsidized partners in exchange for lawful feedback and case-study permission.

### 11.2 Subscription Shape

Test site plus active monitored-asset bands with defined ingestion and retention allowances. Avoid unlimited ingestion or opaque per-GB surprises. Define active asset by stable identity/observation period, exclude duplicates and expired DHCP identities, and disclose how ephemeral cloud workloads are counted.

Possible starting hypothesis for a small supported deployment: INR 40,000-80,000 per month, with onboarding priced separately where needed. Price private deployment, long retention, premium source packs, response and MSSP capabilities separately. Do not promise these ranges without measuring costs and interviewing buyers.

Manual invoicing and explicit entitlements are acceptable for early paid pilots. Secure payment processing and automated billing can follow validated purchasing; never store card data ourselves.

### 11.3 Model the Costs Before Quoting

Include ingestion, parsing, hot/cold storage, DB, inference, explanation jobs, egress, third-party content licenses, monitoring, allocated shared infrastructure and support labor. Include sensor hardware and customer-side maintenance in total cost even if the customer pays directly. Regional availability and hosting prices must be rechecked when choosing a provider.

Illustrative monthly model, not an observed cloud bill:

| Item | Assumed INR |
|---|---:|
| Subscription revenue | 60,000 |
| Allocated cloud/data/inference cost | 8,000 |
| Support and onboarding amortization | 6,000 |
| Content/third-party variable cost | 2,000 |
| Contribution before fixed R&D/sales/admin | 44,000 |
| Illustrative gross contribution | 73.3% |

Target at least 70% mature gross margin after direct support and allocated service costs. If measured cost exceeds roughly 30% of revenue, improve retention, batching/model size and self-service operations, or increase the price; do not hide the loss with unlimited usage. This example is a business hypothesis, not profitability evidence.

At 1,000 normalized events/second, the input is 86.4 million events/day. Storage depends on actual bytes/event, compression, indexing and retention. Packet-rate performance is a different workload. Benchmark real samples before choosing capacity or quoting a bill.

### 11.4 First Sales Motion

Founder-led sales to design partners, followed by one or two credible security-service partners. Demonstrate one authorized real investigation, the evidence supporting it, visibility limits and the measured comparison with the existing workflow. Lead with business pain and workflow outcome, not neural-network architecture.

Procurement pack: supported deployment/sources, security architecture, data flow, DPA, subprocessors, residency/retention, test report, vulnerability disclosure policy, response/support scope, uptime terms, liability/insurance discussion, export/offboarding and commercial ownership. Do not advertise 24/7 MDR without a staffed, costed service.

Renewal metrics: weekly engaged users, source coverage, investigation time, useful incremental cases, nuisance workload, support hours, operating cost, paid conversion and renewal. Three renewing customers with repeatable deployment are more meaningful than a long feature catalog.

## 12. Compliance, Ownership and Trust

Obtain counsel for applicability and contract language. This is an implementation planning section, not legal advice or a claim of compliance.

- Review SIH/team contributions, contributor assignments, third-party code, model weights, datasets, rules and trademark rights. `license = TBD` cannot answer whether the company can commercialize every component.
- Maintain an SBOM and dependency/content license inventory. GPL and other component obligations require actual packaging/use analysis; do not assume every rule feed or dataset permits redistribution or shared training.
- Establish data-fiduciary/processor responsibilities, permissible telemetry processing, training consent, access/deletion requests, subprocessors, incident procedures and data export terms.
- CERT-In directions and FAQs address reportable incidents and ICT log obligations for covered entities, including six-hour reporting and rolling 180-day retention requirements. Map applicable obligations, roles and required log classes with counsel; this does not mean all raw PCAP must always be retained for 180 days. [Directions and FAQs](https://www.cert-in.org.in/Directions70B.jsp)
- MeitY lists the final DPDP Rules 2025, corrigendum and enforcement timeline. Track applicable commencement dates rather than relying on older draft-rule articles or asserting every duty already applies. [Official rules and timeline](https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digit)
- Keep legal retention/security logs separate from configurable investigation data where appropriate. Deletion workflows need exceptions for legitimate holds and a documented backup-expiry process.
- Plan SOC 2 / ISO 27001 evidence and independent audits as demanded by buyers. Certification is an organizational/operational process, not a dashboard feature or a coding task that can be declared complete from tests.
- Product-generated compliance evidence may support a customer's audit, but does not certify its compliance or replace a full SIEM/logging program.

## 13. Release Gates

Maintain three independently evaluated release states: **software integrity**, **operational/security qualification**, and **capability/claim qualification**. A pass in one must not imply a pass in the others.

| Gate | Minimum evidence before the relevant release |
|---|---|
| G0: Commercial rights and data authority | Ownership/license review, permitted data use, approved pilot agreement |
| G1: Measurement integrity | Independent oracle for clocks, censoring, event matching, receipt lead, denominators and baselines |
| G2: Security boundary | Actor/tenant/role tests across API, jobs, objects, exports, caches and support; no unresolved critical/high exploitable issues |
| G3: Real ingestion | Qualified schemas and capabilities, source-loss accounting, rotation/replay tests, onboarding without hidden founder steps |
| G4: Capability value | Prespecified scenario/operational tests; misses/unknowns shown; paid buyer value; qualified forecasts only where evidence supports them |
| G5: Reliability and scale | Restore drill, migration rollback, overload/fairness, sustained soak and verified workload envelope |
| G6: Safe control, if enabled | Separate authority, policy/approval expiry, durable audit, kill switch, remote ambiguity reconciliation and service-impact tests |
| G7: Paid service operation | Support ownership, contracts, entitlements, invoices, incident process and measured unit economics |

Provisional operating targets for a small SaaS edition: 99.5% availability after an observed service period; control-plane recovery-point objective 15 minutes and recovery-time objective four hours; normal streaming window-finalization-to-case p95 under 60 seconds at the explicitly tested load. Freeze contract values only after measured drills. Also report source observation-to-delivery latency, which may be much larger for delayed logs.

Workload qualification should start with declared 100/500-asset deployments and defined normalized-event rates, then test 2x bursts and noisy-tenant isolation. Graph scopes remain within qualified limits. Run a minimum seven-day engineering soak followed by the longer pilot period. Verify sensor buffer overflow, database outage, duplicate queue messages, expired credentials, model mismatch, replayed API calls, deletion, and disconnected/offline behavior.

"Market-worthy" means a buyer can securely deploy, receive useful evidence, operate, recover, upgrade, get support, pay, and leave with its data under an honest contract. It does not mean merely that all screens render.

## 14. What We Should Not Build First

- A replacement EDR agent, full SIEM, general vulnerability scanner, email-security suite or cloud-posture platform.
- Autonomous production firewall actions ported from the synthetic range.
- A chatbot that executes arbitrary security-tool commands.
- A supposed digital twin whose outputs are presented as proven causal effects.
- Broad zero-day/ransomware prediction claims without observability and prospective evidence.
- Federated/continual shared learning before consent, poisoning defenses and promotion controls exist.
- Broad OT support, packet decryption infrastructure, multi-cloud private deployment or air-gapped certification before a committed buyer funds qualification.
- Dozens of superficial connectors, unlimited retention, or a Kubernetes-heavy platform before capacity demands it.

These are possible later businesses or modules, not omissions to disguise. A complete product has a coherent, supported scope, not every cybersecurity category.

## 15. Immediate Build Order

1. Approve the provisional customer/use-case scope and begin discovery/data agreements.
2. Execute B01-B05 in the companion backlog: baseline, measurement oracle, release states, profile selection and secure deployment design.
3. Build B06-B12: identity/authorization, durable tenant data, secure ingestion, real sensors and real identity evidence.
4. Build B13-B18: streaming recovery, scoped detection pack, cases, investigations, notifications and guided onboarding.
5. Run pilot/security/recovery work B19-B23; decide independently whether the ML forecasts earn publication.
6. Complete paid operation and supported V1 work B24-B27; only then pursue response, MSSP and research expansions B28-B32.

I can implement the software packages, tests, local integration harnesses, infrastructure definitions, evidence reports and documentation. The founder/customer must provide business decisions, authorized accounts and telemetry, contracts, hosting expenditure approval and pilot participation. Independent security reviewers, counsel, auditors and staffed service operators remain external responsibilities. No coding agent can manufacture those gates.

Final recommendation: keep FORESIGHT's evidence-accountable forecasting architecture, but make the first purchase about useful, low-noise investigations on real network and identity data. Let qualified predictive capability increase the value of a product customers already trust, rather than make every sale depend on an unproven promise.
