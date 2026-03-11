from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from typing import Any, List, Optional

from agent_messaging.application.app import AgentMessagingApp
from agent_messaging.core.errors import AgentMessagingError, CommandValidationError, InteractionValidationError
from agent_messaging.core.models import ModelOption
from agent_messaging.observability.context import log_context, new_request_context
from agent_messaging.providers.base import (
    ProviderError,
    ProviderResponseTimeout,
    ProviderStartupError,
)
from agent_messaging.runtime.transport import chunk_text


logger = logging.getLogger(__name__)


class DiscordGatewayUnavailable(AgentMessagingError):
    """Raised when discord.py is not installed."""

    error_code = "discord_gateway_unavailable"


def require_discord():
    try:
        import discord  # type: ignore
        from discord import app_commands  # type: ignore
    except ImportError as exc:
        raise DiscordGatewayUnavailable(
            "discord.py is not installed. Install the optional `discord` dependency."
        ) from exc
    return discord, app_commands


def _error_extra(exc: BaseException, **extra: object) -> dict[str, object]:
    payload = {
        "error": str(exc),
        "error_code": getattr(exc, "error_code", "internal_error"),
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
    }
    payload.update(extra)
    return payload


def _exc_info(exc: BaseException) -> tuple[type[BaseException], BaseException, object]:
    return type(exc), exc, exc.__traceback__


