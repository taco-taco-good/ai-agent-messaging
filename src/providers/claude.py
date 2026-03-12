from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from agent_messaging.core.models import ModelOption
from agent_messaging.providers.base import ProviderError, ProviderResponseTimeout, ProviderStartupError
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
        warning_timeout: float = 60.0,
        hard_timeout: float = 180.0,
    ) -> None:
        super().__init__(
            executable=executable or self.default_command,
            default_model=default_model,
            workspace_dir=workspace_dir,
            base_args=base_args,
            supported_commands=self.default_supported_commands,
            model_options=model_options or self.default_model_options,
            use_pty=use_pty,
            warning_timeout=warning_timeout,
            hard_timeout=hard_timeout,
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

    async def send_user_message(self, message: str):
        if not self._uses_one_shot_mode:
            async for chunk in super().send_user_message(message):
                yield chunk
            return
        await self.start()
        async for chunk in self._run_streaming_print_prompt(message):
            yield chunk

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

    async def _run_streaming_print_prompt(self, prompt: str):
        command = self._build_streaming_command(prompt)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(self.workspace_dir) if self.workspace_dir is not None else None,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ProviderStartupError(
                "Provider executable not found: {0}".format(self.executable)
            ) from exc

        if process.stdout is None:
            process.kill()
            await process.wait()
            raise ProviderError("Claude streaming stdout is not available.")
        lines: list[str] = []
        deltas: list[str] = []
        started = asyncio.get_running_loop().time()
        warned = False
        pending = b""

        while True:
            elapsed = asyncio.get_running_loop().time() - started
            if not warned and elapsed >= self.warning_timeout:
                warned = True
                self._timeout_warning_issued = True
            remaining = self.hard_timeout - elapsed
            if remaining <= 0:
                process.kill()
                await process.wait()
                raise ProviderResponseTimeout(
                    "Provider did not respond within {0} seconds.".format(self.hard_timeout)
                )
            try:
                chunk = await asyncio.wait_for(process.stdout.read(4096), timeout=min(1.0, remaining))
            except asyncio.TimeoutError:
                continue
            if not chunk:
                break
            pending += chunk
            while True:
                newline_index = pending.find(b"\n")
                if newline_index < 0:
                    break
                raw_line = pending[:newline_index].decode("utf-8", errors="replace").strip()
                pending = pending[newline_index + 1 :]
                if not raw_line:
                    continue
                lines.append(raw_line)
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                event_type = payload.get("type")
                if event_type == "stream_event":
                    event = payload.get("event") or {}
                    if (
                        isinstance(event, dict)
                        and event.get("type") == "content_block_delta"
                        and isinstance(event.get("delta"), dict)
                    ):
                        text = event["delta"].get("text")
                        if isinstance(text, str) and text:
                            deltas.append(text)
                            yield text

        trailing_line = pending.decode("utf-8", errors="replace").strip()
        if trailing_line:
            lines.append(trailing_line)
            try:
                payload = json.loads(trailing_line)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and payload.get("type") == "stream_event":
                event = payload.get("event") or {}
                if (
                    isinstance(event, dict)
                    and event.get("type") == "content_block_delta"
                    and isinstance(event.get("delta"), dict)
                ):
                    text = event["delta"].get("text")
                    if isinstance(text, str) and text:
                        deltas.append(text)
                        yield text

        final_text = "".join(deltas) or self._extract_streaming_final_text(lines)
        stderr = await process.stderr.read() if process.stderr is not None else b""
        returncode = await process.wait()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if returncode != 0:
            raise ProviderError(stderr_text or final_text or "Claude print command failed.")

        self._has_history = True
        await self._after_one_shot_success(
            raw_output="\n".join(lines),
            parsed_output=final_text,
        )
        if not deltas and final_text:
            yield final_text

    def _build_streaming_command(self, prompt: str) -> list[str]:
        command = self._build_one_shot_command(prompt)
        return [
            *command[:-1],
            "--verbose",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            command[-1],
        ]

    @staticmethod
    def _extract_streaming_final_text(lines: Sequence[str]) -> str:
        for raw_line in reversed(lines):
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "result" and isinstance(payload.get("result"), str):
                return str(payload["result"])
            if payload.get("type") != "assistant":
                continue
            message = payload.get("message") or {}
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            final_text = "".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
            if final_text:
                return final_text
        return ""

    @staticmethod
    def _project_slug(workspace_dir: Path) -> str:
        resolved = workspace_dir.expanduser().resolve()
        return "-{0}".format(str(resolved).lstrip("/").replace("/", "-"))
