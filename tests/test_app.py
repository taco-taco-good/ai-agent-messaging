from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_messaging.application.app import AgentMessagingApp
from agent_messaging.core.errors import InteractionValidationError
from agent_messaging.core.models import AgentConfig, FrontmatterMetadata, MemorySearchRequest
from agent_messaging.config.registry import AgentRegistry
from agent_messaging.providers.base import CLIWrapper
from agent_messaging.runtime.session_manager import SessionManager
from agent_messaging.runtime.session_store import SessionStore


class FakeProvider(CLIWrapper):
    provider_name = "fake"
    supported_commands = ("/help", "/stats", "/model", "/models")
    model_options = ("alpha", "beta")

    def __init__(self, default_model=None):
        super().__init__(default_model=default_model)
        self._alive = False
        self._has_history = False

    async def start(self) -> None:
        self._alive = True
        self.provider_session_id = "fake-session"

    async def send_user_message(self, message: str):
        self._has_history = True
        yield "reply:{0}:{1}".format(message, self.current_model)

    async def send_native_command(self, command: str, args=None):
        args = args or {}
        if command == "/model":
            self.current_model = str(args["model_alias"])
            yield "model:{0}".format(self.current_model)
        elif command == "/models":
            yield "alpha\nbeta"
        else:
            yield "{0}:ok".format(command)

    async def reset_session(self) -> None:
        self._alive = False
        self.provider_session_id = ""

    async def stop(self) -> None:
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive


class AgentMessagingAppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        memory_dir = root / "memory" / "reviewer"
        workspace_dir = root / "workspace" / "reviewer"
        persona_file = root / "config" / "personas" / "reviewer.md"
        persona_file.parent.mkdir(parents=True, exist_ok=True)
        persona_file.write_text("Review code changes and call out correctness issues first.\n", encoding="utf-8")
        source_file = workspace_dir / "src" / "services" / "messaging.py"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("pass\n", encoding="utf-8")

        agent = AgentConfig(
            agent_id="reviewer",
            display_name="Reviewer",
            provider="codex",
            discord_token="token",
            workspace_dir=workspace_dir,
            memory_dir=memory_dir,
            model="alpha",
            persona="Review code changes and call out correctness issues first.",
            persona_file=persona_file,
        )
        registry = AgentRegistry({"reviewer": agent})
        store = SessionStore(root / "runtime" / "sessions.json")
        session_manager = SessionManager(store)
        self.app = AgentMessagingApp(
            registry=registry,
            session_manager=session_manager,
            provider_factory=lambda config, session_key, session_record=None: FakeProvider(
                default_model=(session_record.current_model if session_record else None)
                or config.model
            ),
        )
        self.root = root

    async def test_register_job_delegates_to_job_runtime(self) -> None:
        class FakeTaskRuntime:
            def __init__(self) -> None:
                self.registered = None

            def register_job(self, job) -> None:
                self.registered = job

        fake_runtime = FakeTaskRuntime()
        self.app.job_runtime = fake_runtime
        job = object()

        self.app.register_job(job)

        self.assertIs(fake_runtime.registered, job)

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_user_message_creates_session_and_memory(self) -> None:
        chunks = await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="hello",
            is_dm=False,
            metadata=FrontmatterMetadata(
                tags=["architecture"],
                topic="Greeting",
                summary="A quick hello exchange.",
            ),
        )
        self.assertEqual(chunks, ["reply:hello:alpha"])

        sessions_path = self.root / "runtime" / "sessions.json"
        payload = json.loads(sessions_path.read_text(encoding="utf-8"))
        self.assertIn("discord:channel:123", payload)
        self.assertEqual(payload["discord:channel:123"]["current_model"], "alpha")

        init_doc = self.root / "workspace" / "reviewer" / "AGENTS.md"
        self.assertTrue(init_doc.exists())
        init_doc_text = init_doc.read_text(encoding="utf-8")
        self.assertIn("resources/memory-search/SKILL.md", init_doc_text)
        self.assertIn("resources/memory-search/scripts/search_memory.py", init_doc_text)
        self.assertIn("At the start of a new session", init_doc_text)
        self.assertNotIn("continue prior work or start fresh", init_doc_text)

        memory_files = sorted((self.root / "memory" / "reviewer").rglob("conversation_*.md"))
        self.assertEqual(len(memory_files), 1)
        document = memory_files[0].read_text(encoding="utf-8")
        self.assertIn("Greeting", document)
        self.assertIn("reply:hello:alpha", document)
        snapshot_path = (
            self.root
            / "workspace"
            / "reviewer"
            / ".agent-messaging"
            / "snapshots"
            / "reviewer"
            / "discord_channel_123.json"
        )
        self.assertTrue(snapshot_path.exists())
        snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot_payload["current_task"], "Greeting")
        self.assertEqual(snapshot_payload["next_step"], "reply:hello:alpha")

    async def test_new_app_bootstraps_with_saved_snapshot(self) -> None:
        await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="review src/services/messaging.py",
            is_dm=False,
            metadata=FrontmatterMetadata(
                tags=["architecture", "messaging"],
                topic="Messaging flow review",
                summary="Check how session resume should be assembled.",
            ),
        )
        await self.app.shutdown()

        registry = AgentRegistry({"reviewer": self.app.registry.get("reviewer")})
        session_manager = SessionManager(SessionStore(self.root / "runtime" / "sessions.json"))
        resumed_app = AgentMessagingApp(
            registry=registry,
            session_manager=session_manager,
            provider_factory=lambda config, session_key, session_record=None: FakeProvider(
                default_model=(session_record.current_model if session_record else None)
                or config.model
            ),
        )
        chunks = await resumed_app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="continue",
            is_dm=False,
        )

        self.assertEqual(chunks, ["reply:continue:alpha"])
        await resumed_app.shutdown()

    async def test_new_session_bootstraps_from_latest_agent_snapshot(self) -> None:
        await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="review src/services/messaging.py",
            is_dm=False,
            metadata=FrontmatterMetadata(
                tags=["architecture", "messaging"],
                topic="Messaging flow review",
                summary="Carry the latest task across sessions.",
            ),
        )

        chunks = await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="456",
            content="continue in a new session",
            is_dm=False,
        )

        self.assertEqual(chunks, ["reply:continue in a new session:alpha"])

    async def test_new_session_does_not_resume_unrelated_request(self) -> None:
        await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="review src/services/messaging.py",
            is_dm=False,
            metadata=FrontmatterMetadata(
                tags=["architecture", "messaging"],
                topic="Messaging flow review",
                summary="Carry the latest task across sessions only when relevant.",
            ),
        )

        chunks = await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="456",
            content="write release notes for this week",
            is_dm=False,
        )

        self.assertEqual(chunks, ["reply:write release notes for this week:alpha"])

    async def test_new_session_bootstraps_from_latest_memory_when_snapshot_missing(self) -> None:
        await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="review src/services/messaging.py",
            is_dm=False,
            metadata=FrontmatterMetadata(
                tags=["architecture", "messaging"],
                topic="Messaging flow review",
                summary="Recover from recent memory when session snapshots are gone.",
            ),
        )
        snapshots_dir = (
            self.root
            / "workspace"
            / "reviewer"
            / ".agent-messaging"
            / "snapshots"
            / "reviewer"
        )
        for path in snapshots_dir.glob("*.json"):
            path.unlink()

        chunks = await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="789",
            content="continue after snapshot loss",
            is_dm=False,
        )

        self.assertEqual(chunks, ["reply:continue after snapshot loss:alpha"])

    async def test_new_session_memory_fallback_skips_invalid_utf8_documents(self) -> None:
        await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="review src/services/messaging.py",
            is_dm=False,
            metadata=FrontmatterMetadata(
                tags=["architecture", "messaging"],
                topic="Messaging flow review",
                summary="Recover from the newest valid memory file.",
            ),
        )
        snapshots_dir = (
            self.root
            / "workspace"
            / "reviewer"
            / ".agent-messaging"
            / "snapshots"
            / "reviewer"
        )
        for path in snapshots_dir.glob("*.json"):
            path.unlink()

        corrupted_path = self.root / "memory" / "reviewer" / "9999-12-31" / "conversation_001.md"
        corrupted_path.parent.mkdir(parents=True, exist_ok=True)
        corrupted_path.write_bytes(b"---\ndate: 9999-12-31\n---\nhello\xa1world\n")

        chunks = await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="789",
            content="continue from the previous review",
            is_dm=False,
        )

        self.assertEqual(chunks, ["reply:continue from the previous review:alpha"])

    async def test_shared_workspace_agents_do_not_share_resume_snapshot(self) -> None:
        helper_memory_dir = self.root / "memory" / "helper"
        helper_agent = AgentConfig(
            agent_id="helper",
            display_name="Helper",
            provider="codex",
            discord_token="token",
            workspace_dir=self.root / "workspace" / "reviewer",
            memory_dir=helper_memory_dir,
            model="alpha",
            persona="Summarize and assist.",
            persona_file=self.root / "config" / "personas" / "reviewer.md",
        )
        registry = AgentRegistry(
            {
                "reviewer": self.app.registry.get("reviewer"),
                "helper": helper_agent,
            }
        )
        session_manager = SessionManager(SessionStore(self.root / "runtime" / "sessions.json"))
        multi_app = AgentMessagingApp(
            registry=registry,
            session_manager=session_manager,
            provider_factory=lambda config, session_key, session_record=None: FakeProvider(
                default_model=(session_record.current_model if session_record else None)
                or config.model
            ),
        )
        await multi_app.handle_user_message(
            agent_id="reviewer",
            channel_id="shared",
            content="review src/services/messaging.py",
            is_dm=False,
            metadata=FrontmatterMetadata(
                tags=["review"],
                topic="Reviewer-only task",
                summary="Persist reviewer context only.",
            ),
        )

        chunks = await multi_app.handle_user_message(
            agent_id="helper",
            channel_id="shared",
            content="continue",
            is_dm=False,
        )

        self.assertEqual(chunks, ["reply:continue:alpha"])
        await multi_app.shutdown()

    async def test_corrupted_snapshot_is_ignored_during_bootstrap(self) -> None:
        snapshot_path = (
            self.root
            / "workspace"
            / "reviewer"
            / ".agent-messaging"
            / "snapshots"
            / "reviewer"
            / "discord_channel_123.json"
        )
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text("{invalid json", encoding="utf-8")

        chunks = await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="continue",
            is_dm=False,
        )

        self.assertEqual(chunks, ["reply:continue:alpha"])

    async def test_model_command_updates_session(self) -> None:
        await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="hello",
            is_dm=False,
        )
        pending = self.app.create_pending_interaction(
            agent_id="reviewer",
            command="/model",
            channel_id="123",
            is_dm=False,
        )
        chunks = await self.app.handle_cli_command(
            agent_id="reviewer",
            channel_id="123",
            raw_command="/model",
            is_dm=False,
            interaction_payload={
                "command": "/model",
                "model_alias": "beta",
                "request_id": pending.request_id,
                "session_key": pending.session_key,
            },
        )
        self.assertEqual(chunks, ["model:beta"])

        payload = json.loads(
            (self.root / "runtime" / "sessions.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["discord:channel:123"]["current_model"], "beta")

    async def test_model_command_without_payload_returns_options(self) -> None:
        options = await self.app.handle_cli_command(
            agent_id="reviewer",
            channel_id="123",
            raw_command="/model",
            is_dm=False,
        )
        self.assertEqual(options, ["alpha", "beta"])

    async def test_search_memory_uses_runtime_tool(self) -> None:
        await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="architecture decision",
            is_dm=False,
            metadata=FrontmatterMetadata(
                tags=["architecture"],
                topic="Architecture Review",
                summary="Discussed the memory search runtime boundary.",
            ),
        )
        results = await self.app.search_memory(
            "reviewer",
            MemorySearchRequest(query="architecture", top_k=3, tags=["architecture"]),
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].topic, "Architecture Review")

    async def test_generated_frontmatter_is_not_empty(self) -> None:
        await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="please review the discord session model",
            is_dm=False,
        )
        memory_files = sorted((self.root / "memory" / "reviewer").rglob("conversation_*.md"))
        document = memory_files[0].read_text(encoding="utf-8")
        self.assertIn("topic:", document)
        self.assertNotIn("topic: ''", document)
        self.assertNotIn("tags: []", document)

    async def test_model_command_rejects_mismatched_session_payload(self) -> None:
        with self.assertRaisesRegex(InteractionValidationError, "session mismatch"):
            await self.app.handle_cli_command(
                agent_id="reviewer",
                channel_id="123",
                raw_command="/model",
                is_dm=False,
                interaction_payload={
                    "command": "/model",
                    "model_alias": "beta",
                    "request_id": "req-1",
                    "session_key": "discord:channel:wrong",
                },
            )

    async def test_shutdown_stops_active_wrappers(self) -> None:
        await self.app.handle_user_message(
            agent_id="reviewer",
            channel_id="123",
            content="hello",
            is_dm=False,
        )
        await self.app.shutdown()
        self.assertEqual(self.app._wrappers, {})
