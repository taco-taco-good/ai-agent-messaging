from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, List

from agent_messaging.core.models import FrontmatterMetadata


STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "have",
    "were",
    "what",
    "when",
    "where",
    "while",
    "about",
    "there",
    "their",
    "into",
    "then",
    "than",
    "they",
    "them",
    "will",
    "your",
    "just",
    "like",
    "should",
    "would",
    "could",
    "using",
    "used",
    "user",
    "assistant",
}


class MetadataGenerator:
    def generate(self, user_text: str, assistant_text: str) -> FrontmatterMetadata:
        combined = "{0}\n{1}".format(user_text.strip(), assistant_text.strip())
        tags = self._extract_tags(combined)
        topic = self._extract_topic(user_text)
        summary = self._extract_summary(user_text, assistant_text)
        return FrontmatterMetadata(tags=tags, topic=topic, summary=summary)

    def _extract_tags(self, content: str) -> List[str]:
        words = [
            token
            for token in re.findall(r"[A-Za-z0-9_-]{3,}", content.lower())
            if token not in STOPWORDS
        ]
        counts = Counter(words)
        return [word for word, _ in counts.most_common(5)]

    def _extract_topic(self, user_text: str) -> str:
        line = user_text.strip().splitlines()[0] if user_text.strip() else "Conversation"
        line = re.sub(r"\s+", " ", line).strip()
        return line[:80]

    def _extract_summary(self, user_text: str, assistant_text: str) -> str:
        user_line = self._first_sentence(user_text)
        assistant_line = self._first_sentence(assistant_text)
        parts = [part for part in (user_line, assistant_line) if part]
        return " ".join(parts)[:240]

    def _first_sentence(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return ""
        match = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)
        return match[0][:120]
