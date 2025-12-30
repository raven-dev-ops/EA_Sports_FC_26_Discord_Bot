# Command Reference

## Roster

### /roster [tournament]

- Description: Open the roster dashboard to create/add/remove/view/submit a team.
- Permissions: Coach roles
- Example: `/roster tournament:"Summer Cup"`

### /unlock_roster <coach> [tournament]

- Description: Unlock a coach roster for edits and clear stale submissions.
- Permissions: Staff
- Example: `/unlock_roster @CoachUser tournament:"Summer Cup"`


## Recruitment

### /me

- Description: Show your stored recruit profile preview (ephemeral).
- Permissions: Anyone (in a guild)


## Staff

### /player_pool [position] [archetype] [platform] [mic]

- Description: Search recruit profiles (ephemeral).
- Permissions: Staff

### /player_pool_index

- Description: Post/update a pinned Player Pool index in the recruit listing channel.
- Permissions: Staff


## Operations

### /setup_channels

- Description: Create/update Offside categories, portal/listing channels (including Club Managers), and coach roles in this guild.
- Permissions: Staff

### /ping

- Description: Health check.
- Permissions: Anyone

### /help

- Description: Command catalog and workflow guidance (ephemeral).
- Permissions: Anyone

### /config_view

- Description: View non-secret runtime settings.
- Permissions: Staff

### /config_set <field> <value>

- Description: Set a runtime config value (no persistence).
- Permissions: Staff
- Example: `/config_set banlist_cache_ttl_seconds 600`

### /config_guild_view

- Description: View per-guild overrides.
- Permissions: Staff

### /config_guild_set <field> <value>

- Description: Set a per-guild override.
- Permissions: Staff
- Example: `/config_guild_set announcements_channel 1234567890`

### /rules_template

- Description: Get a starter rules template to paste and edit.
- Permissions: Staff


## Tournament

### /tournament_dashboard

- Description: Staff quick reference for tournament commands.
- Permissions: Staff

### /tournament_create

- Description: Create a tournament.
- Permissions: Staff

### /tournament_state

- Description: Update tournament state (DRAFT/REG_OPEN/IN_PROGRESS/COMPLETED).
- Permissions: Staff

### /tournament_register

- Description: Register a team into a tournament.
- Permissions: Staff

### /tournament_bracket

- Description: Publish first-round bracket and advance state.
- Permissions: Staff

### /tournament_bracket_preview

- Description: Preview first-round bracket (no DB writes).
- Permissions: Staff

### /advance_round

- Description: Advance to next round from recorded winners.
- Permissions: Staff

### /tournament_stats

- Description: Show wins/losses/GD leaderboard.
- Permissions: Staff

### /match_report

- Description: Report a match score.
- Permissions: Staff

### /match_confirm

- Description: Confirm a reported match.
- Permissions: Staff

### /match_deadline

- Description: Set or update a match deadline.
- Permissions: Staff

### /match_forfeit

- Description: Forfeit a match to a winner.
- Permissions: Staff

### /match_reschedule

- Description: Request a reschedule for a match.
- Permissions: Staff

### /dispute_add

- Description: File a dispute on a match.
- Permissions: Staff

### /dispute_resolve

- Description: Resolve the latest dispute on a match.
- Permissions: Staff

### /group_create

- Description: Create a group.
- Permissions: Staff

### /group_register

- Description: Register a team into a group.
- Permissions: Staff

### /group_generate_fixtures

- Description: Generate group fixtures (supports double_round).
- Permissions: Staff

### /group_match_report

- Description: Report a group-stage match score.
- Permissions: Staff

### /group_standings

- Description: Show group standings.
- Permissions: Staff

### /group_advance

- Description: Advance top N from group into bracket.
- Permissions: Staff
