---
name: memory-search
description: Search saved agent memory markdown files for prior conversations, forgotten terms, topics, summaries, and date-filtered history. Use when the user asks what was said before, asks to recall previous context, or explicitly requests a memory search.
---

# Memory Search

Use this tool when the user asks about:

- prior conversations
- forgotten words or phrases
- previous decisions or notes
- topic, tag, or date-based memory lookup

## Inputs

- `memory_dir`: target agent memory directory
- `query`: the words or phrase to find
- optional `--tag`: filter by frontmatter tags
- optional `--date-from` / `--date-to`: filter by `YYYY-MM-DD`
- optional `--top-k`: limit result count

## Command

Run the bundled script with Python:

```bash
python3 scripts/search_memory.py --memory-dir <memory_dir> --query "<query>" --top-k 5
```

## Workflow

1. Read the target `memory_dir` from the agent's init doc.
2. Run the script with the user's query.
3. Add `--tag` when the user gives a category such as `architecture` or `bug`.
4. Add `--date-from` and `--date-to` when the user constrains the time range.
5. Answer with the most relevant result, including the file path and snippet when useful.
6. If no result is found, say that memory search did not find relevant history.

## Examples

```bash
python3 scripts/search_memory.py --memory-dir /repo/memory/gemini --query "architecture decision"
python3 scripts/search_memory.py --memory-dir /repo/memory/codex --query "token" --tag architecture --top-k 3
python3 scripts/search_memory.py --memory-dir /repo/memory/claude --query "pricing" --date-from 2026-03-01 --date-to 2026-03-08
```

## Output

- Default output is a readable ranked list with `path`, `topic`, `summary`, `snippet`, and `score`.
- Use `--json` when structured output is easier to process.
