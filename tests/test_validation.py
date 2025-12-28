from utils.validation import normalize_console, validate_team_name


def test_validate_team_name_accepts_valid_values() -> None:
    assert validate_team_name("Team Alpha")
    assert validate_team_name("Team-01")
    assert validate_team_name("Team_02")


def test_validate_team_name_rejects_invalid_values() -> None:
    assert not validate_team_name("A")
    assert not validate_team_name("ThisNameIsWayTooLongToBeValidInTheRules")
    assert not validate_team_name("Bad@Name")


def test_normalize_console_aliases() -> None:
    assert normalize_console("ps5") == "PS"
    assert normalize_console("XBOX") == "XBOX"
    assert normalize_console("PC") == "PC"
