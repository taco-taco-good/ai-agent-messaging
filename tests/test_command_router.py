from __future__ import annotations

import unittest

from agent_messaging.application.command_router import CommandRouter
from agent_messaging.core.errors import CommandValidationError


class CommandRouterTests(unittest.TestCase):
    def test_parse_accepts_alias_without_slash(self) -> None:
        router = CommandRouter()
        routed = router.parse_cli_command("models")
        self.assertEqual(routed.command, "/models")
        self.assertFalse(routed.requires_interaction)

    def test_parse_rejects_unsupported_command_with_clear_error(self) -> None:
        router = CommandRouter()
        with self.assertRaisesRegex(CommandValidationError, "Supported commands"):
            router.parse_cli_command("/unknown")
