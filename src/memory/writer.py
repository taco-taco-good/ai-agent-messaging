from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
from threading import Lock
from typing import Iterable, Optional, Tuple

from agent_messaging.memory.frontmatter import render_document, split_frontmatter
from agent_messaging.core.models import FrontmatterMetadata


logger = logging.getLogger(__name__)
_SAFE_MEMORY_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class MemoryWriter:
    def __init__(self, line_limit: int = 500) -> None:
        self.line_limit = line_limit
        self._lock = Lock()

    def append_message(
        self,
        agent_id: str,
        display_name: str,
        memory_dir: Path,
        role: str,
        content: str,
        participants: Iterable[str],
        metadata: Optional[FrontmatterMetadata] = None,
        timestamp: Optional[datetime] = None,
    ) -> Path:
        timestamp = timestamp or datetime.now(timezone.utc)
        day_dir = memory_dir / timestamp.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            path = self._select_file(day_dir)
            existing_metadata, body = self._read_document(path)

            entry = self._format_entry(role=role, content=content, timestamp=timestamp)
            updated_body = body + entry
            merged = self._merge_metadata(
                existing_metadata=existing_metadata,
                agent_id=agent_id,
                display_name=display_name,
                participants=participants,
                body=updated_body,
                metadata=metadata,
                timestamp=timestamp,
            )
            self._write_document(path, render_document(merged, updated_body))
        logger.info("memory_appended", extra={"path": str(path), "role": role})
        return path

    def write_job_run(
        self,
        *,
        agent_id: str,
        display_name: str,
        memory_dir: Path,
        job_id: str,
        run_id: int,
        content: str,
        status: str,
        metadata: Optional[FrontmatterMetadata] = None,
        timestamp: Optional[datetime] = None,
    ) -> Path:
        timestamp = timestamp or datetime.now(timezone.utc)
        safe_job_id = self._validate_slug(job_id, label="job_id")
        day_dir = memory_dir / "jobs" / safe_job_id / timestamp.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            path = self._select_prefixed_file(day_dir, prefix="run")
            merged = {
                "date": timestamp.strftime("%Y-%m-%d"),
                "agent": agent_id,
                "display_name": display_name,
                "record_type": "job_run",
                "job_id": safe_job_id,
                "run_id": run_id,
                "status": status,
                "tags": list(metadata.tags) if metadata is not None else [],
                "topic": metadata.topic if metadata is not None else safe_job_id,
                "summary": metadata.summary if metadata is not None else "",
            }
            normalized = content.rstrip() + "\n"
            self._write_document(path, render_document(merged, normalized))
        logger.info("job_memory_written", extra={"path": str(path), "job_id": safe_job_id})
        return path

    def _select_file(self, day_dir: Path) -> Path:
        candidates = sorted(day_dir.glob("conversation_*.md"))
        if not candidates:
            return day_dir / "conversation_001.md"

        current = candidates[-1]
        line_count = len(self._read_text(current).splitlines())
        if line_count >= self.line_limit:
            next_index = len(candidates) + 1
            return day_dir / "conversation_{0:03d}.md".format(next_index)
        return current

    def _select_prefixed_file(self, day_dir: Path, *, prefix: str) -> Path:
        candidates = sorted(day_dir.glob("{0}_*.md".format(prefix)))
        next_index = len(candidates) + 1
        return day_dir / "{0}_{1:03d}.md".format(prefix, next_index)

    def _read_document(self, path: Path) -> Tuple[dict, str]:
        if not path.exists():
            return {}, ""
        return split_frontmatter(self._read_text(path))

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.warning("memory_document_invalid_utf8", extra={"path": str(path)})
            return path.read_bytes().decode("utf-8", errors="replace")

    def _write_document(self, path: Path, document: str) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(document, encoding="utf-8")
        os.replace(tmp_path, path)

    def _merge_metadata(
        self,
        existing_metadata: dict,
        agent_id: str,
        display_name: str,
        participants: Iterable[str],
        body: str,
        metadata: Optional[FrontmatterMetadata],
        timestamp: datetime,
    ) -> dict:
        merged = dict(existing_metadata)
        merged["date"] = timestamp.strftime("%Y-%m-%d")
        merged["agent"] = agent_id
        merged["display_name"] = display_name
        merged["participants"] = sorted(set(existing_metadata.get("participants", [])) | set(participants))
        merged["message_count"] = body.count("\n## ")

        if metadata is not None:
            merged["tags"] = list(metadata.tags)
            merged["topic"] = metadata.topic
            merged["summary"] = metadata.summary
        else:
            merged.setdefault("tags", [])
            merged.setdefault("topic", "")
            merged.setdefault("summary", "")

        return merged

    def _format_entry(self, role: str, content: str, timestamp: datetime) -> str:
        normalized = content.rstrip()
        return "\n## {0} {1}\n{2}\n".format(
            timestamp.isoformat(timespec="seconds"),
            role,
            normalized,
        )

    def _validate_slug(self, value: str, *, label: str) -> str:
        if not _SAFE_MEMORY_SLUG.fullmatch(value):
            raise ValueError(
                "Invalid {0} `{1}`. Use lowercase slug, digits, `_`, `-`.".format(label, value)
            )
        return value