def create_agent_client(app: AgentMessagingApp, agent_id: str):
    discord, app_commands = require_discord()
    agent = app.registry.get(agent_id)
    logger.info("create_agent_client", extra={"agent_id": agent_id, "provider": agent.provider})

    class ModelSelect(discord.ui.Select):  # type: ignore[misc]
        def __init__(
            self,
            channel_id: str,
            is_dm: bool,
            parent_channel_id: Optional[str],
            request_id: str,
            options: list[ModelOption],
        ) -> None:
            options = [
                discord.SelectOption(
                    label=_truncate_select_text(option.label),
                    value=option.value,
                    description=_truncate_select_description(option.description),
                )
                for option in options
            ]
            super().__init__(
                placeholder="Choose a model",
                min_values=1,
                max_values=1,
                options=options,
                custom_id="model:{0}".format(request_id),
            )
            self.channel_id = channel_id
            self.is_dm = is_dm
            self.parent_channel_id = parent_channel_id
            self.request_id = request_id

        async def callback(self, interaction) -> None:  # pragma: no cover - requires discord.py
            session_key = app.session_manager.session_scope_key(
                channel_id=self.channel_id,
                is_dm=self.is_dm,
                parent_channel_id=self.parent_channel_id,
            )
            with log_context(
                **new_request_context(
                    correlation_id=self.request_id,
                    agent_id=agent_id,
                    channel_id=self.channel_id,
                    parent_channel_id=self.parent_channel_id,
                    session_key=session_key,
                    interaction_id=str(interaction.id),
                    command="/model",
                    provider=agent.provider,
                )
            ):
                try:
                    chunks = await app.handle_cli_command(
                        agent_id=agent_id,
                        channel_id=self.channel_id,
                        raw_command="/model",
                        is_dm=self.is_dm,
                        parent_channel_id=self.parent_channel_id,
                        interaction_payload={
                            "command": "/model",
                            "model_alias": self.values[0],
                            "request_id": self.request_id,
                            "session_key": session_key,
                        },
                    )
                except (CommandValidationError, InteractionValidationError) as exc:
                    logger.warning(
                        "discord_interaction_validation_failed",
                        extra=_error_extra(exc),
                        exc_info=_exc_info(exc),
                    )
                    chunks = chunk_text(str(exc))
                except ProviderResponseTimeout as exc:
                    logger.warning(
                        "discord_interaction_timeout",
                        extra=_error_extra(exc),
                        exc_info=_exc_info(exc),
                    )
                    chunks = ["응답 생성에 시간이 걸리고 있습니다."]
                except (ProviderStartupError, ProviderError) as exc:
                    logger.error(
                        "discord_interaction_provider_error",
                        extra=_error_extra(exc),
                        exc_info=_exc_info(exc),
                    )
                    chunks = chunk_text(str(exc))
                except Exception as exc:
                    logger.exception("discord_interaction_unexpected_error", extra=_error_extra(exc))
                    chunks = ["Internal error. error_code=internal_error"]
            await _send_interaction_chunks(interaction, chunks)

    class ModelView(discord.ui.View):  # type: ignore[misc]
        def __init__(
            self,
            channel_id: str,
            is_dm: bool,
            parent_channel_id: Optional[str],
            request_id: str,
            options: list[ModelOption],
        ) -> None:
            super().__init__(timeout=60)
            self.add_item(ModelSelect(channel_id, is_dm, parent_channel_id, request_id, options))

    class AgentClient(discord.Client):  # type: ignore[misc]
        def __init__(self) -> None:
            intents = discord.Intents.default()
            intents.message_content = True
            super().__init__(intents=intents)
            self.tree = app_commands.CommandTree(self)

        async def on_ready(self) -> None:  # pragma: no cover - requires discord.py
            async def _send_to_channel(channel_id: str, chunks: list[str]) -> None:
                channel = self.get_channel(int(channel_id))
                if channel is None:
                    channel = await self.fetch_channel(int(channel_id))
                await _send_channel_chunks(channel, chunks)

            app.register_channel_sender(agent_id, _send_to_channel)
            logger.info("discord_client_ready", extra={"agent_id": agent_id, "user_id": str(self.user.id if self.user else "")})

        async def setup_hook(self) -> None:  # pragma: no cover - requires discord.py
            @self.tree.command(name="new", description="Reset the current CLI session")
            async def new_session(interaction) -> None:
                context = _context_from_channel(interaction.channel, interaction.user.display_name)
                session_key = app.session_manager.session_scope_key(
                    channel_id=context["channel_id"],
                    is_dm=context["is_dm"],
                    parent_channel_id=context["parent_channel_id"],
                )
                with log_context(
                    **new_request_context(
                        correlation_id="discord-interaction:{0}".format(interaction.id),
                        agent_id=agent_id,
                        channel_id=context["channel_id"],
                        parent_channel_id=context["parent_channel_id"],
                        session_key=session_key,
                        interaction_id=str(interaction.id),
                        command="/new",
                        provider=agent.provider,
                    )
                ):
                    logger.info("discord_new_command")
                    await app.handle_new_session(
                        agent_id=agent_id,
                        channel_id=context["channel_id"],
                        is_dm=context["is_dm"],
                        parent_channel_id=context["parent_channel_id"],
                    )
                    await interaction.response.send_message(
                        "Started a new session for this channel.",
                        ephemeral=True,
                    )

            @self.tree.command(name="help", description="Show CLI help information")
            async def cmd_help(interaction) -> None:
                await _handle_simple_command(interaction, "/help")

            @self.tree.command(name="stats", description="Show session statistics")
            async def cmd_stats(interaction) -> None:
                await _handle_simple_command(interaction, "/stats")

            @self.tree.command(name="model", description="Switch the AI model")
            async def cmd_model(interaction) -> None:
                context = _context_from_channel(interaction.channel, interaction.user.display_name)
                session_key = app.session_manager.session_scope_key(
                    channel_id=context["channel_id"],
                    is_dm=context["is_dm"],
                    parent_channel_id=context["parent_channel_id"],
                )
                with log_context(
                    **new_request_context(
                        correlation_id="discord-interaction:{0}".format(interaction.id),
                        agent_id=agent_id,
                        channel_id=context["channel_id"],
                        parent_channel_id=context["parent_channel_id"],
                        session_key=session_key,
                        interaction_id=str(interaction.id),
                        command="/model",
                        provider=agent.provider,
                    )
                ):
                    logger.info("discord_model_command")
                    model_options = await app.available_model_options(
                        agent_id=agent_id,
                        channel_id=context["channel_id"],
                        is_dm=context["is_dm"],
                        parent_channel_id=context["parent_channel_id"],
                    )
                    pending = app.create_pending_interaction(
                        agent_id=agent_id,
                        command="/model",
                        channel_id=context["channel_id"],
                        is_dm=context["is_dm"],
                        parent_channel_id=context["parent_channel_id"],
                    )
                    await interaction.response.send_message(
                        "Choose a model:",
                        view=ModelView(
                            channel_id=context["channel_id"],
                            is_dm=context["is_dm"],
                            parent_channel_id=context["parent_channel_id"],
                            request_id=pending.request_id,
                            options=model_options,
                        ),
                        ephemeral=True,
                    )

            async def _handle_simple_command(interaction, command: str) -> None:
                context = _context_from_channel(interaction.channel, interaction.user.display_name)
                session_key = app.session_manager.session_scope_key(
                    channel_id=context["channel_id"],
                    is_dm=context["is_dm"],
                    parent_channel_id=context["parent_channel_id"],
                )
                with log_context(
                    **new_request_context(
                        correlation_id="discord-interaction:{0}".format(interaction.id),
                        agent_id=agent_id,
                        channel_id=context["channel_id"],
                        parent_channel_id=context["parent_channel_id"],
                        session_key=session_key,
                        interaction_id=str(interaction.id),
                        command=command,
                        provider=agent.provider,
                    )
                ):
                    logger.info("discord_cli_command", extra={"command": command})
                    await interaction.response.defer()
                    try:
                        async def _progress(message_text: str) -> None:
                            await _send_interaction_chunks(interaction, [message_text])

                        chunks = await app.handle_cli_command(
                            agent_id=agent_id,
                            channel_id=context["channel_id"],
                            raw_command=command,
                            is_dm=context["is_dm"],
                            parent_channel_id=context["parent_channel_id"],
                            progress_callback=_progress,
                        )
                    except ProviderResponseTimeout as exc:
                        logger.warning(
                            "discord_cli_timeout",
                            extra=_error_extra(exc),
                            exc_info=_exc_info(exc),
                        )
                        chunks = ["응답 생성에 시간이 걸리고 있습니다."]
                    except (CommandValidationError, InteractionValidationError) as exc:
                        logger.warning(
                            "discord_cli_validation_failed",
                            extra=_error_extra(exc),
                            exc_info=_exc_info(exc),
                        )
                        chunks = chunk_text(str(exc))
                    except (ProviderStartupError, ProviderError) as exc:
                        logger.error(
                            "discord_cli_provider_error",
                            extra=_error_extra(exc),
                            exc_info=_exc_info(exc),
                        )
                        chunks = chunk_text(str(exc))
                    except Exception as exc:
                        logger.exception("discord_cli_unexpected_error", extra=_error_extra(exc))
                        chunks = ["Internal error. error_code=internal_error"]
                    await _send_interaction_chunks(interaction, chunks)

            await self.tree.sync()

        async def on_message(self, message) -> None:  # pragma: no cover - requires discord.py
            if message.author.bot:
                return
            if not _should_handle_message(self.user, message):
                return

            content = _extract_content(self.user, message)
            if not content:
                return

            context = _context_from_channel(message.channel, message.author.display_name)
            session_key = app.session_manager.session_scope_key(
                channel_id=context["channel_id"],
                is_dm=context["is_dm"],
                parent_channel_id=context["parent_channel_id"],
            )
            with log_context(
                **new_request_context(
                    correlation_id="discord-message:{0}".format(message.id),
                    agent_id=agent_id,
                    channel_id=context["channel_id"],
                    parent_channel_id=context["parent_channel_id"],
                    session_key=session_key,
                    provider=agent.provider,
                )
            ):
                logger.info("discord_message_received", extra={"is_dm": context["is_dm"]})
                responder = _ChannelStreamResponder(message.channel, provider=agent.provider)
                async with message.channel.typing():
                    try:
                        async def _progress(message_text: str) -> None:
                            await responder.send_progress(message_text)

                        async def _response(piece: str) -> None:
                            await responder.stream_text(piece)

                        chunks = await app.handle_user_message(
                            agent_id=agent_id,
                            channel_id=context["channel_id"],
                            content=content,
                            is_dm=context["is_dm"],
                            parent_channel_id=context["parent_channel_id"],
                            user_name=context["user_name"],
                            progress_callback=_progress,
                            response_callback=_response,
                        )
                    except ProviderResponseTimeout as exc:
                        logger.warning(
                            "discord_message_timeout",
                            extra=_error_extra(exc),
                            exc_info=_exc_info(exc),
                        )
                        chunks = ["응답 생성에 시간이 걸리고 있습니다."]
                    except (CommandValidationError, InteractionValidationError) as exc:
                        logger.warning(
                            "discord_message_validation_failed",
                            extra=_error_extra(exc),
                            exc_info=_exc_info(exc),
                        )
                        chunks = chunk_text(str(exc))
                    except (ProviderStartupError, ProviderError) as exc:
                        logger.error(
                            "discord_message_provider_error",
                            extra=_error_extra(exc),
                            exc_info=_exc_info(exc),
                        )
                        chunks = chunk_text(str(exc))
                    except Exception as exc:
                        logger.exception("discord_message_unexpected_error", extra=_error_extra(exc))
                        chunks = ["Internal error. error_code=internal_error"]
                if not await responder.finalize(chunks):
                    await _send_channel_chunks(message.channel, chunks)

    return AgentClient()


