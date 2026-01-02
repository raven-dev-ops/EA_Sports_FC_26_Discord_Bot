from services.permission_service import resolve_roster_cap


def test_club_manager_takes_precedence() -> None:
    cap = resolve_roster_cap(
        [100, 200, 300],
        team_coach_role_id=100,
        club_manager_role_id=200,
        league_staff_role_id=300,
        league_owner_role_id=400,
    )
    assert cap == 22


def test_team_coach_when_no_staff_roles() -> None:
    cap = resolve_roster_cap(
        [100],
        team_coach_role_id=100,
        club_manager_role_id=200,
        league_staff_role_id=300,
        league_owner_role_id=400,
    )
    assert cap == 16


def test_club_manager_when_no_team_coach() -> None:
    cap = resolve_roster_cap(
        [200],
        team_coach_role_id=100,
        club_manager_role_id=200,
        league_staff_role_id=300,
        league_owner_role_id=400,
    )
    assert cap == 22


def test_no_matching_roles_returns_none() -> None:
    cap = resolve_roster_cap(
        [999],
        team_coach_role_id=100,
        club_manager_role_id=200,
        league_staff_role_id=300,
        league_owner_role_id=400,
    )
    assert cap is None
