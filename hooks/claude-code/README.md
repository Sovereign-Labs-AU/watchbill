# Wiring Watchbill into Claude Code

Two hooks connect a Claude Code session to the protocol: the **heartbeat** (liveness is
measured, never asserted) and the **guard** (the ownership check before writes/deletes).
Other harnesses wire the same two scripts through whatever hook mechanism they provide —
the scripts are plain CLIs with exit codes; nothing here is vendor-specific except the
JSON plumbing.

Add to your project's `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 scripts/heartbeat.py stamp \"$CLAUDE_SESSION_ID\""
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 hooks/claude-code/guard_hook.py"
          }
        ]
      }
    ]
  }
}
```

`guard_hook.py` (in this directory) reads the tool call's target path from the hook's
stdin JSON, asks `scripts/guard.py` for a verdict, and translates it:

- `BLOCK` → non-zero exit with the reason (the tool call is stopped; the agent sees why
  and the protocol says what to do next: **STOP, ask the Operator**).
- `WARN` → prints the reason, allows the call (fail-open, loud).
- `ALLOW` → silence.

Notes learned the hard way:
- The guard only protects rows whose **Session cell leads with the session_id** and whose
  **Lease-until is a bare date** — run `watchbill_check.py` on a schedule (or in
  pre-commit, via `install_hooks.sh`) so a disarmed row cannot sit silent.
- Fail-open is deliberate: a broken CLAIMS.md must not brick the crew. The checker, not
  the guard, is where brokenness gets caught.
