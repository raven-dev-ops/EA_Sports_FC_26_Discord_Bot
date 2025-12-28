import re


TEAM_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _-]{2,32}$")
DISCORD_ID_PATTERN = re.compile(r"\d+")

CONSOLE_ALIASES = {
    "PS5": "PS",
    "PLAYSTATION": "PS",
    "PSN": "PS",
    "PS": "PS",
    "XBOX": "XBOX",
    "XBOX SERIES": "XBOX",
    "XBOX SERIES X": "XBOX",
    "XBOX SERIES S": "XBOX",
    "PC": "PC",
    "WINDOWS": "PC",
    "SWITCH": "SWITCH",
    "NINTENDO SWITCH": "SWITCH",
}


def validate_team_name(value: str) -> bool:
    return bool(TEAM_NAME_PATTERN.fullmatch(value.strip()))


def normalize_console(value: str) -> str | None:
    key = value.strip().upper()
    return CONSOLE_ALIASES.get(key)


def parse_discord_id(value: str) -> int | None:
    match = DISCORD_ID_PATTERN.search(value)
    if not match:
        return None
    return int(match.group(0))
