from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Optional

from agent_messaging.providers.base import ProgressCallback, ProviderResponseTimeout, ResponseCallback


StreamFactory = Callable[[Any], Any]
RestartFactory = Callable[[], Awaitable[tuple[str, Any]]]
StopSessionCallback = Callable[[str, str], Awaitable[None]]


async def collect_stream(stream, response_callback: Optional[ResponseCallback] = None) -> str:
    parts = []
    async for piece in stream:
        parts.append(piece)
        if response_callback is not None and piece:
            await response_callback(piece)
    return "".join(parts)


async def collect_with_timeout_recovery(
    *,
    agent_id: str,
    session_key: str,
    wrapper: Any,
    stream_factory: StreamFactory,
    progress_callback: Optional[ProgressCallback],
    response_callback: Optional[ResponseCallback] = None,
    restart_factory: RestartFactory,
    stop_session: StopSessionCallback,
) -> tuple[str, Any]:
    wrapper.set_progress_callback(progress_callback)
    try:
        return await collect_stream(stream_factory(wrapper), response_callback), wrapper
    except ProviderResponseTimeout:
        wrapper.set_progress_callback(None)
        await stop_session(agent_id, session_key)
        _, recovered_wrapper = await restart_factory()
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
