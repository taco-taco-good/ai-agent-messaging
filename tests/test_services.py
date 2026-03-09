from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_messaging.core.errors import InteractionValidationError
from agent_messaging.core.models import AgentConfig, FrontmatterMetadata, ModelOption
from agent_messaging.config.registry import AgentRegistry
from agent_messaging.providers.base import CLIWrapper
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
