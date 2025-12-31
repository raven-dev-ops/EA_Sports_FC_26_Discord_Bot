from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from bson.json_util import dumps

from config import load_settings
from database import get_database


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_out_dir(*, guild_id: int) -> Path:
    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    return Path("exports") / f"guild_{guild_id}_{stamp}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a guild database (per-guild DB mode).")
    parser.add_argument("--guild-id", type=int, required=True, help="Discord guild ID to export.")
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="Output directory (default: ./exports/guild_<id>_<timestamp>/).",
    )
    parser.add_argument(
        "--limit-per-collection",
        type=int,
        default=0,
        help="Optional per-collection document limit (0 = no limit).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = load_settings()

    if not settings.mongodb_uri:
        raise SystemExit("MongoDB is not configured (missing MONGODB_URI).")
    if not settings.mongodb_per_guild_db:
        raise SystemExit("Guild export requires MONGODB_PER_GUILD_DB=true.")

    guild_id = int(args.guild_id)
    db = get_database(settings, guild_id=guild_id)

    out_dir = Path(args.out).expanduser() if str(args.out or "").strip() else _default_out_dir(guild_id=guild_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    limit = int(args.limit_per_collection or 0)
    manifest: dict[str, object] = {
        "guild_id": guild_id,
        "db_name": db.name,
        "exported_at": _utc_now().isoformat(),
        "collections": {},
    }

    collection_names = sorted(db.list_collection_names())
    for name in collection_names:
        col = db[name]
        cursor = col.find({})
        if limit > 0:
            cursor = cursor.limit(limit)

        count = 0
        out_file = out_dir / f"{name}.ndjson"
        with out_file.open("w", encoding="utf-8") as handle:
            for doc in cursor:
                handle.write(dumps(doc, sort_keys=True))
                handle.write("\n")
                count += 1

        manifest["collections"][name] = {"file": out_file.name, "count": count}

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(str(out_dir))


if __name__ == "__main__":
    main()

