from __future__ import annotations

import logging
from pathlib import Path

from agent_messaging.core.models import AgentConfig

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEMORY_SEARCH_SKILL_PATH = PROJECT_ROOT / "tools" / "memory-search" / "SKILL.md"
MEMORY_SEARCH_SCRIPT_PATH = (
    PROJECT_ROOT / "tools" / "memory-search" / "scripts" / "search_memory.py"
)


INIT_DOC_NAMES = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
}


def materialize_init_doc(agent: AgentConfig) -> Path | None:
    if agent.persona_file is None:
        logger.info("init_doc_skipped", extra={"agent_id": agent.agent_id, "reason": "no_persona_file"})
        return None
    agent.workspace_dir.mkdir(parents=True, exist_ok=True)
    path = agent.workspace_dir / init_doc_name(agent.provider)
    path.write_text(_render_init_doc(agent), encoding="utf-8")
    logger.info("init_doc_materialized", extra={"agent_id": agent.agent_id, "path": str(path)})
    return path


def init_doc_name(provider: str) -> str:
    try:
        return INIT_DOC_NAMES[provider]
    except KeyError as exc:
        raise ValueError("Unsupported provider for init doc: {0}".format(provider)) from exc


def _render_init_doc(agent: AgentConfig) -> str:
    display_name = agent.display_name or agent.agent_id
    return (
        "# {0}\n\n"
        "You are `{1}`.\n\n"
        "## Persona\n"
        "{2}\n\n"
        "## Memory\n"
        "- Memory directory: `{3}`\n"
        "- Conversation files: `{{MEMORY_DIR}}/{{YYYY-MM-DD}}/conversation_NNN.md`\n"
        "- Frontmatter should maintain `tags`, `topic`, and `summary` for retrieval quality.\n\n"
        "## Discord Transport\n"
        "- Responses are sent to Discord as raw output.\n"
        "- The system may only chunk long responses for transport safety.\n\n"
        "## Tools\n"
        "- Memory search skill: `{4}`\n"
        "- Memory search script: `{5}`\n"
        "- When the user asks about prior conversations, forgotten terms, or memory lookup, open the memory search skill and use its script against `{3}`.\n"
        "- Example: `python3 {5} --memory-dir {3} --query \"architecture\" --top-k 5`\n"
        "- Use provider-native commands such as `/help`, `/stats`, and `/model` when needed.\n"
    ).format(
        display_name,
        agent.agent_id,
        agent.persona or "No persona configured.",
        agent.memory_dir,
        MEMORY_SEARCH_SKILL_PATH,
        MEMORY_SEARCH_SCRIPT_PATH,
    )
