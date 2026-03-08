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
