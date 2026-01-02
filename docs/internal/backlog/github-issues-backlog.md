# GitHub Issues Backlog (from Repository Review)

Source: *AI Telephony Service & CRM – Repository Review* (PDF).

## Conventions

- Each `##` section is intended to become **one GitHub Issue**.
- Sub-issues/subtasks are expressed as checklists under **Subtasks**.
- Priorities: **P0** (must ship for prod hardening), **P1** (next), **P2** (later / polish).
- Suggested labels are included for quick triage.

---

## [P0] Rate limiting + abuse prevention for public endpoints (widget + signup + unauth flows)

**Problem**
Public-facing endpoints (e.g., chat widget and any self-signup/onboarding endpoints) are a cost and availability risk without guardrails (spam/DoS/cost amplification).

**Suggested labels**
`security` `reliability` `backend` `abuse-prevention`

**Related (if using the same repo)**
`raven-dev-ops/ai_telephony_service_crm#88`

### Subtasks
- [ ] Inventory all **public/unauthenticated** routes (widget chat endpoints, signup/onboarding routes when `ALLOW_SELF_SIGNUP=true`, any public health or metadata routes).
- [ ] Decide rate-limit strategy:
  - [ ] Per-IP throttles (burst + sustained)
  - [ ] Per-tenant throttles (by `X-Widget-Token` / tenant key / business id)
  - [ ] Optional per-phone number throttles for SMS inbound flows (where applicable)
- [ ] Implement rate limiting middleware (FastAPI), with:
  - [ ] Clear `429` responses and `Retry-After`
  - [ ] Exemptions for internal/admin endpoints (if needed)
  - [ ] Configurable limits via environment variables
- [ ] Add anomaly detection heuristics (minimum viable):
  - [ ] Sudden request spikes per tenant/IP
  - [ ] Repeated invalid auth tokens / signature failures
  - [ ] High error-rate bursts
- [ ] Add **tenant “lockdown mode”**:
  - [ ] Admin/owner action to disable assistant (chat/voice) for a tenant temporarily
  - [ ] Clear UI/API state surfaced to dashboards (owner/admin)
- [ ] Add tests:
  - [ ] Unit tests for limiter behavior
  - [ ] Integration tests ensuring rate limits do **not** break normal chat flows
- [ ] Update docs (README / API reference):
  - [ ] Document default limits and how to tune them
  - [ ] Guidance for production defaults vs dev

### Acceptance criteria
- [ ] Sustained abusive traffic on public endpoints is throttled (returns `429`) without affecting other tenants.
- [ ] Lockdown mode reliably blocks assistant activity for the selected tenant while preserving admin access.
- [ ] Rate-limit decisions are observable via metrics/logs (count limited requests by route + tenant).

---

## [P0] Webhook security hardening (Twilio + Stripe): signature enforcement + replay protection

**Problem**
Webhook endpoints are a high-impact surface: spoofing or replay can mutate data (appointments, billing state) or trigger assistant behaviors.

**Suggested labels**
`security` `backend` `integrations` `payments` `telephony`

**Related (if using the same repo)**
`raven-dev-ops/ai_telephony_service_crm#89`

### Subtasks
- [ ] Enforce signature verification in production for:
  - [ ] Twilio voice webhooks
  - [ ] Twilio SMS webhooks
  - [ ] Stripe webhooks
- [ ] Add replay protection:
  - [ ] Validate timestamps within an acceptable window
  - [ ] Store/deny seen webhook IDs/nonces (idempotency store)
- [ ] Ensure idempotency for webhook handlers (safe re-delivery):
  - [ ] Stripe event idempotency
  - [ ] Twilio request idempotency (where applicable)
- [ ] Add negative tests:
  - [ ] Missing/invalid signatures
  - [ ] Replayed webhooks
  - [ ] Tampered payloads
- [ ] Add security event logging:
  - [ ] Log invalid signature attempts with minimal PII
  - [ ] Emit metrics counters (invalid, replayed, accepted)

### Acceptance criteria
- [ ] Invalid or replayed webhooks cannot mutate state (no appointments created/modified; no billing changes).
- [ ] Test suite includes explicit invalid/replay cases for each provider.
- [ ] Production defaults reject unsigned webhooks; dev/stub modes remain developer-friendly.

---

## [P0] Centralized logging + P0 alerting rules (Ops readiness)

**Problem**
Telephony systems require fast detection of outages/integration failures; single-instance logs are insufficient as usage grows.

**Suggested labels**
`observability` `reliability` `ops`

### Subtasks
- [ ] Define a log schema (JSON) including correlation fields:
  - [ ] request id / trace id
  - [ ] tenant/business id
  - [ ] call SID / message SID (where available)
