from __future__ import annotations

from pathlib import Path
from typing import Dict

import yaml

from agent_messaging.config.settings import SettingsError
from agent_messaging.skills.models import SkillDefinition


def load_skills(skills_dir: Path) -> Dict[str, SkillDefinition]:
    if not skills_dir.exists():
        return {}

    skills: Dict[str, SkillDefinition] = {}
    for path in sorted(skills_dir.glob("*.md")):
        skill = _load_skill_document(path)
        skills[skill.id] = skill
    return skills


def _load_skill_document(path: Path) -> SkillDefinition:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SettingsError("Skill document must start with frontmatter: {0}".format(path))
    try:
        _, frontmatter, body = text.split("---\n", 2)
    except ValueError as exc:
        raise SettingsError("Skill document frontmatter is malformed: {0}".format(path)) from exc

    raw = yaml.safe_load(frontmatter) or {}
    if not isinstance(raw, dict):
        raise SettingsError("Skill frontmatter must be a mapping: {0}".format(path))

    skill_id = _require_string(raw, "id", path)
    summary = _require_string(raw, "summary", path)
    allowed_tools = raw.get("allowed_tools") or []
    if not isinstance(allowed_tools, list) or not all(isinstance(item, str) for item in allowed_tools):
        raise SettingsError("Skill `allowed_tools` must be a list of strings: {0}".format(path))

    return SkillDefinition(
        id=skill_id,
        summary=summary,
        allowed_tools=list(allowed_tools),
        body=body.lstrip(),
        source_path=path,
    )


def _require_string(payload: dict[str, object], key: str, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SettingsError("Skill requires string `{0}` in {1}".format(key, path))
    return value.strip()
