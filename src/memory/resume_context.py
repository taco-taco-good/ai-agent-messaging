from __future__ import annotations

from agent_messaging.core.models import AgentConfig, MemorySearchRequest
from agent_messaging.memory.search import MemorySearchTool
from agent_messaging.memory.snapshot import SessionSnapshotStore


class ResumeContextAssembler:
    def __init__(
        self,
        snapshot_store: SessionSnapshotStore | None = None,
        *,
        memory_top_k: int = 3,
    ) -> None:
        self.snapshot_store = snapshot_store or SessionSnapshotStore()
        self.memory_top_k = memory_top_k

    def assemble(self, agent: AgentConfig, session_key: str) -> str:
        snapshot = self.snapshot_store.read(agent, session_key)
        if snapshot is None:
            return ""

        lines = [
            "Resume context for this session. Use it as prior working state, not as a user-visible response.",
            "Session key: {0}".format(session_key),
        ]
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
        if snapshot.recent_decisions:
            lines.append("Recent decisions:")
            lines.extend("- {0}".format(item) for item in snapshot.recent_decisions)
        if snapshot.open_questions:
            lines.append("Open questions:")
            lines.extend("- {0}".format(item) for item in snapshot.open_questions)
        if snapshot.next_step:
            lines.append("Next step: {0}".format(snapshot.next_step))
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
