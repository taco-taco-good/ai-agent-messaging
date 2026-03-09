from __future__ import annotations

import sqlite3
import tempfile
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_messaging.config.settings import SettingsError
from agent_messaging.core.models import AgentConfig
from agent_messaging.config.registry import AgentRegistry
from agent_messaging.providers.base import CLIWrapper
from agent_messaging.runtime.tools import ToolRuntime
from agent_messaging.tasks import TaskRegistry, TaskRuntime, TaskScheduler, TaskStore, load_tasks


class _FakeProvider(CLIWrapper):
    provider_name = "fake"

    def __init__(self, default_model=None):
        super().__init__(default_model=default_model)
        self._alive = False

    async def start(self) -> None:
        self._alive = True
        self.provider_session_id = "task-session"

    async def send_user_message(self, message: str):
        yield "generated:{0}".format(message)

    async def send_native_command(self, command: str, args=None):
        yield command

    async def reset_session(self) -> None:
        self._alive = False

    async def stop(self) -> None:
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive


class TaskRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_load_tasks_rejects_unknown_step_type(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            tasks_dir = Path(tempdir)
            (tasks_dir / "bad.yaml").write_text(
                textwrap.dedent(
                    """
                    id: invalid_task
                    description: Invalid task
                    agent: codex
                    enabled: true
                    schedule:
                      kind: cron
                      expr: "0 7 * * *"
                    allowed_tools:
                      - task.noop
                    steps:
                      - id: invalid
                        type: unknown
                        tool: task.noop
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SettingsError, "Unsupported step type"):
                load_tasks(tasks_dir)

    def test_load_tasks_rejects_path_like_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            tasks_dir = Path(tempdir)
            (tasks_dir / "bad.yaml").write_text(
                textwrap.dedent(
                    """
                    id: ../escape
                    description: Invalid task
                    agent: codex
                    enabled: true
                    schedule:
                      kind: cron
                      expr: "0 7 * * *"
                    allowed_tools:
                      - task.noop
                    steps:
                      - id: ping
                        type: load
                        tool: task.noop
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SettingsError, "Invalid task id"):
                load_tasks(tasks_dir)

    async def test_daily_briefing_task_runs_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            tasks_dir = root / "config" / "tasks"
            tasks_dir.mkdir(parents=True)
            data_path = root / "runtime" / "collector.sqlite"
            data_path.parent.mkdir(parents=True)
            connection = sqlite3.connect(data_path)
            connection.execute("CREATE TABLE collected_items (title TEXT)")
            connection.execute("INSERT INTO collected_items (title) VALUES ('local ai update')")
            connection.commit()
            connection.close()

            (tasks_dir / "daily_ai_briefing.yaml").write_text(
                textwrap.dedent(
                    """
                    id: daily_ai_briefing
                    description: Daily briefing task
                    agent: codex
                    enabled: true
                    schedule:
                      kind: cron
                      expr: "0 7 * * *"
                      timezone: "Asia/Seoul"
                    allowed_tools:
                      - task.sqlite_query
                      - task.render_template
                      - task.run_agent_prompt
                      - task.send_discord_message
                      - task.persist_text
                    output:
                      channel_id: "12345"
                      artifact_path: "briefings/daily.md"
                    steps:
                      - id: load_items
                        type: load
                        tool: task.sqlite_query
                        with:
                          database_path: "__DATABASE_PATH__"
                          sql: "SELECT title FROM collected_items"
                      - id: compose_prompt
                        type: generate
                        tool: task.render_template
                        with:
                          template: "Make a briefing from {{ steps.load_items.rows }}"
                      - id: generate_briefing
                        type: generate
                        tool: task.run_agent_prompt
                        with:
                          prompt: "{{ steps.compose_prompt.content }}"
                      - id: deliver
                        type: deliver
                        tool: task.send_discord_message
                        with:
                          content: "{{ steps.generate_briefing.response }}"
                      - id: persist
                        type: persist
                        tool: task.persist_text
                        with:
                          content: "{{ steps.generate_briefing.response }}"
                    """
                ).replace("__DATABASE_PATH__", str(data_path)).strip()
                + "\n",
                encoding="utf-8",
            )

            task_registry = TaskRegistry(load_tasks(tasks_dir))
            agent = AgentConfig(
                agent_id="codex",
                provider="codex",
                discord_token="token",
                workspace_dir=root / "workspace" / "codex",
                memory_dir=root / "memory" / "codex",
                model="alpha",
            )
            sent: list[tuple[str, list[str]]] = []

            async def _send(channel_id: str, chunks: list[str]) -> None:
                sent.append((channel_id, chunks))

            runtime = TaskRuntime(
                registry=task_registry,
                tool_runtime=ToolRuntime(),
                store=TaskStore(root / "runtime" / "tasks.sqlite"),
                agent_registry=AgentRegistry({"codex": agent}),
                provider_factory=lambda config, session_key, session_record=None: _FakeProvider(
                    default_model=config.model
                ),
                runtime_dir=root / "runtime",
            )
            runtime.register_delivery_sender("codex", _send)

            result = await runtime.run_task("daily_ai_briefing")

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(sent[0][0], "12345")
            self.assertIn("generated:Make a briefing", sent[0][1][0])
            self.assertTrue((root / "runtime" / "briefings" / "daily.md").exists())

    async def test_register_task_persists_new_task_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            tasks_dir = root / "config" / "tasks"
            tasks_dir.mkdir(parents=True)
            registry = TaskRegistry({})
            store = TaskStore(root / "runtime" / "tasks.sqlite")
            runtime = TaskRuntime(
                registry=registry,
                tool_runtime=ToolRuntime(),
                store=store,
                runtime_dir=root / "runtime",
            )

            task = load_tasks(_write_single_task(tasks_dir, "heartbeat"))["heartbeat"]
            runtime.register_task(task)

            connection = sqlite3.connect(root / "runtime" / "tasks.sqlite")
            try:
                row = connection.execute(
                    "SELECT task_id, enabled FROM tasks WHERE task_id = ?",
                    ("heartbeat",),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(row, ("heartbeat", 1))

    async def test_persist_memory_writes_task_record(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            tasks_dir = root / "config" / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "persist_memory.yaml").write_text(
                textwrap.dedent(
                    """
                    id: persist_memory
                    description: Persist a task report
                    agent: codex
                    enabled: true
                    schedule:
                      kind: cron
                      expr: "0 7 * * *"
                      timezone: "UTC"
                    allowed_tools:
                      - task.render_template
                      - task.persist_memory
                    steps:
                      - id: compose
                        type: generate
                        tool: task.render_template
                        with:
                          template: "memory body"
                      - id: save
                        type: persist
                        tool: task.persist_memory
                        with:
                          content: "{{ steps.compose.content }}"
                          topic: "daily ai briefing"
                          summary: "Stored from task runtime."
                          tags:
                            - task
                            - briefing
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            agent = AgentConfig(
                agent_id="codex",
                provider="codex",
                discord_token="token",
                workspace_dir=root / "workspace" / "codex",
                memory_dir=root / "memory" / "codex",
                model="alpha",
            )
            runtime = TaskRuntime(
                registry=TaskRegistry(load_tasks(tasks_dir)),
                tool_runtime=ToolRuntime(),
                store=TaskStore(root / "runtime" / "tasks.sqlite"),
                agent_registry=AgentRegistry({"codex": agent}),
                runtime_dir=root / "runtime",
            )

            result = await runtime.run_task("persist_memory")

            assert result is not None
            memory_files = sorted((root / "memory" / "codex" / "tasks" / "persist_memory").rglob("run_*.md"))
            self.assertEqual(len(memory_files), 1)
            document = memory_files[0].read_text(encoding="utf-8")
            self.assertIn("record_type: task_run", document)
            self.assertIn("topic: daily ai briefing", document)
            self.assertIn("memory body", document)

    async def test_scheduler_runs_matching_slot_once(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            tasks_dir = root / "config" / "tasks"
            tasks_dir.mkdir(parents=True)
            (tasks_dir / "heartbeat.yaml").write_text(
                textwrap.dedent(
                    """
                    id: heartbeat
                    description: Heartbeat task
                    agent: codex
                    enabled: true
                    schedule:
                      kind: cron
                      expr: "0 7 * * *"
                      timezone: "UTC"
                    allowed_tools:
                      - task.noop
                    steps:
                      - id: ping
                        type: load
                        tool: task.noop
                        with:
                          message: ok
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            registry = TaskRegistry(load_tasks(tasks_dir))
            runtime = TaskRuntime(
                registry=registry,
                tool_runtime=ToolRuntime(),
                store=TaskStore(root / "runtime" / "tasks.sqlite"),
                runtime_dir=root / "runtime",
            )
            scheduler = TaskScheduler(registry, runtime, poll_interval=0.01)
            current = datetime(2026, 3, 10, 7, 0, tzinfo=timezone.utc)

            await scheduler.run_pending(current)
            await scheduler.run_pending(current)

            connection = sqlite3.connect(root / "runtime" / "tasks.sqlite")
            try:
                count = connection.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 1)


def _write_single_task(tasks_dir: Path, task_id: str) -> Path:
    path = tasks_dir / "{0}.yaml".format(task_id)
    path.write_text(
        textwrap.dedent(
            """
            id: __TASK_ID__
            description: Heartbeat task
            agent: codex
            enabled: true
            schedule:
              kind: cron
              expr: "0 7 * * *"
              timezone: "UTC"
            allowed_tools:
              - task.noop
            steps:
              - id: ping
                type: load
                tool: task.noop
                with:
                  message: ok
            """
        ).replace("__TASK_ID__", task_id).strip()
        + "\n",
        encoding="utf-8",
    )
    return tasks_dir
