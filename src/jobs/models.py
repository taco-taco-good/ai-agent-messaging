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
class JobSchedule:
    kind: str
    expr: str
    timezone: str = "UTC"


@dataclass(frozen=True)
class JobStep:
    id: str
    type: str
    tool: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    when: Optional[str] = None


@dataclass(frozen=True)
class JobOutput:
    channel_id: Optional[str] = None
    artifact_path: Optional[str] = None


@dataclass(frozen=True)
class JobDefinition:
    id: str
    description: str
    agent_id: str
    enabled: bool
    schedule: JobSchedule
    allowed_tools: List[str]
    steps: List[JobStep]
    output: JobOutput = field(default_factory=JobOutput)
    skill_id: Optional[str] = None
    source_path: Optional[Path] = None


@dataclass(frozen=True)
class JobRunSummary:
    job_id: str
    run_id: int
    status: str
    started_at: datetime
    finished_at: Optional[datetime]
    scheduled_for: Optional[datetime]
    message: str = ""
