from __future__ import annotations

import json
import logging
import os
from typing import Any

from agent_messaging.observability.context import get_log_context


DEFAULT_LOG_KEYS = (
    "request_id",
    "correlation_id",
    "agent_id",
    "channel_id",
    "parent_channel_id",
    "session_key",
    "provider",
    "provider_session_id",
    "command",
    "interaction_id",
    "error_code",
)
_RESERVED = set(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime"}


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = get_log_context()
        for key in DEFAULT_LOG_KEYS:
            if not hasattr(record, key):
                setattr(record, key, context.get(key, "-"))
        return True


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = self._build_payload(record)
        prefix = "{0} {1} {2}".format(
            payload["timestamp"],
            payload["level"],
            payload["logger"],
        )
        extras = payload["extras"]
        rendered = " ".join(
            "{0}={1}".format(key, self._encode(value))
            for key, value in extras.items()
        )
        base = "{0} event={1}".format(prefix, self._encode(payload["event"]))
        if rendered:
            base = "{0} {1}".format(base, rendered)
        if record.exc_info:
            return "{0}\n{1}".format(base, self.formatException(record.exc_info))
        if record.stack_info:
            return "{0}\n{1}".format(base, self.formatStack(record.stack_info))
        return base

    def _build_payload(self, record: logging.LogRecord) -> dict[str, Any]:
        record.message = record.getMessage()
        timestamp = self.formatTime(record, self.datefmt)
        extras = self._collect_extras(record)
        return {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "event": record.message,
            "extras": extras,
        }

    def _collect_extras(self, record: logging.LogRecord) -> dict[str, Any]:
        values: dict[str, Any] = {}
        error_code = self._resolve_error_code(record)
        if error_code:
            values["error_code"] = error_code
        for key in DEFAULT_LOG_KEYS:
            value = getattr(record, key, "-")
            if value not in (None, "", "-"):
                values[key] = value
        for key, value in sorted(record.__dict__.items()):
            if key in _RESERVED or key in values or key.startswith("_"):
                continue
            if value in (None, "", "-"):
                continue
            values[key] = value
        return values

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _resolve_error_code(record: logging.LogRecord) -> str | None:
        explicit = getattr(record, "error_code", None)
        if explicit not in (None, "", "-"):
            return str(explicit)
        if record.exc_info and record.exc_info[1] is not None:
            error_code = getattr(record.exc_info[1], "error_code", None)
            if error_code:
                return str(error_code)
        return None


class JsonFormatter(KeyValueFormatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = self._build_payload(record)
        body: dict[str, Any] = {
            "timestamp": payload["timestamp"],
            "level": payload["level"],
            "logger": payload["logger"],
            "event": payload["event"],
        }
        body.update(payload["extras"])
        if record.exc_info and record.exc_info[1] is not None:
            body["exception_type"] = type(record.exc_info[1]).__name__
            body["exception_message"] = str(record.exc_info[1])
            body["traceback"] = self.formatException(record.exc_info)
        if record.stack_info:
            body["stack"] = self.formatStack(record.stack_info)
        return json.dumps(body, ensure_ascii=False, sort_keys=True)


def setup_logging(level: str | None = None) -> None:
    resolved = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    log_format = (os.getenv("LOG_FORMAT") or "text").strip().lower()
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(KeyValueFormatter())
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, resolved, logging.INFO))
    root.addHandler(handler)
