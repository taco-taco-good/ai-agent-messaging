from __future__ import annotations

import json
import sys
import time
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
    if prompt == "__sleep__":
        time.sleep(0.2)
    response = "reply:{0}:{1}".format(prompt, current_model)
    stream_chunks = [response]
    if prompt == "__split__":
        stream_chunks = ["reply:__s", "plit:{0}".format(current_model)]
    if prompt == "__slowstream__":
        stream_chunks = ["reply:", "__", "slow", "stream__:{0}".format(current_model)]
    if prompt == "__success_exit_1__":
        stream_chunks = ["reply:success-exit-1:{0}".format(current_model)]
    if prompt == "__longline__":
        stream_chunks = ["x" * 70000]
    if prompt == "__error_result__":
        response = "synthetic stream failure"
        stream_chunks = []
    if prompt == "__error_result_with_message_field__":
        response = ""
        stream_chunks = []
    if "--output-format" in args and args[args.index("--output-format") + 1] == "stream-json":
        print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
        for chunk in stream_chunks:
            if prompt == "__slowstream__":
                time.sleep(0.12)
            print(
                json.dumps(
                    {
                        "type": "stream_event",
                        "event": {
                            "type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": chunk},
                        },
                    }
                ),
                flush=True,
            )
        result_payload = {"type": "result", "subtype": "success", "result": response}
        if prompt == "__error_result__":
            result_payload["is_error"] = True
        if prompt == "__error_result_with_message_field__":
            result_payload = {
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "message": "synthetic execution failure",
            }
        print(json.dumps(result_payload), flush=True)
    elif "--output-format" in args and args[args.index("--output-format") + 1] == "json":
        print(
            json.dumps({"session_id": session_id or resume_id or "fake-session", "response": response}),
            flush=True,
        )
    else:
        print(response, flush=True)
    raise SystemExit(
        1 if prompt in {"__error_result__", "__error_result_with_message_field__", "__success_exit_1__"} else 0
    )

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
