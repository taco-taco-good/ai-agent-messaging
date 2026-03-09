from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-dir", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--tag")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    memory_dir = Path(args.memory_dir)
    query = args.query.strip().lower()
    if not memory_dir.exists():
        return 0

    files = sorted(memory_dir.rglob("*.md"))
    results: list[tuple[float, Path, str]] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        haystack = text.lower()
        if query not in haystack:
            continue
        score = haystack.count(query)
        if args.tag and ("tags:" not in haystack or args.tag.lower() not in haystack):
            continue
        snippet_match = re.search(re.escape(query), haystack)
        snippet = ""
        if snippet_match:
            start = max(0, snippet_match.start() - 60)
            end = min(len(text), snippet_match.end() + 60)
            snippet = text[start:end].replace("\n", " ").strip()
        results.append((float(score), path, snippet))

    results.sort(key=lambda item: (-item[0], str(item[1])))
    top_results = results[: args.top_k]
    if args.json:
        payload = [
            {
                "path": str(path),
                "score": score,
                "topic": _extract_frontmatter_value(path, "topic"),
                "summary": _extract_frontmatter_value(path, "summary"),
                "snippet": snippet,
            }
            for score, path, snippet in top_results
        ]
        print(json.dumps(payload))
        return 0

    for score, path, snippet in top_results:
        print(f"path: {path}")
        print(f"score: {score}")
        print(f"snippet: {snippet}")
        print()
    return 0


def _extract_frontmatter_value(path: Path, key: str) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip().strip("'\"")


if __name__ == "__main__":
    raise SystemExit(main())
