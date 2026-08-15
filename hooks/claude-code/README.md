# Wiring Watchbill into Claude Code

Two hooks connect a Claude Code session to the protocol: the **heartbeat** (liveness is
measured, never asserted) and the **guard** (the ownership check before writes/edits).
Other harnesses wire the same scripts through whatever hook mechanism they provide — the
adapters here are thin stdin-JSON shims; the logic lives in `scripts/`.

> **Both adapters read `session_id` from the hook's stdin JSON payload** — the stable,
> documented interface. (A harness-version-specific env var may also exist, but names
> change between versions; stdin is the contract.) An earlier draft assumed an env var, and the
> result was a heartbeat that silently never stamped, leaving the guard permanently
> disarmed while looking wired. The adoption audit caught it on a live session.

> **Run everything from the repo root.** The heartbeat store (`.watchbill/`), the guard's
> `CLAIMS.md` default, and the hook commands below are all repo-root-relative. Hooks run
> with cwd at the project root, so this is automatic for hooks — it's the CLI invocations
> that need care.

Add to your project's `.claude/settings.json` (paths assume you copied `hooks/` to your
repo root per the Quickstart — `guard_hook.py` locates `scripts/` two levels up, so keep
the `hooks/claude-code/` depth):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "python3 hooks/claude-code/heartbeat_hook.py" }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": "python3 hooks/claude-code/guard_hook.py" }
        ]
      }
    ]
  }
}
```

Verdict translation (`guard_hook.py`):
- `BLOCK` → non-zero exit with the reason on stderr (Claude Code stops the tool call; the
  protocol says what to do next: **STOP, ask the Operator**).
- `WARN` → reason on stdout, call allowed (fail-open, loud).
- `ALLOW` → silence.

Honest reach: this wiring covers **Write/Edit file operations only**. Destructive shell
commands (`rm`, redirects, remote operations) are outside the shipped adapter's reach —
PROTOCOL.md's "the cases it can reach" means exactly this. Resource-table enforcement is
audit-only (see PROTOCOL §1.1); wire your own Bash-parsing adapter against
`scripts/guard.py` if you need more, and test it the way `tests/` tests ours.

Notes learned the hard way:
- The guard only protects rows whose **Session cell leads with the session_id** and whose
  **Lease-until is a bare date** — run `watchbill_check.py` on a schedule (it's already in
  the pre-commit hook via `install_hooks.sh`) so a disarmed row cannot sit silent.
- Fail-open is deliberate: a broken CLAIMS.md must not brick the crew. The checker, not
  the guard, is where brokenness gets caught.
- **Verify the wiring live before trusting it**: make one tool call, then
  `python3 scripts/heartbeat.py list` — your session must appear with a fresh timestamp.
  A stamp you never verified is a stamp you don't have.
