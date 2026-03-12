from __future__ import annotations

import unittest

from agent_messaging.gateway.discord import _ChannelStreamResponder


class _FakeChannelMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.edits: list[str] = []

    async def edit(self, *, content: str) -> None:
        self.content = content
        self.edits.append(content)


class _FakeChannel:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.messages: list[_FakeChannelMessage] = []

    async def send(self, content: str) -> _FakeChannelMessage:
        self.sent.append(content)
        message = _FakeChannelMessage(content)
        self.messages.append(message)
        return message


class DiscordGatewayResponderTests(unittest.IsolatedAsyncioTestCase):
    async def test_codex_stream_text_sends_each_piece_as_separate_messages(self) -> None:
        channel = _FakeChannel()
        responder = _ChannelStreamResponder(channel, provider="codex")

        await responder.stream_text("hel")
        await responder.stream_text("lo")

        self.assertEqual(channel.sent, ["hel", "lo"])
        self.assertTrue(await responder.finalize(["hello"]))

    async def test_claude_stream_text_buffers_small_pieces_until_finalize(self) -> None:
        channel = _FakeChannel()
        responder = _ChannelStreamResponder(channel, provider="claude")

        await responder.stream_text("안")
        await responder.stream_text("녕")
        await responder.stream_text("하")
        await responder.stream_text("세")
        await responder.stream_text("요")

        self.assertEqual(channel.sent, [])
        self.assertTrue(await responder.finalize(["안녕하세요"]))
        self.assertEqual(channel.sent, ["안녕하세요"])
        self.assertEqual(channel.messages[0].edits, [])

    async def test_claude_stream_text_edits_existing_message_after_flush(self) -> None:
        channel = _FakeChannel()
        responder = _ChannelStreamResponder(channel, provider="claude")

        first = "a" * 210
        second = first + "\nupdated"

        await responder.stream_text(first)
        self.assertEqual(channel.sent, [])

        await responder.stream_text("\nupdated")

        self.assertEqual(channel.sent, [second])
        self.assertEqual(channel.messages[0].content, second)
        self.assertEqual(channel.messages[0].edits, [])
        self.assertTrue(await responder.finalize([second]))

    async def test_claude_stream_text_finalize_edits_last_message_to_full_text(self) -> None:
        channel = _FakeChannel()
        responder = _ChannelStreamResponder(channel, provider="claude")

        await responder.stream_text("a" * 210 + ".")

        self.assertTrue(await responder.finalize(["a" * 210 + ".b"]))
        self.assertEqual(channel.sent, ["a" * 210 + "."])
        self.assertEqual(channel.messages[0].content, "a" * 210 + ".b")
        self.assertEqual(channel.messages[0].edits, ["a" * 210 + ".b"])

    async def test_claude_stream_text_waits_for_sentence_boundary_after_soft_limit(self) -> None:
        channel = _FakeChannel()
        responder = _ChannelStreamResponder(channel, provider="claude")

        await responder.stream_text("a" * 210)
        self.assertEqual(channel.sent, [])

        await responder.stream_text(".")
        self.assertEqual(channel.sent, ["a" * 210 + "."])

    async def test_claude_stream_text_flushes_code_block_after_soft_limit_with_prior_newline(self) -> None:
        channel = _FakeChannel()
        responder = _ChannelStreamResponder(channel, provider="claude")

        prefix = "```\nfoo()\nbar()\n"
        await responder.stream_text(prefix)
        self.assertEqual(channel.sent, [])

        suffix = "x" * 190
        await responder.stream_text(suffix)

        self.assertEqual(len(channel.sent), 1)
        self.assertTrue(channel.sent[0].startswith(prefix + suffix))
        self.assertTrue(channel.sent[0].endswith("```\n"))

    async def test_claude_stream_text_flushes_without_boundary_after_force_limit(self) -> None:
        channel = _FakeChannel()
        responder = _ChannelStreamResponder(channel, provider="claude")

        await responder.stream_text("a" * 610)

        self.assertEqual(channel.sent, ["a" * 610])

    async def test_finalize_returns_false_without_streamed_response(self) -> None:
        channel = _FakeChannel()
        responder = _ChannelStreamResponder(channel, provider="codex")

        self.assertFalse(await responder.finalize(["hello"]))
        self.assertEqual(channel.sent, [])
