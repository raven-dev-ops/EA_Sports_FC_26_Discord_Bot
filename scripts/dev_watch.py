"""
Dev helper: restart the bot when Python files change.

Requires `watchfiles` (already in requirements-dev.txt).
Usage:
  python -m scripts.dev_watch
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from watchfiles import awatch

LOG = logging.getLogger(__name__)


async def _restart_bot(proc: asyncio.subprocess.Process | None) -> asyncio.subprocess.Process:
    if proc and proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
    LOG.info("Starting bot process...")
    return await asyncio.create_subprocess_exec(sys.executable, "-m", "offside_bot")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    proc: asyncio.subprocess.Process | None = None
    proc = await _restart_bot(proc)
    watch_path = Path(".")
    async for changes in awatch(watch_path, stop_event=None):
        if not any(str(path).endswith(".py") for _, path in changes):
            continue
        LOG.info("Changes detected, restarting bot...")
        proc = await _restart_bot(proc)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
