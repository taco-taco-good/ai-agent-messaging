from __future__ import annotations


class DeliveryRuntime:
    def __init__(self) -> None:
        self._senders = {}

    def register(self, agent_id: str, sender) -> None:
        self._senders[agent_id] = sender

    async def send(self, agent_id: str, channel_id: str, chunks: list[str]) -> None:
        try:
            sender = self._senders[agent_id]
        except KeyError as exc:
            raise RuntimeError(
                "No Discord sender registered for agent `{0}`.".format(agent_id)
            ) from exc
        await sender(channel_id, chunks)


__all__ = ["DeliveryRuntime"]
