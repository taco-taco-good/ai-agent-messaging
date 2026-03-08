from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    cwd = None
    while args and args[0] in {"-C", "-c"}:
        if args[0] == "-C":
            cwd = Path(args[1])
        args = args[2:]

    if not args or args[0] != "exec":
        return 2

    resumed = len(args) > 1 and args[1] == "resume"
    index = 1
    if resumed:
        index = 3

    output_path = None
    model = "default"
    prompt = ""

    while index < len(args):
        token = args[index]
        if token == "--skip-git-repo-check" or token == "--json" or token == "--last":
            index += 1
            continue
        if token == "-c":
            index += 2
            continue
        if token == "-C":
            cwd = Path(args[index + 1])
            index += 2
            continue
        if token == "-o":
            output_path = Path(args[index + 1])
            index += 2
            continue
        if token == "-m":
            model = args[index + 1]
            index += 2
            continue
        prompt = token
        index += 1

    if cwd is not None:
        cwd.mkdir(parents=True, exist_ok=True)
    marker = cwd / ".fake-codex-history" if cwd is not None else None

    if resumed and marker is not None and not marker.exists():
        message = (
            "Warning: no last agent message; wrote empty content to "
            "{0}".format(output_path)
        )
        if output_path is not None:
            output_path.write_text("", encoding="utf-8")
        sys.stderr.write(message)
        return 1

    sys.stdout.write('{"type":"thread.started","thread_id":"thread-123"}\n')
    text = "resume:{0}:{1}".format(prompt, model) if resumed else "reply:{0}:{1}".format(prompt, model)
    if marker is not None:
        marker.write_text("has-history\n", encoding="utf-8")
    if output_path is not None:
        output_path.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
