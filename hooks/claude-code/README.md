# Wiring Watchbill into Claude Code

Three hooks connect a Claude Code session to the protocol: the **session-start loader**
(injects the live board at session start — the ritual's first step), the **heartbeat**
(liveness is measured, never asserted), and the **guard** (the ownership check before
writes/edits). Other harnesses wire the same scripts through whatever hook mechanism they
provide — the adapters here are thin stdin-JSON shims; the logic lives in `scripts/` (the
session-start loader carries its own reading and ranking, and reaches into `scripts/` for
one optional extra — the waiting-on notice — which it omits if the script is absent).

> **All three adapters read the hook's stdin JSON payload** (`session_id` for the guard
> and heartbeat) — the stable, documented interface. (A harness-version-specific env var
> may also exist, but names change between versions; stdin is the contract.) An earlier
> draft assumed an env var, and the result was a heartbeat that silently never stamped,
> leaving the guard permanently disarmed while looking wired. The adoption audit caught it
> on a live session.

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
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "python3 hooks/claude-code/session_start_hook.py" }
        ]
      }
    ],
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

Session-start loader (`session_start_hook.py`):
- On every session start it finds `DIARY.md` (searching up from the repo root), extracts
  the `## NOW` block, and returns it as `additionalContext` so the live board is in front
  of the session **before its first tool call** — enforcing the ritual's opening step
  (PROTOCOL.md §2.1: *Orient*) by the machine instead of relying on the agent to remember.
- It **only reads** — it never writes, never blocks. No `DIARY.md`, no `## NOW`, an
  unreadable file, or any error → it prints nothing and exits 0 (fail-open). A brand-new
  repo with no diary yet starts exactly as before.
- The injected block is bounded, and the cap is calibrated under Claude Code's
  10,000-character inline limit for hook output: past that the harness silently persists
  the context to a file with only a ~2KB preview, and the session never sees the rest — so
  the loader cuts loudly here rather than letting the harness cut silently there. The
  budget is derived from the emit's own preamble, not hardcoded, so editing the wording
  cannot quietly push the whole emit over the limit.
- **A board too large to inject whole is DIGESTED, not truncated**: one line per entry (its
  `### ` header — title, `Class:`, `verified:`, `waiting-on:`), ranked live-first, with
  finished/parked entries dropped and *counted*. This is not cosmetic. Measured against a
  real 77-entry board, plain file-order truncation emitted 4 entries and dropped every one
  of the three live production runs — orienting the session by the least urgent thing on
  the board. File order is authoring history, not priority. A free-form board with no
  `### ` entries still falls back to a loud truncation.
- If `scripts/waiting_on.py` is present, the loader appends one line naming any blocker
  `## NOW` still asks about that `## Log` has already ruled — the ruling lives in the
  section nobody loads at session start, so it has to be carried forward mechanically.
  Missing script, or any error in it, and the loader simply omits that line.

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
