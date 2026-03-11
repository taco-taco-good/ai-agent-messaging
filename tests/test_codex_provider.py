from __future__ import annotations

import asyncio
import io
import logging
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from agent_messaging.observability.logging import ContextFilter, KeyValueFormatter
from agent_messaging.providers.codex import CodexWrapper
from agent_messaging.providers.base import (
    ProviderResponseTimeout,
    ProviderStreamDisconnected,
    ProviderStreamParseError,
)


class _BrokenStdout:
    async def read(self, _size: int) -> bytes:
        raise ValueError("pipe is closed")


class CodexProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_codex_wrapper_uses_exec_then_resume(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5",
                workspace_dir=Path(tempdir),
            )
            await wrapper.start()

            first = []
            async for chunk in wrapper.send_user_message("hello"):
                first.append(chunk)
            self.assertEqual(first, ["reply:hello:gpt-5.3-codex"])
            self.assertEqual(wrapper.provider_session_id, "thread-123")

            second = []
            async for chunk in wrapper.send_user_message("again"):
                second.append(chunk)
            self.assertEqual(second, ["resume:again:gpt-5.3-codex"])

    async def test_codex_wrapper_falls_back_to_exec_when_persisted_session_has_no_history(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir)
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5",
                workspace_dir=workspace,
                provider_session_id="session-123",
            )

            first = []
            async for chunk in wrapper.send_user_message("hello"):
                first.append(chunk)
            self.assertEqual(first, ["reply:hello:gpt-5.3-codex"])
            self.assertEqual(wrapper.provider_session_id, "thread-123")

            second = []
            async for chunk in wrapper.send_user_message("again"):
                second.append(chunk)
            self.assertEqual(second, ["resume:again:gpt-5.3-codex"])

    def test_codex_wrapper_builds_resume_command_with_workspace_and_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir) / "workspace"
            output_path = Path(tempdir) / "last-message.txt"
            wrapper = CodexWrapper(
                executable="codex",
                default_model="gpt-5.4",
                workspace_dir=workspace,
                provider_session_id="thread-123",
            )

            command = list(wrapper._build_command("hello", output_path))

            self.assertEqual(command[:5], ["codex", "-c", 'model_reasoning_effort="medium"', "-C", str(workspace)])
            self.assertIn("resume", command)
            self.assertIn("thread-123", command)
            self.assertNotIn("--last", command)

    def test_codex_wrapper_normalizes_gpt5_alias(self) -> None:
        wrapper = CodexWrapper(default_model="gpt-5")
        self.assertEqual(wrapper.current_model, "gpt-5.3-codex")

    async def test_codex_wrapper_model_and_stats_are_adapter_backed(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5",
                workspace_dir=Path(tempdir),
            )

            model = []
            async for chunk in wrapper.send_native_command("/model", {"model_alias": "gpt-5-codex"}):
                model.append(chunk)
            self.assertEqual(model, ["model:gpt-5.3-codex"])

            stats = []
            async for chunk in wrapper.send_native_command("/stats"):
                stats.append(chunk)
            self.assertEqual(len(stats), 1)
            self.assertIn("Selected model: gpt-5.3-codex", stats[0])
            self.assertIn("Exact model: pending confirmation", stats[0])
            self.assertIn("Source: waiting for a new provider response", stats[0])

    async def test_codex_wrapper_does_not_emit_progress_for_fast_response(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5",
                workspace_dir=Path(tempdir),
            )
            progress = []

            async def _progress(message: str) -> None:
                progress.append(message)

            wrapper.set_progress_callback(_progress)
            chunks = []
            async for chunk in wrapper.send_user_message("hello"):
                chunks.append(chunk)

            self.assertEqual(chunks, ["reply:hello:gpt-5.3-codex"])
            self.assertEqual(progress, [])

    async def test_codex_wrapper_emits_warning_progress_for_slow_response(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5",
                workspace_dir=Path(tempdir),
                warning_timeout=0.05,
                hard_timeout=0.5,
            )
            progress = []

            async def _progress(message: str) -> None:
                progress.append(message)

            wrapper.set_progress_callback(_progress)
            chunks = []
            async for chunk in wrapper.send_user_message("__sleep__"):
                chunks.append(chunk)

            self.assertEqual(chunks, ["reply:__sleep__:gpt-5.3-codex"])
            self.assertEqual(progress, ["응답 생성에 시간이 걸리고 있습니다. 계속 처리 중입니다."])

    async def test_codex_wrapper_disables_warning_progress_when_timeout_notice_is_off(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5",
                workspace_dir=Path(tempdir),
                warning_timeout=None,
                hard_timeout=0.5,
            )
            progress = []

            async def _progress(message: str) -> None:
                progress.append(message)

            wrapper.set_progress_callback(_progress)
            chunks = []
            async for chunk in wrapper.send_user_message("__sleep__"):
                chunks.append(chunk)

            self.assertEqual(chunks, ["reply:__sleep__:gpt-5.3-codex"])
            self.assertEqual(progress, [])

    async def test_codex_wrapper_times_out_stalled_exec(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5",
                workspace_dir=Path(tempdir),
                hard_timeout=0.05,
            )

            with self.assertRaisesRegex(ProviderResponseTimeout, "did not respond"):
                async for _chunk in wrapper.send_user_message("__sleep__"):
                    pass

    async def test_codex_wrapper_retries_fresh_session_after_resume_disconnect(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir)
            marker = workspace / ".fake-codex-history"
            marker.write_text("has-history\n", encoding="utf-8")
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5",
                workspace_dir=workspace,
                provider_session_id="thread-123",
            )

            chunks = []
            async for chunk in wrapper.send_user_message("__disconnect__"):
                chunks.append(chunk)

            self.assertEqual(chunks, ["reply:__disconnect__:gpt-5.3-codex"])
            self.assertEqual(wrapper.provider_session_id, "thread-123")

    async def test_codex_wrapper_classifies_stream_disconnect_without_history_retry(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir)
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5",
                workspace_dir=workspace,
            )

            with self.assertRaises(ProviderStreamDisconnected):
                async for _chunk in wrapper.send_user_message("__disconnect_exec__"):
                    pass

    async def test_codex_wrapper_stats_reads_exact_model_from_rollout_log(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            workspace = root / "workspace" / "codex"
            workspace.mkdir(parents=True, exist_ok=True)
            codex_home = root / "codex-home"
            codex_home.mkdir(parents=True, exist_ok=True)
            rollout_path = codex_home / "sessions" / "rollout-test.jsonl"
            rollout_path.parent.mkdir(parents=True, exist_ok=True)
            rollout_path.write_text(
                (
                    '{"type":"turn_context","payload":{"model":"gpt-5.4"}}\n'
                ),
                encoding="utf-8",
            )
            connection = sqlite3.connect(str(codex_home / "state_5.sqlite"))
            try:
                connection.execute(
                    (
                        "create table threads ("
                        "id text primary key, "
                        "rollout_path text not null, "
                        "created_at integer not null, "
                        "updated_at integer not null, "
                        "source text not null default '', "
                        "model_provider text not null default '', "
                        "cwd text not null, "
                        "title text not null default '', "
                        "sandbox_policy text not null default '', "
                        "approval_mode text not null default '', "
                        "tokens_used integer not null default 0, "
                        "has_user_event integer not null default 0, "
                        "archived integer not null default 0, "
                        "archived_at integer, "
                        "git_sha text, "
                        "git_branch text, "
                        "git_origin_url text, "
                        "cli_version text not null default '', "
                        "first_user_message text not null default '', "
                        "agent_nickname text, "
                        "agent_role text, "
                        "memory_mode text not null default 'enabled'"
                        ")"
                    )
                )
                connection.execute(
                    (
                        "insert into threads "
                        "(id, rollout_path, created_at, updated_at, cwd, first_user_message) "
                        "values (?, ?, ?, ?, ?, ?)"
                    ),
                    (
                        "thread-123",
                        str(rollout_path),
                        1,
                        2,
                        str(workspace.resolve()),
                        "hello",
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5.4",
                workspace_dir=workspace,
                codex_home=codex_home,
            )
            stats = []
            async for chunk in wrapper.send_native_command("/stats"):
                stats.append(chunk)
            self.assertEqual(len(stats), 1)
            self.assertIn("Selected model: gpt-5.4", stats[0])
            self.assertIn("Exact model: gpt-5.4", stats[0])
            self.assertIn("Source: codex rollout log", stats[0])
            self.assertIn("Thread: thread-123", stats[0])

    async def test_codex_wrapper_streams_large_json_without_newline_separator(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5.4",
                workspace_dir=Path(tempdir),
            )

            chunks = []
            async for chunk in wrapper.send_user_message("__long_json_line__"):
                chunks.append(chunk)

            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0], "x" * 70000)

    async def test_codex_wrapper_streams_huge_json_without_premature_buffer_failure(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5.4",
                workspace_dir=Path(tempdir),
            )

            chunks = []
            async for chunk in wrapper.send_user_message("__huge_json_line__"):
                chunks.append(chunk)

            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0], "x" * 270000)

    async def test_codex_wrapper_logs_parse_context_for_invalid_long_stream(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5.4",
                workspace_dir=Path(tempdir),
            )

            stream = io.StringIO()
            handler = logging.StreamHandler(stream)
            handler.setFormatter(KeyValueFormatter())
            handler.addFilter(ContextFilter())
            logger = logging.getLogger("agent_messaging.providers.codex")
            previous_handlers = logger.handlers[:]
            previous_propagate = logger.propagate
            previous_level = logger.level
            logger.handlers = [handler]
            logger.propagate = False
            logger.setLevel(logging.ERROR)
            try:
                with self.assertRaises(ProviderStreamParseError) as raised:
                    async for _chunk in wrapper.send_user_message("__invalid_long_line__"):
                        pass
            finally:
                logger.handlers = previous_handlers
                logger.propagate = previous_propagate
                logger.setLevel(previous_level)

            self.assertIn("buffer_chars=", str(raised.exception))
            joined = stream.getvalue()
            self.assertIn("codex_stream_parse_failed", joined)
            self.assertIn('error_code="provider_stream_parse_error"', joined)
            self.assertIsInstance(raised.exception.__cause__, ValueError)
            self.assertIn('exception_type="ValueError"', joined)
            self.assertIn('stream_stage="buffer"', joined)
            self.assertIn("stream_buffer_chars=", joined)
            self.assertIn("stream_chunk_count=", joined)
            self.assertIn("stream_record_count=", joined)
            self.assertIn("stream_buffer_preview=", joined)

    async def test_codex_wrapper_logs_record_context_for_invalid_json_event(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5.4",
                workspace_dir=Path(tempdir),
            )

            stream = io.StringIO()
            handler = logging.StreamHandler(stream)
            handler.setFormatter(KeyValueFormatter())
            handler.addFilter(ContextFilter())
            logger = logging.getLogger("agent_messaging.providers.codex")
            previous_handlers = logger.handlers[:]
            previous_propagate = logger.propagate
            previous_level = logger.level
            logger.handlers = [handler]
            logger.propagate = False
            logger.setLevel(logging.ERROR)
            try:
                with self.assertRaises(ProviderStreamParseError) as raised:
                    async for _chunk in wrapper.send_user_message("__invalid_json_event__"):
                        pass
            finally:
                logger.handlers = previous_handlers
                logger.propagate = previous_propagate
                logger.setLevel(previous_level)

            self.assertIn("stage=decode", str(raised.exception))
            self.assertEqual(type(raised.exception.__cause__).__name__, "JSONDecodeError")
            joined = stream.getvalue()
            self.assertIn("codex_stream_parse_failed", joined)
            self.assertIn('stream_stage="decode"', joined)
            self.assertIn("stream_record_preview=", joined)
            self.assertIn("stream_record_source=", joined)
            self.assertIn('subcommand="exec"', joined)

    async def test_codex_wrapper_wraps_stdout_read_value_error_with_read_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                default_model="gpt-5.4",
                workspace_dir=Path(tempdir),
            )

            class _Process:
                def kill(self) -> None:
                    return None

                async def wait(self) -> int:
                    return 0

            with self.assertRaises(ProviderStreamParseError) as raised:
                records = wrapper._iter_stream_records(
                    _BrokenStdout(),
                    process=_Process(),
                    started_monotonic=asyncio.get_running_loop().time(),
                )
                await anext(records)

            self.assertIn("stage=read", str(raised.exception))
            self.assertIsInstance(raised.exception.__cause__, ValueError)

    async def test_codex_wrapper_logs_explicit_cause_for_non_object_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = CodexWrapper(
                executable=sys.executable,
                default_model="gpt-5.4",
                workspace_dir=Path(tempdir),
            )

            stream = io.StringIO()
            handler = logging.StreamHandler(stream)
            handler.setFormatter(KeyValueFormatter())
            handler.addFilter(ContextFilter())
            logger = logging.getLogger("agent_messaging.providers.codex")
            previous_handlers = logger.handlers[:]
            previous_propagate = logger.propagate
            previous_level = logger.level
            logger.handlers = [handler]
            logger.propagate = False
            logger.setLevel(logging.ERROR)
            try:
                with self.assertRaises(ProviderStreamParseError) as raised:
                    wrapper._parse_stream_payload(
                        "[]",
                        source="line:chunk=1:record=1:chars=2",
                        parser_preview="[]",
                    )
            finally:
                logger.handlers = previous_handlers
                logger.propagate = previous_propagate
                logger.setLevel(previous_level)

            self.assertIn("decoded JSON payload is not an object", str(raised.exception))
            self.assertIsInstance(raised.exception.__cause__, ValueError)
            joined = stream.getvalue()
            self.assertIn("codex_stream_parse_failed", joined)
            self.assertIn('exception_type="ValueError"', joined)
            self.assertIn("decoded JSON payload is not an object", joined)
            self.assertNotIn("NoneType: None", joined)

    async def test_codex_wrapper_cleans_up_process_after_stream_parse_failure(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir)
            wrapper = CodexWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="gpt-5.4",
                workspace_dir=workspace,
            )

            with self.assertRaises(ProviderStreamParseError):
                async for _chunk in wrapper.send_user_message("__invalid_long_line_with_sleep__"):
                    pass

            pid_path = workspace / ".fake-codex-pid"
            self.assertTrue(pid_path.exists())
            child_pid = int(pid_path.read_text(encoding="utf-8").strip())

            await asyncio.sleep(0.1)

            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
