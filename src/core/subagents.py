from __future__ import annotations

import json
import shutil
import textwrap
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from agent_messaging.core.errors import AgentMessagingError
from agent_messaging.core.models import AgentConfig
from agent_messaging.memory.init_docs import materialize_init_doc


class SubagentError(AgentMessagingError):
    error_code = "subagent_error"


class SubagentPersonaNotFound(SubagentError):
    error_code = "subagent_persona_not_found"


@dataclass(frozen=True)
class SubagentPersona:
    persona_id: str
    name: str
    description: str
    instructions: str
    source_path: Path
    source_format: str
    model: Optional[str] = None
    tools: tuple[str, ...] = field(default_factory=tuple)
    max_turns: Optional[int] = None
    timeout_mins: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def render_persona(self) -> str:
        sections = []
        if self.description:
            sections.append("## Role\n{0}".format(self.description))
        if self.tools:
            sections.append(
                "## Preferred Tools\n- {0}".format("\n- ".join(self.tools))
            )
        if self.max_turns is not None or self.timeout_mins is not None:
            constraints = []
            if self.max_turns is not None:
                constraints.append("max_turns={0}".format(self.max_turns))
            if self.timeout_mins is not None:
                constraints.append("timeout_mins={0}".format(self.timeout_mins))
            sections.append("## Constraints\n- {0}".format("\n- ".join(constraints)))
        sections.append("## Instructions\n{0}".format(self.instructions.strip()))
        return "\n\n".join(section for section in sections if section.strip()).strip()


class SubagentPersonaStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def load(self, persona_id: str) -> SubagentPersona:
        for path in self._candidate_paths(persona_id):
            if path.exists():
                return self._parse(path)
        raise SubagentPersonaNotFound(
            "Unknown subagent persona: {0}".format(persona_id)
        )

    def _candidate_paths(self, persona_id: str) -> list[Path]:
        stem = persona_id if persona_id.endswith(".md") else "{0}.md".format(persona_id)
        parent = self.root_dir.parent
        return [
            self.root_dir / stem,
            self.root_dir / ".claude" / "agents" / stem,
            self.root_dir / ".gemini" / "agents" / stem,
            parent / ".claude" / "agents" / stem,
            parent / ".gemini" / "agents" / stem,
        ]

    def _parse(self, path: Path) -> SubagentPersona:
        raw = path.read_text(encoding="utf-8").strip()
        frontmatter, body = _split_frontmatter(raw)
        source_format = _detect_format(path)
        persona_id = str(frontmatter.get("id") or frontmatter.get("name") or path.stem)
        name = str(frontmatter.get("name") or persona_id)
        description = str(frontmatter.get("description") or frontmatter.get("summary") or "")
        model = _coerce_optional_str(frontmatter.get("model"))
        tools = _coerce_tools(frontmatter.get("tools"))
        max_turns = _coerce_optional_int(frontmatter.get("max_turns"))
        timeout_mins = _coerce_optional_int(
            frontmatter.get("timeout_mins", frontmatter.get("timeout"))
        )
        return SubagentPersona(
            persona_id=persona_id,
            name=name,
            description=description,
            instructions=body.strip() or raw,
            source_path=path,
            source_format=source_format,
            model=model,
            tools=tools,
            max_turns=max_turns,
            timeout_mins=timeout_mins,
            metadata=dict(frontmatter),
        )


