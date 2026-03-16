from __future__ import annotations

from typing import Callable, Dict, Optional

from agent_messaging.core.errors import UnsupportedProviderError
from agent_messaging.core.models import AgentConfig, SessionRecord
from agent_messaging.providers.base import CLIWrapper
from agent_messaging.providers.claude import ClaudeWrapper
from agent_messaging.providers.codex import CodexWrapper
from agent_messaging.providers.gemini import GeminiWrapper


ProviderBuilder = Callable[[AgentConfig, Optional[SessionRecord]], CLIWrapper]


def _build_claude(agent: AgentConfig, session_record: Optional[SessionRecord]) -> CLIWrapper:
    kwargs = {}
    if agent.warning_timeout_seconds is not None:
        kwargs["warning_timeout"] = agent.warning_timeout_seconds
    if agent.hard_timeout_seconds is not None:
        kwargs["hard_timeout"] = agent.hard_timeout_seconds
    return ClaudeWrapper(
        default_model=(session_record.current_model if session_record else None) or agent.model,
        workspace_dir=agent.workspace_dir,
        base_args=agent.cli_args,
        provider_session_id=session_record.provider_session_id if session_record else None,
        **kwargs,
    )


def _build_codex(agent: AgentConfig, session_record: Optional[SessionRecord]) -> CLIWrapper:
    return CodexWrapper(
        default_model=(session_record.current_model if session_record else None) or agent.model,
        workspace_dir=agent.workspace_dir,
        base_args=agent.cli_args,
        provider_session_id=session_record.provider_session_id if session_record else None,
    )


def _build_gemini(agent: AgentConfig, session_record: Optional[SessionRecord]) -> CLIWrapper:
    return GeminiWrapper(
        default_model=(session_record.current_model if session_record else None) or agent.model,
        workspace_dir=agent.workspace_dir,
        base_args=agent.cli_args,
    )


PROVIDER_BUILDERS: Dict[str, ProviderBuilder] = {
    "claude": _build_claude,
    "codex": _build_codex,
    "gemini": _build_gemini,
}


def create_provider(
    agent: AgentConfig,
    session_key: str,
    session_record: Optional[SessionRecord] = None,
) -> CLIWrapper:
    del session_key
    try:
        builder = PROVIDER_BUILDERS[agent.provider]
    except KeyError as exc:
        raise UnsupportedProviderError(
            "Unsupported provider: {0}".format(agent.provider)
        ) from exc
    return builder(agent, session_record)
