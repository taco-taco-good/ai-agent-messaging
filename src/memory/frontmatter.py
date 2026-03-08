from __future__ import annotations

from typing import Dict, Tuple

import yaml


def split_frontmatter(document: str) -> Tuple[Dict[str, object], str]:
    if not document.startswith("---\n"):
        return {}, document

    parts = document.split("---\n", 2)
    if len(parts) < 3:
        return {}, document

    try:
        metadata = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}, document
    body = parts[2]
    return metadata, body


def render_document(metadata: Dict[str, object], body: str) -> str:
    header = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
    )
    return "---\n{0}---\n{1}".format(header, body)
