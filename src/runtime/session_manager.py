from __future__ import annotations

from typing import Optional

from agent_messaging.core.models import SessionRecord, utc_now
from agent_messaging.runtime.session_store import SessionStore


class SessionManager:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    @staticmethod
    def session_scope_key(
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> str:
        if is_dm:
            return "discord:dm:{0}".format(channel_id)
        normalized = parent_channel_id or channel_id
        return "discord:channel:{0}".format(normalized)

    async def get(
        self,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> Optional[SessionRecord]:
        return await self.store.get(
            self.session_scope_key(channel_id, is_dm, parent_channel_id)
        )

    async def upsert(
        self,
        channel_id: str,
        is_dm: bool,
        agent_id: str,
        provider: str,
        provider_session_id: str,
        current_model: Optional[str],
        status: str = "active",
        parent_channel_id: Optional[str] = None,
    ) -> SessionRecord:
        session_key = self.session_scope_key(channel_id, is_dm, parent_channel_id)
        record = SessionRecord(
            agent_id=agent_id,
            provider=provider,
            provider_session_id=provider_session_id,
            current_model=current_model,
            last_activity_at=utc_now(),
            status=status,
        )
        return await self.store.upsert(session_key, record)

    async def touch(
        self,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> Optional[SessionRecord]:
        session_key = self.session_scope_key(channel_id, is_dm, parent_channel_id)
        record = await self.store.get(session_key)
        if record is None:
            return None
        record.last_activity_at = utc_now()
        return await self.store.upsert(session_key, record)

    async def update_model(
        self,
        channel_id: str,
        is_dm: bool,
        model: str,
        parent_channel_id: Optional[str] = None,
    ) -> Optional[SessionRecord]:
        session_key = self.session_scope_key(channel_id, is_dm, parent_channel_id)
        record = await self.store.get(session_key)
        if record is None:
            return None
        record.current_model = model
        record.last_activity_at = utc_now()
        return await self.store.upsert(session_key, record)

    async def clear(
        self,
        channel_id: str,
        is_dm: bool,
        parent_channel_id: Optional[str] = None,
    ) -> None:
        await self.store.delete(
            self.session_scope_key(channel_id, is_dm, parent_channel_id)
        )
