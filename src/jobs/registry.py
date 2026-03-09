from __future__ import annotations

from typing import Dict, Iterable

from agent_messaging.core.errors import TaskNotFoundError
from agent_messaging.jobs.models import JobDefinition


class JobRegistry:
    def __init__(self, jobs: Dict[str, JobDefinition] | None = None) -> None:
        self._jobs = dict(jobs or {})

    def register(self, job: JobDefinition) -> None:
        self._jobs[job.id] = job

    def replace(self, jobs: Dict[str, JobDefinition]) -> None:
        self._jobs = dict(jobs)

    def get(self, job_id: str) -> JobDefinition:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise TaskNotFoundError("Unknown job_id: {0}".format(job_id)) from exc

    def all(self) -> Iterable[JobDefinition]:
        return self._jobs.values()
