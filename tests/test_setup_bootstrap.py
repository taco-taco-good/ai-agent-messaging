from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch


def _load_bootstrap_module():
    path = Path(__file__).resolve().parent.parent / "setup" / "bootstrap.py"
    spec = importlib.util.spec_from_file_location("setup_bootstrap", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load setup/bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bootstrap = _load_bootstrap_module()


def _load_status_module():
    path = Path(__file__).resolve().parent.parent / "setup" / "status.py"
    spec = importlib.util.spec_from_file_location("setup_status", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load setup/status.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status_module = _load_status_module()


def _load_restart_module():
    path = Path(__file__).resolve().parent.parent / "setup" / "restart.py"
    spec = importlib.util.spec_from_file_location("setup_restart", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load setup/restart.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


restart_module = _load_restart_module()


class SetupBootstrapTests(unittest.TestCase):
    def test_load_existing_agents_ignores_template_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / "agents.yaml"
            config_path.write_text(
                (
                    "agents:\n"
                    "  <agent-name>:\n"
                    "    provider: <provider>\n"
                    "  codex:\n"
                    "    provider: codex\n"
                    "    discord_token: token\n"
                ),
                encoding="utf-8",
            )
            agents = bootstrap.load_existing_agents(config_path)
            self.assertEqual(list(agents), ["codex"])

    def test_build_launch_agent_plist_uses_venv_binary_and_runtime_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root_dir = Path(tempdir)
            payload = bootstrap.build_launch_agent_plist(
                label="com.example.agent",
                root_dir=root_dir,
                venv_dir=root_dir / ".venv",
                config_path=root_dir / "config" / "agents.yaml",
                path_env="/opt/homebrew/bin:/usr/bin",
            )
            self.assertEqual(payload["Label"], "com.example.agent")
            self.assertEqual(
                payload["ProgramArguments"],
                [
                    str(root_dir / ".venv" / "bin" / "agent-messaging"),
                    "--config",
                    str(root_dir / "config" / "agents.yaml"),
                ],
            )
            self.assertEqual(payload["WorkingDirectory"], str(root_dir))
            self.assertTrue(payload["StandardOutPath"].endswith("runtime/agent-messaging.stdout.log"))

    def test_render_persona_template_includes_agent_name(self) -> None:
        content = bootstrap.render_persona_template("codex", "codex")
        self.assertIn("# codex", content)
        self.assertIn("기본 페르소나", content)

    def test_format_agent_summary_contains_core_fields(self) -> None:
        summary = bootstrap.format_agent_summary(
            "codex",
            {
                "display_name": "codex",
                "provider": "codex",
                "model": "gpt-5.4",
                "workspace_dir": "../workspace/codex",
                "memory_dir": "../memory/codex",
                "cli_args": ["--dangerously-bypass-approvals-and-sandbox"],
            },
        )
        self.assertIn("* codex", summary)
        self.assertIn("provider: codex", summary)
        self.assertIn("model: gpt-5.4", summary)

    def test_parse_cli_args_input_supports_none_keyword(self) -> None:
        self.assertEqual(
            bootstrap.parse_cli_args_input("none", provider="codex"),
            [],
        )

    def test_status_render_includes_launchd_section(self) -> None:
        rendered = status_module.render_status(
            {
                "root_dir": "/tmp/project",
                "config_path": "/tmp/project/config/agents.yaml",
                "config_exists": True,
                "venv_path": "/tmp/project/.venv",
                "venv_exists": True,
                "stdout_log": "/tmp/project/runtime/agent-messaging.stdout.log",
                "stderr_log": "/tmp/project/runtime/agent-messaging.stderr.log",
                "agent_count": 1,
                "agents": [
                    {
                        "agent_id": "codex",
                        "provider": "codex",
                        "model": "gpt-5.4",
                        "workspace_dir": "../workspace/codex",
                        "memory_dir": "../memory/codex",
                    }
                ],
                "launchd": {
                    "label": "com.ai-agent-messaging",
                    "plist_path": "/tmp/com.ai-agent-messaging.plist",
                    "plist_exists": True,
                    "loaded": True,
                    "state": "running",
                },
            }
        )
        self.assertIn("launchd:", rendered)
        self.assertIn("state: running", rendered)

    def test_restart_launch_agent_uses_kickstart_when_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root_dir = Path(tempdir)
            (root_dir / "config").mkdir()
            (root_dir / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
            (root_dir / ".venv" / "bin").mkdir(parents=True)
            (root_dir / ".venv" / "bin" / "agent-messaging").write_text("", encoding="utf-8")
            plist_path = root_dir / "Library" / "LaunchAgents" / "com.ai-agent-messaging.plist"
            plist_path.parent.mkdir(parents=True)
            plist_path.write_text("", encoding="utf-8")

            with (
                patch.object(restart_module.Path, "home", return_value=root_dir),
                patch.object(restart_module.os, "getuid", return_value=501),
                patch.object(restart_module.subprocess, "run") as mock_run,
            ):
                mock_run.side_effect = [
                    unittest.mock.Mock(returncode=0, stdout="state = running\n"),
                    unittest.mock.Mock(returncode=0, stdout=""),
                    unittest.mock.Mock(returncode=0, stdout="state = running\n"),
                ]
                result = restart_module.restart_launch_agent(
                    root_dir=root_dir,
                    label="com.ai-agent-messaging",
                )

            self.assertEqual(result["action"], "kickstart")
            self.assertEqual(result["state"], "running")
            self.assertTrue(result["ok"])
            mock_run.assert_has_calls(
                [
                    call(
                        ["launchctl", "print", "gui/501/com.ai-agent-messaging"],
                        check=False,
                        capture_output=True,
                        text=True,
                    ),
                    call(
                        ["launchctl", "kickstart", "-k", "gui/501/com.ai-agent-messaging"],
                        check=True,
                    ),
                    call(
                        ["launchctl", "print", "gui/501/com.ai-agent-messaging"],
                        check=False,
                        capture_output=True,
                        text=True,
                    ),
                ]
            )

    def test_restart_launch_agent_bootstraps_when_service_not_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root_dir = Path(tempdir)
            (root_dir / "config").mkdir()
            (root_dir / "config" / "agents.yaml").write_text("agents: {}\n", encoding="utf-8")
            (root_dir / ".venv" / "bin").mkdir(parents=True)
            (root_dir / ".venv" / "bin" / "agent-messaging").write_text("", encoding="utf-8")
            plist_path = root_dir / "Library" / "LaunchAgents" / "com.ai-agent-messaging.plist"
            plist_path.parent.mkdir(parents=True)
            plist_path.write_text("", encoding="utf-8")

            with (
                patch.object(restart_module.Path, "home", return_value=root_dir),
                patch.object(restart_module.os, "getuid", return_value=501),
                patch.object(restart_module.subprocess, "run") as mock_run,
            ):
                mock_run.side_effect = [
                    unittest.mock.Mock(returncode=113, stdout=""),
                    unittest.mock.Mock(returncode=0, stdout=""),
                    unittest.mock.Mock(returncode=0, stdout=""),
                    unittest.mock.Mock(returncode=0, stdout=""),
                    unittest.mock.Mock(returncode=0, stdout="state = spawn scheduled\n"),
                ]
                result = restart_module.restart_launch_agent(
                    root_dir=root_dir,
                    label="com.ai-agent-messaging",
                )

            self.assertEqual(result["action"], "bootstrap")
            self.assertEqual(result["state"], "spawn scheduled")
            self.assertTrue(result["ok"])
            mock_run.assert_has_calls(
                [
                    call(
                        ["launchctl", "print", "gui/501/com.ai-agent-messaging"],
                        check=False,
                        capture_output=True,
                        text=True,
                    ),
                    call(
                        [
                            "launchctl",
                            "bootstrap",
                            "gui/501",
                            str(plist_path),
                        ],
                        check=True,
                    ),
                    call(
                        ["launchctl", "enable", "gui/501/com.ai-agent-messaging"],
                        check=True,
                    ),
                    call(
                        ["launchctl", "kickstart", "-k", "gui/501/com.ai-agent-messaging"],
                        check=True,
                    ),
                    call(
                        ["launchctl", "print", "gui/501/com.ai-agent-messaging"],
                        check=False,
                        capture_output=True,
                        text=True,
                    ),
                ]
            )
