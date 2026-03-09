from __future__ import annotations

from typing import Any

from agent_messaging.runtime.tools import ToolRuntime


def register_job_builtin_tools(
    tool_runtime: ToolRuntime,
    *,
    noop: Any,
    sqlite_query: Any,
    render_template: Any,
    run_agent_prompt: Any,
    send_discord_message: Any,
    persist_text: Any,
    persist_memory: Any,
) -> None:
    builtins = {
        "noop": noop,
        "sqlite_query": sqlite_query,
        "render_template": render_template,
        "run_agent_prompt": run_agent_prompt,
        "send_discord_message": send_discord_message,
        "persist_text": persist_text,
        "persist_memory": persist_memory,
    }
    for name, handler in builtins.items():
        tool_runtime.register("job.{0}".format(name), handler)
