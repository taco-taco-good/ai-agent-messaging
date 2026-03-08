#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


DEFAULT_SERVICE_LABEL = "com.ai-agent-messaging"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show local setup status.")
    parser.add_argument("--root", default=".", help="Project root path")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args(argv)

    root_dir = Path(args.root).expanduser().resolve()
    payload = collect_status(root_dir)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_status(payload))
    return 0


def collect_status(root_dir: Path) -> dict[str, Any]:
    config_path = root_dir / "config" / "agents.yaml"
    venv_dir = root_dir / ".venv"
    runtime_dir = root_dir / "runtime"
    launchd = get_launchd_status(DEFAULT_SERVICE_LABEL) if sys.platform == "darwin" else None
    agents = load_agents(config_path)
    return {
        "root_dir": str(root_dir),
        "config_path": str(config_path),
        "config_exists": config_path.exists(),
        "venv_path": str(venv_dir),
        "venv_exists": (venv_dir / "bin" / "python").exists(),
        "runtime_dir": str(runtime_dir),
        "stdout_log": str(runtime_dir / "agent-messaging.stdout.log"),
        "stderr_log": str(runtime_dir / "agent-messaging.stderr.log"),
        "agent_count": len(agents),
        "agents": agents,
        "launchd": launchd,
    }


def load_agents(config_path: Path) -> list[dict[str, str]]:
    if not config_path.exists():
        return []
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    agents = payload.get("agents")
    if not isinstance(agents, dict):
        return []
    output: list[dict[str, str]] = []
    for agent_id, config in sorted(agents.items()):
        if not isinstance(agent_id, str) or not isinstance(config, dict):
            continue
        if agent_id.startswith("<") and agent_id.endswith(">"):
            continue
        output.append(
            {
                "agent_id": agent_id,
                "provider": str(config.get("provider") or ""),
                "model": str(config.get("model") or ""),
                "workspace_dir": str(config.get("workspace_dir") or ""),
                "memory_dir": str(config.get("memory_dir") or ""),
            }
        )
    return output


def get_launchd_status(label: str) -> dict[str, Any] | None:
    uid = str(os.getuid())
    plist_path = Path.home() / "Library" / "LaunchAgents" / "{0}.plist".format(label)
    result = subprocess.run(
        ["launchctl", "print", "gui/{0}/{1}".format(uid, label)],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "label": label,
        "plist_path": str(plist_path),
        "plist_exists": plist_path.exists(),
        "loaded": result.returncode == 0,
        "state": parse_launchctl_state(result.stdout) if result.returncode == 0 else "not_loaded",
    }


def parse_launchctl_state(output: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("state = "):
            return line.split("=", 1)[1].strip()
    return "loaded"


def render_status(payload: dict[str, Any]) -> str:
    lines = [
        "AI Agent Messaging Status",
        "=========================",
        "",
        "프로젝트 경로: {0}".format(payload["root_dir"]),
        "config: {0} ({1})".format(
            payload["config_path"],
            "exists" if payload["config_exists"] else "missing",
        ),
        "venv: {0} ({1})".format(
            payload["venv_path"],
            "ready" if payload["venv_exists"] else "missing",
        ),
        "stdout log: {0}".format(payload["stdout_log"]),
        "stderr log: {0}".format(payload["stderr_log"]),
        "",
        "agent 수: {0}".format(payload["agent_count"]),
    ]
    agents = payload["agents"]
    if agents:
        for agent in agents:
            lines.extend(
                [
                    "- {0}".format(agent["agent_id"]),
                    "  provider: {0}".format(agent["provider"]),
                    "  model: {0}".format(agent["model"]),
                    "  workspace: {0}".format(agent["workspace_dir"]),
                    "  memory: {0}".format(agent["memory_dir"]),
                ]
            )
    else:
        lines.append("- 등록된 agent 없음")
    launchd = payload.get("launchd")
    if launchd is not None:
        lines.extend(
            [
                "",
                "launchd:",
                "  label: {0}".format(launchd["label"]),
                "  plist: {0}".format(launchd["plist_path"]),
                "  plist_exists: {0}".format(launchd["plist_exists"]),
                "  loaded: {0}".format(launchd["loaded"]),
                "  state: {0}".format(launchd["state"]),
            ]
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
