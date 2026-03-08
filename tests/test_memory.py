from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from agent_messaging.memory.search import MemorySearchTool
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
