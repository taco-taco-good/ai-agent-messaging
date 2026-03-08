from __future__ import annotations

import inspect
from typing import Any, Callable, Dict

from agent_messaging.core.errors import ToolNotFoundError


class ToolRuntime:
    def __init__(self) -> None:
        self._tools: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, handler: Callable[..., Any]) -> None:
        self._tools[name] = handler

    async def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        try:
            handler = self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError("Unknown tool: {0}".format(name)) from exc
        result = handler(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
