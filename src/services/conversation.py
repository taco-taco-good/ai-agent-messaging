from __future__ import annotations

import asyncio
import logging
from typing import Optional

from agent_messaging.core.interfaces import (
    AgentRegistryProtocol,
    MetadataGeneratorProtocol,
    MemoryWriterProtocol,
    ProviderRuntimeProtocol,
    ResumeContextAssemblerProtocol,
    SessionManagerProtocol,
    SessionSnapshotStoreProtocol,
)
from agent_messaging.core.models import FrontmatterMetadata
from agent_messaging.memory.resume_context import ResumeContextAssembler
from agent_messaging.memory.snapshot import SessionSnapshotStore
from agent_messaging.memory.metadata import MetadataGenerator
from agent_messaging.memory.writer import MemoryWriter
from agent_messaging.observability.context import log_context
from agent_messaging.providers.base import ProgressCallback, ResponseCallback
from agent_messaging.runtime.transport import chunk_text
from agent_messaging.services.streaming import collect_with_timeout_recovery, reset_session_for_retry


logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(
        self,
        registry: AgentRegistryProtocol,
        session_manager: SessionManagerProtocol,
        provider_runtime: ProviderRuntimeProtocol,
        memory_writer: Optional[MemoryWriterProtocol] = None,
        metadata_generator: Optional[MetadataGeneratorProtocol] = None,
        snapshot_store: Optional[SessionSnapshotStoreProtocol] = None,
        resume_context_assembler: Optional[ResumeContextAssemblerProtocol] = None,
        chunk_limit: int = 2000,
    ) -> None:
        self.registry = registry
        self.session_manager = session_manager
        self.provider_runtime = provider_runtime
        self.memory_writer = memory_writer or MemoryWriter()
        self.metadata_generator = metadata_generator or MetadataGenerator()
        self.snapshot_store = snapshot_store or SessionSnapshotStore()
        self.resume_context_assembler = resume_context_assembler or ResumeContextAssembler(
            snapshot_store=self.snapshot_store
        )
        self.chunk_limit = chunk_limit

    async def handle_user_message(
        self,
        agent_id: str,
        channel_id: str,
        content: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
        user_name: str = "user",
        metadata: Optional[FrontmatterMetadata] = None,
        progress_callback: Optional[ProgressCallback] = None,
        response_callback: Optional[ResponseCallback] = None,
    ) -> list[str]:
        agent = self.registry.get(agent_id)
        logger.info(
            "handle_user_message",
            extra={
                "agent_id": agent_id,
                "channel_id": channel_id,
                "is_dm": is_dm,
                "has_parent_channel": parent_channel_id is not None,
            },
        )
        session_key, wrapper = await self.provider_runtime.ensure_wrapper(
            agent=agent,
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )
        lock = self.provider_runtime.session_lock(agent.agent_id, session_key)
        with log_context(
            session_key=session_key,
            provider=agent.provider,
            provider_session_id=wrapper.provider_session_id or "-",
        ):
            async with lock:
                message_to_send = content
                if not wrapper.has_history():
                    resume_context = await asyncio.to_thread(
                        self.resume_context_assembler.assemble,
                        agent,
                        session_key,
                    )
                    if resume_context:
                        message_to_send = (
                            "{0}\n\nCurrent user message:\n{1}".format(resume_context, content)
                        )
                response, wrapper = await collect_with_timeout_recovery(
                    wrapper=wrapper,
                    stream_factory=lambda current: current.send_user_message(message_to_send),
                    progress_callback=progress_callback,
                    response_callback=response_callback,
                    reset_session=lambda: reset_session_for_retry(
                        logger_extra={
                            "agent_id": agent.agent_id,
                            "channel_id": channel_id,
                            "is_dm": is_dm,
                            "parent_channel_id": parent_channel_id,
                            "provider": agent.provider,
                            "session_key": session_key,
                        },
                        provider_runtime=self.provider_runtime,
                        session_manager=self.session_manager,
                        agent=agent,
                        session_key=session_key,
                        channel_id=channel_id,
                        is_dm=is_dm,
                        parent_channel_id=parent_channel_id,
                    ),
                )
            generated_metadata = metadata or self.metadata_generator.generate(
                user_text=content,
                assistant_text=response,
            )
            participants = (user_name, agent.display_name or agent.agent_id)
            await asyncio.to_thread(
                self.memory_writer.append_message,
                agent_id=agent.agent_id,
                display_name=agent.display_name or agent.agent_id,
                memory_dir=agent.memory_dir,
                role="user",
                content=content,
                participants=participants,
                metadata=generated_metadata,
            )
            await asyncio.to_thread(
                self.memory_writer.append_message,
                agent_id=agent.agent_id,
                display_name=agent.display_name or agent.agent_id,
                memory_dir=agent.memory_dir,
                role="assistant",
                content=response,
                participants=participants,
                metadata=generated_metadata,
            )
            await asyncio.to_thread(
                self.snapshot_store.write,
                agent,
                session_key,
                user_text=content,
                assistant_text=response,
                metadata=generated_metadata,
            )
            await self.session_manager.upsert(
                channel_id=channel_id,
                is_dm=is_dm,
                agent_id=agent.agent_id,
                provider=agent.provider,
                provider_session_id=wrapper.provider_session_id or "",
                current_model=wrapper.current_model or agent.model,
                parent_channel_id=parent_channel_id,
            )
            logger.info("user_message_completed")
            return chunk_text(response, limit=self.chunk_limit)
