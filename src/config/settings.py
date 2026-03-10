from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import yaml

from agent_messaging.core.errors import AgentMessagingError
from agent_messaging.core.models import AgentConfig


class SettingsError(AgentMessagingError):
    """Raised when configuration is invalid."""

    error_code = "settings_error"


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppSettings:
    agents: Dict[str, AgentConfig]
    runtime_dir: Path
    jobs_dir: Path
    skills_dir: Path
    subagents_dir: Path
    tools_dir: Path
    job_store_path: Path


def load_settings(config_path: Path) -> AppSettings:
    logger.info("load_settings", extra={"config_path": str(config_path)})
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raw_agents = raw.get("agents")
    if not isinstance(raw_agents, dict) or not raw_agents:
        raise SettingsError("`agents` must be a non-empty mapping in config.")

    agents: Dict[str, AgentConfig] = {}
    base_dir = config_path.parent
    for agent_id, payload in raw_agents.items():
        if not isinstance(payload, dict):
            raise SettingsError("Each agent config must be a mapping.")

        provider = payload.get("provider") or payload.get("cli_type")
        if not provider:
            raise SettingsError("Each agent requires `provider` or `cli_type`.")

        discord_token = _resolve_discord_token(payload)
        workspace_dir = _resolve_path(
            base_dir,
            payload.get("workspace_dir") or payload.get("workdir"),
        )
        memory_dir = _resolve_path(base_dir, payload.get("memory_dir"))
        persona_file = _resolve_optional_path(base_dir, payload.get("persona_file"))
        persona = _resolve_persona(base_dir, payload, persona_file)

        agents[agent_id] = AgentConfig(
            agent_id=agent_id,
            display_name=payload.get("display_name"),
            provider=str(provider),
            discord_token=discord_token,
            workspace_dir=workspace_dir,
            memory_dir=memory_dir,
            model=payload.get("model"),
            persona=persona,
            persona_file=persona_file,
            cli_args=[str(item) for item in payload.get("cli_args", [])],
        )
        logger.info(
            "agent_config_loaded",
            extra={"agent_id": agent_id, "provider": str(provider)},
        )

    runtime_dir = _resolve_path(base_dir, raw.get("runtime_dir", "../runtime"))
    jobs_dir = _resolve_path(base_dir, raw.get("jobs_dir", "../jobs"))
    skills_dir = _resolve_path(base_dir, raw.get("skills_dir", "../skills"))
    subagents_dir = _resolve_path(base_dir, raw.get("subagents_dir", "../agents"))
    tools_dir = _resolve_path(base_dir, raw.get("tools_dir", "../tools"))
    job_store_path = _resolve_path(
        base_dir,
        raw.get("job_store_path", "../runtime/jobs.sqlite"),
    )
    return AppSettings(
        agents=agents,
        runtime_dir=runtime_dir,
        jobs_dir=jobs_dir,
        skills_dir=skills_dir,
        subagents_dir=subagents_dir,
        tools_dir=tools_dir,
        job_store_path=job_store_path,
    )


def _resolve_discord_token(payload: Dict[str, object]) -> str:
    token = payload.get("discord_token")
    if token:
        return str(token)
    raise SettingsError("Each agent requires `discord_token`.")


def _resolve_path(base_dir: Path, value: object) -> Path:
    if not value:
        raise SettingsError("Expected a filesystem path in config.")
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _resolve_optional_path(base_dir: Path, value: object) -> Path | None:
    if not value:
        return None
    return _resolve_path(base_dir, value)


def _resolve_persona(
    base_dir: Path,
    payload: Dict[str, object],
    persona_file: Path | None,
) -> str:
    if persona_file is not None:
        try:
            return persona_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise SettingsError(
                "Persona file does not exist: {0}".format(persona_file)
            ) from exc

    persona = payload.get("persona", "")
    if not isinstance(persona, str):
        raise SettingsError("`persona` must be a string when provided.")
    del base_dir
    return persona
