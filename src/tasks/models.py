from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ALLOWED_STEP_TYPES = {
    "load",
    "filter",
    "validate",
    "enrich",
    "generate",
    "deliver",
    "persist",
}


@dataclass(frozen=True)
class TaskSchedule:
    kind: str
    expr: str
    timezone: str = "UTC"


@dataclass(frozen=True)
class TaskStep:
    id: str
    type: str
    tool: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    when: Optional[str] = None


@dataclass(frozen=True)
class TaskOutput:
    channel_id: Optional[str] = None
    artifact_path: Optional[str] = None


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    description: str
    agent_id: str
    enabled: bool
    schedule: TaskSchedule
    allowed_tools: List[str]
    steps: List[TaskStep]
    output: TaskOutput = field(default_factory=TaskOutput)
    source_path: Optional[Path] = None


@dataclass(frozen=True)
class TaskRunSummary:
    task_id: str
    run_id: int
    status: str
    started_at: datetime
    finished_at: Optional[datetime]
    scheduled_for: Optional[datetime]
    message: str = ""
