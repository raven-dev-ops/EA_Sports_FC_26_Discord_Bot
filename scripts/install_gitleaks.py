from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen


def _asset_name(*, version: str) -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"aarch64", "arm64"}:
        arch = "arm64"
    else:
        raise RuntimeError(f"Unsupported architecture: {platform.machine()!r}")

    if system == "windows":
        return f"gitleaks_{version}_windows_{arch}.zip"
    if system == "linux":
        return f"gitleaks_{version}_linux_{arch}.tar.gz"
    if system == "darwin":
        return f"gitleaks_{version}_darwin_{arch}.tar.gz"

    raise RuntimeError(f"Unsupported OS: {platform.system()!r}")


def _download(url: str, *, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=60) as resp:  # noqa: S310
        dest.write_bytes(resp.read())


def _extract(archive_path: Path, *, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    if archive_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(out_dir)
        exe = out_dir / "gitleaks.exe"
        if not exe.exists():
            raise RuntimeError("gitleaks.exe not found after extraction.")
        return exe

    if archive_path.name.endswith(".tar.gz"):
        with tarfile.open(archive_path, mode="r:gz") as tf:
            tf.extractall(out_dir)  # noqa: S202
        binary = out_dir / "gitleaks"
        if not binary.exists():
            raise RuntimeError("gitleaks binary not found after extraction.")
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        return binary

    raise RuntimeError(f"Unsupported archive format: {archive_path.name}")


def _append_github_path(dir_path: Path) -> None:
    github_path = os.environ.get("GITHUB_PATH", "").strip()
    if not github_path:
        return
    path_file = Path(github_path)
    with path_file.open("a", encoding="utf-8", newline="") as handle:
        handle.write(str(dir_path))
        handle.write(os.linesep)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install gitleaks binary for CI.")
    parser.add_argument("--version", default="8.30.0", help="Gitleaks version (no leading v).")
    parser.add_argument("--out-dir", default=".tools/gitleaks", help="Directory to install into.")
    args = parser.parse_args()

    version = str(args.version).strip().lstrip("v")
    if not version:
        raise SystemExit("Invalid --version")

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = out_dir / ("gitleaks.exe" if platform.system().lower() == "windows" else "gitleaks")
    if target.exists():
        _append_github_path(out_dir)
        return 0

    asset = _asset_name(version=version)
    url = f"https://github.com/gitleaks/gitleaks/releases/download/v{version}/{asset}"

    with tempfile.TemporaryDirectory(prefix="gitleaks_") as tmp:
        tmp_dir = Path(tmp)
        archive_path = tmp_dir / asset
        _download(url, dest=archive_path)
        extract_dir = tmp_dir / "extract"
        extracted = _extract(archive_path, out_dir=extract_dir)
        shutil.move(str(extracted), str(target))

    _append_github_path(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
