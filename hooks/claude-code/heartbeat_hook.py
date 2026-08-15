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
    # A liveness stamp must NEVER break a tool call: any malformed payload — invalid
    # bytes, non-dict JSON, wrong-typed session_id — degrades to "no stamp", exit 0.
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        session = payload.get("session_id")
        if not isinstance(session, str) or not session.strip():
            return 0
        heartbeat.stamp(session.strip())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
