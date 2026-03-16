from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path


def _run_child(marker_path: Path) -> None:
    def _cleanup_and_exit(*_args) -> None:
        try:
            marker_path.unlink()
        except FileNotFoundError:
            pass
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _cleanup_and_exit)
    signal.signal(signal.SIGINT, _cleanup_and_exit)
    marker_path.write_text("locked\n", encoding="utf-8")
    try:
        while True:
            time.sleep(0.1)
    finally:
        try:
            marker_path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    if "--child" in sys.argv:
        marker_arg = sys.argv[sys.argv.index("--child") + 1]
        _run_child(Path(marker_arg))
        return 0

    args = sys.argv[1:]
    session_id = args[args.index("--session-id") + 1]
    workspace = Path.cwd()
    marker = workspace / ".fake-cli-session-{0}".format(session_id)
    if marker.exists():
        print(
            "Error: Session ID {0} is already in use.".format(session_id),
            file=sys.stderr,
            flush=True,
        )
        return 1

    subprocess.Popen(
        [sys.executable, __file__, "--child", str(marker)],
        cwd=str(workspace),
    )
    time.sleep(10.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
