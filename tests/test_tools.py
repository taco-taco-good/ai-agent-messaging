from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from agent_messaging.runtime.tools import ToolRuntime
from agent_messaging.tools.loader import load_external_tools


class ExternalToolLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_external_tools_registers_command_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            tool_dir = root / "tools" / "echo"
            tool_dir.mkdir(parents=True)
            (tool_dir / "tool.yaml").write_text(
                textwrap.dedent(
                    """
                    id: echo
                    capabilities:
                      - reflect
                    entry:
                      command:
                        - python3
                        - run.py
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (tool_dir / "run.py").write_text(
                textwrap.dedent(
                    """
                    import json
                    import sys

                    payload = json.load(sys.stdin)
                    json.dump(
                        {
                            "capability": payload["capability"],
                            "message": payload["params"]["message"],
                            "job_id": payload["context"]["job"]["id"],
                        },
                        sys.stdout,
                    )
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            runtime = ToolRuntime()
            definitions = load_external_tools(root / "tools", runtime)

            self.assertIn("echo", definitions)
            result = await runtime.call(
                "echo.reflect",
                {"message": "hello"},
                {"job": {"id": "heartbeat"}},
            )
            self.assertEqual(
                result,
                {"capability": "reflect", "message": "hello", "job_id": "heartbeat"},
            )

    async def test_external_tool_invalid_json_raises_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            tool_dir = root / "tools" / "broken"
            tool_dir.mkdir(parents=True)
            (tool_dir / "tool.yaml").write_text(
                textwrap.dedent(
                    """
                    id: broken
                    capabilities:
                      - parse
                    entry:
                      command:
                        - python3
                        - run.py
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (tool_dir / "run.py").write_text(
                "import sys\nsys.stdout.write('not-json')\n",
                encoding="utf-8",
            )

            runtime = ToolRuntime()
            load_external_tools(root / "tools", runtime)

            with self.assertRaisesRegex(RuntimeError, "returned invalid JSON"):
                await runtime.call("broken.parse", {}, {"job": {"id": "heartbeat"}})

    async def test_external_tool_timeout_raises_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            tool_dir = root / "tools" / "slow"
            tool_dir.mkdir(parents=True)
            (tool_dir / "tool.yaml").write_text(
                textwrap.dedent(
                    """
                    id: slow
                    timeout_seconds: 0.05
                    capabilities:
                      - wait
                    entry:
                      command:
                        - python3
                        - run.py
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (tool_dir / "run.py").write_text(
                textwrap.dedent(
                    """
                    import time

                    time.sleep(0.2)
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            runtime = ToolRuntime()
            load_external_tools(root / "tools", runtime)

            with self.assertRaisesRegex(RuntimeError, "timed out"):
                await runtime.call("slow.wait", {}, {"job": {"id": "heartbeat"}})

    def test_invalid_external_tool_manifest_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            tool_dir = root / "tools" / "invalid"
            tool_dir.mkdir(parents=True)
            (tool_dir / "tool.yaml").write_text(
                textwrap.dedent(
                    """
                    id: invalid
                    capabilities: not-a-list
                    entry:
                      command:
                        - python3
                        - run.py
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            runtime = ToolRuntime()
            definitions = load_external_tools(root / "tools", runtime)

            self.assertEqual(definitions, {})
