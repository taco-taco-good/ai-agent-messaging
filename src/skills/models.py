from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class SkillDefinition:
    id: str
    summary: str
    allowed_tools: List[str] = field(default_factory=list)
    body: str = ""
    source_path: Optional[Path] = None