class SubagentRuntime:
    def __init__(
        self,
        *,
        persona_store: SubagentPersonaStore,
        runtime_dir: Path,
        skills_dir: Path,
        provider_factory,
    ) -> None:
        self.persona_store = persona_store
        self.runtime_dir = runtime_dir
        self.skills_dir = skills_dir
        self.provider_factory = provider_factory

    async def run(
        self,
        *,
        agent: AgentConfig,
        persona_id: str,
        task: str,
        context: Any = None,
        skills: Optional[list[str]] = None,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        persona = self.persona_store.load(persona_id)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4().hex
        root_dir = agent.workspace_dir / ".subagents" / run_id
        try:
            workspace_dir = root_dir / "workspace"
            memory_dir = root_dir / "memory"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_dir.mkdir(parents=True, exist_ok=True)
            persona_file = workspace_dir / "{0}.md".format(persona.persona_id)
            persona_file.write_text(persona.render_persona(), encoding="utf-8")

            child_agent = AgentConfig(
                agent_id="{0}-subagent-{1}".format(agent.agent_id, persona.persona_id),
                display_name=persona.name,
                provider=agent.provider,
                discord_token=agent.discord_token,
                workspace_dir=workspace_dir,
                memory_dir=memory_dir,
                model=model or persona.model or agent.model,
                persona=persona.render_persona(),
                persona_file=persona_file,
                cli_args=list(agent.cli_args),
            )
            materialize_init_doc(child_agent)
            wrapper = self.provider_factory(
                child_agent,
                "subagent:{0}".format(uuid.uuid4().hex),
                None,
            )
            try:
                chunks = []
                async for chunk in wrapper.send_user_message(
                    _build_subagent_task(
                        persona=persona,
                        task=task,
                        context=context,
                        skill_paths=self._resolve_skill_paths(skills or []),
                    )
                ):
                    chunks.append(chunk)
            finally:
                await wrapper.stop()
        finally:
            shutil.rmtree(root_dir, ignore_errors=True)

        return {
            "persona_id": persona.persona_id,
            "name": persona.name,
            "description": persona.description,
            "source_path": str(persona.source_path),
            "source_format": persona.source_format,
            "response": "".join(chunks),
            "model": child_agent.model or "",
            "workspace_root": str(root_dir),
        }

    def _resolve_skill_paths(self, skills: list[str]) -> list[Path]:
        resolved = []
        for skill in skills:
            candidate = Path(skill)
            if candidate.is_absolute():
                resolved.append(candidate)
                continue
            if candidate.suffix != ".md":
                candidate = candidate.with_suffix(".md")
            resolved.append((self.skills_dir / candidate).resolve())
        return resolved


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    marker = "\n---\n"
    end = raw.find(marker, 4)
    if end < 0:
        return {}, raw
    frontmatter_text = raw[4:end]
    body = raw[end + len(marker):]
    payload = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(payload, dict):
        raise SubagentError("Subagent frontmatter must be a mapping.")
    return dict(payload), body


def _detect_format(path: Path) -> str:
    parts = path.parts
    if ".claude" in parts and "agents" in parts:
        return "claude"
    if ".gemini" in parts and "agents" in parts:
        return "gemini"
    return "generic"


def _coerce_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_tools(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
        return tuple(item for item in items if item)
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _build_subagent_task(
    *,
    persona: SubagentPersona,
    task: str,
    context: Any,
    skill_paths: list[Path],
) -> str:
    blocks = [
        "You are an ephemeral subagent. Follow the persona instructions below and return only the final result.",
        "## Persona\n{0}".format(persona.render_persona()),
    ]
    blocks.append("## Task\n{0}".format(task.strip()))
    if context not in (None, "", {}):
        blocks.append("## Context\n{0}".format(_render_context(context)))
    if skill_paths:
        blocks.append(
            "## Referenced Skills\nUse these existing skill files if they help:\n- {0}".format(
                "\n- ".join(str(path) for path in skill_paths)
            )
        )
    return "\n\n".join(blocks)


def _render_context(context: Any) -> str:
    if isinstance(context, str):
        return context.strip()
    if isinstance(context, Mapping):
        return json.dumps(dict(context), ensure_ascii=False, indent=2, sort_keys=True)
    if isinstance(context, list):
        return json.dumps(context, ensure_ascii=False, indent=2)
    return textwrap.dedent(str(context)).strip()
