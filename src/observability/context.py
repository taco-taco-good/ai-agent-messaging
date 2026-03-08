from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator


_LOG_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})


def get_log_context() -> dict[str, Any]:
    return dict(_LOG_CONTEXT.get())


def bind_log_context(**values: Any) -> Token:
    current = get_log_context()
    current.update({key: value for key, value in values.items() if value is not None})
    return _LOG_CONTEXT.set(current)


def reset_log_context(token: Token) -> None:
    _LOG_CONTEXT.reset(token)


def clear_log_context() -> None:
    _LOG_CONTEXT.set({})


@contextmanager
def log_context(**values: Any) -> Iterator[dict[str, Any]]:
    token = bind_log_context(**values)
    try:
        yield get_log_context()
    finally:
        reset_log_context(token)


def new_request_context(correlation_id: str | None = None, **values: Any) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    resolved_correlation = correlation_id or request_id
    payload = {
        "request_id": request_id,
        "correlation_id": resolved_correlation,
    }
    payload.update({key: value for key, value in values.items() if value is not None})
    return payload
