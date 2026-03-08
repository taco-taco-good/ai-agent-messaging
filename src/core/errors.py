from __future__ import annotations


class AgentMessagingError(RuntimeError):
    """Base application error."""

    error_code = "agent_messaging_error"

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code


class CommandValidationError(AgentMessagingError):
    """Raised when a Discord-exposed CLI command is invalid for this app."""

    error_code = "command_validation_error"


class InteractionValidationError(AgentMessagingError):
    """Raised when an interactive command payload does not match its request."""

    error_code = "interaction_validation_error"


class AgentNotFoundError(AgentMessagingError):
    """Raised when an unknown agent id is requested."""

    error_code = "agent_not_found"


class ToolNotFoundError(AgentMessagingError):
    """Raised when an unknown runtime tool is requested."""

    error_code = "tool_not_found"


class UnsupportedProviderError(AgentMessagingError):
    """Raised when an unsupported provider is requested."""

    error_code = "unsupported_provider"
