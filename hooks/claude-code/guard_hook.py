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
    # Fail-open on ANY malformed payload — and fail-open EXPLICITLY, never by crashing:
    # an uncaught exception exits 1, which is indistinguishable from a real WARN to the
    # caller. The battle-proof gauntlet caught exactly that disguise.
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        tool_input = payload.get("tool_input")
        target = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        session = payload.get("session_id")
        if not isinstance(target, str) or not target or not isinstance(session, str) or not session:
            return 0
        verdict, reason = decide(Path("CLAIMS.md"), Path(".watchbill/heartbeats.json"),
                                 session, target)
    except Exception:
        return 0
    if verdict == "block":
        print(f"watchbill guard: {reason}", file=sys.stderr)
        return 2
    if verdict == "warn":
        print(f"watchbill guard (warn): {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
