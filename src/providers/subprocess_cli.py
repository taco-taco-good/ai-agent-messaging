from __future__ import annotations

import asyncio
import json
import logging
import os
import pty
import re
import shutil
import uuid
import select
import subprocess
import termios
from pathlib import Path
from typing import AsyncIterator, Callable, Dict, Iterable, List, Optional, Sequence

from agent_messaging.providers.base import (
    CLIWrapper,
    ProviderError,
    ProviderResponseTimeout,
    ProviderStartupError,
)


logger = logging.getLogger(__name__)
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\].*?(?:\x07|\x1b\\))")


class SubprocessCLIWrapper(CLIWrapper):
    provider_name = "subprocess"

    def __init__(
        self,
        executable: str,
        default_model: Optional[str] = None,
        workspace_dir: Optional[Path] = None,
        base_args: Optional[Sequence[str]] = None,
        supported_commands: Optional[Iterable[str]] = None,
        model_options: Optional[Sequence[str]] = None,
        read_timeout: float = 120.0,
        idle_timeout: float = 1.0,
        use_pty: bool = True,
        warning_timeout: float = 60.0,
        hard_timeout: float = 180.0,
        prompt_args: Optional[Sequence[str]] = None,
        model_args_builder: Optional[Callable[[str], Sequence[str]]] = None,
        initial_session_args_builder: Optional[Callable[[str], Sequence[str]]] = None,
        resume_session_args_builder: Optional[Callable[[str], Sequence[str]]] = None,
        provider_session_id: Optional[str] = None,
        output_parser: Optional[Callable[[str], str]] = None,
        reset_session_on_model_change: bool = False,
    ) -> None:
        super().__init__(default_model=default_model)
        self.executable = executable
        self.workspace_dir = workspace_dir
        self.base_args = list(base_args or [])
        self.supported_commands = tuple(supported_commands or self.supported_commands)
        self.model_options = tuple(model_options or self.model_options)
        self.read_timeout = read_timeout
        self.idle_timeout = idle_timeout
        self.use_pty = use_pty
        self.warning_timeout = warning_timeout
        self.hard_timeout = hard_timeout
        self.prompt_args = tuple(prompt_args or ())
        self.model_args_builder = model_args_builder
        self.initial_session_args_builder = initial_session_args_builder
        self.resume_session_args_builder = resume_session_args_builder
        self._process: Optional[asyncio.subprocess.Process] = None
        self._pty_process: Optional[subprocess.Popen] = None
        self._pty_master_fd: Optional[int] = None
        self._io_lock = asyncio.Lock()
        self._timeout_warning_issued = False
        self._started = False
        self.provider_session_id = provider_session_id or ""
        self._has_history = provider_session_id is not None
        self.output_parser = output_parser
        self.reset_session_on_model_change = reset_session_on_model_change

    async def start(self) -> None:
        if self.is_alive():
            return

        if self.workspace_dir is not None:
            self.workspace_dir.mkdir(parents=True, exist_ok=True)

        if self._uses_one_shot_mode:
            self._ensure_executable_exists()
            if not self.provider_session_id:
                self.provider_session_id = str(uuid.uuid4())
            self._started = True
            logger.info(
                "provider_started",
                extra={
                    "provider": self.provider_name,
                    "executable": self.executable,
                    "use_pty": False,
                    "execution_mode": "one_shot",
                    "provider_session_id": self.provider_session_id,
                },
            )
            return

        if self.use_pty:
            await asyncio.to_thread(self._start_pty_process)
        else:
            try:
                self._process = await asyncio.create_subprocess_exec(
                    self.executable,
                    *self.base_args,
                    cwd=str(self.workspace_dir) if self.workspace_dir is not None else None,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except FileNotFoundError as exc:
                raise ProviderStartupError(
                    "Provider executable not found: {0}".format(self.executable)
                ) from exc
        self.provider_session_id = str(uuid.uuid4())
        logger.info(
            "provider_started",
            extra={
                "provider": self.provider_name,
                "executable": self.executable,
                "use_pty": self.use_pty,
                "provider_session_id": self.provider_session_id,
            },
        )

    async def send_user_message(self, message: str) -> AsyncIterator[str]:
        if self._uses_one_shot_mode:
            await self.start()
            yield await self._run_one_shot_prompt(message)
            return
        response = await self._send_line(message)
        yield response

    async def send_native_command(
        self,
        command: str,
        args: Optional[Dict[str, object]] = None,
    ) -> AsyncIterator[str]:
        if self._uses_one_shot_mode:
            if command == "/stats":
                yield await self.stats_response()
                return
            response = self._handle_local_command(command, args or {})
            if response is None:
                response = await self._run_one_shot_prompt(self._format_command(command, args or {}))
            yield response
            return
        payload = self._format_command(command, args or {})
        response = await self._send_line(payload)
        yield response

    async def reset_session(self) -> None:
        await self.stop()
        await self.start()

    async def stop(self) -> None:
        if self._uses_one_shot_mode:
            self._started = False
            self.provider_session_id = ""
            self._has_history = False
            logger.info(
                "provider_stopped",
                extra={
                    "provider": self.provider_name,
                    "use_pty": False,
                    "execution_mode": "one_shot",
                    "provider_session_id": self.provider_session_id,
                },
            )
            return
        if self._pty_process is not None:
            await asyncio.to_thread(self._stop_pty_process)
            logger.info(
                "provider_stopped",
                extra={
                    "provider": self.provider_name,
                    "use_pty": True,
                    "provider_session_id": self.provider_session_id,
                },
            )
            return
        if self._process is None:
            return
        if self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._process = None
        self.provider_session_id = ""
        logger.info(
            "provider_stopped",
            extra={
                "provider": self.provider_name,
                "use_pty": False,
                "provider_session_id": self.provider_session_id,
            },
        )

    def is_alive(self) -> bool:
        if self._uses_one_shot_mode:
            return self._started
        if self._pty_process is not None:
            return self._pty_process.poll() is None
        return self._process is not None and self._process.returncode is None

    @property
    def _uses_one_shot_mode(self) -> bool:
        return bool(self.prompt_args)

    async def _send_line(self, payload: str) -> str:
        await self.start()
        logger.debug(
            "provider_send_line",
            extra={"provider": self.provider_name, "payload_preview": payload[:120]},
        )
        if self._pty_process is not None:
            return await asyncio.to_thread(self._send_line_via_pty, payload)
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("Provider process is not available.")

        async with self._io_lock:
            self._process.stdin.write((payload.rstrip("\n") + "\n").encode("utf-8"))
            await self._process.stdin.drain()
            return await self._read_until_idle()

    async def _read_until_idle(self) -> str:
        if self._process is None or self._process.stdout is None:
            return ""

        self._timeout_warning_issued = False
        chunks: List[str] = []

        # Stage 1: wait for initial response with staged timeouts
        first = await self._read_first_line_staged()

        if first:
            chunks.append(first.decode("utf-8", errors="replace"))

        while True:
            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=self.idle_timeout,
                )
            except asyncio.TimeoutError:
                break
            if not line:
                break
            chunks.append(line.decode("utf-8", errors="replace"))

        return self._sanitize_output("".join(chunks).rstrip("\n"))

    async def _read_first_line_staged(self) -> bytes:
        """Read with warning_timeout -> read_timeout -> hard_timeout stages."""
        assert self._process is not None and self._process.stdout is not None
        remaining = self.hard_timeout

        # Stage 1: warning timeout
        stage1 = min(self.warning_timeout, remaining)
        try:
            return await asyncio.wait_for(self._process.stdout.readline(), timeout=stage1)
        except asyncio.TimeoutError:
            pass

        remaining -= stage1
        if remaining <= 0:
            raise ProviderResponseTimeout(
                "Provider did not respond within {0} seconds.".format(self.hard_timeout)
            )

        self._timeout_warning_issued = True
        logger.warning(
            "provider_response_slow",
            extra={"provider": self.provider_name, "elapsed_seconds": stage1},
        )

        # Stage 2: continue waiting until read_timeout
        stage2 = min(self.read_timeout - stage1, remaining)
        if stage2 > 0:
            try:
                return await asyncio.wait_for(self._process.stdout.readline(), timeout=stage2)
            except asyncio.TimeoutError:
                pass
            remaining -= stage2

        if remaining <= 0:
            raise ProviderResponseTimeout(
                "Provider did not respond within {0} seconds.".format(self.hard_timeout)
            )

        # Stage 3: hard timeout (last chance)
        logger.warning(
            "provider_response_timeout_approaching",
            extra={"provider": self.provider_name, "remaining_seconds": remaining},
        )
        try:
            return await asyncio.wait_for(self._process.stdout.readline(), timeout=remaining)
        except asyncio.TimeoutError:
            logger.warning(
                "provider_response_timeout",
                extra={"provider": self.provider_name, "timeout_seconds": self.hard_timeout},
            )
            raise ProviderResponseTimeout(
                "Provider did not respond within {0} seconds.".format(self.hard_timeout)
            )

    def _start_pty_process(self) -> None:
        master_fd, slave_fd = pty.openpty()
        try:
            attrs = termios.tcgetattr(slave_fd)
            attrs[3] = attrs[3] & ~termios.ECHO
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
            self._pty_process = subprocess.Popen(
                [self.executable, *self.base_args],
                cwd=str(self.workspace_dir) if self.workspace_dir is not None else None,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
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
            os.close(master_fd)
            raise ProviderStartupError(
                "Provider executable not found: {0}".format(self.executable)
            ) from exc
        except Exception:
            # Ensure master_fd is closed on any unexpected error
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)
        self._pty_master_fd = master_fd

    def _stop_pty_process(self) -> None:
        proc = self._pty_process
        fd = self._pty_master_fd
        self._pty_process = None
        self._pty_master_fd = None
        self.provider_session_id = ""
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
        finally:
            # Always close the fd, even if terminate/kill raised
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _send_line_via_pty(self, payload: str) -> str:
        if self._pty_process is None or self._pty_master_fd is None:
            raise RuntimeError("Provider PTY process is not available.")

        os.write(self._pty_master_fd, (payload.rstrip("\n") + "\n").encode("utf-8"))

        self._timeout_warning_issued = False
        chunks: List[bytes] = []
        started = False
        elapsed = 0.0

        while True:
            if started:
                timeout = self.idle_timeout
            elif elapsed < self.warning_timeout:
                timeout = min(self.warning_timeout - elapsed, self.hard_timeout - elapsed)
            elif elapsed < self.read_timeout:
                timeout = min(self.read_timeout - elapsed, self.hard_timeout - elapsed)
            else:
                timeout = max(self.hard_timeout - elapsed, 0.0)

            if timeout <= 0:
                raise ProviderResponseTimeout(
                    "Provider did not respond within {0} seconds.".format(self.hard_timeout)
                )

            ready, _, _ = select.select([self._pty_master_fd], [], [], timeout)
            if not ready:
                if started:
                    break
                elapsed += timeout
                if elapsed >= self.hard_timeout:
                    raise ProviderResponseTimeout(
                        "Provider did not respond within {0} seconds.".format(self.hard_timeout)
                    )
                if not self._timeout_warning_issued and elapsed >= self.warning_timeout:
                    self._timeout_warning_issued = True
                    logger.warning(
                        "provider_response_slow",
                        extra={"provider": self.provider_name, "elapsed_seconds": elapsed},
                    )
                continue

            try:
                chunk = os.read(self._pty_master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            started = True
            chunks.append(chunk)

        return self._sanitize_output(
            b"".join(chunks).decode("utf-8", errors="replace").rstrip("\r\n")
        )

    async def _run_one_shot_prompt(self, prompt: str) -> str:
        command = self._build_one_shot_command(prompt)
        logger.debug(
            "provider_send_line",
            extra={
                "provider": self.provider_name,
                "payload_preview": prompt[:120],
                "execution_mode": "one_shot",
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
            raise ProviderStartupError(
                "Provider executable not found: {0}".format(self.executable)
            ) from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.hard_timeout,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise ProviderResponseTimeout(
                "Provider did not respond within {0} seconds.".format(self.hard_timeout)
            ) from exc
        output = stdout.decode("utf-8", errors="replace")
        error_output = stderr.decode("utf-8", errors="replace")
        combined_output = "\n".join(part for part in (output, error_output) if part)
        sanitized_output = self._sanitize_output(output).strip()
        sanitized_combined = self._sanitize_output(combined_output).strip()
        if self.output_parser is not None:
            try:
                parsed = self.output_parser(sanitized_output or sanitized_combined).strip()
            except ProviderError:
                raise
            else:
                if process.returncode == 0:
                    self._has_history = True
                    await self._after_one_shot_success(
                        raw_output=sanitized_output or sanitized_combined,
                        parsed_output=parsed,
                    )
                    return parsed
        if process.returncode != 0:
            raise ProviderStartupError(
                "Provider exited with code {0}: {1}".format(
                    process.returncode,
                    sanitized_combined or "unknown error",
                )
            )
        self._has_history = True
        await self._after_one_shot_success(
            raw_output=sanitized_output or sanitized_combined,
            parsed_output=sanitized_output or sanitized_combined,
        )
        return sanitized_output or sanitized_combined

    def _build_one_shot_command(self, prompt: str) -> List[str]:
        command = [self.executable, *self.base_args]
        if self.provider_session_id:
            if self._has_history and self.resume_session_args_builder is not None:
                command.extend(self.resume_session_args_builder(self.provider_session_id))
            elif not self._has_history and self.initial_session_args_builder is not None:
                command.extend(self.initial_session_args_builder(self.provider_session_id))
        if self.model_args_builder is not None and self.current_model:
            command.extend(self.model_args_builder(self.current_model))
        command.extend(self.prompt_args)
        command.append(prompt)
        return command

    def _handle_local_command(self, command: str, args: Dict[str, object]) -> Optional[str]:
        if command == "/help":
            return "Supported commands: {0}".format(", ".join(self.supported_commands))
        if command == "/model":
            model_alias = args.get("model_alias")
            if model_alias:
                self.current_model = str(model_alias)
                self.clear_resolved_model()
                if self.reset_session_on_model_change and self._uses_one_shot_mode:
                    self.provider_session_id = str(uuid.uuid4())
                    self._has_history = False
            return "model:{0}".format(self.current_model or "default")
        if command == "/models":
            return "\n".join(self.available_model_options())
        return None

    async def _after_one_shot_success(self, raw_output: str, parsed_output: str) -> None:
        del raw_output
        del parsed_output

    def _ensure_executable_exists(self) -> None:
        executable_path = Path(self.executable)
        if executable_path.is_absolute() or "/" in self.executable:
            exists = executable_path.exists()
        else:
            exists = shutil.which(self.executable) is not None
        if not exists:
            raise ProviderStartupError(
                "Provider executable not found: {0}".format(self.executable)
            )

    def _sanitize_output(self, output: str) -> str:
        return _ANSI_ESCAPE_RE.sub("", output)

    def _format_command(self, command: str, args: Dict[str, object]) -> str:
        if command == "/model" and args.get("model_alias"):
            self.current_model = str(args["model_alias"])
            return "{0} {1}".format(command, self.current_model)

        if not args:
            return command

        parts = [command]
        for key in sorted(args):
            value = args[key]
            if value is None:
                continue
            parts.append(str(value))
        return " ".join(parts)
