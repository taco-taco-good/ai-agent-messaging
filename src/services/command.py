from __future__ import annotations

import logging
from typing import Optional

from agent_messaging.services.command_router import CommandRouter
from agent_messaging.core.errors import InteractionValidationError
from agent_messaging.core.interfaces import (
    AgentRegistryProtocol,
    PendingInteractionStoreProtocol,
    ProviderRuntimeProtocol,
    SessionManagerProtocol,
)
from agent_messaging.core.models import ModelOption
from agent_messaging.runtime.transport import chunk_text
from agent_messaging.observability.context import log_context
from agent_messaging.providers.base import ProviderResponseTimeout
from agent_messaging.runtime.interactions import PendingInteractionStore


logger = logging.getLogger(__name__)


class CommandService:
    def __init__(
        self,
        registry: AgentRegistryProtocol,
        session_manager: SessionManagerProtocol,
        provider_runtime: ProviderRuntimeProtocol,
        command_router: Optional[CommandRouter] = None,
        pending_interactions: Optional[PendingInteractionStoreProtocol] = None,
        chunk_limit: int = 2000,
    ) -> None:
        self.registry = registry
        self.session_manager = session_manager
        self.provider_runtime = provider_runtime
        self.command_router = command_router or CommandRouter()
        self.pending_interactions = pending_interactions or PendingInteractionStore()
        self.chunk_limit = chunk_limit

    async def handle_cli_command(
        self,
        agent_id: str,
        channel_id: str,
        raw_command: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
        interaction_payload: Optional[dict[str, object]] = None,
        progress_callback=None,
    ) -> list[str]:
        expected_session_key = self.session_manager.session_scope_key(
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )
        logger.info(
            "handle_cli_command",
            extra={
                "agent_id": agent_id,
                "channel_id": channel_id,
                "command": raw_command.strip(),
                "session_key": expected_session_key,
            },
        )
        self._validate_interaction_payload(
            agent_id=agent_id,
            raw_command=raw_command,
            expected_session_key=expected_session_key,
            interaction_payload=interaction_payload,
        )
        routed = self.command_router.parse_cli_command(raw_command, interaction_payload)
        agent = self.registry.get(agent_id)
        with log_context(
            session_key=expected_session_key,
            provider=agent.provider,
            command=routed.command,
        ):
            if routed.requires_interaction:
                model_options = await self.provider_runtime.options_for(
                    agent=agent,
                    channel_id=channel_id,
                    is_dm=is_dm,
                    parent_channel_id=parent_channel_id,
                )
                logger.info("cli_command_requires_interaction")
                return (
                    [option.label for option in model_options]
                    or ["This provider has no declared model options."]
                )
            if routed.command == "/models":
                model_options = await self.provider_runtime.options_for(
                    agent=agent,
                    channel_id=channel_id,
                    is_dm=is_dm,
                    parent_channel_id=parent_channel_id,
                )
                return (
                    [option.label for option in model_options]
                    or ["This provider has no declared model options."]
                )

            _, wrapper = await self.provider_runtime.ensure_wrapper(
                agent=agent,
                channel_id=channel_id,
                is_dm=is_dm,
                parent_channel_id=parent_channel_id,
            )
            lock = self.provider_runtime.session_lock(agent.agent_id, expected_session_key)
            with log_context(provider_session_id=wrapper.provider_session_id or "-"):
                async with lock:
                    response, wrapper = await self._collect_with_timeout_recovery(
                        agent_id=agent.agent_id,
                        session_key=expected_session_key,
                        wrapper=wrapper,
                        stream_factory=lambda current: current.send_native_command(
                            routed.command, routed.args
                        ),
                        progress_callback=progress_callback,
                        restart_factory=lambda: self.provider_runtime.ensure_wrapper(
                            agent=agent,
                            channel_id=channel_id,
                            is_dm=is_dm,
                            parent_channel_id=parent_channel_id,
                        ),
                    )
                if routed.command == "/model" and routed.args.get("model_alias"):
                    await self.session_manager.upsert(
                        channel_id=channel_id,
                        is_dm=is_dm,
                        agent_id=agent.agent_id,
                        provider=agent.provider,
                        provider_session_id=wrapper.provider_session_id or "",
                        current_model=wrapper.current_model or str(routed.args["model_alias"]),
                        parent_channel_id=parent_channel_id,
                    )
                    logger.info(
                        "model_updated",
                        extra={
                            "model": str(routed.args["model_alias"]),
                            "provider_session_id": wrapper.provider_session_id or "-",
                        },
                    )
                return chunk_text(response, limit=self.chunk_limit)

    async def handle_new_session(
        self,
        agent_id: str,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> None:
        session_key = self.session_manager.session_scope_key(
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )
        logger.info(
            "reset_session",
            extra={"agent_id": agent_id, "session_key": session_key},
        )
        with log_context(session_key=session_key, agent_id=agent_id):
            await self.provider_runtime.stop_session(agent_id=agent_id, session_key=session_key)
            await self.session_manager.clear(
                channel_id=channel_id,
                is_dm=is_dm,
                parent_channel_id=parent_channel_id,
            )

    def create_pending_interaction(
        self,
        agent_id: str,
        command: str,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ):
        session_key = self.session_manager.session_scope_key(
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )
        return self.pending_interactions.create(
            agent_id=agent_id,
            command=command,
            session_key=session_key,
        )

    async def available_model_options(
        self,
        agent_id: str,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> list[ModelOption]:
        agent = self.registry.get(agent_id)
        return await self.provider_runtime.options_for(
            agent=agent,
            channel_id=channel_id,
            is_dm=is_dm,
            parent_channel_id=parent_channel_id,
        )

    def clear(self) -> None:
        self.pending_interactions.clear()

    def _validate_interaction_payload(
        self,
        agent_id: str,
        raw_command: str,
        expected_session_key: str,
        interaction_payload: Optional[dict[str, object]],
    ) -> None:
        if not interaction_payload:
            return
        if interaction_payload.get("session_key"):
            if str(interaction_payload["session_key"]) != expected_session_key:
                raise InteractionValidationError("Interactive command session mismatch.")
        if interaction_payload.get("command"):
            if str(interaction_payload["command"]) != raw_command.strip():
                raise InteractionValidationError("Interactive command payload mismatch.")
        if interaction_payload.get("request_id"):
            self.pending_interactions.consume(
                request_id=str(interaction_payload["request_id"]),
                agent_id=agent_id,
                command=raw_command.strip(),
                session_key=expected_session_key,
            )

    async def _collect(self, stream) -> str:
        parts = []
        async for piece in stream:
            parts.append(piece)
        return "".join(parts)

    async def _collect_with_timeout_recovery(
        self,
        *,
        agent_id: str,
        session_key: str,
        wrapper,
        stream_factory,
        progress_callback,
        restart_factory,
    ) -> tuple[str, object]:
        wrapper.set_progress_callback(progress_callback)
        try:
            return await self._collect(stream_factory(wrapper)), wrapper
        except ProviderResponseTimeout:
            wrapper.set_progress_callback(None)
            await self.provider_runtime.stop_session(agent_id=agent_id, session_key=session_key)
            _, recovered_wrapper = await restart_factory()
            recovered_wrapper.set_progress_callback(progress_callback)
            try:
                return await self._collect(stream_factory(recovered_wrapper)), recovered_wrapper
            finally:
                recovered_wrapper.set_progress_callback(None)
        finally:
            wrapper.set_progress_callback(None)
