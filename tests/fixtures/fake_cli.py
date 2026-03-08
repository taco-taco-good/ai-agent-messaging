from __future__ import annotations

import json
import sys
from pathlib import Path

current_model = "alpha"

args = sys.argv[1:]
if "-p" in args:
    prompt = args[-1]
    session_id = None
    resume_id = None
    if "--session-id" in args:
        session_id = args[args.index("--session-id") + 1]
    if "--resume" in args:
        resume_id = args[args.index("--resume") + 1]
    workspace = Path.cwd()
    if session_id is not None:
        marker = workspace / ".fake-cli-session-{0}".format(session_id)
        if marker.exists():
            print(
                "Error: Session ID {0} is already in use.".format(session_id),
                file=sys.stderr,
                flush=True,
            )
            raise SystemExit(1)
        marker.write_text("created\n", encoding="utf-8")
    if resume_id is not None:
        marker = workspace / ".fake-cli-session-{0}".format(resume_id)
        if not marker.exists():
            print(
                "Error: Session ID {0} does not exist.".format(resume_id),
                file=sys.stderr,
                flush=True,
            )
            raise SystemExit(1)
    if "--model" in args:
        current_model = args[args.index("--model") + 1]
    elif "-m" in args:
        current_model = args[args.index("-m") + 1]
    if "--betas" in args and "context-1m-2025-08-07" in args:
        current_model = "{0}-1m".format(current_model)
    response = "reply:{0}:{1}".format(prompt, current_model)
    if "--output-format" in args and args[args.index("--output-format") + 1] == "json":
        print(
            json.dumps({"session_id": session_id or resume_id or "fake-session", "response": response}),
            flush=True,
        )
    else:
        print(response, flush=True)
    raise SystemExit(0)

for line in sys.stdin:
    payload = line.strip()
    if not payload:
        continue
    if payload.startswith("/model "):
        current_model = payload.split(" ", 1)[1]
        print("model:{0}".format(current_model), flush=True)
    elif payload == "/help":
        print("/help:/stats:/model", flush=True)
    elif payload == "/stats":
        print("stats:model={0}".format(current_model), flush=True)
    else:
        print("reply:{0}:{1}".format(payload, current_model), flush=True)
