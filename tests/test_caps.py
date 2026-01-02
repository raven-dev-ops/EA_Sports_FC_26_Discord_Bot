from services.permission_service import resolve_roster_cap


def test_club_manager_plus_takes_precedence() -> None:
    cap = resolve_roster_cap(
        [100, 210, 300],
        team_coach_role_id=100,
        coach_plus_role_id=110,
        club_manager_role_id=200,
        club_manager_plus_role_id=210,
        league_staff_role_id=300,
        league_owner_role_id=400,
    )
    assert cap == 25


def test_club_manager_takes_precedence() -> None:
    cap = resolve_roster_cap(
        [100, 200, 300],
        team_coach_role_id=100,
        coach_plus_role_id=110,
        club_manager_role_id=200,
        club_manager_plus_role_id=210,
        league_staff_role_id=300,
        league_owner_role_id=400,
    )
    assert cap == 22


def test_coach_plus_when_no_manager_roles() -> None:
    cap = resolve_roster_cap(
        [110],
        team_coach_role_id=100,
        coach_plus_role_id=110,
        club_manager_role_id=200,
        club_manager_plus_role_id=210,
        league_staff_role_id=300,
        league_owner_role_id=400,
    )
    assert cap == 22


def test_team_coach_when_no_staff_roles() -> None:
    cap = resolve_roster_cap(
        [100],
        team_coach_role_id=100,
        coach_plus_role_id=110,
        club_manager_role_id=200,
        club_manager_plus_role_id=210,
        league_staff_role_id=300,
        league_owner_role_id=400,
    )
    assert cap == 16


def test_no_matching_roles_returns_none() -> None:
    cap = resolve_roster_cap(
        [999],
        team_coach_role_id=100,
        coach_plus_role_id=110,
        club_manager_role_id=200,
        club_manager_plus_role_id=210,
        league_staff_role_id=300,
        league_owner_role_id=400,
    )
    assert cap is None
