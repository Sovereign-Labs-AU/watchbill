#!/usr/bin/env python3
"""Claude Code PostToolUse adapter for scripts/heartbeat.py.

Reads the hook JSON from stdin and stamps the session's heartbeat. This exists because
hook commands receive `session_id` in their stdin JSON payload — NOT as an environment
variable. (An earlier draft of this wiring used an env var that does not exist; the
adoption audit caught that the stamp would silently never land, leaving the guard
permanently disarmed while looking wired. Hence: stdin, like guard_hook.py.)

Always exits 0 — a liveness stamp must never break a tool call.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import heartbeat  # noqa: E402


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    session = (payload.get("session_id") or "").strip()
    if session:
        try:
            heartbeat.stamp(session)
        except OSError:
            pass  # a full disk must not brick the session; the checker will notice staleness
    return 0


if __name__ == "__main__":
    sys.exit(main())
