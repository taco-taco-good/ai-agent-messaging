from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from agent_messaging.memory.search import MemorySearchTool
from agent_messaging.memory.snapshot import SessionSnapshotStore
from agent_messaging.memory.writer import MemoryWriter
from agent_messaging.core.models import FrontmatterMetadata, MemorySearchRequest


class MemoryWriterTests(unittest.TestCase):
    def test_writer_rolls_over_when_line_limit_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            writer = MemoryWriter(line_limit=3)
            first = writer.append_message(
                agent_id="reviewer",
                display_name="Reviewer",
                memory_dir=root,
                role="user",
                content="one",
                participants=("user", "Reviewer"),
                timestamp=datetime(2026, 3, 7, 12, 0, 0),
            )
            second = writer.append_message(
                agent_id="reviewer",
                display_name="Reviewer",
                memory_dir=root,
                role="assistant",
                content="two",
                participants=("user", "Reviewer"),
                timestamp=datetime(2026, 3, 7, 12, 1, 0),
            )
            self.assertNotEqual(first, second)
            self.assertTrue(second.name.endswith("002.md"))

    def test_search_filters_by_date_and_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            writer = MemoryWriter()
            writer.append_message(
                agent_id="reviewer",
                display_name="Reviewer",
                memory_dir=root,
                role="user",
                content="architecture notes",
                participants=("user", "Reviewer"),
                metadata=FrontmatterMetadata(
                    tags=["architecture"],
                    topic="Architecture",
                    summary="Architecture summary.",
                ),
                timestamp=datetime(2026, 3, 7, 12, 0, 0),
            )

            search = MemorySearchTool(root)
            results = search.search(
                MemorySearchRequest(
                    query="architecture",
                    date_from="2026-03-07",
                    date_to="2026-03-07",
                    tags=["architecture"],
                )
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].topic, "Architecture")

    def test_writer_recovers_from_invalid_utf8_document(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            day_dir = root / "2026-03-07"
            day_dir.mkdir(parents=True, exist_ok=True)
            path = day_dir / "conversation_001.md"
            path.write_bytes(b"---\ndate: 2026-03-07\n---\nhello\xa1world\n")

            writer = MemoryWriter()
            writer.append_message(
                agent_id="reviewer",
                display_name="Reviewer",
                memory_dir=root,
                role="assistant",
                content="two",
                participants=("user", "Reviewer"),
                timestamp=datetime(2026, 3, 7, 12, 2, 0),
            )

            document = path.read_text(encoding="utf-8")
            self.assertIn("two", document)

    def test_writer_preserves_user_then_assistant_order(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            writer = MemoryWriter()
            writer.append_message(
                agent_id="reviewer",
                display_name="Reviewer",
                memory_dir=root,
                role="user",
                content="one",
                participants=("user", "Reviewer"),
                timestamp=datetime(2026, 3, 7, 12, 0, 0),
            )
            writer.append_message(
                agent_id="reviewer",
                display_name="Reviewer",
                memory_dir=root,
                role="assistant",
                content="two",
                participants=("user", "Reviewer"),
                timestamp=datetime(2026, 3, 7, 12, 1, 0),
            )

            document = (root / "2026-03-07" / "conversation_001.md").read_text(encoding="utf-8")
            self.assertLess(document.find("one"), document.find("two"))

    def test_writer_persists_job_run_under_job_scoped_path(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            writer = MemoryWriter()

            path = writer.write_job_run(
                agent_id="codex",
                display_name="codex",
                memory_dir=root,
                job_id="daily_ai_briefing",
                run_id=7,
                content="briefing body",
                status="succeeded",
                metadata=FrontmatterMetadata(
                    tags=["job", "briefing"],
                    topic="daily ai briefing",
                    summary="Generated daily briefing.",
                ),
                timestamp=datetime(2026, 3, 9, 7, 0, 0),
            )

            self.assertEqual(
                path,
                root / "jobs" / "daily_ai_briefing" / "2026-03-09" / "run_001.md",
            )
            document = path.read_text(encoding="utf-8")
            self.assertIn("record_type: job_run", document)
            self.assertIn("run_id: 7", document)
            self.assertIn("briefing body", document)

    def test_snapshot_store_round_trips_resume_state(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            workspace_dir = root / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            touched = workspace_dir / "src" / "services" / "messaging.py"
            touched.parent.mkdir(parents=True, exist_ok=True)
            touched.write_text("pass\n", encoding="utf-8")
            store = SessionSnapshotStore()
            agent = type("Agent", (), {"agent_id": "reviewer", "workspace_dir": workspace_dir})()

            store.write(
                agent,
                "discord:channel:123",
                user_text="Please inspect src/services/messaging.py\nWhat should change?",
                assistant_text="- Adjust the bootstrap flow.\n- Keep it deterministic.",
                metadata=FrontmatterMetadata(
                    tags=["resume"],
                    topic="Session resume",
                    summary="Persist a compact resume snapshot.",
                ),
            )

            snapshot = store.read(agent, "discord:channel:123")

            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.current_task, "Session resume")
            self.assertEqual(snapshot.activity_type, "review")
            self.assertEqual(snapshot.work_status, "in_progress")
            self.assertEqual(snapshot.current_artifact, "Referenced artifacts: src/services/messaging.py")
            self.assertEqual(snapshot.latest_conclusion, "Persist a compact resume snapshot.")
            self.assertEqual(snapshot.evidence_basis, ["code_inspection"])
            self.assertEqual(snapshot.artifacts, ["src/services/messaging.py"])
            self.assertEqual(snapshot.tags, ["resume"])
            self.assertIn("src/services/messaging.py", snapshot.touched_files)
            self.assertEqual(snapshot.open_questions, ["What should change?"])

    def test_snapshot_store_captures_research_artifacts_without_code_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            workspace_dir = root / "workspace"
            docs_path = workspace_dir / "docs" / "git.md"
            docs_path.parent.mkdir(parents=True, exist_ok=True)
            docs_path.write_text("# Git\n", encoding="utf-8")
            store = SessionSnapshotStore()
            agent = type("Agent", (), {"agent_id": "researcher", "workspace_dir": workspace_dir})()

            store.write(
                agent,
                "discord:channel:456",
                user_text="docs/git.md 기준으로 구조 설계를 조사해줘",
                assistant_text="- 현재 규칙을 정리했습니다.\n- 다음은 snapshot schema 비교입니다.",
                metadata=FrontmatterMetadata(
                    tags=["snapshot", "docs"],
                    topic="Snapshot schema research",
                    summary="Compare research-friendly resume fields.",
                ),
            )

            snapshot = store.read(agent, "discord:channel:456")

            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.activity_type, "design")
            self.assertEqual(snapshot.current_artifact, "Referenced artifacts: docs/git.md, project docs")
            self.assertEqual(snapshot.evidence_basis, ["code_inspection", "document_review"])
            self.assertEqual(snapshot.artifacts, ["docs/git.md", "project docs"])

    def test_snapshot_store_separates_agents_with_shared_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            workspace_dir = Path(tempdir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            store = SessionSnapshotStore()
            reviewer = type("Agent", (), {"agent_id": "reviewer", "workspace_dir": workspace_dir})()
            helper = type("Agent", (), {"agent_id": "helper", "workspace_dir": workspace_dir})()

            reviewer_path = store.write(
                reviewer,
                "discord:channel:shared",
                user_text="review this",
                assistant_text="done",
            )
            helper_path = store.write(
                helper,
                "discord:channel:shared",
                user_text="summarize this",
                assistant_text="done",
            )

            self.assertNotEqual(reviewer_path, helper_path)
            self.assertIn("/reviewer/", str(reviewer_path))
            self.assertIn("/helper/", str(helper_path))

    def test_snapshot_store_reads_latest_agent_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            workspace_dir = Path(tempdir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            store = SessionSnapshotStore()
            agent = type("Agent", (), {"agent_id": "reviewer", "workspace_dir": workspace_dir})()

            store.write(
                agent,
                "discord:channel:123",
                user_text="review the bootstrap flow",
                assistant_text="first response",
                metadata=FrontmatterMetadata(
                    tags=["bootstrap"],
                    topic="Bootstrap review",
                    summary="Initial review state.",
                ),
            )
            store.write(
                agent,
                "discord:channel:456",
                user_text="continue with runtime refactor",
                assistant_text="second response",
                metadata=FrontmatterMetadata(
                    tags=["runtime"],
                    topic="Runtime refactor",
                    summary="Latest review state.",
                ),
            )

            snapshot = store.read_latest(agent, exclude_session_key="discord:channel:789")

            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.session_key, "discord:channel:456")
            self.assertEqual(snapshot.current_task, "Runtime refactor")

    def test_snapshot_store_ignores_corrupted_json(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            workspace_dir = Path(tempdir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            store = SessionSnapshotStore()
            agent = type("Agent", (), {"agent_id": "reviewer", "workspace_dir": workspace_dir})()
            path = (
                workspace_dir
                / ".agent-messaging"
                / "snapshots"
                / "reviewer"
                / "discord_channel_123.json"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{invalid json", encoding="utf-8")

            snapshot = store.read(agent, "discord:channel:123")

            self.assertIsNone(snapshot)