async def run_discord_gateways(app: AgentMessagingApp) -> None:
    clients = []
    tasks = []
    for agent in app.registry.all():
        client = create_agent_client(app, agent.agent_id)
        clients.append(client)
        tasks.append(asyncio.create_task(client.start(agent.discord_token)))
    app.start_background_tasks()
    try:
        await asyncio.gather(*tasks)
    finally:
        for client in clients:
            with suppress(Exception):
                await client.close()
        await app.shutdown()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _context_from_channel(channel: Any, user_name: str) -> dict:
    parent = getattr(channel, "parent", None)
    return {
        "channel_id": str(channel.id),
        "parent_channel_id": str(parent.id) if parent is not None else None,
        "is_dm": getattr(channel, "guild", None) is None,
        "user_name": user_name,
    }


def _should_handle_message(bot_user: Any, message: Any) -> bool:
    return True


def _extract_content(bot_user: Any, message: Any) -> str:
    content = message.content or ""
    if getattr(message.channel, "guild", None) is None or bot_user is None:
        return content.strip()

    for mention in ("<@{0}>".format(bot_user.id), "<@!{0}>".format(bot_user.id)):
        content = content.replace(mention, "")
    return content.strip()


_CHUNK_SEND_DELAY = 0.3  # seconds between consecutive chunk sends
_DISCORD_SELECT_TEXT_LIMIT = 100
_STREAM_EDIT_LIMIT = 1900
_STREAM_FLUSH_CHARS = 200


