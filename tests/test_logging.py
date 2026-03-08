from __future__ import annotations

import io
import json
import logging
import os
import unittest

from agent_messaging.core.errors import InteractionValidationError
from agent_messaging.observability.context import clear_log_context, log_context, new_request_context
from agent_messaging.observability.logging import ContextFilter, JsonFormatter, KeyValueFormatter, setup_logging


class LoggingTests(unittest.TestCase):
    def test_formatter_includes_request_context_and_extras(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(KeyValueFormatter())
        handler.addFilter(ContextFilter())

        logger = logging.getLogger("test.logging")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)

        clear_log_context()
        with log_context(**new_request_context(agent_id="reviewer", channel_id="123")):
            logger.info("hello", extra={"command": "/model"})

        output = stream.getvalue()
        self.assertIn('event="hello"', output)
        self.assertIn("request_id=", output)
        self.assertIn("correlation_id=", output)
        self.assertIn('agent_id="reviewer"', output)
        self.assertIn('channel_id="123"', output)
        self.assertIn('command="/model"', output)

    def test_formatter_includes_error_code_from_exception(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(KeyValueFormatter())
        handler.addFilter(ContextFilter())

        logger = logging.getLogger("test.logging.error")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)

        try:
            raise InteractionValidationError("bad interaction")
        except InteractionValidationError:
            logger.exception("request_failed")

        output = stream.getvalue()
        self.assertIn('event="request_failed"', output)
        self.assertIn('error_code="interaction_validation_error"', output)

    def test_json_formatter_outputs_json_payload(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        handler.addFilter(ContextFilter())

        logger = logging.getLogger("test.logging.json")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)

        clear_log_context()
        with log_context(**new_request_context(agent_id="reviewer", channel_id="123")):
            logger.info("hello", extra={"command": "/model"})

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["event"], "hello")
        self.assertEqual(payload["agent_id"], "reviewer")
        self.assertEqual(payload["channel_id"], "123")
        self.assertEqual(payload["command"], "/model")
        self.assertIn("request_id", payload)
        self.assertIn("correlation_id", payload)

    def test_setup_logging_uses_json_formatter_when_requested(self) -> None:
        previous = os.environ.get("LOG_FORMAT")
        try:
            os.environ["LOG_FORMAT"] = "json"
            setup_logging(level="INFO")
            root = logging.getLogger()
            self.assertIsInstance(root.handlers[0].formatter, JsonFormatter)
        finally:
            if previous is None:
                os.environ.pop("LOG_FORMAT", None)
            else:
                os.environ["LOG_FORMAT"] = previous
