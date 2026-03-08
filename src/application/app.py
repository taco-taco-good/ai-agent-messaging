from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from agent_messaging.config.settings import load_settings
from agent_messaging.core.interfaces import (
    AgentRegistryProtocol,
    MetadataGeneratorProtocol,
    ProviderFactoryProtocol,
    ToolRuntimeProtocol,
)
from agent_messaging.core.registry import AgentRegistry
from agent_messaging.memory.init_docs import materialize_init_doc
from agent_messaging.memory.metadata import MetadataGenerator
from agent_messaging.memory.search import MemorySearchTool
from agent_messaging.memory.writer import MemoryWriter
from agent_messaging.observability.logging import setup_logging
from agent_messaging.providers.factory import create_provider
from agent_messaging.runtime.session_manager import SessionManager
from agent_messaging.runtime.session_store import SessionStore
from agent_messaging.runtime.tools import ToolRuntime
from agent_messaging.services import MessagingService, PendingInteractionStore, ProviderRuntime


logger = logging.getLogger(__name__)


class AgentMessagingApp:
    def __init__(
        self,
        service: Optional[MessagingService] = None,
        *,
        registry: Optional[AgentRegistryProtocol] = None,
        session_manager: Optional[SessionManager] = None,
        provider_factory: Optional[ProviderFactoryProtocol] = None,
        memory_writer: Optional[MemoryWriter] = None,
        tool_runtime: Optional[ToolRuntimeProtocol] = None,
        metadata_generator: Optional[MetadataGeneratorProtocol] = None,
        chunk_limit: int = 2000,
    ) -> None:
        if service is None:
            if registry is None or session_manager is None or provider_factory is None:
                raise TypeError(
                    "AgentMessagingApp requires either `service` or "
                    "`registry`, `session_manager`, and `provider_factory`."
                )
            resolved_tool_runtime = tool_runtime or ToolRuntime()
            self._initialize_agents(registry=registry, tool_runtime=resolved_tool_runtime)
            provider_runtime = ProviderRuntime(
                session_manager=session_manager,
                provider_factory=provider_factory,
            )
            service = MessagingService(
                registry=registry,
                session_manager=session_manager,
                provider_runtime=provider_runtime,
                memory_writer=memory_writer,
                tool_runtime=resolved_tool_runtime,
                metadata_generator=metadata_generator,
                pending_interactions=PendingInteractionStore(),
                chunk_limit=chunk_limit,
            )
        self.service = service
        self.registry = service.registry
        self.session_manager = service.session_manager
        self.provider_factory = service.provider_runtime.provider_factory
        self._provider_runtime = service.provider_runtime
        self._pending_interactions = service.pending_interactions

    async def handle_user_message(self, *args, **kwargs):
        return await self.service.handle_user_message(*args, **kwargs)

    async def handle_new_session(self, *args, **kwargs):
        return await self.service.handle_new_session(*args, **kwargs)

    async def handle_cli_command(self, *args, **kwargs):
        return await self.service.handle_cli_command(*args, **kwargs)

    async def search_memory(self, *args, **kwargs):
        return await self.service.search_memory(*args, **kwargs)

    def create_pending_interaction(self, *args, **kwargs):
        return self.service.create_pending_interaction(*args, **kwargs)

    async def available_model_options(self, *args, **kwargs):
        return await self.service.available_model_options(*args, **kwargs)

    async def shutdown(self) -> None:
        await self.service.shutdown()

    @property
    def _wrappers(self):
        return self._provider_runtime._wrappers

    @staticmethod
    def _initialize_agents(registry: AgentRegistry, tool_runtime: ToolRuntimeProtocol) -> None:
        for agent in registry.all():
            materialize_init_doc(agent)
            logger.info(
                "agent_initialized",
                extra={"agent_id": agent.agent_id, "provider": agent.provider},
            )
            tool_runtime.register(
                "memory_search:{0}".format(agent.agent_id),
                lambda request, tool=MemorySearchTool(agent.memory_dir): asyncio.to_thread(
                    tool.search, request
                ),
            )


def build_app(config_path: Path) -> AgentMessagingApp:
    settings = load_settings(config_path=config_path)
    registry = AgentRegistry(settings.agents)
    session_store = SessionStore(settings.runtime_dir / "sessions.json")
    session_manager = SessionManager(session_store)
    tool_runtime = ToolRuntime()
    AgentMessagingApp._initialize_agents(registry=registry, tool_runtime=tool_runtime)
    provider_runtime = ProviderRuntime(
        session_manager=session_manager,
        provider_factory=create_provider,
    )
    service = MessagingService(
        registry=registry,
        session_manager=session_manager,
        provider_runtime=provider_runtime,
        tool_runtime=tool_runtime,
        pending_interactions=PendingInteractionStore(),
    )
    return AgentMessagingApp(service)


def main(argv: Optional[List[str]] = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="AI agent messaging MVP bootstrap.")
    parser.add_argument(
        "--config",
        default="config/agents.yaml",
        help="Path to the agent YAML config.",
    )
    args = parser.parse_args(argv)
    app = build_app(Path(args.config))
    from agent_messaging.gateway.discord import DiscordGatewayUnavailable, run_discord_gateways

    logger.info("startup", extra={"agent_count": len(app.registry.all())})
    try:
        asyncio.run(run_discord_gateways(app))
    except DiscordGatewayUnavailable as exc:
        logger.error(
            "discord_gateway_unavailable",
            extra={"error": str(exc), "error_code": getattr(exc, "error_code", "internal_error")},
        )
        return 1
    except KeyboardInterrupt:
        logger.info("shutdown_requested")
        return 130
    except Exception as exc:
        logger.exception(
            "startup_failed",
            extra={"error": str(exc), "error_code": getattr(exc, "error_code", "internal_error")},
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
