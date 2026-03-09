from __future__ import annotations

from typing import Dict, Iterable

from agent_messaging.core.errors import TaskNotFoundError
from agent_messaging.tasks.models import TaskDefinition


class TaskRegistry:
    def __init__(self, tasks: Dict[str, TaskDefinition] | None = None) -> None:
        self._tasks = dict(tasks or {})

    def register(self, task: TaskDefinition) -> None:
        self._tasks[task.id] = task

    def replace(self, tasks: Dict[str, TaskDefinition]) -> None:
        self._tasks = dict(tasks)

    def get(self, task_id: str) -> TaskDefinition:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise TaskNotFoundError("Unknown task_id: {0}".format(task_id)) from exc

    def all(self) -> Iterable[TaskDefinition]:
        return self._tasks.values()
