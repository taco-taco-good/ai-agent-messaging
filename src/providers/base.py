from __future__ import annotations

from abc import ABC, abstractmethod
import time
from typing import AsyncIterator, Awaitable, Callable, Dict, Iterable, Optional, Sequence

from agent_messaging.core.models import ModelOption


ProgressCallback = Callable[[str], Awaitable[None]]
ResponseCallback = Callable[[str], Awaitable[None]]


class ProviderError(RuntimeError):
    """Base provider runtime error."""

    error_code = "provider_error"

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code


class ProviderStartupError(ProviderError):
    """Raised when a provider process cannot be started."""

    error_code = "provider_startup_error"


class ProviderResponseTimeout(ProviderError):
    """Raised when a provider does not produce output within the timeout."""

    error_code = "provider_response_timeout"


class ProviderStaleSession(ProviderError):
    """Raised when a persisted provider session cannot be resumed safely."""

    error_code = "provider_stale_session"


class ProviderStreamDisconnected(ProviderError):
    """Raised when a provider stream disconnects before completion."""

    error_code = "provider_stream_disconnected"


class ProviderProcessKilled(ProviderError):
    """Raised when a provider subprocess is terminated unexpectedly."""

    error_code = "provider_process_killed"


class CLIWrapper(ABC):
    provider_name = "unknown"
    supported_commands: Iterable[str] = ()
    model_options: Sequence[str] = ()
    model_catalog: Sequence[ModelOption] = ()

    def __init__(self, default_model: Optional[str] = None) -> None:
        self.current_model = default_model
        self.provider_session_id = ""
        self._timeout_warning_issued = False
        self.resolved_model: Optional[str] = None
        self.resolved_model_source: Optional[str] = None
        self.resolved_model_session_id: Optional[str] = None
        self._exact_model_pending_since: Optional[float] = None
        self._progress_callback: Optional[ProgressCallback] = None

    @property
    def timeout_warning_issued(self) -> bool:
        """True if the last send operation hit the warning timeout stage."""
        return self._timeout_warning_issued

    def set_progress_callback(self, callback: Optional[ProgressCallback]) -> None:
        self._progress_callback = callback

    async def emit_progress(self, message: str) -> None:
        if self._progress_callback is None:
            return
        await self._progress_callback(message)

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def send_user_message(self, message: str) -> AsyncIterator[str]:
        raise NotImplementedError

    @abstractmethod
    async def send_native_command(
        self,
        command: str,
        args: Optional[Dict[str, object]] = None,
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    @abstractmethod
    async def reset_session(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_alive(self) -> bool:
        raise NotImplementedError

    def supports_native_command(self, command: str) -> bool:
        return command in set(self.supported_commands)

    def session_scope_key(
        self,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> str:
        if is_dm:
            return "discord:dm:{0}".format(channel_id)
        normalized = parent_channel_id or channel_id
        return "discord:channel:{0}".format(normalized)

    def available_model_options(self) -> Sequence[str]:
        if self.model_catalog:
            return [option.label for option in self.model_catalog]
        return list(self.model_options)

    def available_model_catalog(self) -> Sequence[ModelOption]:
        if self.model_catalog:
            return list(self.model_catalog)
        return [
            ModelOption(value=option, label=option)
            for option in self.model_options
        ]

    def clear_resolved_model(self) -> None:
        self.resolved_model = None
        self.resolved_model_source = None
        self.resolved_model_session_id = None
        self._exact_model_pending_since = time.time()

    def set_resolved_model(
        self,
        model: Optional[str],
        source: str,
        *,
        session_id: Optional[str] = None,
    ) -> None:
        if not model:
            return
        self.resolved_model = model
        self.resolved_model_source = source
        self.resolved_model_session_id = session_id
        self._exact_model_pending_since = None

    def format_stats_response(self, extra: Optional[Dict[str, str]] = None) -> str:
        selected_model = self.current_model or "default"
        exact_model = self.resolved_model or "pending confirmation"
        source = self.resolved_model_source or "waiting for a new provider response"
        lines = [
            "Selected model: {0}".format(selected_model),
            "Exact model: {0}".format(exact_model),
            "Source: {0}".format(source),
        ]
        if self.provider_session_id:
            lines.append("Session: {0}".format(self.provider_session_id))
        if self.resolved_model_session_id and self.resolved_model_session_id != self.provider_session_id:
            lines.append("Observed session: {0}".format(self.resolved_model_session_id))
        for key, value in (extra or {}).items():
            if value:
                label = key.replace("_", " ").capitalize()
                lines.append("{0}: {1}".format(label, value))
        return "\n".join(lines)

    async def stats_response(self) -> str:
        return self.format_stats_response()
