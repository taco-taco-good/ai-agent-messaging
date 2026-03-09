from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml

from agent_messaging.runtime.tools import ToolRuntime


@dataclass(frozen=True)
class ExternalToolDefinition:
    tool_id: str
    capabilities: List[str]
    command: List[str]
    working_dir: Path
    timeout_seconds: float


def load_external_tools(tools_dir: Path, tool_runtime: ToolRuntime) -> Dict[str, ExternalToolDefinition]:
    loaded: Dict[str, ExternalToolDefinition] = {}
    if not tools_dir.exists():
        return loaded

    for tool_yaml in sorted(tools_dir.glob("*/tool.yaml")):
        raw = yaml.safe_load(tool_yaml.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            continue
        tool_id = str(raw.get("id", "")).strip()
        entry = raw.get("entry") or {}
        capabilities = raw.get("capabilities") or []
        command = list((entry.get("command") or [])) if isinstance(entry, dict) else []
        if (
            not tool_id
            or not command
            or not isinstance(capabilities, list)
            or not all(isinstance(item, str) for item in command)
            or not all(isinstance(item, str) for item in capabilities)
        ):
            continue
        definition = ExternalToolDefinition(
            tool_id=tool_id,
            capabilities=[str(item) for item in capabilities],
            command=[str(item) for item in command],
            working_dir=tool_yaml.parent,
            timeout_seconds=_parse_timeout_seconds(raw.get("timeout_seconds")),
        )
        loaded[tool_id] = definition
        for capability in definition.capabilities:
            tool_runtime.register(
                "{0}.{1}".format(tool_id, capability),
                _make_command_handler(definition, capability),
            )
    return loaded


def _make_command_handler(definition: ExternalToolDefinition, capability: str):
    async def _handler(params, context):
        payload = {
            "capability": capability,
            "params": params,
            "context": context,
        }
        return await asyncio.to_thread(_run_external_tool, definition, capability, payload)

    return _handler


def _run_external_tool(
    definition: ExternalToolDefinition,
    capability: str,
    payload: Dict[str, object],
) -> Dict[str, object]:
    try:
        result = subprocess.run(
            definition.command,
            cwd=definition.working_dir,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            timeout=definition.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "External tool `{0}.{1}` timed out after {2:g}s.".format(
                definition.tool_id,
                capability,
                definition.timeout_seconds,
            )
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(
            "External tool `{0}.{1}` failed: {2}".format(definition.tool_id, capability, detail)
        )
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "External tool `{0}.{1}` returned invalid JSON.".format(
                definition.tool_id, capability
            )
        ) from exc


def _parse_timeout_seconds(value: object) -> float:
    if value is None:
        return 60.0
    try:
        timeout_seconds = float(value)
    except (TypeError, ValueError):
        return 60.0
    if timeout_seconds <= 0:
        return 60.0
    return timeout_seconds
