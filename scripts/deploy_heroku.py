from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _heroku_token(dotenv: dict[str, str]) -> str | None:
    return os.environ.get("HEROKU_API_KEY", "").strip() or dotenv.get("HEROKU_API_KEY", "").strip() or None


def _heroku_request(
    *,
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.heroku+json; version=3",
        "Authorization": f"Bearer {token}",
    }
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, method=method.upper(), headers=headers)
    with urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _create_source(*, token: str) -> tuple[str, str]:
    data = _heroku_request(method="POST", url="https://api.heroku.com/sources", token=token)
    blob = data.get("source_blob") or {}
    put_url = str(blob.get("put_url") or "")
    get_url = str(blob.get("get_url") or "")
    if not put_url or not get_url:
        raise RuntimeError("Heroku source_blob URLs missing from /sources response.")
    return put_url, get_url


def _upload_source(*, put_url: str, archive_path: Path) -> None:
    payload = archive_path.read_bytes()
    req = Request(
        put_url,
        data=payload,
        method="PUT",
        headers={"Content-Type": "application/octet-stream"},
    )
    with urlopen(req, timeout=120) as resp:
        resp.read()


def _git_sha(*, ref: str) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", ref],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _git_archive(*, ref: str, out_path: Path) -> None:
    if out_path.exists():
        out_path.unlink()
    subprocess.run(
        ["git", "archive", "--format=tar.gz", ref, "-o", str(out_path)],
        check=True,
    )


def _create_build(*, app: str, token: str, source_url: str, version: str) -> str:
    data = _heroku_request(
        method="POST",
        url=f"https://api.heroku.com/apps/{app}/builds",
        token=token,
        payload={"source_blob": {"url": source_url, "version": version}},
    )
    build_id = str(data.get("id") or "")
    if not build_id:
        raise RuntimeError("Build id missing from /builds response.")
    return build_id


def _wait_build(*, app: str, token: str, build_id: str, timeout_seconds: int) -> dict[str, Any]:
    started = time.time()
    last_status = None
    while True:
        data = _heroku_request(
            method="GET",
            url=f"https://api.heroku.com/apps/{app}/builds/{build_id}",
            token=token,
        )
        status = str(data.get("status") or "")
        if status and status != last_status:
            print(f"build_status={status}")
            last_status = status
        if status in {"succeeded", "failed"}:
            return data
        if time.time() - started > timeout_seconds:
            raise RuntimeError("Timed out waiting for Heroku build to finish.")
        time.sleep(3.0)


def _scale_process(*, app: str, token: str, process_type: str, quantity: int) -> None:
    _heroku_request(
        method="PATCH",
        url=f"https://api.heroku.com/apps/{app}/formation/{process_type}",
        token=token,
        payload={"quantity": quantity},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy the current git ref to Heroku via the Platform API.")
    parser.add_argument("--app", default="official-offside-bot", help="Heroku app name")
    parser.add_argument("--ref", default="HEAD", help="Git ref to deploy (default: HEAD)")
    parser.add_argument("--dotenv", default=".env", help="Dotenv path (for HEROKU_API_KEY)")
    parser.add_argument("--timeout", type=int, default=600, help="Build timeout seconds")
    parser.add_argument("--scale-web", type=int, default=1, help="web dyno quantity after deploy")
    parser.add_argument("--scale-worker", type=int, default=1, help="worker dyno quantity after deploy")
    args = parser.parse_args()

    dotenv = _parse_dotenv(Path(args.dotenv))
    token = _heroku_token(dotenv)
    if not token:
        print("Missing HEROKU_API_KEY (set it in env or in the dotenv file).")
        return 2

    sha = _git_sha(ref=args.ref)
    archive_path = Path(".heroku-src.tar.gz")
    _git_archive(ref=args.ref, out_path=archive_path)

    try:
        put_url, get_url = _create_source(token=token)
        _upload_source(put_url=put_url, archive_path=archive_path)
        build_id = _create_build(app=args.app, token=token, source_url=get_url, version=sha)
        result = _wait_build(app=args.app, token=token, build_id=build_id, timeout_seconds=args.timeout)
        if str(result.get("status")) != "succeeded":
            print("Build failed.")
            return 1

        _scale_process(app=args.app, token=token, process_type="web", quantity=args.scale_web)
        _scale_process(app=args.app, token=token, process_type="worker", quantity=args.scale_worker)
        print("Deploy complete.")
        return 0
    except HTTPError as e:
        print(f"Heroku API error: HTTP {e.code} {e.reason}")
        return 1
    except URLError as e:
        print(f"Heroku API connection error: {e.reason}")
        return 1
    finally:
        try:
            archive_path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