- [ ] Add/verify request-scoped correlation IDs across FastAPI routes.
- [ ] Choose log aggregation target (cloud logging / SIEM / self-hosted stack).
- [ ] Implement log forwarding configuration in deployment (Docker/Cloud Run/etc.).
- [ ] Define P0 alert conditions and thresholds:
  - [ ] Twilio webhook error rate spikes
  - [ ] Stripe webhook failures
  - [ ] Elevated 5xx rate
  - [ ] Latency SLO breach on voice/chat endpoints
- [ ] Add runbook entries for each P0 alert (triage steps + rollback/mitigation).

### Acceptance criteria
- [ ] Logs are centrally queryable by tenant and by call/message IDs.
- [ ] Alerting fires for a simulated outage/failure and includes actionable context.
- [ ] Runbook has explicit steps for each P0 class incident.

---

## [P0] Backup/restore + disaster recovery drills with RPO/RTO evidence

**Problem**
Production readiness requires validated backups and restore procedures (not just “we think backups exist”).

**Suggested labels**
`ops` `reliability` `data` `compliance`

### Subtasks
- [ ] Document backup scope (DB + any object storage artifacts like recordings/exports if applicable).
- [ ] Implement automated backups (schedule + retention policy).
- [ ] Write a one-command restore procedure (staging first).
- [ ] Run DR drills:
  - [ ] Restore into clean environment
  - [ ] Verify application integrity (auth, tenant isolation, scheduling reads)
- [ ] Record evidence:
  - [ ] Achieved RPO (data freshness)
  - [ ] Achieved RTO (time-to-restore)
- [ ] Add runbook section for DR scenarios and owner/admin communication templates.

### Acceptance criteria
- [ ] Backups are automated and tested via at least one successful restore drill.
- [ ] Evidence artifacts exist (timestamps, commands, validation checklist).

---

## [P0] Enforce multi-tenant isolation defaults (fail-safe configuration)

**Problem**
In multi-tenant mode, tenant isolation must be “secure by default” (e.g., requiring tenant API keys).

**Suggested labels**
`security` `backend` `multi-tenant`

### Subtasks
- [ ] Add guardrails so that when multiple tenants exist and environment is non-dev:
  - [ ] `REQUIRE_BUSINESS_API_KEY` (or equivalent) must be true (or app fails fast).
- [ ] Ensure owner/admin dashboards cannot accidentally access cross-tenant data due to misconfiguration.
- [ ] Add tests that verify cross-tenant access is rejected.

### Acceptance criteria
- [ ] Misconfiguration that would weaken tenant isolation is rejected in non-dev environments.
- [ ] Automated tests cover cross-tenant access denial cases.

---

## [P1] Expand critical-path test coverage to near-100%

**Problem**
Existing test coverage is high, but critical paths should be exceptionally well covered (especially security + billing + emergency routing).

**Suggested labels**
`testing` `quality` `security`

### Subtasks
- [ ] Identify and prioritize critical paths:
  - [ ] Emergency triage/routing flows
  - [ ] Subscription enforcement paths (`ENFORCE_SUBSCRIPTION` and plan guardrails)
  - [ ] Webhook signature verification & replay protection
  - [ ] OAuth state management (Google Calendar, QBO)
  - [ ] Twilio number provisioning flows (if used)
- [ ] Add negative tests for each critical path (bad inputs, missing auth, invalid signatures).
- [ ] Add coverage reporting per critical module (optional: separate coverage thresholds for `/routers/voice.py`, billing, webhook handlers).
- [ ] Ensure tests run in CI using stub providers (no real external calls).

### Acceptance criteria
- [ ] Critical modules have coverage targets >= 95% (or explicit justification if excluded).
- [ ] Each critical flow has at least one negative test.

---

## [P1] Google Calendar two-way sync hardening (webhooks + time zones + idempotency)

**Problem**
Scheduling correctness depends on reliable calendar sync, especially when changes occur outside the assistant (owner edits calendar directly).

**Suggested labels**
`integrations` `calendar` `backend`

### Subtasks
- [ ] Verify/complete Google Calendar webhook processing for event updates.
- [ ] Ensure mapping between Calendar Events ↔ Appointments is stable and idempotent.
- [ ] Implement conflict handling rules (e.g., owner moves an event; assistant should update appointment state).
- [ ] Add time-zone and DST coverage:
  - [ ] Tests around DST transitions
  - [ ] Tests for tenant-configured time zone vs server default
- [ ] Add integration-style tests using stubbed calendar provider (and at least one optional real-provider test in a gated pipeline).

