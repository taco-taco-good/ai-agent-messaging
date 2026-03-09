from __future__ import annotations

import logging
from typing import Optional

from agent_messaging.services.command_router import CommandRouter
from agent_messaging.core.interfaces import (
    AgentRegistryProtocol,
    CommandServiceProtocol,
    ConversationServiceProtocol,
    MetadataGeneratorProtocol,
    MemoryWriterProtocol,
    PendingInteractionStoreProtocol,
    ProviderRuntimeProtocol,
    SessionManagerProtocol,
    ToolRuntimeProtocol,
)
from agent_messaging.core.models import FrontmatterMetadata, MemorySearchRequest
from agent_messaging.memory.metadata import MetadataGenerator
from agent_messaging.memory.writer import MemoryWriter
from agent_messaging.runtime.tools import ToolRuntime
from agent_messaging.services.command import CommandService
from agent_messaging.services.conversation import ConversationService
from agent_messaging.runtime.interactions import PendingInteractionStore


logger = logging.getLogger(__name__)


class MessagingService:
    def __init__(
        self,
        registry: AgentRegistryProtocol,
        session_manager: SessionManagerProtocol,
        provider_runtime: ProviderRuntimeProtocol,
        memory_writer: Optional[MemoryWriterProtocol] = None,
        tool_runtime: Optional[ToolRuntimeProtocol] = None,
        metadata_generator: Optional[MetadataGeneratorProtocol] = None,
        command_router: Optional[CommandRouter] = None,
        pending_interactions: Optional[PendingInteractionStoreProtocol] = None,
        conversation_service: Optional[ConversationServiceProtocol] = None,
        command_service: Optional[CommandServiceProtocol] = None,
        chunk_limit: int = 2000,
    ) -> None:
        resolved_memory_writer = memory_writer or MemoryWriter()
        resolved_tool_runtime = tool_runtime or ToolRuntime()
        resolved_metadata_generator = metadata_generator or MetadataGenerator()
        resolved_pending_interactions = pending_interactions or PendingInteractionStore()

        self.registry = registry
        self.session_manager = session_manager
        self.provider_runtime = provider_runtime
        self.tool_runtime = resolved_tool_runtime
        self.pending_interactions = resolved_pending_interactions
        self.conversation_service = conversation_service or ConversationService(
            registry=registry,
            session_manager=session_manager,
            provider_runtime=provider_runtime,
            memory_writer=resolved_memory_writer,
            metadata_generator=resolved_metadata_generator,
            chunk_limit=chunk_limit,
        )
        self.command_service = command_service or CommandService(
            registry=registry,
            session_manager=session_manager,
            provider_runtime=provider_runtime,
            command_router=command_router,
            pending_interactions=resolved_pending_interactions,
            chunk_limit=chunk_limit,
        )

    async def handle_user_message(
        self,
        agent_id: str,
        channel_id: str,
        content: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
        user_name: str = "user",
        metadata: Optional[FrontmatterMetadata] = None,
    ) -> list[str]:
        return await self.conversation_service.handle_user_message(
            agent_id=agent_id,
            channel_id=channel_id,
            content=content,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
            user_name=user_name,
            metadata=metadata,
        )

    async def handle_cli_command(
        self,
        agent_id: str,
        channel_id: str,
        raw_command: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
        interaction_payload: Optional[dict[str, object]] = None,
    ) -> list[str]:
        return await self.command_service.handle_cli_command(
            agent_id=agent_id,
            channel_id=channel_id,
            raw_command=raw_command,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
            interaction_payload=interaction_payload,
        )

    async def handle_new_session(
        self,
        agent_id: str,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> None:
        await self.command_service.handle_new_session(
            agent_id=agent_id,
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )

    async def search_memory(self, agent_id: str, request: MemorySearchRequest):
        logger.info("search_memory", extra={"agent_id": agent_id, "query": request.query})
        return await self.tool_runtime.call("memory_search:{0}".format(agent_id), request)

    def create_pending_interaction(
        self,
        agent_id: str,
        command: str,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ):
        return self.command_service.create_pending_interaction(
            agent_id=agent_id,
            command=command,
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )

    async def available_model_options(
        self,
        agent_id: str,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> list[str]:
        return await self.command_service.available_model_options(
            agent_id=agent_id,
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )

    async def shutdown(self) -> None:
        await self.provider_runtime.shutdown()
        self.command_service.clear()
