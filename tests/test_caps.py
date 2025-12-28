from services.permission_service import resolve_roster_cap


def test_super_league_takes_precedence() -> None:
    cap = resolve_roster_cap(
        [100, 200, 300],
        super_league_role_id=100,
        premium_role_id=200,
        premium_plus_role_id=300,
    )
    assert cap == 16


def test_premium_plus_over_premium() -> None:
    cap = resolve_roster_cap(
        [200, 300],
        super_league_role_id=100,
        premium_role_id=200,
        premium_plus_role_id=300,
    )
    assert cap == 25


def test_premium_when_no_premium_plus() -> None:
    cap = resolve_roster_cap(
        [200],
        super_league_role_id=100,
        premium_role_id=200,
        premium_plus_role_id=300,
    )
    assert cap == 22


def test_no_matching_roles_returns_none() -> None:
    cap = resolve_roster_cap(
        [999],
        super_league_role_id=100,
        premium_role_id=200,
        premium_plus_role_id=300,
    )
    assert cap is None