### Acceptance criteria
- [ ] Calendar changes made by the owner are reflected in CRM appointments without duplication.
- [ ] Time-zone/DST edge cases are tested and documented.

---

## [P1] Replace STT/TTS stubs with production providers + real-world validation plan

**Problem**
Speech interfaces are core to telephony; moving from stubs to production STT/TTS requires provider robustness testing.

**Suggested labels**
`voice` `integrations` `backend`

### Subtasks
- [ ] Confirm provider interface for STT/TTS is stable and supports multiple implementations.
- [ ] Add at least one non-OpenAI provider option (e.g., cloud STT/TTS alternative) to reduce vendor risk.
- [ ] Validate Twilio audio stream integration with selected STT provider(s).
- [ ] Create a repeatable validation harness:
  - [ ] Accent/noise test suite (sample audio clips)
  - [ ] Latency measurements per step (STT → intent → response → TTS)
- [ ] Add failure-mode handling:
  - [ ] STT timeout fallback behavior
  - [ ] Circuit-breaker for provider outages (if not present)

### Acceptance criteria
- [ ] At least one production STT/TTS provider path works end-to-end in staging.
- [ ] Measured latency + error-rate baselines are documented.

---

## [P1] In-app feedback & bug reporting (dashboard + widget) with context capture

**Problem**
A structured feedback mechanism accelerates beta iteration and support by capturing tenant + session context automatically.

**Suggested labels**
`product` `support` `frontend` `backend`

### Subtasks
- [ ] Add a feedback entry-point in Owner Dashboard UI (and optionally widget).
- [ ] Capture structured context:
  - [ ] tenant/business id
  - [ ] call SID / conversation id (when available)
  - [ ] page route / timestamp
  - [ ] optional user email/name
- [ ] Persist feedback in DB and/or forward to a support channel (email, ticketing webhook).
- [ ] Add admin view/filtering for feedback items.
- [ ] Add privacy guardrails (avoid collecting unnecessary sensitive content by default).

### Acceptance criteria
- [ ] A beta user can submit feedback in < 30 seconds.
- [ ] Support/admin can view feedback with enough context to reproduce the issue.

---

## [P1] Add audit logging for security-relevant events (rate limit, webhook failures, auth anomalies)

**Problem**
Security hardening should produce actionable forensic signals without exposing PII.

**Suggested labels**
`security` `observability` `backend`

### Subtasks
- [ ] Define what constitutes a security event (minimum set):
  - [ ] Invalid webhook signature
  - [ ] Replayed webhook detection
  - [ ] Rate limit triggered
  - [ ] Repeated invalid tokens / auth failures
- [ ] Implement structured logs for security events (minimize PII; hash where needed).
- [ ] Add metrics counters for each event class.
- [ ] Add admin dashboard surfaces (optional) for event summaries.

### Acceptance criteria
- [ ] Security events are queryable by tenant and time window.
- [ ] No sensitive payload data is stored in logs by default.

---

## [P1] Session store backend for multi-instance deployments (Redis or equivalent)

**Problem**
Default in-memory session/state does not work reliably under horizontal scaling.

**Suggested labels**
`scalability` `backend` `ops`

### Subtasks
- [ ] Identify all in-memory state dependencies (voice session state, chat sessions, locks, idempotency caches).
- [ ] Implement a shared session store backend option (e.g., Redis) behind the existing setting (e.g., `SESSION_STORE_BACKEND`).
- [ ] Add local dev support via docker-compose (optional Redis service).
- [ ] Add tests verifying sessions survive across process boundaries (simulated multi-instance).

### Acceptance criteria
- [ ] Two backend instances can serve the same tenant with consistent session behavior.
- [ ] Configuration and runbooks clearly document how to enable shared session store.

---

## [P2] Dashboard maintainability refactor (split large static HTML/JS into modules)

**Problem**
As features grow, very large single-file dashboards become hard to maintain and review.

**Suggested labels**
`frontend` `tech-debt` `dashboard`

### Subtasks
- [ ] Extract dashboard JS into logical modules (API client, state store, components/cards).
- [ ] Keep build tooling minimal (target: no heavy framework required).
- [ ] Add basic linting/formatting for frontend JS (optional).
- [ ] Ensure dashboards still serve as static assets via backend or proxy.

### Acceptance criteria
- [ ] Owner dashboard codebase is modular and readable (no monolithic ~9000-line file).
- [ ] No regression in dashboard functionality.

---

## [P2] Make dashboards mobile-friendly (responsive layouts)

**Problem**
Owners may need to use dashboards on phones; static layouts often degrade on small screens.

