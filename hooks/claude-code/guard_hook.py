#!/usr/bin/env python3
"""Claude Code PreToolUse adapter for scripts/guard.py.

Reads the hook JSON from stdin (tool_input.file_path + session_id), asks the guard core
for a verdict, and maps it to hook semantics: block -> exit 2 with reason on stderr
(Claude Code stops the tool call and shows the reason); warn -> reason on stdout, exit 0;
allow -> exit 0.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from guard import decide  # noqa: E402


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # fail-open: a malformed hook payload must not brick the session
    target = (payload.get("tool_input") or {}).get("file_path") or ""
    session = payload.get("session_id") or ""
    if not target or not session:
        return 0
    verdict, reason = decide(Path("CLAIMS.md"), Path(".watchbill/heartbeats.json"),
                             session, target)
    if verdict == "block":
        print(f"watchbill guard: {reason}", file=sys.stderr)
        return 2
    if verdict == "warn":
        print(f"watchbill guard (warn): {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
