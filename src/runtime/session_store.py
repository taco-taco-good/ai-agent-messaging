from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Callable, Dict, Optional

from agent_messaging.core.models import SessionRecord


logger = logging.getLogger(__name__)


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._loaded = False
        self._cache: Dict[str, SessionRecord] = {}

    async def load(self) -> Dict[str, SessionRecord]:
        async with self._lock:
            await self._ensure_loaded()
            return dict(self._cache)

    async def get(self, session_key: str) -> Optional[SessionRecord]:
        async with self._lock:
            await self._ensure_loaded()
            return self._cache.get(session_key)

    async def upsert(self, session_key: str, record: SessionRecord) -> SessionRecord:
        async with self._lock:
            await self._ensure_loaded()
            self._cache[session_key] = record
            await self._persist()
            logger.info("session_upserted", extra={"session_key": session_key})
            return record

    async def delete(self, session_key: str) -> None:
        async with self._lock:
            await self._ensure_loaded()
            self._cache.pop(session_key, None)
            await self._persist()
            logger.info("session_deleted", extra={"session_key": session_key})

    async def delete_where(
        self,
        predicate: Callable[[str, SessionRecord], bool],
        *,
        reason: str,
    ) -> list[str]:
        async with self._lock:
            await self._ensure_loaded()
            removed = [
                session_key
                for session_key, record in self._cache.items()
                if predicate(session_key, record)
            ]
            if not removed:
                return []
            for session_key in removed:
                record = self._cache.pop(session_key)
                logger.info(
                    "startup_session_invalidated",
                    extra={
                        "session_key": session_key,
                        "provider": record.provider,
                        "provider_session_id": record.provider_session_id,
                        "reason": reason,
                    },
                )
            await self._persist()
            return removed

    def delete_where_sync(
        self,
        predicate: Callable[[str, SessionRecord], bool],
        *,
        reason: str,
    ) -> list[str]:
        raw = self._read_json()
        cache = {
            session_key: SessionRecord.from_dict(payload)
            for session_key, payload in raw.items()
        }
        removed = [
            session_key
            for session_key, record in cache.items()
            if predicate(session_key, record)
        ]
        if not removed:
            return []
        for session_key in removed:
            record = cache.pop(session_key)
            logger.info(
                "session_invalidated",
                extra={
                    "session_key": session_key,
                    "provider": record.provider,
                    "provider_session_id": record.provider_session_id,
                    "reason": reason,
                },
            )
        payload = {
            session_key: record.to_dict()
            for session_key, record in sorted(cache.items())
        }
        self._write_json(payload)
        return removed

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        raw = await asyncio.to_thread(self._read_json)
        self._cache = {
            session_key: SessionRecord.from_dict(payload)
            for session_key, payload in raw.items()
        }
        self._loaded = True
        logger.info("session_store_loaded", extra={"path": str(self.path), "count": len(self._cache)})

    async def _persist(self) -> None:
        payload = {
            session_key: record.to_dict()
            for session_key, record in sorted(self._cache.items())
        }
        await asyncio.to_thread(self._write_json, payload)

    def _read_json(self) -> Dict[str, dict]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")
        return json.loads(self.path.read_text(encoding="utf-8") or "{}")

    def _write_json(self, payload: Dict[str, dict]) -> None:
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, self.path)
        logger.info("session_store_persisted", extra={"path": str(self.path), "count": len(payload)})
