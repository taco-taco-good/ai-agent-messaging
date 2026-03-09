from __future__ import annotations

from typing import Dict, Iterable

from agent_messaging.core.errors import AgentNotFoundError
from agent_messaging.core.models import AgentConfig


class AgentRegistry:
    def __init__(self, agents: Dict[str, AgentConfig]) -> None:
        self._agents = dict(agents)

    def get(self, agent_id: str) -> AgentConfig:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise AgentNotFoundError("Unknown agent_id: {0}".format(agent_id)) from exc

    def all(self) -> Iterable[AgentConfig]:
        return self._agents.values()
