from __future__ import annotations

from pathlib import Path
import re

from agent_messaging.core.models import AgentConfig, MemorySearchRequest
from agent_messaging.memory.frontmatter import split_frontmatter
from agent_messaging.memory.search import MemorySearchTool
from agent_messaging.memory.snapshot import SessionSnapshotStore

_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]{1,}")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "review",
    "task",
    "work",
    "agent",
    "session",
    "message",
    "continue",
    "continuing",
    "resume",
    "latest",
    "saved",
    "context",
    "after",
    "before",
    "into",
    "new",
    "please",
    "help",
    "need",
    "write",
    "start",
    "fresh",
}
_CONTINUE_MARKERS = (
    "continue",
    "continuing",
    "resume",
    "pick up",
    "pick this up",
    "carry on",
    "keep going",
    "go on",
    "이어",
    "이어서",
    "계속",
    "마저",
    "다시 이어",
)


class ResumeContextAssembler:
    def __init__(
        self,
        snapshot_store: SessionSnapshotStore | None = None,
        *,
        memory_top_k: int = 3,
    ) -> None:
        self.snapshot_store = snapshot_store or SessionSnapshotStore()
        self.memory_top_k = memory_top_k

    def assemble(self, agent: AgentConfig, session_key: str, user_text: str) -> str:
        snapshot = self.snapshot_store.read(agent, session_key)
        if snapshot is not None:
            return self._render_snapshot_context(agent, session_key, snapshot, scope="session")

        snapshot = self.snapshot_store.read_latest(agent, exclude_session_key=session_key)
        if snapshot is not None and self._should_resume_from_snapshot(user_text, snapshot):
            return self._render_snapshot_context(agent, session_key, snapshot, scope="agent")
        return self._render_recent_memory_context(agent, session_key, user_text)

    def _render_snapshot_context(
        self,
        agent: AgentConfig,
        session_key: str,
        snapshot,
        *,
        scope: str,
    ) -> str:
        lines = [
            (
                "Resume context for this session. Use it as prior working state, not as a user-visible response."
                if scope == "session"
                else "Resume context from the latest saved agent work state. Use it as prior working state, not as a user-visible response."
            ),
            "Current session key: {0}".format(session_key),
        ]
        if scope != "session":
            lines.append("Source session key: {0}".format(snapshot.session_key))
        if snapshot.updated_at.tzinfo is not None:
            lines.append(
                "Snapshot updated at: {0}".format(
                    snapshot.updated_at.astimezone().isoformat(timespec="seconds")
                )
            )
        if snapshot.current_task:
            lines.append("Current task: {0}".format(snapshot.current_task))
        if snapshot.summary:
            lines.append("Summary: {0}".format(snapshot.summary))
        if snapshot.activity_type:
            lines.append("Activity type: {0}".format(snapshot.activity_type))
        if snapshot.work_status:
            lines.append("Work status: {0}".format(snapshot.work_status))
        if snapshot.current_artifact:
            lines.append("Current artifact: {0}".format(snapshot.current_artifact))
        if snapshot.latest_conclusion:
            lines.append("Latest conclusion: {0}".format(snapshot.latest_conclusion))
        if snapshot.evidence_basis:
            lines.append("Evidence basis: {0}".format(", ".join(snapshot.evidence_basis)))
        if snapshot.last_user_message:
            lines.append("Last user message: {0}".format(snapshot.last_user_message))
        if snapshot.last_assistant_summary:
            lines.append(
                "Last assistant response summary: {0}".format(snapshot.last_assistant_summary)
            )
        if snapshot.recent_decisions:
            lines.append("Recent decisions:")
            lines.extend("- {0}".format(item) for item in snapshot.recent_decisions)
        if snapshot.open_questions:
            lines.append("Open questions:")
            lines.extend("- {0}".format(item) for item in snapshot.open_questions)
        if snapshot.next_step:
            lines.append("Next step: {0}".format(snapshot.next_step))
        if snapshot.artifacts:
            lines.append("Artifacts:")
            lines.extend("- {0}".format(item) for item in snapshot.artifacts)
        if snapshot.touched_files:
            lines.append("Touched files:")
            lines.extend("- {0}".format(path) for path in snapshot.touched_files)

        for result in self._search_related_memory(agent, snapshot):
            lines.append(
                "- Memory {0} | topic={1} | summary={2}".format(
                    result.date,
                    result.topic or "-",
                    result.summary or result.snippet or "-",
                )
            )

        return "\n".join(lines).strip()

    def _render_recent_memory_context(
        self,
        agent: AgentConfig,
        session_key: str,
        user_text: str,
    ) -> str:
        latest_memory = self._latest_memory_record(agent.memory_dir)
        if latest_memory is None:
            return ""
        metadata, last_user_message, assistant_summary = latest_memory
        if not self._should_resume_from_memory(user_text, metadata, last_user_message, assistant_summary):
            return ""
        topic = str(metadata.get("topic", "")).strip()
        summary = str(metadata.get("summary", "")).strip()
        tags = [str(tag).strip() for tag in metadata.get("tags", []) if str(tag).strip()]
        date = str(metadata.get("date", "")).strip()

        lines = [
            "Resume context from the latest saved agent memory. Use it as prior working state, not as a user-visible response.",
            "Current session key: {0}".format(session_key),
        ]
        if date:
            lines.append("Memory date: {0}".format(date))
        if topic:
            lines.append("Current task: {0}".format(topic))
        if summary:
            lines.append("Summary: {0}".format(summary))
        if tags:
            lines.append("Tags: {0}".format(", ".join(tags[:5])))
        if last_user_message:
            lines.append("Last user message: {0}".format(last_user_message))
        if assistant_summary:
            lines.append("Latest assistant summary: {0}".format(assistant_summary))
        return "\n".join(lines).strip()

    def _search_related_memory(self, agent: AgentConfig, snapshot):
        query_parts = []
        if snapshot.topic:
            query_parts.append(snapshot.topic)
        if snapshot.current_task and snapshot.current_task != snapshot.topic:
            query_parts.append(snapshot.current_task)
        query_parts.extend(snapshot.tags[:3])
        query = " ".join(part.strip() for part in query_parts if part.strip())
        if not query:
            return []
        tool = MemorySearchTool(agent.memory_dir)
        return tool.search(
            MemorySearchRequest(
                query=query,
                top_k=self.memory_top_k,
                tags=snapshot.tags[:3],
            )
        )

    def _latest_memory_record(self, memory_dir: Path) -> tuple[dict, str, str] | None:
        candidates = sorted(
            (
                path
                for path in memory_dir.rglob("conversation_*.md")
                if "jobs" not in path.parts
            ),
            reverse=True,
        )
        for path in candidates:
            try:
                metadata, body = split_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            last_user_message = self._last_role_entry(body, "user")
            assistant_summary = self._last_role_entry(body, "assistant")
            if metadata or last_user_message or assistant_summary:
                return metadata, last_user_message, assistant_summary
        return None

    def _last_role_entry(self, body: str, role: str) -> str:
        sections = []
        current_role = ""
        current_lines: list[str] = []
        for line in body.splitlines():
            if line.startswith("## "):
                if current_role == role and current_lines:
                    sections.append(" ".join(part.strip() for part in current_lines if part.strip()))
                current_lines = []
                current_role = role if line.strip().endswith(" {0}".format(role)) else ""
                continue
            if current_role == role:
                current_lines.append(line)
        if current_role == role and current_lines:
            sections.append(" ".join(part.strip() for part in current_lines if part.strip()))
        if not sections:
            return ""
        summary = sections[-1].strip()
        if len(summary) <= 300:
            return summary
        return summary[:297].rstrip() + "..."

    def _should_resume_from_snapshot(self, user_text: str, snapshot) -> bool:
        context_parts = [
            snapshot.current_task,
            snapshot.topic,
            snapshot.summary,
            snapshot.current_artifact,
            snapshot.latest_conclusion,
            snapshot.next_step,
            snapshot.last_user_message,
            snapshot.last_assistant_summary,
            " ".join(snapshot.tags),
            " ".join(snapshot.touched_files),
            " ".join(snapshot.artifacts),
        ]
        return self._should_resume(user_text, context_parts)

    def _should_resume_from_memory(
        self,
        user_text: str,
        metadata: dict,
        last_user_message: str,
        assistant_summary: str,
    ) -> bool:
        context_parts = [
            str(metadata.get("topic", "")),
            str(metadata.get("summary", "")),
            " ".join(str(tag) for tag in metadata.get("tags", [])),
            last_user_message,
            assistant_summary,
        ]
        return self._should_resume(user_text, context_parts)

    def _should_resume(self, user_text: str, context_parts: list[str]) -> bool:
        normalized_user_text = user_text.lower()
        if any(marker in normalized_user_text for marker in _CONTINUE_MARKERS):
            return True
        user_tokens = self._meaningful_tokens(user_text)
        if not user_tokens:
            return False
        context_tokens = set()
        for part in context_parts:
            context_tokens.update(self._meaningful_tokens(part))
        overlap = user_tokens.intersection(context_tokens)
        if len(overlap) >= 2:
            return True
        return any(token in overlap for token in user_tokens if "/" in token or "." in token)

    def _meaningful_tokens(self, text: str) -> set[str]:
        tokens = set()
        for token in _TOKEN_PATTERN.findall(text.lower()):
            if len(token) < 3:
                continue
            if token in _STOPWORDS:
                continue
            tokens.add(token)
        return tokens
