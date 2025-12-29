# FC25 Clubs Stats Integration Policy (Draft)

This document describes how the optional FC25 Clubs stats integration works in Offside, what data is stored, and how users can revoke consent and delete data.

## Decision

Proceed, but **opt-in only**:
- Disabled by default (feature flag).
- Users must explicitly link their stats and can unlink at any time.
- Store a minimal set of fields needed to render “Verified Stats” on the profile card.

## Consent language (UI)

When a user links FC25 Clubs stats, show (or equivalent):

> By linking FC25 Clubs stats, you consent to the bot fetching your Clubs stats from EA endpoints and storing a limited subset of those stats in this Discord server for recruitment/profile display. You can unlink at any time to delete the stored link and cached snapshots.

## What we store

### Link record (`record_type="fc25_stats_link"`)

Purpose: connect a Discord user to a Clubs identity.

Stored fields (recommended):
- `guild_id`, `user_id`
- `platform_key` (e.g., `common-gen5`)
- `club_id`, `club_name`
- `member_name`
- `verified`, `verified_at`
- `last_fetched_at`, `last_fetch_status`
- `created_at`, `updated_at`

### Snapshot record (`record_type="fc25_stats_snapshot"`)

Purpose: cache a small, normalized subset of stats for rendering.

Stored fields (recommended):
- `guild_id`, `user_id`, `platform_key`, `club_id`
- `snapshot` (normalized subset only; avoid storing raw responses)
- `fetched_at`

## Retention

- Links: retained until the user unlinks or staff removes the record.
- Snapshots: retained for a limited window (e.g., 30 days) and/or pruned to the latest snapshot per user.

## Deletion / Unlink behavior

Users must have an explicit “Unlink FC25 Stats” path that:
- Deletes the link record for the guild/user.
- Deletes cached snapshots for the guild/user.
- Removes “Verified Stats” from the recruitment profile embed on the next upsert.

## Operational limits

To protect the bot and upstream endpoints:
- Cache TTL: default 900s (configurable).
- HTTP timeout: default 7s (configurable).
- Concurrency limit: default 3 (configurable).
- Per-guild rate limits: default 20 requests / 10 minutes (configurable).

## How this relates to existing policies

- This feature extends data processed under `PRIVACY_POLICY.md` and `TERMS_OF_SERVICE.md`.
- It should be treated as **user-provided opt-in enrichment**; it must not be enabled silently.
