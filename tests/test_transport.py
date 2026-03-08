from __future__ import annotations

import unittest

from agent_messaging.runtime.transport import chunk_text, sanitize_discord_text


class TransportTests(unittest.TestCase):
    def test_chunk_text_preserves_code_fences(self) -> None:
        text = "```python\nprint('a')\nprint('b')\nprint('c')\n```\n"
        chunks = chunk_text(text, limit=24)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(chunk.count("```") % 2, 0)

    def test_chunk_text_splits_plain_text(self) -> None:
        chunks = chunk_text("abcdefghij", limit=4)
        self.assertEqual(chunks, ["abcd", "efgh", "ij"])

    def test_chunk_text_drops_empty_control_only_payload(self) -> None:
        chunks = chunk_text("\x00\x1b\n\r", limit=10)
        self.assertEqual(chunks, [])

    def test_sanitize_discord_text_removes_control_characters(self) -> None:
        text = sanitize_discord_text("hello\x00world\r\nnext\x1fline")
        self.assertEqual(text, "helloworld\nnextline")
