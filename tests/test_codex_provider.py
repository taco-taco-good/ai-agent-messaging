from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from agent_messaging.providers.codex import CodexWrapper


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
