from __future__ import annotations

import re
from typing import List


FENCE_RE = re.compile(r"^(```+|~~~+)(.*)$")
_DISCORD_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_discord_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return _DISCORD_CONTROL_RE.sub("", normalized)


def chunk_text(text: str, limit: int = 2000) -> List[str]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    text = sanitize_discord_text(text)
    if not text.strip():
        return []

    lines = text.splitlines(keepends=True)
    chunks: List[str] = []
    current = ""
    open_fence = ""

    for line in lines:
        fence_match = FENCE_RE.match(line.rstrip("\n"))
        line_to_add = line
        while line_to_add:
            closing = "{0}\n".format(open_fence) if open_fence else ""
            projected = current + line_to_add
            if open_fence and not current.endswith(closing) and len(projected) > limit:
                projected = current + closing

            if len(projected) <= limit:
                current += line_to_add
                line_to_add = ""
            else:
                if not current:
                    cut = max(1, limit - len(closing))
                    current = line_to_add[:cut]
                    line_to_add = line_to_add[cut:]
                if open_fence and not current.endswith(closing):
                    current += closing
                chunks.append(current)
                current = open_fence + "\n" if open_fence else ""

        if fence_match:
            marker = fence_match.group(1)
            if open_fence == marker:
                open_fence = ""
            elif not open_fence:
                open_fence = marker

    if current:
        if open_fence and not current.endswith("{0}\n".format(open_fence)):
            current += "{0}\n".format(open_fence)
        chunks.append(current)

    return [chunk for chunk in chunks if chunk.strip()]
