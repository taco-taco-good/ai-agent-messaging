from __future__ import annotations

import logging
import json
from json import JSONDecodeError
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from agent_messaging.core.models import AgentConfig, FrontmatterMetadata, SessionSnapshot, utc_now


logger = logging.getLogger(__name__)
_SESSION_KEY_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")
_RELATIVE_PATH_PATTERN = re.compile(r"(?:^|[\s`(])((?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+)")


class SessionSnapshotStore:
    def write(
        self,
        agent: AgentConfig,
        session_key: str,
        *,
        user_text: str,
        assistant_text: str,
        metadata: Optional[FrontmatterMetadata] = None,
    ) -> Path:
        snapshot = SessionSnapshot(
            session_key=session_key,
            updated_at=utc_now(),
            current_task=_current_task(user_text=user_text, metadata=metadata),
            topic=metadata.topic if metadata is not None else "",
            summary=metadata.summary if metadata is not None else "",
            tags=list(metadata.tags) if metadata is not None else [],
            recent_decisions=_recent_decisions(assistant_text, metadata),
            open_questions=_open_questions(user_text),
            next_step=_next_step(assistant_text),
            touched_files=_touched_files(agent.workspace_dir, user_text, assistant_text),
            last_user_message=_truncate(user_text, 500),
            last_assistant_summary=_truncate(assistant_text, 500),
        )
        path = self._path_for(agent, session_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.stem + ".",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_file.write(json.dumps(snapshot.to_dict(), ensure_ascii=True, indent=2))
            tmp_path = Path(tmp_file.name)
        os.replace(tmp_path, path)
        return path

    def read(self, agent: AgentConfig, session_key: str) -> SessionSnapshot | None:
        path = self._path_for(agent, session_key)
        if not path.exists():
            return None
        return self._read_path(path, agent=agent, session_key=session_key)

    def read_latest(
        self,
        agent: AgentConfig,
        *,
        exclude_session_key: str | None = None,
    ) -> SessionSnapshot | None:
        snapshots_dir = agent.workspace_dir / ".agent-messaging" / "snapshots" / self._safe_agent_id(agent)
        if not snapshots_dir.exists():
            return None

        latest: SessionSnapshot | None = None
        for path in sorted(snapshots_dir.glob("*.json")):
            snapshot = self._read_path(path, agent=agent, session_key=path.stem)
            if snapshot is None:
                continue
            if exclude_session_key is not None and snapshot.session_key == exclude_session_key:
                continue
            if latest is None or snapshot.updated_at > latest.updated_at:
                latest = snapshot
        return latest

    def _read_path(
        self,
        path: Path,
        *,
        agent: AgentConfig,
        session_key: str,
    ) -> SessionSnapshot | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return SessionSnapshot.from_dict(payload)
        except (JSONDecodeError, KeyError, TypeError, ValueError, OSError, UnicodeDecodeError) as exc:
            logger.warning(
                "snapshot_read_failed",
                extra={
                    "agent_id": getattr(agent, "agent_id", "unknown"),
                    "path": str(path),
                    "session_key": session_key,
                    "error": str(exc),
                },
            )
            return None

    def _path_for(self, agent: AgentConfig, session_key: str) -> Path:
        safe_agent = self._safe_agent_id(agent)
        safe_key = _SESSION_KEY_SAFE.sub("_", session_key).strip("_") or "default"
        return (
            agent.workspace_dir
            / ".agent-messaging"
            / "snapshots"
            / safe_agent
            / "{0}.json".format(safe_key)
        )

    def _safe_agent_id(self, agent: AgentConfig) -> str:
        return _SESSION_KEY_SAFE.sub("_", agent.agent_id).strip("_") or "agent"


def _current_task(*, user_text: str, metadata: Optional[FrontmatterMetadata]) -> str:
    if metadata is not None and metadata.topic:
        return metadata.topic
    return _first_meaningful_line(user_text)


def _recent_decisions(assistant_text: str, metadata: Optional[FrontmatterMetadata]) -> list[str]:
    decisions = []
    if metadata is not None and metadata.summary:
        decisions.append(_truncate(metadata.summary, 180))
    for line in assistant_text.splitlines():
        normalized = line.strip(" -*")
        if not normalized:
            continue
        decisions.append(_truncate(normalized, 180))
        if len(decisions) >= 3:
            break
    return _dedupe(decisions)[:3]


def _open_questions(user_text: str) -> list[str]:
    questions = []
    for line in user_text.splitlines():
        stripped = line.strip()
        if stripped.endswith("?"):
            questions.append(_truncate(stripped, 180))
        if len(questions) >= 3:
            break
    return questions


def _next_step(assistant_text: str) -> str:
    for line in assistant_text.splitlines():
        stripped = line.strip(" -*")
        if stripped:
            return _truncate(stripped, 180)
    return ""


def _touched_files(workspace_dir: Path, user_text: str, assistant_text: str) -> list[str]:
    matches = []
    for source in (user_text, assistant_text):
        for match in _RELATIVE_PATH_PATTERN.finditer(source):
            candidate = match.group(1).strip()
            if not candidate:
                continue
            path = (workspace_dir / candidate).resolve()
            if path.exists() and path.is_file():
                try:
                    relative = path.relative_to(workspace_dir.resolve())
                except ValueError:
                    continue
                matches.append(str(relative))
    return _dedupe(matches)[:5]


def _first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return _truncate(stripped, 180)
    return ""


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _truncate(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."
