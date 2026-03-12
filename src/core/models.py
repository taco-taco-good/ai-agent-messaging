from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    provider: str
    discord_token: str
    workspace_dir: Path
    memory_dir: Path
    display_name: Optional[str] = None
    model: Optional[str] = None
    persona: str = ""
    persona_file: Optional[Path] = None
    cli_args: List[str] = field(default_factory=list)

    @property
    def workdir(self) -> Path:
        """Backward-compatible alias for older call sites."""
        return self.workspace_dir


@dataclass
class SessionRecord:
    agent_id: str
    provider: str
    provider_session_id: str
    current_model: Optional[str]
    last_activity_at: datetime
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "provider": self.provider,
            "provider_session_id": self.provider_session_id,
            "current_model": self.current_model,
            "last_activity_at": self.last_activity_at.isoformat(),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SessionRecord":
        return cls(
            agent_id=payload["agent_id"],
            provider=payload["provider"],
            provider_session_id=payload.get("provider_session_id", ""),
            current_model=payload.get("current_model"),
            last_activity_at=datetime.fromisoformat(payload["last_activity_at"]),
            status=payload.get("status", "active"),
        )


@dataclass(frozen=True)
class ModelOption:
    value: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class RuntimeCommand:
    kind: str
    agent_id: str
    session_key: str
    channel_id: str
    is_dm: bool
    payload: Dict[str, Any]
    parent_channel_id: Optional[str] = None


@dataclass(frozen=True)
class FrontmatterMetadata:
    tags: List[str] = field(default_factory=list)
    topic: str = ""
    summary: str = ""


@dataclass(frozen=True)
class MemorySearchRequest:
    query: str
    top_k: int = 5
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemorySearchResult:
    path: str
    date: str
    topic: str
    summary: str
    snippet: str
    score: float


@dataclass
class SessionSnapshot:
    session_key: str
    updated_at: datetime
    current_task: str = ""
    topic: str = ""
    summary: str = ""
    activity_type: str = ""
    work_status: str = ""
    current_artifact: str = ""
    latest_conclusion: str = ""
    evidence_basis: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    recent_decisions: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    next_step: str = ""
    touched_files: List[str] = field(default_factory=list)
    last_user_message: str = ""
    last_assistant_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_key": self.session_key,
            "updated_at": self.updated_at.isoformat(),
            "current_task": self.current_task,
            "topic": self.topic,
            "summary": self.summary,
            "activity_type": self.activity_type,
            "work_status": self.work_status,
            "current_artifact": self.current_artifact,
            "latest_conclusion": self.latest_conclusion,
            "evidence_basis": list(self.evidence_basis),
            "artifacts": list(self.artifacts),
            "tags": list(self.tags),
            "recent_decisions": list(self.recent_decisions),
            "open_questions": list(self.open_questions),
            "next_step": self.next_step,
            "touched_files": list(self.touched_files),
            "last_user_message": self.last_user_message,
            "last_assistant_summary": self.last_assistant_summary,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SessionSnapshot":
        return cls(
            session_key=str(payload["session_key"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            current_task=str(payload.get("current_task", "")),
            topic=str(payload.get("topic", "")),
            summary=str(payload.get("summary", "")),
            activity_type=str(payload.get("activity_type", "")),
            work_status=str(payload.get("work_status", "")),
            current_artifact=str(payload.get("current_artifact", "")),
            latest_conclusion=str(payload.get("latest_conclusion", "")),
            evidence_basis=[str(item) for item in payload.get("evidence_basis", [])],
            artifacts=[str(item) for item in payload.get("artifacts", [])],
            tags=[str(tag) for tag in payload.get("tags", [])],
            recent_decisions=[str(item) for item in payload.get("recent_decisions", [])],
            open_questions=[str(item) for item in payload.get("open_questions", [])],
            next_step=str(payload.get("next_step", "")),
            touched_files=[str(item) for item in payload.get("touched_files", [])],
            last_user_message=str(payload.get("last_user_message", "")),
            last_assistant_summary=str(payload.get("last_assistant_summary", "")),
        )


@dataclass(frozen=True)
class RoutedCLICommand:
    command: str
    args: Dict[str, Any] = field(default_factory=dict)
    requires_interaction: bool = False


@dataclass(frozen=True)
class PendingInteraction:
    request_id: str
    agent_id: str
    command: str
    session_key: str
