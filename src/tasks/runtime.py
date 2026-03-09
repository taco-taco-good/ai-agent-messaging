from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from agent_messaging.core.errors import AgentMessagingError, ToolNotFoundError
from agent_messaging.config.registry import AgentRegistry
from agent_messaging.providers.base import CLIWrapper
from agent_messaging.runtime.delivery import DeliveryRuntime
from agent_messaging.runtime.tools import ToolRuntime
from agent_messaging.runtime.transport import chunk_text
from agent_messaging.tasks.registry import TaskRegistry
from agent_messaging.tasks.store import TaskStore


logger = logging.getLogger(__name__)


class TaskExecutionError(AgentMessagingError):
    error_code = "task_execution_error"


class TaskRuntime:
    def __init__(
        self,
        registry: TaskRegistry,
        tool_runtime: ToolRuntime,
        store: TaskStore,
        *,
        agent_registry: Optional[AgentRegistry] = None,
        provider_factory: Optional[Any] = None,
        delivery_runtime: Optional[DeliveryRuntime] = None,
        runtime_dir: Optional[Path] = None,
    ) -> None:
        self.registry = registry
        self.tool_runtime = tool_runtime
        self.store = store
        self.agent_registry = agent_registry
        self.provider_factory = provider_factory
        self.delivery_runtime = delivery_runtime or DeliveryRuntime()
        self.runtime_dir = runtime_dir or Path.cwd()
        self._locks: Dict[str, asyncio.Lock] = {}
        self._register_builtin_tools()
        self.store.register_tasks(self.registry.all())

    async def run_task(
        self,
        task_id: str,
        *,
        scheduled_for: Optional[datetime] = None,
        trigger: str = "manual",
    ):
        task = self.registry.get(task_id)
        if not task.enabled:
            raise TaskExecutionError("Task `{0}` is disabled.".format(task_id))

        lock = self._locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            if scheduled_for is not None:
                already_ran = await asyncio.to_thread(
                    self.store.has_run_for_slot,
                    task_id,
                    scheduled_for,
                )
                if already_ran:
                    logger.info("task_slot_already_processed", extra={"task_id": task_id})
                    return None

            run = await asyncio.to_thread(self.store.start_run, task_id, scheduled_for, trigger)
            context: Dict[str, Any] = {
                "task": asdict(task),
                "run": {
                    "id": run.run_id,
                    "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
                    "trigger": trigger,
                },
                "steps": {},
                "artifacts": [],
                "now": run.started_at.isoformat(),
            }
            try:
                for step in task.steps:
                    if not self._should_run(step.when, context):
                        continue
                    payload = self._resolve_structure(step.parameters, context)
                    result = await self.tool_runtime.call(step.tool, payload, context)
                    normalized = self._normalize_result(result)
                    context["steps"][step.id] = normalized
                    await asyncio.to_thread(
                        self.store.write_artifact,
                        run.run_id,
                        task.id,
                        step.id,
                        normalized,
                    )
                await asyncio.to_thread(self.store.finish_run, run.run_id, status="succeeded", message="")
                return context
            except Exception as exc:
                await asyncio.to_thread(
                    self.store.finish_run,
                    run.run_id,
                    status="failed",
                    message=str(exc),
                )
                raise

    def register_delivery_sender(self, agent_id: str, sender: Any) -> None:
        self.delivery_runtime.register(agent_id, sender)

    def register_task(self, task) -> None:
        self.registry.register(task)
        self.store.register_tasks([task])

    def _register_builtin_tools(self) -> None:
        self.tool_runtime.register("task.noop", lambda params, context: {"params": params, "context": context["run"]})
        self.tool_runtime.register("task.sqlite_query", self._tool_sqlite_query)
        self.tool_runtime.register("task.render_template", self._tool_render_template)
        self.tool_runtime.register("task.run_agent_prompt", self._tool_run_agent_prompt)
        self.tool_runtime.register("task.send_discord_message", self._tool_send_discord_message)
        self.tool_runtime.register("task.persist_text", self._tool_persist_text)

    def _should_run(self, when: Optional[str], context: Dict[str, Any]) -> bool:
        if not when:
            return True
        resolved = self._resolve_reference(when, context)
        return bool(resolved)

    def _normalize_result(self, result: Any) -> Dict[str, Any]:
        if result is None:
            return {}
        if isinstance(result, dict):
            return result
        return {"value": result}

    def _resolve_structure(self, value: Any, context: Dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {key: self._resolve_structure(item, context) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_structure(item, context) for item in value]
        if isinstance(value, str):
            return self._render_string(value, context)
        return value

    def _render_string(self, text: str, context: Dict[str, Any]) -> Any:
        if text.startswith("{{") and text.endswith("}}") and text.count("{{") == 1:
            return self._resolve_reference(text[2:-2].strip(), context)

        rendered = text
        start = rendered.find("{{")
        while start != -1:
            end = rendered.find("}}", start)
            if end == -1:
                break
            expression = rendered[start + 2 : end].strip()
            resolved = self._resolve_reference(expression, context)
            rendered = "{0}{1}{2}".format(rendered[:start], "" if resolved is None else resolved, rendered[end + 2 :])
            start = rendered.find("{{")
        return rendered

    def _resolve_reference(self, expression: str, context: Dict[str, Any]) -> Any:
        current: Any = context
        for part in expression.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    async def _tool_sqlite_query(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        database_path = Path(str(params["database_path"]))
        sql = str(params["sql"])
        query_params = params.get("params", [])

        def _read_rows() -> Dict[str, Any]:
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
            try:
                rows = connection.execute(sql, query_params).fetchall()
                return {"rows": [dict(row) for row in rows], "count": len(rows)}
            finally:
                connection.close()

        del context
        return await asyncio.to_thread(_read_rows)

    async def _tool_render_template(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        template = params.get("template")
        if template is None:
            raise TaskExecutionError("task.render_template requires `template`.")
        return {"content": self._resolve_structure(template, context)}

    async def _tool_run_agent_prompt(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        if self.agent_registry is None or self.provider_factory is None:
            raise TaskExecutionError("Agent execution is not configured for task runtime.")

        agent_id = str(params.get("agent_id") or context["task"]["agent_id"])
        prompt = str(params["prompt"])
        agent = self.agent_registry.get(agent_id)
        wrapper: CLIWrapper = self.provider_factory(agent, "task:{0}:{1}".format(context["task"]["id"], context["run"]["id"]), None)
        await wrapper.start()
        try:
            parts = []
            async for piece in wrapper.send_user_message(prompt):
                parts.append(piece)
            response = "".join(parts)
        finally:
            await wrapper.stop()
        return {"response": response, "chunks": chunk_text(response, limit=1900)}

    async def _tool_send_discord_message(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        channel_id = str(params.get("channel_id") or context["task"]["output"]["channel_id"] or "")
        if not channel_id:
            raise TaskExecutionError("Discord delivery requires `channel_id`.")
        content = params.get("content")
        if content is None:
            raise TaskExecutionError("Discord delivery requires `content`.")
        chunks = content if isinstance(content, list) else chunk_text(str(content), limit=1900)
        await self.delivery_runtime.send(str(context["task"]["agent_id"]), channel_id, chunks)
        return {"channel_id": channel_id, "chunk_count": len(chunks)}

    async def _tool_persist_text(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        path_value = params.get("path") or context["task"]["output"]["artifact_path"]
        content = params.get("content")
        if not path_value or content is None:
            raise TaskExecutionError("Persist step requires `path` and `content`.")
        path = Path(str(path_value))
        if not path.is_absolute():
            path = (self.runtime_dir / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, str(content), encoding="utf-8")
        return {"path": str(path)}
