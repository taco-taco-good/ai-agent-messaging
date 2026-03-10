from __future__ import annotations

import logging
import tempfile
import textwrap
import unittest
from pathlib import Path

from agent_messaging.application.app import AgentMessagingApp
from agent_messaging.config.registry import AgentRegistry
from agent_messaging.core.models import AgentConfig
from agent_messaging.core.subagents import SubagentPersonaStore
from agent_messaging.memory.init_docs import init_doc_name
from agent_messaging.providers.base import CLIWrapper
from agent_messaging.runtime.session_manager import SessionManager
from agent_messaging.runtime.session_store import SessionStore


class _SubagentProvider(CLIWrapper):
    def __init__(self, agent: AgentConfig, default_model=None):
        super().__init__(default_model=default_model)
        self.agent = agent
        self._alive = False

    async def start(self) -> None:
        self._alive = True
        self.provider_session_id = "subagent-session"

    async def send_user_message(self, message: str):
        await self.start()
        init_doc = (
            self.agent.workspace_dir / init_doc_name(self.agent.provider)
        ).read_text(encoding="utf-8")
        yield "WORKSPACE={0}\nMODEL={1}\nPROMPT={2}\nMESSAGE={3}".format(
            self.agent.workspace_dir,
            self.current_model,
            init_doc,
            message,
        )

    async def send_native_command(self, command: str, args=None):
        yield command

    async def reset_session(self) -> None:
        self._alive = False

    async def stop(self) -> None:
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive


class SubagentPersonaStoreTests(unittest.TestCase):
    def test_load_supports_generic_claude_and_gemini_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            agents_dir = root / "agents"
            agents_dir.mkdir()
            (agents_dir / "reviewer.md").write_text(
                textwrap.dedent(
                    """
                    ---
                    description: Review implementation details.
                    tools:
                      - rg
                    ---
                    Focus on correctness first.
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            claude_dir = root / ".claude" / "agents"
            claude_dir.mkdir(parents=True)
            (claude_dir / "architect.md").write_text(
                textwrap.dedent(
                    """
                    ---
                    name: architect
                    description: Design large changes.
                    tools:
                      - read
                      - write
                    ---
                    Produce a concise architecture proposal.
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            gemini_dir = root / ".gemini" / "agents"
            gemini_dir.mkdir(parents=True)
            (gemini_dir / "planner.md").write_text(
                textwrap.dedent(
                    """
                    ---
                    name: planner
                    description: Break work into executable steps.
                    model: gemini-2.5-pro
                    max_turns: 8
                    timeout_mins: 3
                    ---
                    Return a short implementation plan.
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            store = SubagentPersonaStore(agents_dir)

            reviewer = store.load("reviewer")
            architect = store.load("architect")
            planner = store.load("planner")

            self.assertEqual(reviewer.source_format, "generic")
            self.assertEqual(reviewer.tools, ("rg",))
            self.assertEqual(architect.source_format, "claude")
            self.assertEqual(architect.tools, ("read", "write"))
            self.assertEqual(planner.source_format, "gemini")
            self.assertEqual(planner.model, "gemini-2.5-pro")
            self.assertEqual(planner.max_turns, 8)
            self.assertEqual(planner.timeout_mins, 3)


class SubagentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_registers_subagent_run_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            personas_dir = root / "config" / "personas"
            personas_dir.mkdir(parents=True)
            persona_file = personas_dir / "reviewer.md"
            persona_file.write_text("Main assistant persona.\n", encoding="utf-8")
            skills_dir = root / "skills"
            skills_dir.mkdir()
            (skills_dir / "reality-checker.md").write_text(
                "Reality checker skill.\n",
                encoding="utf-8",
            )
            agents_dir = root / "agents"
            agents_dir.mkdir()
            (agents_dir / "architect.md").write_text(
                textwrap.dedent(
                    """
                    ---
                    name: architect
                    description: Design the requested change.
                    model: beta
                    tools:
                      - read
                    ---
                    Provide a concise design.
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            agent = AgentConfig(
                agent_id="reviewer",
                display_name="Reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=root / "workspace" / "reviewer",
                memory_dir=root / "memory" / "reviewer",
                model="alpha",
                persona="Main assistant persona.",
                persona_file=persona_file,
            )
            registry = AgentRegistry({"reviewer": agent})
            session_manager = SessionManager(SessionStore(root / "runtime" / "sessions.json"))
            app = AgentMessagingApp(
                registry=registry,
                session_manager=session_manager,
                provider_factory=lambda config, session_key, session_record=None: _SubagentProvider(
                    config,
                    default_model=(session_record.current_model if session_record else None)
                    or config.model,
                ),
                subagents_dir=agents_dir,
                runtime_dir=root / "runtime",
                skills_dir=skills_dir,
            )

            result = await app.service.tool_runtime.call(
                "subagent.run",
                "reviewer",
                "architect",
                "Design a subagent system.",
                {"repo": "ai-agent-messaging"},
                ["reality-checker"],
            )

            self.assertEqual(result["persona_id"], "architect")
            self.assertEqual(result["source_format"], "generic")
            self.assertEqual(result["model"], "beta")
            self.assertIn(str(agent.workspace_dir / ".subagents"), result["workspace_root"])
            self.assertIn("Design the requested change.", result["response"])
            self.assertIn("Provide a concise design.", result["response"])
            self.assertIn("Design a subagent system.", result["response"])
            self.assertIn('"repo": "ai-agent-messaging"', result["response"])
            self.assertIn("## Persona", result["response"])
            self.assertIn(str((skills_dir / "reality-checker.md").resolve()), result["response"])
            self.assertFalse(Path(result["workspace_root"]).exists())

    async def test_subagent_emits_observability_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            skills_dir = root / "skills"
            skills_dir.mkdir()
            agents_dir = root / "agents"
            agents_dir.mkdir()
            (agents_dir / "architect.md").write_text(
                "---\nname: architect\n---\nDo the work.\n",
                encoding="utf-8",
            )

            agent = AgentConfig(
                agent_id="reviewer",
                display_name="Reviewer",
                provider="codex",
                discord_token="token",
                workspace_dir=root / "workspace" / "reviewer",
                memory_dir=root / "memory" / "reviewer",
                model="alpha",
                persona="Main assistant persona.",
            )
            registry = AgentRegistry({"reviewer": agent})
            session_manager = SessionManager(SessionStore(root / "runtime" / "sessions.json"))
            app = AgentMessagingApp(
                registry=registry,
                session_manager=session_manager,
                provider_factory=lambda config, session_key, session_record=None: _SubagentProvider(
                    config,
                    default_model=(session_record.current_model if session_record else None)
                    or config.model,
                ),
                subagents_dir=agents_dir,
                runtime_dir=root / "runtime",
                skills_dir=skills_dir,
            )

            with self.assertLogs("agent_messaging.core.subagents", level=logging.INFO) as captured:
                await app.service.tool_runtime.call(
                    "subagent.run",
                    "reviewer",
                    "architect",
                    "Do the work.",
                )

            joined = "\n".join(captured.output)
            self.assertIn("subagent_started", joined)
            self.assertIn("subagent_completed", joined)
