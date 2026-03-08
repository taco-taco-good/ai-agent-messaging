#!/usr/bin/env python3

from __future__ import annotations

import argparse
import curses
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


PROVIDER_CHOICES = ("codex", "claude", "gemini")
DEFAULT_MODELS = {
    "codex": "gpt-5.4",
    "claude": "sonnet",
    "gemini": "gemini-2.5-flash",
}
DEFAULT_CLI_ARGS = {
    "codex": ["--dangerously-bypass-approvals-and-sandbox"],
    "claude": ["--dangerously-skip-permissions"],
    "gemini": ["--approval-mode=yolo"],
}
DEFAULT_SERVICE_LABEL = "com.ai-agent-messaging"
_SECTION_WIDTH = 72
_COLOR_HEADER = 1
_COLOR_ACCENT = 2
_COLOR_OK = 3
_COLOR_WARN = 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive setup wizard.")
    parser.add_argument("--config", required=True, help="Path to config/agents.yaml")
    parser.add_argument("--no-tui", action="store_true", help="Use plain prompt mode")
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()
    root_dir = config_path.parent.parent
    venv_dir = root_dir / ".venv"

    agents = load_existing_agents(config_path)
    if should_use_tui(args.no_tui):
        agents = run_tui_wizard(
            config_path=config_path,
            root_dir=root_dir,
            venv_dir=venv_dir,
            existing_agents=agents,
        )
    else:
        print_header("AI Agent Messaging Setup")
        print_kv("프로젝트 경로", str(root_dir))
        print_kv("설정 파일", str(config_path))
        print_kv("가상환경", str(venv_dir))
        print("")
        print_section("현재 agent")
        print_existing_agents(agents)
        agents = prompt_agents(agents)
    if not agents:
        print("설정된 agent가 없습니다. 기존 파일은 유지합니다.")
        return 0

    print_section("저장 예정 설정")
    print_existing_agents(agents)
    write_agents_config(config_path, agents)
    ensure_persona_files(config_path.parent / "personas", agents)

    print("")
    print_section("저장 완료")
    print_kv("설정 파일", str(config_path))
    print_kv("agent 수", str(len(agents)))

    if sys.platform == "darwin":
        print("")
        print_section("백그라운드 실행")
        if prompt_yes_no(
            "launchd로 백그라운드 실행과 재부팅 후 자동 시작을 설정할까요?", True
        ):
            install_launch_agent(
                root_dir=root_dir,
                venv_dir=venv_dir,
                config_path=config_path,
                label=DEFAULT_SERVICE_LABEL,
            )
            status = get_launch_agent_state(DEFAULT_SERVICE_LABEL)
            print_kv("launchd 레이블", DEFAULT_SERVICE_LABEL)
            print_kv("launchd 상태", status or "unknown")
            print("launchd 서비스 설치 및 시작 완료")
        else:
            print("launchd 서비스 설치를 건너뛰었습니다.")
    else:
        print("")
        print("현재 플랫폼에서는 자동 시작 설정을 건너뜁니다: {0}".format(sys.platform))

    print("")
    print_section("다음 실행 명령")
    print("  source {0}/bin/activate".format(venv_dir))
    print("  agent-messaging --config {0}".format(config_path))
    return 0


def should_use_tui(disabled: bool) -> bool:
    if disabled:
        return False
    if sys.platform == "win32":
        return False
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    term = os.environ.get("TERM", "").lower()
    return bool(term and term != "dumb")


