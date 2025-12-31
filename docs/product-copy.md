# Product Copy (Canonical)

This document is the source of truth for Offside product positioning and plan gating.

## Tagline

Offside turns your EA Sports FC Discord into an ops dashboard: rosters, recruiting, clubs, tournaments, and analytics.

## Value (3 bullets)

- **Rosters:** coaches create/manage rosters; staff review and publish approved listings.
- **Recruiting:** structured player profiles + searchable player pool, backed by listing channels.
- **Tournaments:** staff tooling for brackets, fixtures, match reporting, disputes, and standings.

## Target audiences

- **Server owners / league operators:** want consistent workflows, visibility, and guardrails.
- **Staff & moderators:** need review, auditability, and reliable listing channels.
- **Coaches:** want fast roster actions, clear caps/openings, and a clean submission flow.

## Modules (canonical names)

| Module | Who it’s for | What it does |
| --- | --- | --- |
| Dashboards + Setup Wizard | owners + staff | guided setup checks, portal dashboards, and idempotent reposting |
| Rosters | coaches + staff | roster lifecycle: create, add/remove, caps, submit, review, approve/reject/unlock |
| Recruiting | staff | recruit profiles + player pool search; recruit listings and availability workflows |
| Clubs | managers + staff | club ads, club listings, premium coach workflows and reporting |
| Tournaments | staff | tournament creation, registration, brackets, fixtures, match/dispute flows |
| Analytics | owners + staff | per-guild collection analytics + operational visibility |

## Plans (gating)

Implementation note: feature gating is implemented in `services/entitlements_service.py`.

### Free

Free is the default plan and includes all core workflows.

### Pro

Pro unlocks feature-keys listed in `services/entitlements_service.py` `PRO_FEATURE_KEYS`:

- `premium_coach_tiers` (Coach Premium / Coach Premium+ roles and caps)
- `premium_coaches_report` (Premium Coaches listing channel/report)
- `fc25_stats` (FC stats integration)
- `banlist` (Google Sheets banlist integration)
- `tournament_automation` (advanced tournament automation tooling)

### Enterprise

Enterprise is for large organizations that need custom workflows, dedicated support, and/or custom deployments.
It includes everything in Pro, plus negotiated features and operational commitments (SLA, onboarding, custom integrations).

