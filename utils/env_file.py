from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path, *, override: bool = False) -> dict[str, str]:
    """
    Load KEY=VALUE pairs from a .env-style file into os.environ.

    - Ignores blank lines and comments (# ...).
    - Supports optional "export " prefix.
    - Strips matching single/double quotes around values.
    - By default, does not override existing environment variables.

    Returns a dict of variables that were set/overridden.
    """
    env_path = Path(path)
    if not env_path.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]

        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = value

    return loaded

