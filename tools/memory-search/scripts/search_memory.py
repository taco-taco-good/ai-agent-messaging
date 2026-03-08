#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent_messaging.core.models import MemorySearchRequest
from agent_messaging.memory.search import MemorySearchTool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search agent memory markdown files.")
    parser.add_argument("--memory-dir", required=True, help="Path to the agent memory directory.")
    parser.add_argument("--query", required=True, help="Search query.")
    parser.add_argument("--top-k", type=int, default=5, help="Maximum number of results to return.")
    parser.add_argument(
        "--date-from",
        help="Only include results on or after this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--date-to",
        help="Only include results on or before this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Frontmatter tag filter. Repeat for multiple tags.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of plain text.",
    )
    return parser.parse_args(argv)


def render_text(results: list[object]) -> str:
    if not results:
        return "No memory results found."

    blocks: list[str] = []
    for index, result in enumerate(results, start=1):
        blocks.append(
            (
                "[{0}] {1} | {2}\n"
                "path: {3}\n"
                "score: {4:.1f}\n"
                "summary: {5}\n"
                "snippet: {6}"
            ).format(
                index,
                result.date or "-",
                result.topic or "(no topic)",
                result.path,
                result.score,
                result.summary or "(no summary)",
                result.snippet or "(no snippet)",
            )
        )
    return "\n\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    memory_dir = Path(args.memory_dir).expanduser().resolve()
    if not memory_dir.exists():
        sys.stderr.write("Memory directory does not exist: {0}\n".format(memory_dir))
        return 2

    tool = MemorySearchTool(memory_dir)
    request = MemorySearchRequest(
        query=args.query,
        top_k=args.top_k,
        date_from=args.date_from,
        date_to=args.date_to,
        tags=list(args.tag),
    )
    results = tool.search(request)

    if args.json:
        payload = [
            {
                "path": result.path,
                "date": result.date,
                "topic": result.topic,
                "summary": result.summary,
                "snippet": result.snippet,
                "score": result.score,
            }
            for result in results
        ]
        sys.stdout.write(json.dumps(payload, ensure_ascii=True, indent=2))
        sys.stdout.write("\n")
        return 0

    sys.stdout.write(render_text(results))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
