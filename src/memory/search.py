from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List

from agent_messaging.memory.frontmatter import split_frontmatter
from agent_messaging.core.models import MemorySearchRequest, MemorySearchResult


logger = logging.getLogger(__name__)


class MemorySearchTool:
    def __init__(self, memory_dir: Path, rg_binary: str = "rg") -> None:
        self.memory_dir = memory_dir
        self.rg_binary = rg_binary

    def search(self, request: MemorySearchRequest) -> List[MemorySearchResult]:
        logger.info(
            "memory_search_start",
            extra={"query": request.query, "top_k": request.top_k, "memory_dir": str(self.memory_dir)},
        )
        candidates = self._candidate_files(request)
        results: List[MemorySearchResult] = []
        for path in candidates:
            metadata, body = split_frontmatter(path.read_text(encoding="utf-8"))
            date = str(metadata.get("date", path.parent.name))
            if not self._date_matches(date, request):
                continue
            if request.tags and not set(request.tags).intersection(metadata.get("tags", [])):
                continue

            score = self._score(request.query, metadata, body)
            if score <= 0:
                continue

            results.append(
                MemorySearchResult(
                    path=str(path),
                    date=date,
                    topic=str(metadata.get("topic", "")),
                    summary=str(metadata.get("summary", "")),
                    snippet=self._snippet(request.query, body, metadata),
                    score=score,
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        logger.info("memory_search_complete", extra={"result_count": len(results)})
        return results[: request.top_k]

    def _candidate_files(self, request: MemorySearchRequest) -> List[Path]:
        tokens = [token for token in request.query.lower().split() if token]
        if not tokens:
            return sorted(self.memory_dir.rglob("*.md"))

        command = [self.rg_binary, "-l", "-i", "--glob", "*.md"]
        for token in tokens:
            command.extend(["-e", token])
        command.append(str(self.memory_dir))

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return sorted(self.memory_dir.rglob("*.md"))

        if completed.returncode not in (0, 1):
            return sorted(self.memory_dir.rglob("*.md"))

        matches = [
            Path(line.strip())
            for line in completed.stdout.splitlines()
            if line.strip()
        ]
        if matches:
            return matches
        return sorted(self.memory_dir.rglob("*.md"))

    def _date_matches(self, date: str, request: MemorySearchRequest) -> bool:
        if request.date_from and date < request.date_from:
            return False
        if request.date_to and date > request.date_to:
            return False
        return True

    def _score(self, query: str, metadata: dict, body: str) -> float:
        tokens = [token for token in query.lower().split() if token]
        if not tokens:
            return 0.0

        haystacks = {
            "topic": str(metadata.get("topic", "")).lower(),
            "summary": str(metadata.get("summary", "")).lower(),
            "tags": " ".join(str(tag).lower() for tag in metadata.get("tags", [])),
            "body": body.lower(),
        }
        score = 0.0
        for token in tokens:
            if token in haystacks["topic"]:
                score += 5.0
            if token in haystacks["summary"]:
                score += 3.0
            if token in haystacks["tags"]:
                score += 2.0
            if token in haystacks["body"]:
                score += 1.0
        return score

    def _snippet(self, query: str, body: str, metadata: dict) -> str:
        tokens = [token for token in query.lower().split() if token]
        for line in body.splitlines():
            lowered = line.lower()
            if any(token in lowered for token in tokens):
                return line.strip()
        return str(metadata.get("summary", "")) or str(metadata.get("topic", ""))