**Suggested labels**
`frontend` `ux` `dashboard`

### Subtasks
- [ ] Add responsive CSS breakpoints for core dashboard layouts (KPIs, schedule cards, tables).
- [ ] Validate touch usability (tap targets, scrolling behaviors).
- [ ] Add a minimal “mobile view” navigation pattern if necessary.

### Acceptance criteria
- [ ] Core owner workflows are usable on common phone viewport widths.
- [ ] No overlapping text or unusable controls on small screens.

---

## [P2] Accessibility audit + fixes (dashboard + widget)

**Problem**
Accessibility improvements reduce legal risk and improve usability for all users.

**Suggested labels**
`frontend` `accessibility`

### Subtasks
- [ ] Run an accessibility audit (Lighthouse + manual keyboard navigation).
- [ ] Add/verify ARIA labels where appropriate (widget button already has some).
- [ ] Ensure keyboard navigation works for:
  - [ ] Chat widget open/close and message send
  - [ ] Dashboard filters/buttons
- [ ] Validate color contrast and focus indicators.

### Acceptance criteria
- [ ] Keyboard-only navigation works for core interactions.
- [ ] Lighthouse accessibility score improves (target set by team).

---

## [P2] Add error tracking/APM (e.g., Sentry) + uptime checks for telephony endpoints

**Problem**
Central logs alone often miss exception context and user-impact correlation; telephony endpoints need uptime monitoring.

**Suggested labels**
`observability` `ops` `reliability`

### Subtasks
- [ ] Add error tracking SDK to backend with environment-based enablement.
- [ ] Ensure PII scrubbing/redaction rules are in place.
- [ ] Add uptime checks (synthetic requests) for key endpoints:
  - [ ] Twilio voice webhook
  - [ ] chat endpoints used by widget
- [ ] Create dashboards/alerts for:
  - [ ] exception rate
  - [ ] endpoint uptime
  - [ ] latency

### Acceptance criteria
- [ ] Exceptions include tenant + request context for triage.
- [ ] Uptime alerts fire on simulated endpoint failure.

---

## [P2] Refactor shared assistant logic between voice and chat to reduce duplication

**Problem**
Duplicated logic across voice/chat increases bug risk and makes policy changes harder (e.g., emergency flows).

**Suggested labels**
`backend` `tech-debt` `voice` `chat`

### Subtasks
- [ ] Identify duplicated flows (intent routing, emergency triage, scheduling prompts).
- [ ] Extract shared “assistant policy” module used by both voice and chat routers.
- [ ] Add regression tests ensuring identical behavior across channels for shared scenarios.

### Acceptance criteria
- [ ] Core triage/scheduling flows behave consistently across voice and chat.
- [ ] Reduced duplicated code paths in routers/services.

---

## [P2] Tighten typing (reduce `mypy` ignores) for DB/models and critical services

**Problem**
Type ignore sections can hide bugs in core data access layers.

**Suggested labels**
`quality` `tech-debt` `backend`

### Subtasks
- [ ] Identify files currently excluded/ignored by type checking (DB/models/services).
- [ ] Add/repair type annotations and SQLAlchemy typing patterns.
- [ ] Remove/limit ignores incrementally with CI enforcement.

### Acceptance criteria
- [ ] Reduced mypy ignore surface area for core modules.
- [ ] No new type regressions introduced.

---

## [P2] Quickstart sample data + demo seeding script to improve onboarding

**Problem**
A sample dataset helps new developers/testers validate end-to-end flows quickly.

**Suggested labels**
`docs` `developer-experience`

### Subtasks
- [ ] Add a script/command to seed:
  - [ ] demo tenant
  - [ ] customers + appointments
  - [ ] a few conversations/transcripts
- [ ] Document how to run it in dev modes (in-memory DB and DB-backed).
- [ ] Ensure seeded data supports dashboard cards and analytics endpoints.

### Acceptance criteria
- [ ] A new developer can run a single command and see meaningful dashboard data.

---

## [P2] Internationalization groundwork (UI + assistant prompts)

**Problem**
If future markets require non-English support, groundwork should be laid early to avoid hardcoded strings everywhere.

**Suggested labels**
`frontend` `product` `i18n`

### Subtasks
- [ ] Centralize UI strings (dashboard + widget) into a simple dictionary/module.
- [ ] Centralize assistant prompt strings similarly, with locale selection per tenant.
- [ ] Add one “proof” second locale (even partial) to validate approach.

### Acceptance criteria
- [ ] UI and prompt strings are not scattered across many files.
- [ ] Locale selection mechanism exists (even if only used in dev initially).
