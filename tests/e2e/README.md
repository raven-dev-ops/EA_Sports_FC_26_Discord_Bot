## End-to-end harness (optional)

These are manual/automation-ready scenarios that can be exercised with mocked credentials or in a staging guild. They are meant to guide end-to-end validation without hitting production:

1) **Roster lifecycle**
   - `/roster` create → add 8 players → submit → approve/reject → unlock → resubmit.
   - Verify approved roster posts to roster listing channel; staff card cleans up on decision.
2) **Tournament flow**
   - `/tournament_create` → `/tournament_register` 4 teams → `/tournament_bracket_preview` → `/tournament_bracket` → `/match_report` + `/match_confirm` → `/advance_round` → `/tournament_stats`.
3) **Recovery**
   - Insert a submitted roster without submission record; restart worker and confirm it auto-unlocks.
4) **Permissions**
   - Non-staff user attempts tournament commands and is denied; staff user succeeds.

For automation, stub Discord interactions with the integration tests pattern in `tests/integration/`, or wire a test bot token in a staging guild and run the above sequentially. Keep `TEST_MODE=true` and route noise to the staff monitor channel created automatically under `--OFFSIDE REPORTS--`.
