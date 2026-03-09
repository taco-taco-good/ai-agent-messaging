from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from agent_messaging.config.registry import AgentRegistry
from agent_messaging.core.errors import AgentMessagingError
from agent_messaging.core.models import FrontmatterMetadata
from agent_messaging.jobs.registry import JobRegistry
from agent_messaging.jobs.store import JobStore
from agent_messaging.memory.writer import MemoryWriter
from agent_messaging.providers.base import CLIWrapper
from agent_messaging.runtime.delivery import DeliveryRuntime
from agent_messaging.runtime.tools import ToolRuntime
from agent_messaging.runtime.transport import chunk_text
from agent_messaging.skills.models import SkillDefinition
from agent_messaging.tools import register_job_builtin_tools


logger = logging.getLogger(__name__)


class JobExecutionError(AgentMessagingError):
    error_code = "job_execution_error"


class JobRuntime:
    def __init__(
        self,
        registry: JobRegistry,
        tool_runtime: ToolRuntime,
        store: JobStore,
        *,
        agent_registry: Optional[AgentRegistry] = None,
        provider_factory: Optional[Any] = None,
        delivery_runtime: Optional[DeliveryRuntime] = None,
        memory_writer: Optional[MemoryWriter] = None,
        runtime_dir: Optional[Path] = None,
        skills: Optional[Dict[str, SkillDefinition]] = None,
    ) -> None:
        self.registry = registry
        self.tool_runtime = tool_runtime
        self.store = store
        self.agent_registry = agent_registry
        self.provider_factory = provider_factory
        self.delivery_runtime = delivery_runtime or DeliveryRuntime()
        self.memory_writer = memory_writer or MemoryWriter()
        self.runtime_dir = runtime_dir or Path.cwd()
        self.skills = dict(skills or {})
        self._locks: Dict[str, asyncio.Lock] = {}
        self._register_builtin_tools()
        self.store.register_jobs(self.registry.all())

    async def run_job(
        self,
        job_id: str,
        *,
        scheduled_for: Optional[datetime] = None,
        trigger: str = "manual",
    ):
        job = self.registry.get(job_id)
        if not job.enabled:
            raise JobExecutionError("Job `{0}` is disabled.".format(job_id))

        lock = self._locks.setdefault(job_id, asyncio.Lock())
        async with lock:
            if scheduled_for is not None:
                already_ran = await asyncio.to_thread(self.store.has_run_for_slot, job_id, scheduled_for)
                if already_ran:
                    logger.info("job_slot_already_processed", extra={"job_id": job_id})
                    return None

            run = await asyncio.to_thread(self.store.start_run, job_id, scheduled_for, trigger)
            skill = self.skills.get(job.skill_id or "") if job.skill_id else None
            context: Dict[str, Any] = {
                "job": asdict(job),
                "skill": asdict(skill) if skill is not None else None,
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
                for step in job.steps:
                    if not self._should_run(step.when, context):
                        continue
                    payload = self._resolve_structure(step.parameters, context)
                    result = await self.tool_runtime.call(step.tool, payload, context)
                    normalized = self._normalize_result(result)
                    context["steps"][step.id] = normalized
                    await asyncio.to_thread(self.store.write_artifact, run.run_id, job.id, step.id, normalized)
                await asyncio.to_thread(self.store.finish_run, run.run_id, status="succeeded", message="")
                return context
            except Exception as exc:
                await asyncio.to_thread(self.store.finish_run, run.run_id, status="failed", message=str(exc))
                raise

    def register_delivery_sender(self, agent_id: str, sender: Any) -> None:
        self.delivery_runtime.register(agent_id, sender)

    def register_job(self, job) -> None:
        self.registry.register(job)
        self.store.register_jobs([job])

    def _register_builtin_tools(self) -> None:
        register_job_builtin_tools(
            self.tool_runtime,
            noop=lambda params, context: {"params": params, "context": context["run"]},
            sqlite_query=self._tool_sqlite_query,
            render_template=self._tool_render_template,
            run_agent_prompt=self._tool_run_agent_prompt,
            send_discord_message=self._tool_send_discord_message,
            persist_text=self._tool_persist_text,
            persist_memory=self._tool_persist_memory,
        )

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
            raise JobExecutionError("job.render_template requires `template`.")
        return {"content": self._resolve_structure(template, context)}

    async def _tool_run_agent_prompt(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        if self.agent_registry is None or self.provider_factory is None:
            raise JobExecutionError("Agent execution is not configured for job runtime.")

        agent_id = str(params.get("agent_id") or context["job"]["agent_id"])
        prompt = params.get("prompt")
        skill_body = ((context.get("skill") or {}).get("body") if context.get("skill") else None) or ""
        if prompt is None and not skill_body:
            raise JobExecutionError("job.run_agent_prompt requires `prompt` or linked skill content.")
        final_prompt = str(prompt or "")
        if skill_body:
            final_prompt = "{0}\n\nContext:\n{1}".format(skill_body.strip(), final_prompt).strip()

        agent = self.agent_registry.get(agent_id)
        wrapper: CLIWrapper = self.provider_factory(agent, "job:{0}:{1}".format(context["job"]["id"], context["run"]["id"]), None)
        await wrapper.start()
        try:
            parts = []
            async for piece in wrapper.send_user_message(final_prompt):
                parts.append(piece)
            response = "".join(parts)
        finally:
            await wrapper.stop()
        return {"response": response, "chunks": chunk_text(response, limit=1900)}

    async def _tool_send_discord_message(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        channel_id = str(params.get("channel_id") or context["job"]["output"]["channel_id"] or "")
        if not channel_id:
            raise JobExecutionError("Discord delivery requires `channel_id`.")
        content = params.get("content")
        if content is None:
            raise JobExecutionError("Discord delivery requires `content`.")
        chunks = content if isinstance(content, list) else chunk_text(str(content), limit=1900)
        await self.delivery_runtime.send(str(context["job"]["agent_id"]), channel_id, chunks)
        return {"channel_id": channel_id, "chunk_count": len(chunks)}

    async def _tool_persist_text(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        path_value = params.get("path") or context["job"]["output"]["artifact_path"]
        content = params.get("content")
        if not path_value or content is None:
            raise JobExecutionError("Persist step requires `path` and `content`.")
        path = Path(str(path_value))
        if not path.is_absolute():
            path = (self.runtime_dir / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, str(content), encoding="utf-8")
        return {"path": str(path)}

    async def _tool_persist_memory(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        if self.agent_registry is None:
            raise JobExecutionError("Memory persistence requires agent registry.")
        agent = self.agent_registry.get(str(context["job"]["agent_id"]))
        content = params.get("content")
        if content is None:
            raise JobExecutionError("Memory persistence requires `content`.")

        raw_tags = params.get("tags") or ["job", str(context["job"]["id"])]
        if not isinstance(raw_tags, list):
            raise JobExecutionError("Memory persistence `tags` must be a list.")
        tags = [str(tag) for tag in raw_tags]
        topic = str(params.get("topic") or context["job"]["description"] or context["job"]["id"])
        summary = str(params.get("summary") or "")
        status = str(params.get("status") or "succeeded")
        job_id = str(params.get("job_id") or context["job"]["id"])
        timestamp = datetime.fromisoformat(str(context["now"]))

        path = await asyncio.to_thread(
            self.memory_writer.write_job_run,
            agent_id=agent.agent_id,
            display_name=agent.display_name or agent.agent_id,
            memory_dir=agent.memory_dir,
            job_id=job_id,
            run_id=int(context["run"]["id"]),
            content=str(content),
            status=status,
            metadata=FrontmatterMetadata(tags=tags, topic=topic, summary=summary),
            timestamp=timestamp,
        )
        return {"path": str(path), "job_id": job_id}
