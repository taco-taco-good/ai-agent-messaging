#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_SERVICE_LABEL = "com.ai-agent-messaging"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restart the local AI Agent Messaging service.")
    parser.add_argument("--root", default=".", help="Project root path")
    parser.add_argument("--label", default=DEFAULT_SERVICE_LABEL, help="launchd service label")
    args = parser.parse_args(argv)

    root_dir = Path(args.root).expanduser().resolve()
    if sys.platform != "darwin":
        print("이 명령은 현재 macOS launchd 환경에서만 지원합니다.")
        print_manual_run_hint(root_dir)
        return 1

    result = restart_launch_agent(root_dir=root_dir, label=args.label)
    print(render_restart_result(result))
    return 0 if result["ok"] else 1


def restart_launch_agent(*, root_dir: Path, label: str) -> dict[str, str | bool]:
    plist_path = Path.home() / "Library" / "LaunchAgents" / "{0}.plist".format(label)
    config_path = root_dir / "config" / "agents.yaml"
    venv_agent_binary = root_dir / ".venv" / "bin" / "agent-messaging"
    uid = str(os.getuid())
    target = "gui/{0}/{1}".format(uid, label)

    if not plist_path.exists():
        return {
            "ok": False,
            "label": label,
            "target": target,
            "action": "missing_plist",
            "state": "not_loaded",
            "message": "launchd 서비스가 설치되어 있지 않습니다.",
        }

    if not config_path.exists():
        return {
            "ok": False,
            "label": label,
            "target": target,
            "action": "missing_config",
            "state": "not_loaded",
            "message": "config/agents.yaml이 없어 서비스를 시작할 수 없습니다.",
        }

    if not venv_agent_binary.exists():
        return {
            "ok": False,
            "label": label,
            "target": target,
            "action": "missing_binary",
            "state": "not_loaded",
            "message": ".venv/bin/agent-messaging가 없어 서비스를 시작할 수 없습니다.",
        }

    status = subprocess.run(
        ["launchctl", "print", target],
        check=False,
        capture_output=True,
        text=True,
    )
    was_loaded = status.returncode == 0
    action = "kickstart" if was_loaded else "bootstrap"

    if was_loaded:
        subprocess.run(["launchctl", "kickstart", "-k", target], check=True)
    else:
        subprocess.run(["launchctl", "bootstrap", "gui/{0}".format(uid), str(plist_path)], check=True)
        subprocess.run(["launchctl", "enable", target], check=True)
        subprocess.run(["launchctl", "kickstart", "-k", target], check=True)

    final_status = subprocess.run(
        ["launchctl", "print", target],
        check=False,
        capture_output=True,
        text=True,
    )
    state = parse_launchctl_state(final_status.stdout) if final_status.returncode == 0 else "unknown"
    return {
        "ok": final_status.returncode == 0,
        "label": label,
        "target": target,
        "action": action,
        "state": state,
        "message": "서비스를 재시작했고 변경사항은 다음 startup부터 반영됩니다.",
    }


def parse_launchctl_state(output: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("state = "):
            return line.split("=", 1)[1].strip()
    return "loaded"


def render_restart_result(result: dict[str, str | bool]) -> str:
    lines = [
        "AI Agent Messaging Restart",
        "==========================",
        "",
        "label: {0}".format(result["label"]),
        "target: {0}".format(result["target"]),
        "action: {0}".format(result["action"]),
        "state: {0}".format(result["state"]),
        "ok: {0}".format(result["ok"]),
        "message: {0}".format(result["message"]),
    ]
    return "\n".join(lines)


def print_manual_run_hint(root_dir: Path) -> None:
    print("수동 실행 명령:")
    print("  {0}".format(root_dir / ".venv" / "bin" / "agent-messaging"))
    print("  --config {0}".format(root_dir / "config" / "agents.yaml"))


if __name__ == "__main__":
    raise SystemExit(main())
