from __future__ import annotations

import asyncio
import codecs
import json
import logging
import sqlite3
import tempfile
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from json import JSONDecodeError, JSONDecoder
from pathlib import Path
from typing import AsyncIterator, Dict, Optional, Sequence

from agent_messaging.core.models import ModelOption
from agent_messaging.providers.base import (
    CLIWrapper,
    ProviderError,
    ProviderProcessKilled,
    ProviderResponseTimeout,
    ProviderStreamParseError,
    ProviderStaleSession,
    ProviderStartupError,
    ProviderStreamDisconnected,
)


logger = logging.getLogger(__name__)

LEGACY_MODEL_ALIASES = {
    "gpt-5": "gpt-5.3-codex",
    "gpt-5-codex": "gpt-5.3-codex",
    "gpt-5-codex-spark": "gpt-5.3-codex-spark",
}
_DEFAULT_REASONING_EFFORT = "medium"
_STDOUT_READ_CHUNK_SIZE = 4096
_STREAM_BUFFER_LIMIT = 256 * 1024
_LOG_PREVIEW_LIMIT = 240


@dataclass
class _StreamRecord:
    raw: str
    source: str


class _JsonStreamBuffer:
    def __init__(self, *, max_buffer_chars: int) -> None:
        self._buffer = ""
        self._max_buffer_chars = max_buffer_chars
        self._decoder = JSONDecoder()

    def feed(self, text: str) -> list[_StreamRecord]:
        self._buffer += text
        records: list[_StreamRecord] = []
        records.extend(self._drain_lines())
        if "\n" not in self._buffer and len(self._buffer) > self._max_buffer_chars:
            records.extend(self._drain_json_objects(strict=False))
            if len(self._buffer) > self._max_buffer_chars and self._exceeds_limit_without_json_start():
                raise ValueError("stream buffer exceeded limit without a JSON object boundary")
        return records

    def finalize(self) -> list[_StreamRecord]:
        records = self._drain_lines()
        records.extend(self._drain_json_objects(strict=False))
        tail = self._buffer.strip()
        self._buffer = ""
        if tail:
            records.append(_StreamRecord(raw=tail, source="tail"))
        return records

    @property
    def buffer_chars(self) -> int:
        return len(self._buffer)

    @property
    def preview(self) -> str:
        return _truncate_preview(self._buffer)

    def _drain_lines(self) -> list[_StreamRecord]:
        records: list[_StreamRecord] = []
        while True:
            newline_index = self._buffer.find("\n")
            if newline_index < 0:
                return records
            line = self._buffer[:newline_index]
            self._buffer = self._buffer[newline_index + 1 :]
            stripped = line.strip()
            if stripped:
                records.append(_StreamRecord(raw=stripped, source="line"))

    def _drain_json_objects(self, *, strict: bool) -> list[_StreamRecord]:
        records: list[_StreamRecord] = []
        while self._buffer:
            original_length = len(self._buffer)
            stripped = self._buffer.lstrip()
            whitespace = original_length - len(stripped)
            if not stripped:
                self._buffer = ""
                break
            if not stripped.startswith("{"):
                if strict:
                    raise ValueError("stream buffer exceeded limit without a JSON object boundary")
                break
            try:
                _, end = self._decoder.raw_decode(stripped)
            except JSONDecodeError:
                if strict:
                    raise ValueError("stream buffer exceeded limit before a complete JSON object was received")
                break
            raw = stripped[:end].strip()
            self._buffer = stripped[end:]
            if whitespace:
                self._buffer = (" " * whitespace) + self._buffer
            if raw:
                records.append(_StreamRecord(raw=raw, source="json_object"))
        return records

    def _exceeds_limit_without_json_start(self) -> bool:
        stripped = self._buffer.lstrip()
        return bool(stripped) and not stripped.startswith("{")


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
        warning_timeout: float | None = None,
        hard_timeout: float = 1200.0,
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
        self.warning_timeout = warning_timeout
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
                stdout_records: list[str] = []
                response_parts: list[str] = []
                stream_failed = False
                try:
                    async for record in self._iter_stream_records(
                        process.stdout,
                        process=process,
                        started_monotonic=started_monotonic,
                    ):
                        raw_line = record.raw
                        stdout_records.append(raw_line)
                        payload = self._parse_stream_payload(
                            raw_line,
                            source=record.source,
                            parser_preview=_truncate_preview(_stdout_text_preview(stdout_records)),
                        )
                        if payload.get("type") == "thread.started":
                            thread_id = payload.get("thread_id")
                            if isinstance(thread_id, str) and thread_id:
                                self.provider_session_id = thread_id
                                self.runtime_thread_id = thread_id
                        elif payload.get("type") == "item.completed":
                            item = payload.get("item") or {}
                            if isinstance(item, dict) and item.get("type") == "agent_message":
                                text = item.get("text")
                                if isinstance(text, str) and text:
                                    response_parts.append(text)
                                    yield text
                except BaseException:
                    stream_failed = True
                    raise
                finally:
                    if stream_failed:
                        await self._cleanup_failed_process(process)

                stderr = await process.stderr.read() if process.stderr is not None else b""
                returncode = await process.wait()
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                stdout_text = "\n".join(stdout_records).strip()
                self._capture_runtime_metadata(stdout_text)
                reconnect_messages = self._extract_reconnect_messages(stderr_text, stdout_text)
                for reconnect_message in reconnect_messages:
                    logger.warning(
                        "codex_stream_reconnect_attempt",
                        extra={
                            "provider_session_id": self.provider_session_id,
                            "reconnect_message": reconnect_message,
                        },
                    )
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
                if (
                    self._has_history
                    and attempt == 0
                    and self._looks_like_stream_disconnect(detail, stderr_text, stdout_text, returncode)
                ):
                    logger.warning(
                        "codex_resume_stream_disconnect_retry",
                        extra={"provider_session_id": self.provider_session_id},
                    )
                    self._has_history = False
                    self.provider_session_id = ""
                    self.runtime_thread_id = ""
                    continue
                if "no last agent message" in detail.lower():
                    raise ProviderStaleSession(
                        "Codex resume failed due to stale session: {0}".format(detail),
                    )
                if self._looks_like_stream_disconnect(detail, stderr_text, stdout_text, returncode):
                    raise ProviderStreamDisconnected(
                        "Codex stream disconnected before completion: {0}".format(
                            detail or "unknown error"
                        ),
                    )
                if returncode == -9:
                    raise ProviderProcessKilled(
                        "Codex subprocess was killed: {0}".format(detail or "unknown error"),
                    )
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

    async def _cleanup_failed_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        with suppress(Exception):
            await process.wait()
        if process.stderr is not None:
            with suppress(Exception):
                await process.stderr.read()

    async def _iter_stream_records(
        self,
        stdout,
        *,
        process: asyncio.subprocess.Process,
        started_monotonic: float,
    ) -> AsyncIterator[_StreamRecord]:
        parser = _JsonStreamBuffer(max_buffer_chars=_STREAM_BUFFER_LIMIT)
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        warned = False
        chunk_count = 0
        total_chars = 0
        record_count = 0
        while True:
            elapsed = asyncio.get_running_loop().time() - started_monotonic
            if (
                not warned
                and self.warning_timeout is not None
                and self.warning_timeout > 0
                and elapsed >= self.warning_timeout
            ):
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
                chunk = await asyncio.wait_for(
                    stdout.read(_STDOUT_READ_CHUNK_SIZE),
                    timeout=min(1.0, remaining),
                )
            except asyncio.TimeoutError:
                continue
            except ValueError as exc:
                raise self._stream_parse_error(
                    "Codex stream read failed.",
                    parser=parser,
                    cause=exc,
                    stage="read",
                    chunk_count=chunk_count,
                    record_count=record_count,
                    total_chars=total_chars,
                ) from exc
            if not chunk:
                break
            text = decoder.decode(chunk)
            chunk_count += 1
            total_chars += len(text)
            try:
                for record in parser.feed(text):
                    record_count += 1
                    record.source = "{0}:chunk={1}:record={2}:chars={3}".format(
                        record.source,
                        chunk_count,
                        record_count,
                        total_chars,
                    )
                    yield record
            except ValueError as exc:
                raise self._stream_parse_error(
                    "Codex stream framing failed while buffering stdout.",
                    parser=parser,
                    cause=exc,
                    stage="buffer",
                    chunk_count=chunk_count,
                    record_count=record_count,
                    total_chars=total_chars,
                ) from exc

        tail = decoder.decode(b"", final=True)
        if tail:
            total_chars += len(tail)
            try:
                for record in parser.feed(tail):
                    record_count += 1
                    record.source = "{0}:flush:record={1}:chars={2}".format(
                        record.source,
                        record_count,
                        total_chars,
                    )
                    yield record
            except ValueError as exc:
                raise self._stream_parse_error(
                    "Codex stream framing failed while flushing stdout.",
                    parser=parser,
                    cause=exc,
                    stage="flush",
                    chunk_count=chunk_count,
                    record_count=record_count,
                    total_chars=total_chars,
                ) from exc
        for record in parser.finalize():
            record_count += 1
            record.source = "{0}:finalize:record={1}:chars={2}".format(
                record.source,
                record_count,
                total_chars,
            )
            yield record

    def _parse_stream_payload(
        self,
        raw_line: str,
        *,
        source: str,
        parser_preview: str,
    ) -> dict:
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise self._stream_parse_error(
                "Codex stream JSON decode failed.",
                parser_preview=parser_preview,
                cause=exc,
                stage="decode",
                raw_record=raw_line,
                record_source=source,
            ) from exc
        if not isinstance(payload, dict):
            cause = ValueError("decoded JSON payload is not an object")
            raise self._stream_parse_error(
                "Codex stream JSON payload must be an object.",
                parser_preview=parser_preview,
                cause=cause,
                stage="decode",
                raw_record=raw_line,
                record_source=source,
            ) from cause
        return payload

    def _stream_parse_error(
        self,
        message: str,
        *,
        parser: _JsonStreamBuffer | None = None,
        parser_preview: str | None = None,
        cause: BaseException,
        stage: str,
        chunk_count: int | None = None,
        record_count: int | None = None,
        total_chars: int | None = None,
        raw_record: str | None = None,
        record_source: str | None = None,
    ) -> ProviderStreamParseError:
        resolved_preview = parser.preview if parser is not None else (parser_preview or "-")
        error = ProviderStreamParseError(
            (
                "{0} provider={1} stage={2} buffer_chars={3} chunk_count={4} "
                "record_count={5} total_chars={6} record_source={7} preview={8!r} "
                "record_preview={9!r} cause={10}: {11}"
            ).format(
                message,
                self.provider_name,
                stage,
                parser.buffer_chars if parser is not None else 0,
                chunk_count if chunk_count is not None else "-",
                record_count if record_count is not None else "-",
                total_chars if total_chars is not None else "-",
                record_source or "-",
                resolved_preview,
                _truncate_preview(raw_record or ""),
                type(cause).__name__,
                str(cause),
            )
        )
        logger.error(
            "codex_stream_parse_failed",
            extra={
                "provider": self.provider_name,
                "provider_session_id": self.provider_session_id or "-",
                "error_code": error.error_code,
                "stream_stage": stage,
                "stream_buffer_chars": parser.buffer_chars if parser is not None else 0,
                "stream_buffer_preview": resolved_preview,
                "stream_chunk_count": chunk_count,
                "stream_record_count": record_count,
                "stream_total_chars": total_chars,
                "stream_record_source": record_source,
                "stream_record_preview": _truncate_preview(raw_record or ""),
                "subcommand": "resume" if self._has_history else "exec",
                "exception_type": type(cause).__name__,
                "exception_message": str(cause),
            },
            exc_info=(type(cause), cause, cause.__traceback__),
        )
        return error

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

    def _extract_reconnect_messages(self, stderr_text: str, stdout_text: str) -> list[str]:
        messages: list[str] = []
        for raw_line in (stderr_text + "\n" + stdout_text).splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "Reconnecting..." in line or "stream disconnected before completion" in line:
                messages.append(line)
        return messages

    def _looks_like_stream_disconnect(
        self,
        detail: str,
        stderr_text: str,
        stdout_text: str,
        returncode: int,
    ) -> bool:
        combined = "\n".join(part for part in (detail, stderr_text, stdout_text) if part).lower()
        if "stream disconnected before completion" in combined:
            return True
        if "reconnecting..." in combined:
            return True
        return returncode == -9 and "request id" in combined


def _truncate_preview(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= _LOG_PREVIEW_LIMIT:
        return compact
    return "{0}...".format(compact[: _LOG_PREVIEW_LIMIT - 3])


def _stdout_text_preview(stdout_records: Sequence[str]) -> str:
    if not stdout_records:
        return ""
    return "\n".join(stdout_records[-5:])
