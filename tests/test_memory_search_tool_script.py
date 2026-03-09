from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_messaging.memory.writer import MemoryWriter
from agent_messaging.core.models import FrontmatterMetadata


class MemorySearchToolScriptTests(unittest.TestCase):
    def test_script_returns_ranked_json_results(self) -> None:
        script = (
            Path(__file__).resolve().parents[1]
            / "resources"
            / "memory-search"
            / "scripts"
            / "search_memory.py"
        )
        writer = MemoryWriter()
        with tempfile.TemporaryDirectory() as tempdir:
            memory_dir = Path(tempdir) / "memory" / "gemini"
            writer.append_message(
                agent_id="gemini",
                display_name="Geminii",
                memory_dir=memory_dir,
                role="user",
                content="architecture decision and memory lookup",
                participants=("Taco", "Geminii"),
                metadata=FrontmatterMetadata(
                    tags=["architecture"],
                    topic="Architecture Review",
                    summary="Discussed memory lookup behavior.",
                ),
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--memory-dir",
                    str(memory_dir),
                    "--query",
                    "architecture",
                    "--tag",
                    "architecture",
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["topic"], "Architecture Review")
