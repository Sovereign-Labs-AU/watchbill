#!/usr/bin/env python3
"""Claude Code Stop adapter — the close-out reminder, addressed to the AGENT.

PROTOCOL.md §2.5-2.6 (reconcile, close out) is the one ritual step with nothing behind it, and
its failure is silent. This speaks when — and only when — the session actually owes something:
a live lease in its name, or an open notebook, with no `## Log` entry from it.

TWO CHANNELS, and the difference is the whole point:

  * `systemMessage`      -> the OPERATOR sees it. Verified in production.
  * `decision: "block"`  -> the reason is fed back to the MODEL, which keeps working instead of
                            stopping. This is Claude Code's documented Stop-hook contract for
                            returning control to the agent.

An earlier tool in this family reports to the operator precisely because a drifted agent
ignores warnings aimed at itself. This one is the other half: the agent is not drifted here, it
is simply DONE and about to walk away with the ledger half-written, which is a thing it can fix
in thirty seconds if something tells it now rather than telling somebody else tomorrow.

LOOP GUARD: Claude Code sets `stop_hook_active` when it is already continuing because of a stop
hook. If that is set, this NEVER blocks again — it downgrades to a message. A reminder that can
re-fire on the turn it caused is not a reminder, it is a trap, and the agent cannot escape it to
do the very work being demanded.

FAIL-OPEN: any error -> print nothing, exit 0. It must never be the reason a session cannot end.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            return 0
        session = str(payload.get("session_id") or "").strip()
        if not session:
            return 0                      # nothing to check against
        already_continuing = bool(payload.get("stop_hook_active"))
        r = subprocess.run(
            [sys.executable, str(REPO / "scripts/closeout.py"), "check", "--session", session],
            capture_output=True, text=True, cwd=str(Path.cwd()), timeout=10)
        if r.returncode != 1:
            return 0                      # 0 = nothing owed, 2 = unreadable: stay silent
        reason = r.stdout.strip()
        if not reason:
            return 0
        if already_continuing:
            # Say it once more where the operator can see it, but let the session end.
            print(json.dumps({"systemMessage": reason}))
            return 0
        print(json.dumps({
            "decision": "block",
            "reason": reason + "\n\nDo these now, then stop. If the work is still live, say so "
                               "and renew the lease instead of releasing it.",
            "systemMessage": "close-out incomplete — the session was asked to finish the ritual.",
        }))
    except Exception:
        return 0                          # fail-open: never trap a session
    return 0


if __name__ == "__main__":
    sys.exit(main())
