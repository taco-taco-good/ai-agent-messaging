from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from agent_messaging.config.settings import load_settings


class SettingsTests(unittest.TestCase):
    def test_load_settings_reads_yaml_token(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_dir = root / "config"
            config_dir.mkdir()
            personas_dir = config_dir / "personas"
            personas_dir.mkdir()
            (personas_dir / "reviewer.md").write_text(
                "Review code changes and call out correctness issues first.\n",
                encoding="utf-8",
            )
            (config_dir / "agents.yaml").write_text(
                textwrap.dedent(
                    """
                    agents:
                      reviewer:
                        provider: codex
                        discord_token: yaml-token
                        persona_file: ./personas/reviewer.md
                        workspace_dir: ../workspace/reviewer
                        memory_dir: ../memory
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            settings = load_settings(config_dir / "agents.yaml")
            self.assertEqual(settings.agents["reviewer"].discord_token, "yaml-token")
            self.assertEqual(
                settings.agents["reviewer"].persona,
                "Review code changes and call out correctness issues first.",
            )
            self.assertEqual(
                settings.agents["reviewer"].workspace_dir,
                (root / "workspace" / "reviewer").resolve(),
            )
            self.assertEqual(settings.runtime_dir, (root / "runtime").resolve())
            self.assertEqual(settings.tasks_dir, (root / "config" / "tasks").resolve())
            self.assertEqual(settings.task_store_path, (root / "runtime" / "tasks.sqlite").resolve())
