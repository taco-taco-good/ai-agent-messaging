from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_messaging.core.models import SessionRecord, utc_now
from agent_messaging.runtime.session_manager import SessionManager
from agent_messaging.runtime.session_store import SessionStore


class SessionStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "runtime" / "sessions.json"
            store = SessionStore(path)
            record = SessionRecord(
                agent_id="reviewer",
                provider="claude",
                provider_session_id="abc",
                current_model="sonnet",
                last_activity_at=utc_now(),
            )
            await store.upsert("discord:channel:123", record)

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["discord:channel:123"]["provider"], "claude")

            loaded = await store.get("discord:channel:123")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.current_model, "sonnet")

    async def test_thread_normalizes_to_parent_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "runtime" / "sessions.json"
            manager = SessionManager(SessionStore(path))
            await manager.upsert(
                channel_id="thread-1",
                is_dm=False,
                parent_channel_id="channel-1",
                agent_id="reviewer",
                provider="claude",
                provider_session_id="abc",
                current_model="sonnet",
            )
            record = await manager.get(
                channel_id="thread-2",
                is_dm=False,
                parent_channel_id="channel-1",
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.provider_session_id, "abc")
