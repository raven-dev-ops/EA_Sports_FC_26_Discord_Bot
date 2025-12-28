from utils.formatting import format_submission_message


def test_submission_format_includes_status_and_counts() -> None:
    message = format_submission_message(
        team_name="Thunderbolts",
        coach_mention="@Coach123",
        roster_count=2,
        cap=25,
        roster_lines=[
            "@PlayerA / GT1 / EA1 / PS",
            "@PlayerB / GT2 / EA2 / XBOX",
        ],
        status_text="Approved",
    )

    assert "Team: Thunderbolts" in message
    assert "Roster (2/25):" in message
    assert "Status: Approved" in message
