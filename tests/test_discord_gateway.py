from __future__ import annotations

import unittest

from agent_messaging.gateway.discord import _ChannelStreamResponder


class _FakeChannelMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChannel:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str) -> _FakeChannelMessage:
        self.sent.append(content)
        return _FakeChannelMessage(content)


class DiscordGatewayResponderTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_text_sends_each_piece_as_separate_messages(self) -> None:
        channel = _FakeChannel()
        responder = _ChannelStreamResponder(channel)

        await responder.stream_text("hel")
        await responder.stream_text("lo")

        self.assertEqual(channel.sent, ["hel", "lo"])
        self.assertTrue(await responder.finalize(["hello"]))

    async def test_finalize_returns_false_without_streamed_response(self) -> None:
        channel = _FakeChannel()
        responder = _ChannelStreamResponder(channel)

        self.assertFalse(await responder.finalize(["hello"]))
        self.assertEqual(channel.sent, [])

