from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_messaging.core.errors import InteractionValidationError
from agent_messaging.core.models import AgentConfig, FrontmatterMetadata, ModelOption
from agent_messaging.config.registry import AgentRegistry
from agent_messaging.providers.base import CLIWrapper, ProviderResponseTimeout
from agent_messaging.services import (
    CommandService,
    CommandRouter,
    ConversationService,
    MessagingService,
)
from agent_messaging.runtime import PendingInteractionStore, ProviderRuntime
from agent_messaging.runtime.session_manager import SessionManager
from agent_messaging.runtime.session_store import SessionStore


class _FakeProvider(CLIWrapper):
    supported_commands = ("/help", "/stats", "/model", "/models")
    model_options = ("alpha", "beta")

    def __init__(self, default_model=None):
        super().__init__(default_model=default_model)
        self._alive = False

    async def start(self) -> None:
        self._alive = True
        self.provider_session_id = "session-1"

    async def send_user_message(self, message: str):
        yield "ok"

    async def send_native_command(self, command: str, args=None):
        if command == "/models":
            yield "alpha\nbeta"
            return
        yield command

    async def reset_session(self) -> None:
        self._alive = False

    async def stop(self) -> None:
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive


class _RotatingModelProvider(_FakeProvider):
    async def send_native_command(self, command: str, args=None):
        args = args or {}
        if command == "/model":
            self.current_model = str(args["model_alias"])
            self.provider_session_id = "session-2"
            yield "model:{0}".format(self.current_model)
            return
        async for chunk in super().send_native_command(command, args):
            yield chunk


class _RotatingConversationProvider(_FakeProvider):
    async def send_user_message(self, message: str):
        self.provider_session_id = "session-2"
        yield "ok"


class _TimeoutOnceProvider(_FakeProvider):
    def __init__(self, default_model=None):
        super().__init__(default_model=default_model)
        self._timed_out = False

    async def send_user_message(self, message: str):
        if not self._timed_out:
            self._timed_out = True
            raise ProviderResponseTimeout("simulated timeout")
        yield "ok-after-retry"


class PendingInteractionStoreTests(unittest.TestCase):
    def test_consume_rejects_wrong_session(self) -> None:
        store = PendingInteractionStore()
        pending = store.create("reviewer", "/model", "discord:channel:1")
        with self.assertRaisesRegex(InteractionValidationError, "session mismatch"):
            store.consume(
                request_id=pending.request_id,
                agent_id="reviewer",
                command="/model",
                session_key="discord:channel:2",
            )


class ProviderRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_wrapper_for_same_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="alpha",
            )
            registry = AgentRegistry({"reviewer": agent})
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            session_manager = SessionManager(store)
            runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=lambda config, session_key, session_record=None: _FakeProvider(
                    default_model=config.model
                ),
            )
            _, first = await runtime.ensure_wrapper(agent, "1", False, None)
            _, second = await runtime.ensure_wrapper(agent, "1", False, None)
            self.assertIs(first, second)

    async def test_startup_can_invalidate_provider_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            manager = SessionManager(store)
            await manager.upsert(
                channel_id="1",
                is_dm=True,
                agent_id="codex-agent",
                provider="codex",
                provider_session_id="thread-1",
                current_model="alpha",
            )
            await manager.upsert(
                channel_id="2",
                is_dm=True,
                agent_id="claude-agent",
                provider="claude",
                provider_session_id="thread-2",
                current_model="beta",
            )

            removed = await manager.invalidate_provider_sessions(
                provider="codex",
                reason="test_cleanup",
            )

            self.assertEqual(removed, ["discord:dm:1"])
            self.assertIsNone(await manager.get(channel_id="1", is_dm=True))
            self.assertIsNotNone(await manager.get(channel_id="2", is_dm=True))


class MessagingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_available_model_options_comes_from_provider_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="alpha",
            )
            registry = AgentRegistry({"reviewer": agent})
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            session_manager = SessionManager(store)
            runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=lambda config, session_key, session_record=None: _FakeProvider(
                    default_model=config.model
                ),
            )
            service = MessagingService(
                registry=registry,
                session_manager=session_manager,
                provider_runtime=runtime,
            )
            self.assertEqual(
                await service.available_model_options(
                    agent_id="reviewer",
                    channel_id="1",
                    is_dm=False,
                ),
                [
                    ModelOption(value="alpha", label="alpha"),
                    ModelOption(value="beta", label="beta"),
                ],
            )


class ConversationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_user_message_returns_provider_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="alpha",
                display_name="Reviewer",
            )
            registry = AgentRegistry({"reviewer": agent})
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            session_manager = SessionManager(store)
            runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=lambda config, session_key, session_record=None: _FakeProvider(
                    default_model=config.model
                ),
            )
            service = ConversationService(
                registry=registry,
                session_manager=session_manager,
                provider_runtime=runtime,
            )
            chunks = await service.handle_user_message(
                agent_id="reviewer",
                channel_id="1",
                content="hello",
                is_dm=False,
                metadata=FrontmatterMetadata(
                    tags=["greeting"],
                    topic="Greeting",
                    summary="Said hello.",
                ),
            )
            self.assertEqual(chunks, ["ok"])

    async def test_handle_user_message_retries_once_after_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="alpha",
                display_name="Reviewer",
            )
            registry = AgentRegistry({"reviewer": agent})
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            session_manager = SessionManager(store)
            attempts = {"count": 0}
            timed_out = {"done": False}

            def _factory(config, session_key, session_record=None):
                attempts["count"] += 1
                provider = _TimeoutOnceProvider(default_model=config.model)
                provider._timed_out = timed_out["done"]
                if not timed_out["done"]:
                    timed_out["done"] = True
                return provider

            runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=_factory,
            )
            service = ConversationService(
                registry=registry,
                session_manager=session_manager,
                provider_runtime=runtime,
            )
            progress = []

            async def _progress(message: str) -> None:
                progress.append(message)

            chunks = await service.handle_user_message(
                agent_id="reviewer",
                channel_id="1",
                content="hello",
                is_dm=False,
                metadata=FrontmatterMetadata(
                    tags=["greeting"],
                    topic="Greeting",
                    summary="Said hello.",
                ),
                progress_callback=_progress,
            )

            self.assertEqual(chunks, ["ok-after-retry"])
            self.assertEqual(attempts["count"], 2)

    async def test_timeout_retry_clears_persisted_provider_session(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="alpha",
                display_name="Reviewer",
            )
            registry = AgentRegistry({"reviewer": agent})
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            session_manager = SessionManager(store)
            await session_manager.upsert(
                channel_id="1",
                is_dm=False,
                agent_id=agent.agent_id,
                provider=agent.provider,
                provider_session_id="stale-thread",
                current_model=agent.model,
            )
            seen_session_ids = []
            timed_out = {"done": False}

            def _factory(config, session_key, session_record=None):
                del config
                del session_key
                seen_session_ids.append(
                    session_record.provider_session_id if session_record is not None else None
                )
                provider = _TimeoutOnceProvider(default_model=agent.model)
                provider._timed_out = timed_out["done"]
                if not timed_out["done"]:
                    timed_out["done"] = True
                return provider

            runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=_factory,
            )
            service = ConversationService(
                registry=registry,
                session_manager=session_manager,
                provider_runtime=runtime,
            )

            chunks = await service.handle_user_message(
                agent_id="reviewer",
                channel_id="1",
                content="hello",
                is_dm=False,
                metadata=FrontmatterMetadata(
                    tags=["greeting"],
                    topic="Greeting",
                    summary="Said hello.",
                ),
            )

            self.assertEqual(chunks, ["ok-after-retry"])
            self.assertEqual(seen_session_ids, ["stale-thread", None])

    async def test_handle_user_message_chunks_long_reply(self) -> None:
        class _LongProvider(_FakeProvider):
            async def send_user_message(self, message: str):
                yield "x" * 5005

        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="alpha",
                display_name="Reviewer",
            )
            registry = AgentRegistry({"reviewer": agent})
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            session_manager = SessionManager(store)
            runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=lambda config, session_key, session_record=None: _LongProvider(
                    default_model=config.model
                ),
            )
            service = ConversationService(
                registry=registry,
                session_manager=session_manager,
                provider_runtime=runtime,
            )

            chunks = await service.handle_user_message(
                agent_id="reviewer",
                channel_id="1",
                content="hello",
                is_dm=False,
                metadata=FrontmatterMetadata(
                    tags=["greeting"],
                    topic="Greeting",
                    summary="Said hello.",
                ),
            )

            self.assertEqual(sum(len(chunk) for chunk in chunks), 5005)
            self.assertTrue(all(len(chunk) <= 2000 for chunk in chunks))

    async def test_streamed_response_is_persisted_as_final_message(self) -> None:
        class _ChunkedProvider(_FakeProvider):
            async def send_user_message(self, message: str):
                yield "hel"
                yield "lo"

        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="alpha",
                display_name="Reviewer",
            )
            registry = AgentRegistry({"reviewer": agent})
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            session_manager = SessionManager(store)
            runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=lambda config, session_key, session_record=None: _ChunkedProvider(
                    default_model=config.model
                ),
            )
            streamed = []

            async def _response(piece: str) -> None:
                streamed.append(piece)

            service = ConversationService(
                registry=registry,
                session_manager=session_manager,
                provider_runtime=runtime,
            )

            chunks = await service.handle_user_message(
                agent_id="reviewer",
                channel_id="1",
                content="hello",
                is_dm=False,
                metadata=FrontmatterMetadata(
                    tags=["greeting"],
                    topic="Greeting",
                    summary="Said hello.",
                ),
                response_callback=_response,
            )

            self.assertEqual(streamed, ["hel", "lo"])
            self.assertEqual(chunks, ["hello"])
            documents = sorted((Path(tempdir) / "memory").rglob("conversation_*.md"))
            self.assertEqual(len(documents), 1)
            self.assertIn("hello", documents[0].read_text(encoding="utf-8"))

    async def test_handle_user_message_persists_updated_provider_session(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="alpha",
                display_name="Reviewer",
            )
            registry = AgentRegistry({"reviewer": agent})
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            session_manager = SessionManager(store)
            runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=lambda config, session_key, session_record=None: _RotatingConversationProvider(
                    default_model=config.model
                ),
            )
            service = ConversationService(
                registry=registry,
                session_manager=session_manager,
                provider_runtime=runtime,
            )

            chunks = await service.handle_user_message(
                agent_id="reviewer",
                channel_id="1",
                content="hello",
                is_dm=False,
                metadata=FrontmatterMetadata(
                    tags=["greeting"],
                    topic="Greeting",
                    summary="Said hello.",
                ),
            )

            self.assertEqual(chunks, ["ok"])
            session = await session_manager.get(channel_id="1", is_dm=False)
            self.assertIsNotNone(session)
            self.assertEqual(session.provider_session_id, "session-2")


class CommandServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_cli_command_supports_model_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="alpha",
            )
            registry = AgentRegistry({"reviewer": agent})
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            session_manager = SessionManager(store)
            runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=lambda config, session_key, session_record=None: _FakeProvider(
                    default_model=config.model
                ),
            )
            service = CommandService(
                registry=registry,
                session_manager=session_manager,
                provider_runtime=runtime,
            )
            options = await service.handle_cli_command(
                agent_id="reviewer",
                channel_id="1",
                raw_command="models",
                is_dm=False,
            )
            self.assertEqual(options, ["alpha", "beta"])

    async def test_model_change_persists_rotated_provider_session(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            agent = AgentConfig(
                agent_id="reviewer",
                provider="claude",
                discord_token="token",
                workspace_dir=Path(tempdir) / "workspace" / "reviewer",
                memory_dir=Path(tempdir) / "memory",
                model="haiku",
            )
            registry = AgentRegistry({"reviewer": agent})
            store = SessionStore(Path(tempdir) / "runtime" / "sessions.json")
            session_manager = SessionManager(store)
            runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=lambda config, session_key, session_record=None: _RotatingModelProvider(
                    default_model=config.model
                ),
            )
            service = CommandService(
                registry=registry,
                session_manager=session_manager,
                provider_runtime=runtime,
            )

            await runtime.ensure_wrapper(agent, "1", False, None)
            chunks = await service.handle_cli_command(
                agent_id="reviewer",
                channel_id="1",
                raw_command="/model",
                is_dm=False,
                interaction_payload={
                    "command": "/model",
                    "model_alias": "sonnet",
                    "session_key": "discord:channel:1",
                },
            )
            self.assertEqual(chunks, ["model:sonnet"])

            session = await session_manager.get(channel_id="1", is_dm=False)
            self.assertIsNotNone(session)
            self.assertEqual(session.current_model, "sonnet")
            self.assertEqual(session.provider_session_id, "session-2")
