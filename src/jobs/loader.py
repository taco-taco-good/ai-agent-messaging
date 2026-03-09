from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict

import yaml

from agent_messaging.config.settings import SettingsError
from agent_messaging.jobs.models import ALLOWED_STEP_TYPES, JobDefinition, JobOutput, JobSchedule, JobStep

_SAFE_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def load_jobs(jobs_dir: Path) -> Dict[str, JobDefinition]:
    if not jobs_dir.exists():
        return {}

    jobs: Dict[str, JobDefinition] = {}
    for path in sorted(jobs_dir.glob("*.yml")) + sorted(jobs_dir.glob("*.yaml")):
        job = _load_job_document(path)
        jobs[job.id] = job
    return jobs


def _load_job_document(path: Path) -> JobDefinition:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SettingsError("Job document must be a mapping: {0}".format(path))

    schedule = raw.get("schedule")
    if not isinstance(schedule, dict):
        raise SettingsError("Job requires `schedule` mapping: {0}".format(path))

    allowed_tools = raw.get("allowed_tools") or []
    if not isinstance(allowed_tools, list) or not all(isinstance(item, str) for item in allowed_tools):
        raise SettingsError("`allowed_tools` must be a list of strings: {0}".format(path))

    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise SettingsError("Job requires non-empty `steps`: {0}".format(path))

    parsed_steps = [_parse_step(step, allowed_tools, path) for step in steps]
    job_id = _require_string(raw, "id", path)
    _validate_identifier(job_id, label="job id", path=path)
    skill_id = str(raw.get("skill")).strip() if raw.get("skill") is not None else None
    if skill_id:
        _validate_identifier(skill_id, label="skill id", path=path)

    return JobDefinition(
        id=job_id,
        description=str(raw.get("description", "")).strip(),
        agent_id=_require_string(raw, "agent", path),
        enabled=bool(raw.get("enabled", True)),
        schedule=JobSchedule(
            kind=_require_string(schedule, "kind", path),
            expr=_require_string(schedule, "expr", path),
            timezone=str(schedule.get("timezone", "UTC")),
        ),
        allowed_tools=list(allowed_tools),
        steps=parsed_steps,
        output=_parse_output(raw.get("output"), path),
        skill_id=skill_id,
        source_path=path,
    )


def _parse_step(payload: Any, allowed_tools: list[str], path: Path) -> JobStep:
    if not isinstance(payload, dict):
        raise SettingsError("Each job step must be a mapping: {0}".format(path))
    step_type = _require_string(payload, "type", path)
    if step_type not in ALLOWED_STEP_TYPES:
        raise SettingsError("Unsupported step type `{0}` in {1}".format(step_type, path))
    tool = _require_string(payload, "tool", path)
    if allowed_tools and tool not in allowed_tools:
        raise SettingsError("Step tool `{0}` must appear in allowed_tools for {1}".format(tool, path))
    raw_parameters = payload.get("with", {})
    if not isinstance(raw_parameters, dict):
        raise SettingsError("Step `with` must be a mapping: {0}".format(path))
    step_id = _require_string(payload, "id", path)
    _validate_identifier(step_id, label="step id", path=path)
    return JobStep(
        id=step_id,
        type=step_type,
        tool=tool,
        parameters=raw_parameters,
        when=str(payload["when"]) if payload.get("when") is not None else None,
    )


def _parse_output(payload: Any, path: Path) -> JobOutput:
    if payload is None:
        return JobOutput()
    if not isinstance(payload, dict):
        raise SettingsError("Job `output` must be a mapping: {0}".format(path))
    return JobOutput(
        channel_id=str(payload["channel_id"]) if payload.get("channel_id") is not None else None,
        artifact_path=str(payload["artifact_path"]) if payload.get("artifact_path") is not None else None,
    )


def _require_string(payload: Dict[str, Any], key: str, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SettingsError("Job requires string `{0}` in {1}".format(key, path))
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
