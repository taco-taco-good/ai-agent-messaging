from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_messaging.core.models import AgentConfig, SessionRecord, utc_now
from agent_messaging.providers.claude import ClaudeWrapper
from agent_messaging.providers.factory import PROVIDER_BUILDERS, create_provider
from agent_messaging.providers.codex import CodexWrapper
from agent_messaging.providers.gemini import GeminiWrapper


class ProviderFactoryTests(unittest.TestCase):
    def test_provider_registry_contains_supported_builders(self) -> None:
        self.assertIn("claude", PROVIDER_BUILDERS)
        self.assertIn("codex", PROVIDER_BUILDERS)
        self.assertIn("gemini", PROVIDER_BUILDERS)

    def test_create_provider_rehydrates_codex_session_record(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="gpt-5",
            )
            session = SessionRecord(
                agent_id="reviewer",
                provider="codex",
                provider_session_id="session-123",
                current_model="gpt-5-codex",
                last_activity_at=utc_now(),
            )
            wrapper = create_provider(agent, "discord:channel:1", session)
            self.assertIsInstance(wrapper, CodexWrapper)
            self.assertEqual(wrapper.current_model, "gpt-5.3-codex")
            self.assertEqual(wrapper.provider_session_id, "session-123")

    def test_create_provider_rehydrates_claude_session_model(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="claude",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="sonnet",
            )
            session = SessionRecord(
                agent_id="reviewer",
                provider="claude",
                provider_session_id="session-claude",
                current_model="opus-1m",
                last_activity_at=utc_now(),
            )
            wrapper = create_provider(agent, "discord:channel:1", session)
            self.assertIsInstance(wrapper, ClaudeWrapper)
            self.assertEqual(wrapper.current_model, "opus-1m")
            self.assertEqual(wrapper.provider_session_id, "session-claude")
            self.assertEqual(wrapper.warning_timeout, 60.0)
            self.assertEqual(wrapper.hard_timeout, 3600.0)

    def test_create_provider_applies_claude_timeouts_from_agent_config(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="claude",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="opus",
                warning_timeout_seconds=90.0,
                hard_timeout_seconds=3600.0,
            )

            wrapper = create_provider(agent, "discord:channel:1")

            self.assertIsInstance(wrapper, ClaudeWrapper)
            self.assertEqual(wrapper.warning_timeout, 90.0)
            self.assertEqual(wrapper.hard_timeout, 3600.0)

    def test_create_provider_rehydrates_gemini_session_model(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="gemini",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="gemini-2.5-flash",
            )
            session = SessionRecord(
                agent_id="reviewer",
                provider="gemini",
                provider_session_id="session-gemini",
                current_model="auto-gemini-2.5",
                last_activity_at=utc_now(),
            )
            wrapper = create_provider(agent, "discord:channel:1", session)
            self.assertIsInstance(wrapper, GeminiWrapper)
            self.assertEqual(wrapper.current_model, "auto-gemini-2.5")
