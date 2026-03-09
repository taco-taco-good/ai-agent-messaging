from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from agent_messaging.tasks.cron import CronExpression
from agent_messaging.tasks.registry import TaskRegistry
from agent_messaging.tasks.runtime import TaskRuntime


logger = logging.getLogger(__name__)


class TaskScheduler:
    def __init__(
        self,
        registry: TaskRegistry,
        runtime: TaskRuntime,
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
        self._task = asyncio.create_task(self._loop(), name="task_scheduler")
        logger.info("task_scheduler_started", extra={"poll_interval": self.poll_interval})

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
        for task in self.registry.all():
            if not task.enabled or task.schedule.kind != "cron":
                continue
            cron = CronExpression.parse(task.schedule.expr, timezone=task.schedule.timezone)
            if cron.matches(current):
                await self.runtime.run_task(task.id, scheduled_for=cron.slot_for(current), trigger="schedule")

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_pending()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                logger.info("task_scheduler_stopped")
                return
            except Exception:
                logger.exception("task_scheduler_error")
