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

    async def start(self) -> None:
        self._alive = True
        self.provider_session_id = "fake-session"

    async def send_user_message(self, message: str):
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

        memory_files = sorted((self.root / "memory" / "reviewer").rglob("conversation_*.md"))
        self.assertEqual(len(memory_files), 1)
        document = memory_files[0].read_text(encoding="utf-8")
        self.assertIn("Greeting", document)
        self.assertIn("reply:hello:alpha", document)

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
