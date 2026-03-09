from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict

import yaml

from agent_messaging.config.settings import SettingsError
from agent_messaging.tasks.models import ALLOWED_STEP_TYPES, TaskDefinition, TaskOutput, TaskSchedule, TaskStep

_SAFE_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def load_tasks(tasks_dir: Path) -> Dict[str, TaskDefinition]:
    if not tasks_dir.exists():
        return {}

    tasks: Dict[str, TaskDefinition] = {}
    for path in sorted(tasks_dir.glob("*.yml")) + sorted(tasks_dir.glob("*.yaml")):
        task = _load_task_document(path)
        tasks[task.id] = task
    return tasks


def _load_task_document(path: Path) -> TaskDefinition:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SettingsError("Task document must be a mapping: {0}".format(path))

    schedule = raw.get("schedule")
    if not isinstance(schedule, dict):
        raise SettingsError("Task requires `schedule` mapping: {0}".format(path))

    allowed_tools = raw.get("allowed_tools") or []
    if not isinstance(allowed_tools, list) or not all(isinstance(item, str) for item in allowed_tools):
        raise SettingsError("`allowed_tools` must be a list of strings: {0}".format(path))

    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise SettingsError("Task requires non-empty `steps`: {0}".format(path))

    parsed_steps = [_parse_step(step, allowed_tools, path) for step in steps]
    task_id = _require_string(raw, "id", path)
    _validate_identifier(task_id, label="task id", path=path)
    return TaskDefinition(
        id=task_id,
        description=str(raw.get("description", "")).strip(),
        agent_id=_require_string(raw, "agent", path),
        enabled=bool(raw.get("enabled", True)),
        schedule=TaskSchedule(
            kind=_require_string(schedule, "kind", path),
            expr=_require_string(schedule, "expr", path),
            timezone=str(schedule.get("timezone", "UTC")),
        ),
        allowed_tools=list(allowed_tools),
        steps=parsed_steps,
        output=_parse_output(raw.get("output"), path),
        source_path=path,
    )


def _parse_step(payload: Any, allowed_tools: list[str], path: Path) -> TaskStep:
    if not isinstance(payload, dict):
        raise SettingsError("Each task step must be a mapping: {0}".format(path))
    step_type = _require_string(payload, "type", path)
    if step_type not in ALLOWED_STEP_TYPES:
        raise SettingsError(
            "Unsupported step type `{0}` in {1}".format(step_type, path)
        )
    tool = _require_string(payload, "tool", path)
    if allowed_tools and tool not in allowed_tools:
        raise SettingsError(
            "Step tool `{0}` must appear in allowed_tools for {1}".format(tool, path)
        )
    raw_parameters = payload.get("with", {})
    if not isinstance(raw_parameters, dict):
        raise SettingsError("Step `with` must be a mapping: {0}".format(path))
    step_id = _require_string(payload, "id", path)
    _validate_identifier(step_id, label="step id", path=path)
    return TaskStep(
        id=step_id,
        type=step_type,
        tool=tool,
        parameters=raw_parameters,
        when=str(payload["when"]) if payload.get("when") is not None else None,
    )


def _parse_output(payload: Any, path: Path) -> TaskOutput:
    if payload is None:
        return TaskOutput()
    if not isinstance(payload, dict):
        raise SettingsError("Task `output` must be a mapping: {0}".format(path))
    return TaskOutput(
        channel_id=str(payload["channel_id"]) if payload.get("channel_id") is not None else None,
        artifact_path=str(payload["artifact_path"]) if payload.get("artifact_path") is not None else None,
    )


def _require_string(payload: Dict[str, Any], key: str, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SettingsError("Task requires string `{0}` in {1}".format(key, path))
    return value.strip()


def _validate_identifier(value: str, *, label: str, path: Path) -> None:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise SettingsError(
            "Invalid {0} `{1}` in {2}. Use lowercase slug, digits, `_`, `-`.".format(
                label,
                value,
                path,
            )
        )
