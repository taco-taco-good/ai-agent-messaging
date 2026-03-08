from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from agent_messaging.providers.claude import ClaudeWrapper
from agent_messaging.providers.base import ProviderStartupError
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