def run_tui_wizard(
    *,
    config_path: Path,
    root_dir: Path,
    venv_dir: Path,
    existing_agents: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    state = {
        "config_path": str(config_path),
        "root_dir": str(root_dir),
        "venv_dir": str(venv_dir),
        "agents": dict(existing_agents),
    }
    return curses.wrapper(_run_tui, state)


def _run_tui(stdscr, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    curses.curs_set(0)
    curses.use_default_colors()
    curses.start_color()
    curses.init_pair(_COLOR_HEADER, curses.COLOR_CYAN, -1)
    curses.init_pair(_COLOR_ACCENT, curses.COLOR_MAGENTA, -1)
    curses.init_pair(_COLOR_OK, curses.COLOR_GREEN, -1)
    curses.init_pair(_COLOR_WARN, curses.COLOR_YELLOW, -1)

    agents = dict(state["agents"])
    while True:
        draw_dashboard(
            stdscr,
            root_dir=state["root_dir"],
            config_path=state["config_path"],
            venv_dir=state["venv_dir"],
            agents=agents,
        )
        key = stdscr.getch()
        if key in {ord("q"), ord("Q")}:
            return dict(state["agents"])
        if key in {ord("s"), ord("S")}:
            return agents
        if key in {ord("a"), ord("A"), ord("e"), ord("E")}:
            result = tui_prompt_agent(stdscr, agents)
            if result is None:
                continue
            agent_id, payload = result
            agents[agent_id] = payload


def draw_dashboard(
    stdscr,
    *,
    root_dir: str,
    config_path: str,
    venv_dir: str,
    agents: dict[str, dict[str, Any]],
) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    add_line(stdscr, 1, 2, "AI Agent Messaging Setup", curses.color_pair(_COLOR_HEADER) | curses.A_BOLD)
    add_line(stdscr, 3, 2, "프로젝트 경로: {0}".format(trim_to_width(root_dir, width - 6)))
    add_line(stdscr, 4, 2, "설정 파일: {0}".format(trim_to_width(config_path, width - 6)))
    add_line(stdscr, 5, 2, "가상환경: {0}".format(trim_to_width(venv_dir, width - 6)))
    add_line(stdscr, 7, 2, "현재 agent", curses.color_pair(_COLOR_ACCENT) | curses.A_BOLD)
    row = 8
    if not agents:
        add_line(stdscr, row, 4, "등록된 agent가 없습니다.", curses.color_pair(_COLOR_WARN))
        row += 1
    else:
        for agent_id in sorted(agents):
            summary = format_agent_summary(agent_id, agents[agent_id]).splitlines()
            for line in summary:
                if row >= height - 5:
                    break
                add_line(stdscr, row, 4, trim_to_width(line, width - 8))
                row += 1
            row += 1
            if row >= height - 5:
                break
    add_line(
        stdscr,
        height - 3,
        2,
        "[A] agent 추가/수정   [S] 저장 후 계속   [Q] 취소",
        curses.color_pair(_COLOR_OK) | curses.A_BOLD,
    )
    stdscr.refresh()


def tui_prompt_agent(stdscr, existing_agents: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    agent_id = tui_prompt_text(
        stdscr,
        title="agent id 입력",
        label="agent id",
        default="",
        required=True,
    )
    if agent_id is None:
        return None
    if agent_id in existing_agents:
        overwrite = tui_prompt_yes_no(
            stdscr,
            "이미 존재하는 agent입니다. 덮어쓸까요?",
            default=False,
        )
        if not overwrite:
            return None
    existing = existing_agents.get(agent_id, {})
    display_name = tui_prompt_text(
        stdscr,
        title="agent 설정",
        label="display_name",
        default=str(existing.get("display_name") or agent_id),
        required=True,
        help_text="Discord와 로그에 표시되는 이름",
    )
    if display_name is None:
        return None
    provider = tui_prompt_choice(
        stdscr,
        title="agent 설정",
        label="provider",
        choices=PROVIDER_CHOICES,
        default=str(existing.get("provider") or "codex"),
    )
    if provider is None:
        return None
    model = tui_prompt_text(
        stdscr,
        title="agent 설정",
        label="model",
        default=str(existing.get("model") or DEFAULT_MODELS[provider]),
        required=True,
        help_text="기본 모델",
    )
    if model is None:
        return None
    discord_token = tui_prompt_text(
        stdscr,
        title="agent 설정",
        label="discord_token",
        default=str(existing.get("discord_token") or ""),
        required=True,
        help_text="Discord Bot 토큰",
    )
    if discord_token is None:
        return None
    persona_file = tui_prompt_text(
        stdscr,
        title="agent 설정",
        label="persona_file",
        default=str(existing.get("persona_file") or "./personas/{0}.md".format(agent_id)),
        required=True,
        help_text="persona markdown 경로",
    )
    if persona_file is None:
        return None
    workspace_dir = tui_prompt_text(
        stdscr,
        title="agent 설정",
        label="workspace_dir",
        default=str(existing.get("workspace_dir") or "../workspace/{0}".format(agent_id)),
        required=True,
        help_text="CLI 작업 디렉터리",
    )
    if workspace_dir is None:
        return None
    memory_dir = tui_prompt_text(
        stdscr,
        title="agent 설정",
        label="memory_dir",
        default=str(existing.get("memory_dir") or "../memory/{0}".format(agent_id)),
        required=True,
        help_text="메모리 저장 디렉터리",
    )
    if memory_dir is None:
        return None
    cli_args = tui_prompt_text(
        stdscr,
        title="agent 설정",
        label="cli_args",
        default=", ".join(
            [str(item) for item in existing.get("cli_args", [])] or DEFAULT_CLI_ARGS[provider]
        ),
        required=False,
        help_text="쉼표로 구분, none 입력 시 비움",
    )
    if cli_args is None:
        return None
    payload = {
        "display_name": display_name,
        "provider": provider,
        "discord_token": discord_token,
        "model": model,
        "persona_file": persona_file,
        "workspace_dir": workspace_dir,
        "memory_dir": memory_dir,
        "cli_args": parse_cli_args_input(cli_args, provider=provider),
    }
    show_message(stdscr, "입력 완료: {0}".format(agent_id))
    return agent_id, payload


def tui_prompt_text(
    stdscr,
    *,
    title: str,
    label: str,
    default: str,
    required: bool,
    help_text: str = "",
) -> str | None:
    curses.curs_set(1)
    buffer = default
    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        add_line(stdscr, 1, 2, title, curses.color_pair(_COLOR_HEADER) | curses.A_BOLD)
        add_line(stdscr, 3, 2, label, curses.color_pair(_COLOR_ACCENT) | curses.A_BOLD)
        if help_text:
            add_line(stdscr, 4, 2, trim_to_width(help_text, width - 4))
        add_line(stdscr, 6, 2, "현재값: {0}".format(trim_to_width(default or "(empty)", width - 12)))
        add_line(stdscr, 8, 2, "> " + trim_to_width(buffer, width - 6))
        add_line(stdscr, height - 3, 2, "Enter 저장   Esc 취소   Backspace 삭제", curses.color_pair(_COLOR_OK))
        stdscr.move(8, min(width - 2, 4 + len(buffer)))
        stdscr.refresh()
        key = stdscr.get_wch()
        if key in ("\n", "\r"):
            if buffer.strip():
                curses.curs_set(0)
                return buffer.strip()
            if default:
                curses.curs_set(0)
                return default
            if not required:
                curses.curs_set(0)
                return ""
        elif key == "\x1b":
            curses.curs_set(0)
            return None
        elif key in ("\b", "\x7f") or key == curses.KEY_BACKSPACE:
            buffer = buffer[:-1]
        elif isinstance(key, str) and key.isprintable():
            buffer += key


def tui_prompt_choice(
    stdscr,
    *,
    title: str,
    label: str,
    choices: tuple[str, ...],
    default: str,
) -> str | None:
    index = choices.index(default) if default in choices else 0
    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        add_line(stdscr, 1, 2, title, curses.color_pair(_COLOR_HEADER) | curses.A_BOLD)
        add_line(stdscr, 3, 2, label, curses.color_pair(_COLOR_ACCENT) | curses.A_BOLD)
        add_line(stdscr, 5, 2, "좌우 방향키로 선택", curses.color_pair(_COLOR_OK))
        for offset, choice in enumerate(choices):
            marker = ">" if offset == index else " "
            style = curses.color_pair(_COLOR_OK) | curses.A_BOLD if offset == index else curses.A_NORMAL
            add_line(stdscr, 7 + offset, 4, "{0} {1}".format(marker, choice), style)
        add_line(stdscr, height - 3, 2, "Enter 저장   Esc 취소", curses.color_pair(_COLOR_OK))
        stdscr.refresh()
        key = stdscr.getch()
        if key in {curses.KEY_LEFT, curses.KEY_UP}:
            index = (index - 1) % len(choices)
        elif key in {curses.KEY_RIGHT, curses.KEY_DOWN}:
            index = (index + 1) % len(choices)
        elif key in {10, 13}:
            return choices[index]
        elif key == 27:
            return None


def tui_prompt_yes_no(stdscr, question: str, *, default: bool) -> bool:
    while True:
        stdscr.erase()
        height, _ = stdscr.getmaxyx()
        add_line(stdscr, 2, 2, question, curses.color_pair(_COLOR_HEADER) | curses.A_BOLD)
        add_line(
            stdscr,
            4,
            2,
            "Y = 예   N = 아니오   기본값 = {0}".format("예" if default else "아니오"),
            curses.color_pair(_COLOR_OK),
        )
        add_line(stdscr, height - 3, 2, "Esc는 기본값으로 처리합니다.", curses.color_pair(_COLOR_WARN))
        stdscr.refresh()
        key = stdscr.getch()
        if key in {ord("y"), ord("Y")}:
            return True
        if key in {ord("n"), ord("N")}:
            return False
        if key in {10, 13, 27}:
            return default


def show_message(stdscr, message: str) -> None:
    stdscr.erase()
    add_line(stdscr, 2, 2, message, curses.color_pair(_COLOR_OK) | curses.A_BOLD)
    add_line(stdscr, 4, 2, "아무 키나 누르면 계속합니다.")
    stdscr.refresh()
    stdscr.getch()


def add_line(stdscr, row: int, col: int, text: str, style: int = 0) -> None:
    height, width = stdscr.getmaxyx()
    if row >= height or col >= width:
        return
    stdscr.addnstr(row, col, text, max(0, width - col - 1), style)


def trim_to_width(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def print_header(title: str) -> None:
    line = "=" * min(max(len(title), 24), _SECTION_WIDTH)
    print(line)
    print(title)
    print(line)


def print_section(title: str) -> None:
    line = "-" * _SECTION_WIDTH
    print(line)
    print(title)
    print(line)


def print_kv(label: str, value: str) -> None:
    print("{0}: {1}".format(label, value))


def load_existing_agents(config_path: Path) -> dict[str, dict[str, Any]]:
    if not config_path.exists():
        return {}
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    agents = payload.get("agents")
    if not isinstance(agents, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for agent_id, config in agents.items():
        if not isinstance(agent_id, str) or not isinstance(config, dict):
            continue
        if agent_id.startswith("<") and agent_id.endswith(">"):
            continue
        provider = config.get("provider")
        if isinstance(provider, str) and provider.startswith("<") and provider.endswith(">"):
            continue
        normalized[agent_id] = dict(config)
    return normalized


def prompt_agents(existing_agents: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    agents = dict(existing_agents)
    while True:
        default_add = not agents
        if not prompt_yes_no("agent를 추가하거나 수정할까요?", default_add):
            break
        print("")
        print_section("agent 입력")
        agent_id, payload = prompt_agent_config(agents)
        agents[agent_id] = payload
        print("")
        print("입력 완료:")
        print(format_agent_summary(agent_id, payload))
        print("")
    return agents


def prompt_agent_config(existing_agents: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    while True:
        agent_id = prompt_text("agent id", required=True)
        if agent_id not in existing_agents:
            break
        if prompt_yes_no("이미 존재하는 agent입니다. 덮어쓸까요?", False):
            break

    existing = existing_agents.get(agent_id, {})
    display_name = prompt_text(
        "display_name",
        default=str(existing.get("display_name") or agent_id),
        required=True,
    )
    provider = prompt_choice(
        "provider",
        PROVIDER_CHOICES,
        default=str(existing.get("provider") or "codex"),
    )
    model = prompt_text(
        "model",
        default=str(existing.get("model") or DEFAULT_MODELS[provider]),
        required=True,
    )
    discord_token = prompt_secret(
        "discord_token",
        default=str(existing.get("discord_token") or ""),
        required=True,
    )
    persona_file = prompt_text(
        "persona_file",
        default=str(existing.get("persona_file") or "./personas/{0}.md".format(agent_id)),
        required=True,
    )
    workspace_dir = prompt_text(
        "workspace_dir",
        default=str(existing.get("workspace_dir") or "../workspace/{0}".format(agent_id)),
        required=True,
    )
    memory_dir = prompt_text(
        "memory_dir",
        default=str(existing.get("memory_dir") or "../memory/{0}".format(agent_id)),
        required=True,
    )
    cli_args = prompt_cli_args(
        existing.get("cli_args"),
        provider=provider,
    )
    payload = {
        "display_name": display_name,
        "provider": provider,
        "discord_token": discord_token,
        "model": model,
        "persona_file": persona_file,
        "workspace_dir": workspace_dir,
        "memory_dir": memory_dir,
        "cli_args": cli_args,
    }
    return agent_id, payload


def prompt_cli_args(existing: Any, *, provider: str) -> list[str]:
    if isinstance(existing, list) and existing:
        default_args = [str(item) for item in existing]
    else:
        default_args = list(DEFAULT_CLI_ARGS[provider])
    default_display = ", ".join(default_args)
    raw = input(
        "cli_args (쉼표로 구분, 빈 값이면 기본값 사용) [{0}]: ".format(default_display)
    ).strip()
    return parse_cli_args_input(raw, provider=provider, default_args=default_args)


def parse_cli_args_input(
    raw: str,
    *,
    provider: str,
    default_args: list[str] | None = None,
) -> list[str]:
    resolved_default = default_args or list(DEFAULT_CLI_ARGS[provider])
    if not raw:
        return resolved_default
    if raw.lower() in {"none", "no", "-"}:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def prompt_text(label: str, default: str | None = None, *, required: bool = False) -> str:
    while True:
        suffix = " [{0}]".format(default) if default else ""
        value = input("{0}{1}: ".format(label, suffix)).strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""


def prompt_secret(label: str, default: str | None = None, *, required: bool = False) -> str:
    while True:
        suffix = " [existing]" if default else ""
        value = input("{0}{1}: ".format(label, suffix)).strip()
        if value:
            return value
        if default:
            return default
        if not required:
            return ""


def prompt_choice(label: str, choices: tuple[str, ...], *, default: str) -> str:
    indexed = {str(index + 1): choice for index, choice in enumerate(choices)}
    while True:
        print("{0}:".format(label))
        for index, choice in indexed.items():
            marker = " (default)" if choice == default else ""
            print("  {0}. {1}{2}".format(index, choice, marker))
        raw = input("> ").strip().lower()
        if not raw:
            return default
        if raw in indexed:
            return indexed[raw]
        if raw in choices:
            return raw


def prompt_yes_no(question: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw = input("{0} {1}: ".format(question, suffix)).strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False


def write_agents_config(config_path: Path, agents: dict[str, dict[str, Any]]) -> None:
    payload = {"agents": agents}
    config_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def ensure_persona_files(persona_dir: Path, agents: dict[str, dict[str, Any]]) -> None:
    persona_dir.mkdir(parents=True, exist_ok=True)
    for agent_id, payload in agents.items():
        relative_path = str(payload.get("persona_file") or "./personas/{0}.md".format(agent_id))
        target = resolve_persona_path(persona_dir.parent, relative_path)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            render_persona_template(agent_id, str(payload.get("display_name") or agent_id)),
            encoding="utf-8",
        )


def resolve_persona_path(config_dir: Path, relative_path: str) -> Path:
    return (config_dir / relative_path).resolve()


def render_persona_template(agent_id: str, display_name: str) -> str:
    return (
        "# {0}\n\n"
        "{1}의 기본 페르소나를 여기에 작성하세요.\n"
        "역할, 말투, 작업 원칙, 우선순위를 명확히 적는 것을 권장합니다.\n"
    ).format(agent_id, display_name)


def print_existing_agents(agents: dict[str, dict[str, Any]]) -> None:
    if not agents:
        print("기존 agent가 없습니다.")
        return
    for agent_id in sorted(agents):
        print(format_agent_summary(agent_id, agents[agent_id]))


def format_agent_summary(agent_id: str, payload: dict[str, Any]) -> str:
    provider = str(payload.get("provider") or "-")
    model = str(payload.get("model") or "-")
    display_name = str(payload.get("display_name") or agent_id)
    workspace_dir = str(payload.get("workspace_dir") or "-")
    memory_dir = str(payload.get("memory_dir") or "-")
    cli_args = payload.get("cli_args") or []
    cli_args_text = ", ".join(str(item) for item in cli_args) if cli_args else "(none)"
    return (
        "* {agent_id}\n"
        "  display_name: {display_name}\n"
        "  provider: {provider}\n"
        "  model: {model}\n"
        "  workspace: {workspace_dir}\n"
        "  memory: {memory_dir}\n"
        "  cli_args: {cli_args_text}"
    ).format(
        agent_id=agent_id,
        display_name=display_name,
        provider=provider,
        model=model,
        workspace_dir=workspace_dir,
        memory_dir=memory_dir,
        cli_args_text=cli_args_text,
    )


def install_launch_agent(
    *,
    root_dir: Path,
    venv_dir: Path,
    config_path: Path,
    label: str,
) -> None:
    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents_dir / "{0}.plist".format(label)
    plist_payload = build_launch_agent_plist(
        label=label,
        root_dir=root_dir,
        venv_dir=venv_dir,
        config_path=config_path,
        path_env=os.environ.get("PATH", ""),
    )
    plist_path.write_bytes(plistlib.dumps(plist_payload))

    uid = str(os.getuid())
    subprocess.run(
        ["launchctl", "bootout", "gui/{0}/{1}".format(uid, label)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["launchctl", "bootstrap", "gui/{0}".format(uid), str(plist_path)], check=True)
    subprocess.run(["launchctl", "enable", "gui/{0}/{1}".format(uid, label)], check=True)
    subprocess.run(
        ["launchctl", "kickstart", "-k", "gui/{0}/{1}".format(uid, label)],
        check=True,
    )


def get_launch_agent_state(label: str) -> str | None:
    uid = str(os.getuid())
    result = subprocess.run(
        ["launchctl", "print", "gui/{0}/{1}".format(uid, label)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("state = "):
            return line.split("=", 1)[1].strip()
    return "loaded"


def build_launch_agent_plist(
    *,
    label: str,
    root_dir: Path,
    venv_dir: Path,
    config_path: Path,
    path_env: str,
) -> dict[str, Any]:
    runtime_dir = root_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    agent_binary = venv_dir / "bin" / "agent-messaging"
    return {
        "Label": label,
        "ProgramArguments": [
            str(agent_binary),
            "--config",
            str(config_path),
        ],
        "WorkingDirectory": str(root_dir),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(runtime_dir / "agent-messaging.stdout.log"),
        "StandardErrorPath": str(runtime_dir / "agent-messaging.stderr.log"),
        "EnvironmentVariables": {
            "PATH": path_env,
            "PYTHONUNBUFFERED": "1",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
