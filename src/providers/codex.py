from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, Optional, Sequence

from agent_messaging.core.models import ModelOption
from agent_messaging.providers.base import (
    CLIWrapper,
    ProviderError,
    ProviderResponseTimeout,
    ProviderStartupError,
)


logger = logging.getLogger(__name__)

LEGACY_MODEL_ALIASES = {
    "gpt-5": "gpt-5.3-codex",
    "gpt-5-codex": "gpt-5.3-codex",
    "gpt-5-codex-spark": "gpt-5.3-codex-spark",
}
_DEFAULT_REASONING_EFFORT = "medium"


class CodexWrapper(CLIWrapper):
    provider_name = "codex"
    default_command = "codex"
    default_supported_commands = ("/help", "/stats", "/model", "/models")
    default_model_catalog = (
        ModelOption(
            value="gpt-5.3-codex",
            label="gpt-5.3-codex",
            description="Latest frontier agentic coding model",
        ),
        ModelOption(
            value="gpt-5.4",
            label="gpt-5.4",
            description="Latest frontier agentic coding model",
        ),
        ModelOption(
            value="gpt-5.3-codex-spark",
            label="gpt-5.3-codex-spark",
            description="Ultra-fast coding model",
        ),
        ModelOption(
            value="gpt-5.2-codex",
            label="gpt-5.2-codex",
            description="Frontier agentic coding model",
        ),
        ModelOption(
            value="gpt-5.1-codex-max",
            label="gpt-5.1-codex-max",
            description="Codex-optimized flagship for deep and fast reasoning",
        ),
        ModelOption(
            value="gpt-5.2",
            label="gpt-5.2",
            description="Latest frontier model across knowledge, reasoning, and coding",
        ),
        ModelOption(
            value="gpt-5.1-codex-mini",
            label="gpt-5.1-codex-mini",
            description="Cheaper and faster, with lower capability",
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
        use_pty: bool = False,
        provider_session_id: Optional[str] = None,
        codex_home: Optional[Path] = None,
        hard_timeout: float = 180.0,
    ) -> None:
        super().__init__(default_model=default_model)
        self.executable = executable or self.default_command
        self.workspace_dir = workspace_dir
        self.base_args = list(base_args or [])
        self.supported_commands = tuple(self.default_supported_commands)
        self.model_options = tuple(model_options or self.default_model_options)
        self.model_catalog = tuple(self.default_model_catalog)
        self.use_pty = use_pty
        self.provider_session_id = provider_session_id or ""
        self._started = False
        self._has_history = bool(provider_session_id)
        self.current_model = self._normalize_model_alias(self.current_model)
        self.codex_home = codex_home or (Path.home() / ".codex")
        self.hard_timeout = hard_timeout
        self.runtime_thread_id = ""

    async def start(self) -> None:
        if self._started:
            return
        if self.workspace_dir is not None:
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._started = True
        logger.info(
            "provider_started",
            extra={
                "provider": self.provider_name,
                "provider_session_id": self.provider_session_id,
                "mode": "exec",
            },
        )

    async def send_user_message(self, message: str):
        await self.start()
        async for chunk in self._run_codex(message):
            yield chunk

    async def send_native_command(self, command: str, args: Optional[Dict[str, object]] = None):
        args = args or {}
        if command == "/help":
            yield "Supported commands: /help, /stats, /model"
            return
        if command == "/stats":
            yield await self.stats_response()
            return
        if command == "/model":
            model_alias = args.get("model_alias")
            if model_alias:
                self.current_model = self._normalize_model_alias(str(model_alias))
                self.clear_resolved_model()
                self.runtime_thread_id = ""
            yield "model:{0}".format(self.current_model or "default")
            return
        if command == "/models":
            yield "\n".join(self.available_model_options())
            return
        raise ProviderError("Unsupported Codex command: {0}".format(command))

    async def reset_session(self) -> None:
        await self.stop()
        self.provider_session_id = ""
        self._has_history = False
        self.clear_resolved_model()
        self.runtime_thread_id = ""
        await self.start()

    async def stop(self) -> None:
        self._started = False
        self.provider_session_id = ""
        self._has_history = False
        logger.info(
            "provider_stopped",
            extra={
                "provider": self.provider_name,
                "provider_session_id": self.provider_session_id,
            },
        )

    def is_alive(self) -> bool:
        return self._started

    def _normalize_model_alias(self, model: Optional[str]) -> Optional[str]:
        if model is None:
            return None
        normalized = LEGACY_MODEL_ALIASES.get(model, model)
        if normalized != model:
            logger.info(
                "codex_model_alias_normalized",
                extra={"from_model": model, "to_model": normalized},
            )
        return normalized

    async def stats_response(self) -> str:
        await asyncio.to_thread(self._refresh_resolved_model_from_rollout, None, None)
        extra = {}
        if self.runtime_thread_id:
            extra["thread"] = self.runtime_thread_id
        return self.format_stats_response(extra=extra)

    async def _run_codex(self, prompt: str):
        if not prompt.strip():
            return

        started_at = time.time()
        started_monotonic = asyncio.get_running_loop().time()
        with tempfile.TemporaryDirectory() as tempdir:
            output_path = Path(tempdir) / "last-message.txt"
            for attempt in range(2):
                command = self._build_command(prompt=prompt, output_path=output_path)
                logger.debug(
                    "provider_send_line",
                    extra={
                        "provider": self.provider_name,
                        "payload_preview": prompt[:120],
                        "provider_session_id": self.provider_session_id,
                        "subcommand": "resume" if self._has_history else "exec",
                    },
                )
                try:
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        cwd=str(self.workspace_dir) if self.workspace_dir is not None else None,
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                except FileNotFoundError as exc:
                    logger.error(
                        "provider_executable_missing",
                        extra={
                            "provider": self.provider_name,
                            "executable": self.executable,
                            "error_code": ProviderStartupError.error_code,
                        },
                    )
                    raise ProviderStartupError(
                        "Provider executable not found: {0}".format(self.executable)
                    ) from exc

                if process.stdout is None:
                    process.kill()
                    await process.wait()
                    raise ProviderError("Codex streaming stdout is not available.")
                stdout_lines: list[str] = []
                response_parts: list[str] = []
                warned = False
                while True:
                    elapsed = asyncio.get_running_loop().time() - started_monotonic
                    if not warned and elapsed >= min(60.0, self.hard_timeout):
                        warned = True
                        self._timeout_warning_issued = True
                        await self.emit_progress("응답 생성에 시간이 걸리고 있습니다. 계속 처리 중입니다.")
                    remaining = self.hard_timeout - elapsed
                    if remaining <= 0:
                        process.kill()
                        await process.wait()
                        raise ProviderResponseTimeout(
                            "Codex did not respond within {0} seconds.".format(self.hard_timeout)
                        )
                    try:
                        line = await asyncio.wait_for(
                            process.stdout.readline(),
                            timeout=min(1.0, remaining),
                        )
                    except asyncio.TimeoutError:
                        continue
                    if not line:
                        break
                    raw_line = line.decode("utf-8", errors="replace").strip()
                    if not raw_line:
                        continue
                    stdout_lines.append(raw_line)
                    try:
                        payload = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("type") == "thread.started":
                        thread_id = payload.get("thread_id")
                        if isinstance(thread_id, str) and thread_id:
                            self.provider_session_id = thread_id
                            self.runtime_thread_id = thread_id
                    elif payload.get("type") == "turn.started":
                        await self.emit_progress("Codex가 응답을 생성하고 있습니다.")
                    elif payload.get("type") == "item.completed":
                        item = payload.get("item") or {}
                        if isinstance(item, dict) and item.get("type") == "agent_message":
                            text = item.get("text")
                            if isinstance(text, str) and text:
                                response_parts.append(text)
                                yield text

                stderr = await process.stderr.read() if process.stderr is not None else b""
                returncode = await process.wait()
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                stdout_text = "\n".join(stdout_lines).strip()
                self._capture_runtime_metadata(stdout_text)
                if returncode == 0:
                    break

                detail = self._extract_runtime_error(stdout_text)
                if not detail:
                    detail = stderr_text
                if not detail:
                    detail = stdout_text
                if (
                    self._has_history
                    and attempt == 0
                    and "no last agent message" in detail.lower()
                ):
                    logger.warning(
                        "codex_resume_missing_history",
                        extra={"provider_session_id": self.provider_session_id},
                    )
                    self._has_history = False
                    self.provider_session_id = ""
                    self.runtime_thread_id = ""
                    continue
                raise ProviderError(
                    "Codex exec failed with exit code {0}: {1}".format(
                        returncode,
                        detail or "unknown error",
                    )
                )

            response = "".join(response_parts)
            if output_path.exists():
                file_output = output_path.read_text(encoding="utf-8").strip()
                if file_output and not response:
                    response = file_output
            if not response:
                response = stdout_text
            await asyncio.to_thread(self._refresh_resolved_model_from_rollout, prompt, started_at)
            self._has_history = bool(self.provider_session_id)
            if not response_parts and response:
                yield response

    def _build_command(self, prompt: str, output_path: Path) -> Sequence[str]:
        model = self.current_model or ""
        command = [
            self.executable,
            *self.base_args,
            "-c",
            'model_reasoning_effort="{0}"'.format(_DEFAULT_REASONING_EFFORT),
        ]
        if self.workspace_dir is not None:
            command.extend(["-C", str(self.workspace_dir)])
        command.append("exec")
        if self._has_history and self.provider_session_id:
            command.extend(["resume", self.provider_session_id])
        command.extend(
            [
                "--skip-git-repo-check",
                "--json",
                "-o",
                str(output_path),
            ]
        )
        if model:
            command.extend(["-m", model])
        command.append(prompt)
        return command

    def _refresh_resolved_model_from_rollout(
        self,
        prompt: Optional[str],
        started_at: Optional[float],
    ) -> None:
        thread = self._latest_thread(prompt=prompt, started_at=started_at)
        if thread is None:
            return
        rollout_path = thread["rollout_path"]
        if not rollout_path.exists():
            return
        for raw_line in reversed(rollout_path.read_text(encoding="utf-8").splitlines()):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "turn_context":
                continue
            context = payload.get("payload")
            if not isinstance(context, dict):
                continue
            model = context.get("model")
            if isinstance(model, str) and model:
                thread_id = str(thread["id"])
                self.provider_session_id = thread_id
                self.runtime_thread_id = thread_id
                self.set_resolved_model(
                    model,
                    "codex rollout log",
                    session_id=thread_id,
                )
                return

    def _latest_thread(
        self,
        prompt: Optional[str],
        started_at: Optional[float],
    ) -> Optional[dict[str, object]]:
        if self.workspace_dir is None:
            return None
        db_path = self.codex_home / "state_5.sqlite"
        if not db_path.exists():
            return None
        connection = sqlite3.connect(str(db_path))
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                (
                    "select id, rollout_path, created_at, updated_at, first_user_message "
                    "from threads where cwd = ? order by updated_at desc limit 20"
                ),
                (str(self.workspace_dir.expanduser().resolve()),),
            ).fetchall()
        finally:
            connection.close()
        if not rows:
            return None
        if self.provider_session_id:
            for row in rows:
                if str(row["id"]) == self.provider_session_id:
                    return {
                        "id": str(row["id"]),
                        "rollout_path": Path(str(row["rollout_path"])),
                        "created_at": int(row["created_at"]),
                        "updated_at": int(row["updated_at"]),
                        "first_user_message": str(row["first_user_message"] or ""),
                    }
        prompt_matches = []
        recent_matches = []
        pending_matches = []
        for row in rows:
            record = {
                "id": str(row["id"]),
                "rollout_path": Path(str(row["rollout_path"])),
                "created_at": int(row["created_at"]),
                "updated_at": int(row["updated_at"]),
                "first_user_message": str(row["first_user_message"] or ""),
            }
            if prompt and record["first_user_message"] == prompt:
                prompt_matches.append(record)
            if started_at is not None and record["updated_at"] >= int(started_at) - 5:
                recent_matches.append(record)
            if (
                self._exact_model_pending_since is not None
                and record["updated_at"] >= int(self._exact_model_pending_since) - 5
            ):
                pending_matches.append(record)
        if prompt_matches:
            return prompt_matches[0]
        if recent_matches:
            return recent_matches[0]
        if self._exact_model_pending_since is not None:
            if pending_matches:
                return pending_matches[0]
            return None
        return {
            "id": str(rows[0]["id"]),
            "rollout_path": Path(str(rows[0]["rollout_path"])),
            "created_at": int(rows[0]["created_at"]),
            "updated_at": int(rows[0]["updated_at"]),
            "first_user_message": str(rows[0]["first_user_message"] or ""),
        }

    def _capture_runtime_metadata(self, stdout_text: str) -> None:
        for raw_line in stdout_text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line.startswith("{"):
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "thread.started":
                continue
            thread_id = payload.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                self.provider_session_id = thread_id
                self.runtime_thread_id = thread_id

    def _extract_runtime_error(self, stdout_text: str) -> str:
        messages: list[str] = []
        for raw_line in stdout_text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line.startswith("{"):
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "error":
                continue
            message = payload.get("message")
            if isinstance(message, str) and message:
                messages.append(message)
        return "\n".join(messages)
