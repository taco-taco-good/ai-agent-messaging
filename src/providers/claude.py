from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from agent_messaging.core.models import ModelOption
from agent_messaging.providers.subprocess_cli import SubprocessCLIWrapper


_CONTEXT_1M_BETA = "context-1m-2025-08-07"


def _build_claude_model_args(model: str) -> list[str]:
    if model in {"sonnet-1m", "claude-sonnet-4-6-1m"}:
        return ["--model", "sonnet", "--betas", _CONTEXT_1M_BETA]
    if model in {"opus-1m", "claude-opus-4-6-1m"}:
        return ["--model", "opus", "--betas", _CONTEXT_1M_BETA]
    return ["--model", model]


class ClaudeWrapper(SubprocessCLIWrapper):
    provider_name = "claude"
    default_command = "claude"
    default_supported_commands = ("/help", "/stats", "/model", "/models")
    default_model_catalog = (
        ModelOption(
            value="sonnet",
            label="Default (recommended)",
            description="Sonnet 4.6 · Best for everyday tasks",
        ),
        ModelOption(
            value="sonnet-1m",
            label="Sonnet (1M context)",
            description="Sonnet 4.6 with 1M context · Extra usage",
        ),
        ModelOption(
            value="opus",
            label="Opus",
            description="Opus 4.6 · Most capable for complex work",
        ),
        ModelOption(
            value="opus-1m",
            label="Opus (1M context)",
            description="Opus 4.6 with 1M context · Extra usage",
        ),
        ModelOption(
            value="haiku",
            label="Haiku",
            description="Haiku 4.5 · Fastest for quick answers",
        ),
    )
    default_model_options = tuple(option.value for option in default_model_catalog)

    def __init__(
        self,
        executable: Optional[str] = None,
        default_model: Optional[str] = None,
        workspace_dir: Optional[Path] = None,
        base_args: Optional[Sequence[str]] = None,
        model_options: Optional[Sequence[str]] = None,
        use_pty: bool = True,
        provider_session_id: Optional[str] = None,
        config_dir: Optional[Path] = None,
    ) -> None:
        super().__init__(
            executable=executable or self.default_command,
            default_model=default_model,
            workspace_dir=workspace_dir,
            base_args=base_args,
            supported_commands=self.default_supported_commands,
            model_options=model_options or self.default_model_options,
            use_pty=use_pty,
            prompt_args=("-p",),
            model_args_builder=_build_claude_model_args,
            initial_session_args_builder=lambda session_id: ["--session-id", session_id],
            resume_session_args_builder=lambda session_id: ["--resume", session_id],
            provider_session_id=provider_session_id,
            reset_session_on_model_change=True,
        )
        self.model_catalog = tuple(self.default_model_catalog)
        self.config_dir = config_dir or (Path.home() / ".claude")

    async def _after_one_shot_success(self, raw_output: str, parsed_output: str) -> None:
        del raw_output
        del parsed_output
        self._refresh_resolved_model_from_session_log()

    async def stats_response(self) -> str:
        self._refresh_resolved_model_from_session_log()
        return self.format_stats_response()

    def _refresh_resolved_model_from_session_log(self) -> None:
        if self.workspace_dir is None or not self.provider_session_id:
            return
        session_path = (
            self.config_dir
            / "projects"
            / self._project_slug(self.workspace_dir)
            / "{0}.jsonl".format(self.provider_session_id)
        )
        if not session_path.exists():
            return
        for raw_line in reversed(session_path.read_text(encoding="utf-8").splitlines()):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "assistant":
                continue
            message = payload.get("message")
            if not isinstance(message, dict):
                continue
            model = message.get("model")
            if isinstance(model, str) and model:
                observed_at = payload.get("timestamp")
                if self._exact_model_pending_since is not None and isinstance(observed_at, str):
                    try:
                        observed_ts = datetime.fromisoformat(
                            observed_at.replace("Z", "+00:00")
                        ).timestamp()
                    except ValueError:
                        observed_ts = None
                    if observed_ts is not None and observed_ts < self._exact_model_pending_since:
                        continue
                self.set_resolved_model(
                    model,
                    "claude session log",
                    session_id=self.provider_session_id,
                )
                return

    @staticmethod
    def _project_slug(workspace_dir: Path) -> str:
        resolved = workspace_dir.expanduser().resolve()
        return "-{0}".format(str(resolved).lstrip("/").replace("/", "-"))
