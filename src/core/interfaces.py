from __future__ import annotations

from typing import Any, Optional, Protocol, Sequence, Tuple

from agent_messaging.core.models import ModelOption
from agent_messaging.providers.base import CLIWrapper, ProgressCallback, ResponseCallback


class MetadataGeneratorProtocol(Protocol):
    def generate(self, user_text: str, assistant_text: str): ...


class AgentRegistryProtocol(Protocol):
    def get(self, agent_id: str) -> Any: ...

    def all(self) -> Any: ...


class MemoryWriterProtocol(Protocol):
    def append_message(
        self,
        agent_id: str,
        display_name: str,
        memory_dir: Any,
        role: str,
        content: str,
        participants: Any,
        metadata: Any = None,
        timestamp: Any = None,
    ) -> Any: ...


class SessionSnapshotStoreProtocol(Protocol):
    def write(
        self,
        agent: Any,
        session_key: str,
        *,
        user_text: str,
        assistant_text: str,
        metadata: Any = None,
    ) -> Any: ...

    def read(self, agent: Any, session_key: str) -> Any: ...


class ResumeContextAssemblerProtocol(Protocol):
    def assemble(self, agent: Any, session_key: str) -> str: ...


class ToolRuntimeProtocol(Protocol):
    def register(self, name: str, handler: Any) -> None: ...

    async def call(self, name: str, *args: Any, **kwargs: Any) -> Any: ...


class SessionManagerProtocol(Protocol):
    def session_scope_key(
        self,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> str: ...

    async def get(
        self,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> Any: ...

    async def upsert(
        self,
        channel_id: str,
        is_dm: bool,
        agent_id: str,
        provider: str,
        provider_session_id: str,
        current_model: Optional[str],
        status: str = "active",
        parent_channel_id: Optional[str] = None,
    ) -> Any: ...

    async def touch(
        self,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> Any: ...

    async def update_model(
        self,
        channel_id: str,
        is_dm: bool,
        model: str,
        parent_channel_id: Optional[str] = None,
    ) -> Any: ...

    async def clear(
        self,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> None: ...


class ProviderFactoryProtocol(Protocol):
    def __call__(self, agent: Any, session_key: str, session_record: Optional[Any] = None) -> CLIWrapper: ...


class ProviderRuntimeProtocol(Protocol):
    async def ensure_wrapper(
        self,
        agent: Any,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str],
    ) -> Tuple[str, CLIWrapper]: ...

    def session_lock(self, agent_id: str, session_key: str) -> Any: ...

    async def stop_session(self, agent_id: str, session_key: str) -> None: ...

    async def shutdown(self) -> None: ...

    async def options_for(
        self,
        agent: Any,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> Sequence[ModelOption]: ...


class PendingInteractionStoreProtocol(Protocol):
    def create(self, agent_id: str, command: str, session_key: str) -> Any: ...

    def consume(self, request_id: str, agent_id: str, command: str, session_key: str) -> None: ...

    def clear(self) -> None: ...


class ConversationServiceProtocol(Protocol):
    async def handle_user_message(
        self,
        agent_id: str,
        channel_id: str,
        content: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
        user_name: str = "user",
        metadata: Any = None,
        progress_callback: Optional[ProgressCallback] = None,
        response_callback: Optional[ResponseCallback] = None,
    ) -> list[str]: ...


class CommandServiceProtocol(Protocol):
    async def handle_cli_command(
        self,
        agent_id: str,
        channel_id: str,
        raw_command: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
        interaction_payload: Optional[dict[str, object]] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> list[str]: ...

    async def handle_new_session(
        self,
        agent_id: str,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> None: ...

    def create_pending_interaction(
        self,
        agent_id: str,
        command: str,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> Any: ...

    async def available_model_options(
        self,
        agent_id: str,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> list[ModelOption]: ...
