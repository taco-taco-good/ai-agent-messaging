from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

from agent_messaging.providers.claude import ClaudeWrapper
from agent_messaging.providers.base import (
    ProviderError,
    ProviderResponseTimeout,
    ProviderStaleSession,
    ProviderStartupError,
)
from agent_messaging.providers.gemini import GeminiWrapper


class SubprocessProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_subprocess_wrapper_handles_messages_and_model_switch(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="alpha",
                workspace_dir=Path(tempdir),
            )
            await wrapper.start()

            first = []
            async for chunk in wrapper.send_user_message("hello"):
                first.append(chunk)
            self.assertEqual(first, ["reply:hello:alpha"])

            resumed = []
            async for chunk in wrapper.send_user_message("again"):
                resumed.append(chunk)
            self.assertEqual(resumed, ["reply:again:alpha"])

            second = []
            async for chunk in wrapper.send_native_command("/model", {"model_alias": "beta"}):
                second.append(chunk)
            self.assertEqual(second, ["model:beta"])

            third = []
            async for chunk in wrapper.send_native_command("/stats"):
                third.append(chunk)
            self.assertEqual(len(third), 1)
            self.assertIn("Selected model: beta", third[0])
            self.assertIn("Exact model: pending confirmation", third[0])
            self.assertIn("Source: waiting for a new provider response", third[0])

            await wrapper.stop()

    async def test_subprocess_wrapper_reports_missing_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = ClaudeWrapper(
                executable="definitely-missing-cli-binary",
                base_args=[],
                default_model="alpha",
                workspace_dir=Path(tempdir),
            )
            with self.assertRaises(ProviderStartupError):
                await wrapper.start()

    async def test_gemini_wrapper_parses_json_output(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = GeminiWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="2.5-pro",
                workspace_dir=Path(tempdir),
            )

            chunks = []
            async for chunk in wrapper.send_user_message("hello"):
                chunks.append(chunk)
            self.assertEqual(chunks, ["reply:hello:2.5-pro"])

    async def test_claude_context_model_switch_changes_followup_prompt_args(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
                workspace_dir=Path(tempdir),
            )
            initial_session_id = wrapper.provider_session_id

            async for _ in wrapper.send_native_command("/model", {"model_alias": "sonnet-1m"}):
                pass

            self.assertNotEqual(wrapper.provider_session_id, initial_session_id)
            chunks = []
            async for chunk in wrapper.send_user_message("hello"):
                chunks.append(chunk)
            self.assertEqual(chunks, ["reply:hello:sonnet-1m"])

    async def test_claude_wrapper_stats_reads_exact_model_from_session_log(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            workspace = root / "workspace" / "claude"
            workspace.mkdir(parents=True, exist_ok=True)
            config_dir = root / "claude-home"
            session_id = "session-claude"
            project_dir = (
                config_dir
                / "projects"
                / "-{0}".format(str(workspace.resolve()).lstrip("/").replace("/", "-"))
            )
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "{0}.jsonl".format(session_id)).write_text(
                (
                    '{"type":"assistant","message":{"model":"claude-sonnet-4-6"}}\n'
                ),
                encoding="utf-8",
            )
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
                workspace_dir=workspace,
                provider_session_id=session_id,
                config_dir=config_dir,
            )
            chunks = []
            async for chunk in wrapper.send_native_command("/stats"):
                chunks.append(chunk)
            self.assertEqual(len(chunks), 1)
            self.assertIn("Selected model: sonnet", chunks[0])
            self.assertIn("Exact model: claude-sonnet-4-6", chunks[0])
            self.assertIn("Source: claude session log", chunks[0])

    async def test_claude_wrapper_does_not_emit_progress_before_hard_timeout(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
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

            self.assertEqual(chunks, ["reply:__sleep__:sonnet"])
            self.assertEqual(progress, [])

    async def test_claude_wrapper_clears_session_lock_after_timeout(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_forking_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir)
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
                workspace_dir=workspace,
                warning_timeout=0.05,
                hard_timeout=0.1,
            )
            await wrapper.start()
            session_id = wrapper.provider_session_id

            with self.assertRaises(ProviderResponseTimeout):
                async for _ in wrapper.send_user_message("timeout"):
                    pass

            for _ in range(50):
                marker = workspace / ".fake-cli-session-{0}".format(session_id)
                if not marker.exists():
                    break
                await asyncio.sleep(0.02)
            else:
                self.fail("Session lock marker was not cleared after timeout.")

            with self.assertRaises(ProviderResponseTimeout):
                async for _ in wrapper.send_user_message("retry"):
                    pass

    async def test_claude_wrapper_streams_multiple_text_deltas_in_order(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
                workspace_dir=Path(tempdir),
            )

            chunks = []
            async for chunk in wrapper.send_user_message("__split__"):
                chunks.append(chunk)

            self.assertEqual(chunks, ["reply:__s", "plit:sonnet"])

    async def test_claude_wrapper_keeps_long_running_stream_alive_while_output_continues(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
                workspace_dir=Path(tempdir),
                warning_timeout=0.05,
                hard_timeout=0.3,
            )

            chunks = []
            async for chunk in wrapper.send_user_message("__slowstream__"):
                chunks.append(chunk)

            self.assertEqual(chunks, ["reply:", "__", "slow", "stream__:sonnet"])

    async def test_claude_wrapper_handles_stream_json_lines_over_reader_limit(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
                workspace_dir=Path(tempdir),
            )

            chunks = []
            async for chunk in wrapper.send_user_message("__longline__"):
                chunks.append(chunk)

            self.assertEqual(chunks, ["x" * 70000])

    async def test_claude_wrapper_surfaces_stream_json_error_result_text(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
                workspace_dir=Path(tempdir),
            )

            with self.assertRaises(ProviderError) as context:
                async for _ in wrapper.send_user_message("__error_result__"):
                    pass

            self.assertEqual(str(context.exception), "synthetic stream failure")

    async def test_claude_wrapper_surfaces_stream_json_error_message_field(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
                workspace_dir=Path(tempdir),
            )

            with self.assertRaises(ProviderError) as context:
                async for _ in wrapper.send_user_message("__error_result_with_message_field__"):
                    pass

            self.assertEqual(str(context.exception), "synthetic execution failure")

    async def test_claude_wrapper_accepts_nonzero_exit_after_successful_stream(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
                workspace_dir=Path(tempdir),
            )

            chunks = []
            async for chunk in wrapper.send_user_message("__success_exit_1__"):
                chunks.append(chunk)

            self.assertEqual(chunks, ["reply:success-exit-1:sonnet"])

    async def test_claude_wrapper_classifies_stale_initial_session_error(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir)
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="sonnet",
                workspace_dir=workspace,
            )
            await wrapper.start()
            marker = workspace / ".fake-cli-session-{0}".format(wrapper.provider_session_id)
            marker.write_text("created\n", encoding="utf-8")

            with self.assertRaises(ProviderStaleSession) as context:
                async for _ in wrapper.send_user_message("hello"):
                    pass

            self.assertIn("already in use", str(context.exception))

    async def test_claude_wrapper_kills_streaming_process_on_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            fixture = root / "slow_stream.py"
            pid_file = root / "child.pid"
            fixture.write_text(
                (
                    "from __future__ import annotations\n"
                    "import sys\n"
                    "import time\n"
                    "from pathlib import Path\n"
                    "Path(sys.argv[1]).write_text(str(__import__('os').getpid()), encoding='utf-8')\n"
                    "time.sleep(30)\n"
                ),
                encoding="utf-8",
            )
            wrapper = ClaudeWrapper(
                executable=sys.executable,
                base_args=[str(fixture), str(pid_file)],
                default_model="sonnet",
                workspace_dir=root,
                warning_timeout=5.0,
                hard_timeout=60.0,
            )

            async def _consume() -> None:
                async for _ in wrapper.send_user_message("hello"):
                    pass

            task = asyncio.create_task(_consume())
            for _ in range(50):
                if pid_file.exists():
                    break
                await asyncio.sleep(0.02)
            self.assertTrue(pid_file.exists())
            child_pid = int(pid_file.read_text(encoding="utf-8").strip())

            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

            for _ in range(50):
                try:
                    os.kill(child_pid, 0)
                except OSError:
                    break
                await asyncio.sleep(0.02)
            else:
                self.fail("Claude streaming subprocess was not terminated after cancellation.")

    async def test_gemini_wrapper_stats_reads_exact_model_from_chat_log(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            workspace = root / "workspace" / "gemini"
            workspace.mkdir(parents=True, exist_ok=True)
            config_dir = root / "gemini-home"
            chats_dir = config_dir / "tmp" / "gemini" / "chats"
            chats_dir.mkdir(parents=True, exist_ok=True)
            import hashlib
            project_hash = hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()
            (chats_dir / "session-2026-03-08T11-03-042c8a20.json").write_text(
                (
                    "{{\n"
                    '  "sessionId": "042c8a20-9886-4922-85b7-ab035831ff13",\n'
                    '  "projectHash": "{0}",\n'
                    '  "lastUpdated": "2026-03-08T11:03:12.699Z",\n'
                    '  "messages": [\n'
                    '    {{"type": "gemini", "model": "gemini-2.5-flash"}}\n'
                    "  ]\n"
                    "}}\n"
                ).format(project_hash),
                encoding="utf-8",
            )
            wrapper = GeminiWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="auto-gemini-2.5",
                workspace_dir=workspace,
                config_dir=config_dir,
            )
            chunks = []
            async for chunk in wrapper.send_native_command("/stats"):
                chunks.append(chunk)
            self.assertEqual(len(chunks), 1)
            self.assertIn("Selected model: auto-gemini-2.5", chunks[0])
            self.assertIn("Exact model: gemini-2.5-flash", chunks[0])
            self.assertIn("Source: gemini chat log", chunks[0])
            self.assertIn("Observed session: 042c8a20-9886-4922-85b7-ab035831ff13", chunks[0])

    async def test_gemini_wrapper_stats_waits_for_new_response_after_model_change(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "fake_cli.py"
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            workspace = root / "workspace" / "gemini"
            workspace.mkdir(parents=True, exist_ok=True)
            config_dir = root / "gemini-home"
            chats_dir = config_dir / "tmp" / "gemini" / "chats"
            chats_dir.mkdir(parents=True, exist_ok=True)
            import hashlib
            project_hash = hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()
            (chats_dir / "session-2026-03-08T11-03-042c8a20.json").write_text(
                (
                    "{{\n"
                    '  "sessionId": "042c8a20-9886-4922-85b7-ab035831ff13",\n'
                    '  "projectHash": "{0}",\n'
                    '  "lastUpdated": "2026-03-08T11:03:12.699Z",\n'
                    '  "messages": [\n'
                    '    {{"type": "gemini", "model": "gemini-2.5-flash"}}\n'
                    "  ]\n"
                    "}}\n"
                ).format(project_hash),
                encoding="utf-8",
            )
            wrapper = GeminiWrapper(
                executable=sys.executable,
                base_args=[str(fixture)],
                default_model="auto-gemini-2.5",
                workspace_dir=workspace,
                config_dir=config_dir,
            )

            async for _ in wrapper.send_native_command("/model", {"model_alias": "gemini-2.5-pro"}):
                pass

            chunks = []
            async for chunk in wrapper.send_native_command("/stats"):
                chunks.append(chunk)
            self.assertEqual(len(chunks), 1)
            self.assertIn("Selected model: gemini-2.5-pro", chunks[0])
            self.assertIn("Exact model: pending confirmation", chunks[0])
            self.assertIn("Source: waiting for a new provider response", chunks[0])
