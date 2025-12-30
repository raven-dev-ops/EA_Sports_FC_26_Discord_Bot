from __future__ import annotations

import argparse
import base64
import json
import os
from netrc import NetrcParseError, netrc
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEPRECATED_KEYS: set[str] = {
    # removed from .env.example / docs
    "DISCORD_CLIENT_ID",
    "DISCORD_PUBLIC_KEY",
    "DISCORD_INTERACTIONS_ENDPOINT_URL",
    # old local/dev keys
    "DISCORD_TEST_CHANNEL",
    "HEROKU_API_KEY",
    "MONGODB_COLLECTION2",
    # legacy overrides
    "ROLE_SUPER_LEAGUE_COACH_ID",
    "CHANNEL_ROSTER_PORTAL_ID",
}

OVERRIDE_KEYS: set[str] = {
    "STAFF_ROLE_IDS",
}


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")

    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key_raw, value_raw = line.split("=", 1)
        key = key_raw.strip()
        if not key:
            continue
        value = value_raw.strip()
        if not value:
            out[key] = ""
            continue

        if value[0] in {"'", '"'}:
            quote = value[0]
            if len(value) >= 2 and value.endswith(quote):
                out[key] = value[1:-1]
            else:
                out[key] = value.lstrip(quote)
            continue

        # Strip inline comments for unquoted values (e.g. `KEY= # comment`).
        cleaned_chars: list[str] = []
        for idx, ch in enumerate(value_raw):
            if ch == "#" and (idx == 0 or value_raw[idx - 1].isspace()):
                break
            cleaned_chars.append(ch)
        out[key] = "".join(cleaned_chars).strip()
    return out


def _parse_env_key_whitelist(example_path: Path) -> set[str]:
    keys: set[str] = set()
    if not example_path.exists():
        return keys
    for raw_line in example_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def _is_override_key(key: str) -> bool:
    if key in OVERRIDE_KEYS:
        return True
    return key.startswith("ROLE_") or key.startswith("CHANNEL_")


def _get_auth_header(*, dotenv: dict[str, str] | None = None) -> str | None:
    dotenv = dotenv or {}
    token = os.environ.get("HEROKU_API_KEY", "").strip() or dotenv.get("HEROKU_API_KEY", "").strip()
    email = os.environ.get("HEROKU_EMAIL", "").strip() or dotenv.get("HEROKU_EMAIL", "").strip()
    if email and token:
        encoded = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"
    if token:
        # If an API key/token is explicitly provided, prefer it over any _netrc credentials.
        return f"Bearer {token}"

    userprofile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    for candidate in (Path(userprofile) / "_netrc", Path(userprofile) / ".netrc"):
        if not candidate.exists():
            continue
        try:
            auth = netrc(str(candidate)).authenticators("api.heroku.com")
        except (OSError, NetrcParseError):
            continue
        if not auth:
            continue
        login, _account, password = auth
        if login and password:
            encoded = base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("ascii")
            return f"Basic {encoded}"
    return None


def _patch_heroku_config(*, app: str, auth_header: str, payload: dict[str, object]) -> None:
    url = f"https://api.heroku.com/apps/{app}/config-vars"
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=data,
        method="PATCH",
        headers={
            "Accept": "application/vnd.heroku+json; version=3",
            "Content-Type": "application/json",
            "Authorization": auth_header,
        },
    )
    with urlopen(req, timeout=30) as resp:
        resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync .env values to Heroku config vars (no secret values printed)."
    )
    parser.add_argument("--app", default="official-offside-bot", help="Heroku app name")
    parser.add_argument("--dotenv", default=".env", help="Path to dotenv file")
    parser.add_argument(
        "--example",
        default=".env.example",
        help="Path to .env.example for whitelisting keys",
    )
    parser.add_argument(
        "--prune-deprecated",
        action="store_true",
        help="Unset known deprecated keys in Heroku config",
    )
    parser.add_argument(
        "--include-overrides",
        action="store_true",
        help="Include ROLE_*/CHANNEL_* and STAFF_ROLE_IDS overrides (not recommended for multi-guild prod)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print keys that would be set/cleared without making API calls",
    )
    args = parser.parse_args()

    env_values = _parse_dotenv(Path(args.dotenv))
    auth_header = _get_auth_header(dotenv=env_values)
    if not auth_header:
        print(
            "Missing Heroku credentials. Set HEROKU_API_KEY (and optional HEROKU_EMAIL) in the environment or in the dotenv file, "
            "or ensure USERPROFILE/_netrc contains api.heroku.com credentials."
        )
        return 2

    whitelist = _parse_env_key_whitelist(Path(args.example))

    to_set: dict[str, str] = {}
    for key in sorted(whitelist):
        if not args.include_overrides and _is_override_key(key):
            continue
        value = env_values.get(key, "")
        if value != "":
            to_set[key] = value

    payload: dict[str, object] = dict(to_set)
    to_clear: list[str] = []
    if args.prune_deprecated:
        for key in sorted(DEPRECATED_KEYS):
            payload[key] = None
            to_clear.append(key)

    print(f"Heroku app: {args.app}")
    print(f"Set {len(to_set)} config vars:")
    for key in sorted(to_set):
        print(f"- {key}")
    if to_clear:
        print(f"Clear {len(to_clear)} deprecated vars:")
        for key in to_clear:
            print(f"- {key}")

    if args.dry_run:
        print("Dry run: no changes applied.")
        return 0

    try:
        _patch_heroku_config(app=args.app, auth_header=auth_header, payload=payload)
    except HTTPError as e:
        print(f"Heroku API error: HTTP {e.code} {e.reason}")
        return 1
    except URLError as e:
        print(f"Heroku API connection error: {e.reason}")
        return 1

    print("Heroku config vars updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
