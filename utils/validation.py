import re

TEAM_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _-]{2,32}$")
DISCORD_ID_PATTERN = re.compile(r"\d+")
MASS_MENTION_PATTERN = re.compile(r"@everyone|@here", re.IGNORECASE)

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


def sanitize_text(value: str, *, max_length: int = 300, allow_newlines: bool = False) -> str:
    """
    Trim, collapse whitespace, optionally strip newlines, and enforce a max length.
    """
    cleaned = value.strip()
    if not allow_newlines:
        cleaned = cleaned.replace("\n", " ").replace("\r", " ")
    # Collapse multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def ensure_safe_text(value: str, *, max_length: int = 300) -> str:
    """
    Sanitize text and block mass mentions.
    """
    cleaned = sanitize_text(value, max_length=max_length, allow_newlines=False)
    if MASS_MENTION_PATTERN.search(cleaned):
        raise ValueError("Mass mentions are not allowed.")
    return cleaned
