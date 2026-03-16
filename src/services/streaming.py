from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from agent_messaging.providers.base import (
    ProgressCallback,
    ProviderResponseTimeout,
    ProviderStaleSession,
    ResponseCallback,
)


logger = logging.getLogger(__name__)

StreamFactory = Callable[[Any], Any]
ResetSessionCallback = Callable[[], Awaitable[tuple[str, Any]]]


async def collect_stream(stream, response_callback: Optional[ResponseCallback] = None) -> str:
    parts = []
    async for piece in stream:
        parts.append(piece)
        if response_callback is not None and piece:
            await response_callback(piece)
    return "".join(parts)


async def collect_with_timeout_recovery(
    *,
    wrapper: Any,
    stream_factory: StreamFactory,
    progress_callback: Optional[ProgressCallback],
    response_callback: Optional[ResponseCallback] = None,
    reset_session: ResetSessionCallback,
) -> tuple[str, Any]:
    wrapper.set_progress_callback(progress_callback)
    try:
        return await collect_stream(stream_factory(wrapper), response_callback), wrapper
    except (ProviderResponseTimeout, ProviderStaleSession):
        wrapper.set_progress_callback(None)
        _, recovered_wrapper = await reset_session()
        recovered_wrapper.set_progress_callback(progress_callback)
        try:
            return (
                await collect_stream(stream_factory(recovered_wrapper), response_callback),
                recovered_wrapper,
            )
        finally:
            recovered_wrapper.set_progress_callback(None)
    finally:
        wrapper.set_progress_callback(None)


async def reset_session_for_retry(
    *,
    logger_extra: dict[str, Any],
    provider_runtime: Any,
    session_manager: Any,
    agent: Any,
    session_key: str,
    channel_id: str,
    is_dm: bool,
    parent_channel_id: Optional[str],
) -> tuple[str, Any]:
    logger.info("session_reset_for_retry", extra=logger_extra)
    await provider_runtime.stop_session(agent_id=agent.agent_id, session_key=session_key)
    await session_manager.clear(
        channel_id=channel_id,
        is_dm=is_dm,
        parent_channel_id=parent_channel_id,
    )
    return await provider_runtime.ensure_wrapper(
        agent=agent,
        channel_id=channel_id,
        is_dm=is_dm,
        parent_channel_id=parent_channel_id,
    )
