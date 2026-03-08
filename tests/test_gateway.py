from __future__ import annotations

import unittest
from types import SimpleNamespace

from agent_messaging.gateway.discord import (
    _context_from_channel,
    _extract_content,
    _send_channel_chunks,
    _should_handle_message,
)


class DiscordGatewayHelperTests(unittest.TestCase):
    def test_context_from_thread_uses_parent(self) -> None:
        parent = SimpleNamespace(id=123)
        channel = SimpleNamespace(id=456, parent=parent, guild=object())
        context = _context_from_channel(channel, "taco")
        self.assertEqual(context["channel_id"], "456")
        self.assertEqual(context["parent_channel_id"], "123")
        self.assertFalse(context["is_dm"])

    def test_should_handle_dm_without_mention(self) -> None:
        message = SimpleNamespace(channel=SimpleNamespace(guild=None))
        self.assertTrue(_should_handle_message(None, message))

    def test_extract_content_strips_bot_mention(self) -> None:
        bot_user = SimpleNamespace(id=42)
        channel = SimpleNamespace(guild=object())
        message = SimpleNamespace(channel=channel, content="<@42> hello there")
        self.assertEqual(_extract_content(bot_user, message), "hello there")

    def test_send_channel_chunks_uses_fallback_for_empty_chunks(self) -> None:
        sent = []

        class FakeChannel:
            async def send(self, content):
                sent.append(content)

        import asyncio

        asyncio.run(_send_channel_chunks(FakeChannel(), []))
        self.assertEqual(sent, ["응답이 비어 있습니다."])
