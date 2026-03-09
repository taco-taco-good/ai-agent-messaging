from __future__ import annotations

import logging
import uuid
from typing import Dict

from agent_messaging.core.errors import InteractionValidationError
from agent_messaging.core.models import PendingInteraction


logger = logging.getLogger(__name__)


class PendingInteractionStore:
    def __init__(self) -> None:
        self._pending: Dict[str, PendingInteraction] = {}

    def create(
        self,
        agent_id: str,
        command: str,
        session_key: str,
    ) -> PendingInteraction:
        pending = PendingInteraction(
            request_id=str(uuid.uuid4()),
            agent_id=agent_id,
            command=command,
            session_key=session_key,
        )
        self._pending[pending.request_id] = pending
        logger.info(
            "pending_interaction_created",
            extra={
                "agent_id": agent_id,
                "command": command,
                "request_id": pending.request_id,
                "session_key": session_key,
            },
        )
        return pending

    def consume(
        self,
        request_id: str,
        agent_id: str,
        command: str,
        session_key: str,
    ) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            raise InteractionValidationError("Interactive command request mismatch.")
        if pending.agent_id != agent_id:
            raise InteractionValidationError("Interactive command agent mismatch.")
        if pending.command != command:
            raise InteractionValidationError("Interactive command payload mismatch.")
        if pending.session_key != session_key:
            raise InteractionValidationError("Interactive command session mismatch.")
        logger.info(
            "pending_interaction_consumed",
            extra={
                "agent_id": agent_id,
                "command": command,
                "request_id": request_id,
                "session_key": session_key,
            },
        )

    def clear(self) -> None:
        self._pending.clear()
