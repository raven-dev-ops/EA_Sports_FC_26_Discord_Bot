from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict


class Job:
    def __init__(self, name: str, interval: float, coro: Callable[[], Awaitable[None]]) -> None:
        self.name = name
        self.interval = interval
        self.coro = coro
        self.task: asyncio.Task | None = None


class Scheduler:
    def __init__(self) -> None:
        self.jobs: Dict[str, Job] = {}
        self._running = False

    def add_job(self, name: str, interval: float, coro: Callable[[], Awaitable[None]]) -> None:
        if name in self.jobs:
            raise RuntimeError(f"Job {name} already exists.")
        self.jobs[name] = Job(name, interval, coro)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for job in self.jobs.values():
            job.task = asyncio.create_task(self._run_job(job))

    async def stop(self) -> None:
        self._running = False
        for job in self.jobs.values():
            if job.task:
                job.task.cancel()
        await asyncio.gather(
            *(job.task for job in self.jobs.values() if job.task), return_exceptions=True
        )

    async def _run_job(self, job: Job) -> None:
        while self._running:
            try:
                await job.coro()
            except Exception:
                logging.exception("Scheduler job %s failed", job.name)
            await asyncio.sleep(job.interval)
