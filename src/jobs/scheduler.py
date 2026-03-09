from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from agent_messaging.jobs.cron import CronExpression
from agent_messaging.jobs.registry import JobRegistry
from agent_messaging.jobs.runtime import JobRuntime


logger = logging.getLogger(__name__)


class JobScheduler:
    def __init__(
        self,
        registry: JobRegistry,
        runtime: JobRuntime,
        *,
        poll_interval: float = 30.0,
    ) -> None:
        self.registry = registry
        self.runtime = runtime
        self.poll_interval = poll_interval
        self._task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="job_scheduler")
        logger.info("job_scheduler_started", extra={"poll_interval": self.poll_interval})

    async def shutdown(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_pending(self, when: Optional[datetime] = None) -> None:
        current = when or datetime.now(timezone.utc)
        for job in self.registry.all():
            if not job.enabled or job.schedule.kind != "cron":
                continue
            cron = CronExpression.parse(job.schedule.expr, timezone=job.schedule.timezone)
            if cron.matches(current):
                await self.runtime.run_job(job.id, scheduled_for=cron.slot_for(current), trigger="schedule")

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_pending()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                logger.info("job_scheduler_stopped")
                return
            except Exception:
                logger.exception("job_scheduler_error")