def _truncate_select_text(text: str) -> str:
    if len(text) <= _DISCORD_SELECT_TEXT_LIMIT:
        return text
    return "{0}...".format(text[: _DISCORD_SELECT_TEXT_LIMIT - 3])


def _truncate_select_description(text: str) -> Optional[str]:
    if not text:
        return None
    return _truncate_select_text(text)


async def _send_channel_chunks(channel: Any, chunks: List[str]) -> None:
    if not chunks:
        chunks = ["응답이 비어 있습니다."]
    for i, chunk in enumerate(chunks):
        if i > 0:
            await asyncio.sleep(_CHUNK_SEND_DELAY)
        try:
            await channel.send(chunk)
        except Exception as exc:
            logger.warning("discord_send_chunk_failed", extra={"chunk_index": i, "error": str(exc)})
            raise


class _ChannelStreamResponder:
    def __init__(self, channel: Any, provider: str) -> None:
        self.channel = channel
        self.provider = provider
        self._messages: List[Any] = []
        self._sent_response = False
        self._last_progress = ""
        self._text = ""
        self._rendered_length = 0
        self._lock = asyncio.Lock()

    async def stream_text(self, piece: str) -> None:
        if not piece:
            return
        async with self._lock:
            if self.provider == "claude":
                self._text += piece
                should_flush = (
                    len(self._text) - self._rendered_length >= _STREAM_FLUSH_CHARS
                    or "\n" in piece
                )
                if not should_flush:
                    return
                await self._sync_messages()
                self._rendered_length = len(self._text)
            else:
                await _send_channel_chunks(
                    self.channel,
                    chunk_text(piece, limit=_STREAM_EDIT_LIMIT),
                )
            self._sent_response = True

    async def send_progress(self, message: str) -> None:
        if not message:
            return
        async with self._lock:
            if message == self._last_progress:
                return
            await _send_channel_chunks(self.channel, [message])
            self._last_progress = message

    async def finalize(self, chunks: List[str]) -> bool:
        async with self._lock:
            if self.provider == "claude":
                if not self._text:
                    return False
                self._text = "".join(chunks)
                await self._sync_messages(force=True)
                self._rendered_length = len(self._text)
                self._sent_response = True
            return self._sent_response

    async def _sync_messages(self, force: bool = False) -> None:
        chunks = chunk_text(self._text, limit=_STREAM_EDIT_LIMIT)
        if not chunks:
            return
        for index, chunk in enumerate(chunks):
            if index < len(self._messages):
                current = self._messages[index]
                if force or getattr(current, "content", None) != chunk:
                    try:
                        await current.edit(content=chunk)
                    except Exception as exc:
                        logger.warning(
                            "discord_stream_edit_failed",
                            extra={"chunk_index": index, "error": str(exc)},
                        )
                        replacement = await self.channel.send(chunk)
                        self._messages[index] = replacement
            else:
                try:
                    message = await self.channel.send(chunk)
                except Exception as exc:
                    logger.warning(
                        "discord_stream_send_failed",
                        extra={"chunk_index": index, "error": str(exc)},
                    )
                    raise
                self._messages.append(message)


async def _send_interaction_chunks(interaction: Any, chunks: List[str]) -> None:
    if not chunks:
        chunks = ["응답이 비어 있습니다."]
    if interaction.response.is_done():
        sender = interaction.followup.send
    else:
        sender = interaction.response.send_message

    first = True
    for i, chunk in enumerate(chunks):
        if not first:
            await asyncio.sleep(_CHUNK_SEND_DELAY)
        try:
            if first:
                await sender(chunk)
                first = False
            else:
                await interaction.followup.send(chunk)
        except Exception as exc:
            logger.warning("discord_send_chunk_failed", extra={"chunk_index": i, "error": str(exc)})
            raise
