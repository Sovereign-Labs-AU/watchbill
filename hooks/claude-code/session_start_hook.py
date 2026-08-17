#!/usr/bin/env python3
"""Claude Code SessionStart adapter — loads DIARY.md `## NOW` into context.

The protocol's session ritual (PROTOCOL.md §2.1) opens with **Orient**: read
`DIARY.md ## NOW` before acting — do not work from memory. The guard and heartbeat
adapters enforce the *rest* of the ritual (ownership, liveness) but nothing loaded the
live state of play at session start, so that first step relied on the agent remembering
to do it. This closes the gap: it reads `## NOW` from the adopter's DIARY.md and injects
it straight into the model's context via the SessionStart hook, so the board is in front
of the session before its first tool call.

Reads the hook JSON from stdin (session_id, for parity with the other adapters — the
injection itself needs nothing from it). Emits Claude Code SessionStart JSON on stdout:
  {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}

FAIL-OPEN: any error, or no DIARY.md / no `## NOW` — print nothing, exit 0. A context
loader must never block a session start (there may be no diary yet, or the tree may not
be a Watchbill repo at all).
"""
import json
import sys
from pathlib import Path

# Bound the injected context: `## NOW` is the live board, not the whole diary. A NOW
# that has grown past this is itself a smell (finished work should have moved to ## Log),
# so truncate loudly rather than flood the window.
#
# CALIBRATION (measured 2026-08-17): Claude Code inlines hook output only up to 10,000
# characters — anything larger is silently persisted to a file with a ~2KB preview, so
# the session does NOT see it. The cap must keep the WHOLE emit (preamble + block +
# truncation note) under that, or the loud truncation here is replaced by a silent one
# there. 9,000 leaves margin for the ~600-char preamble and the note.
MAX_CHARS = 9000


def find_diary():
    """Locate the adopter's DIARY.md by searching up from cwd (hooks run at repo root).

    Watchbill's paths are repo-root-relative and hooks run with cwd at the project root,
    so `./DIARY.md` is the normal case; the walk up covers a session launched from a
    subdirectory. Returns the Path, or None if no DIARY.md is found — nothing to load.
    """
    start = Path.cwd().resolve()
    for p in (start, *start.parents):
        candidate = p / "DIARY.md"
        if candidate.is_file():
            return candidate
    return None


def extract_now(diary):
    """The `## NOW` block: from the `## NOW` heading to the next top-level `## ` heading.

    Returns the block (heading included) only when it has real body content; a bare
    heading with nothing under it is treated as empty, so it injects nothing.
    """
    body = []
    heading = None
    inside = False
    for ln in diary.splitlines():
        if ln.startswith("## NOW"):
            inside = True
            heading = ln
            continue
        if inside and ln.startswith("## ") and not ln.startswith("## NOW"):
            break
        if inside:
            body.append(ln)
    if heading is None or not any(ln.strip() for ln in body):
        return ""
    return (heading + "\n" + "\n".join(body)).strip()


def main():
    # Fail-open on ANY error: a missing diary, an unreadable file, malformed stdin. This
    # adapter only ever adds context — it must never be the reason a session won't start.
    try:
        # Drain stdin like the other adapters (the payload carries session_id and the
        # start source); the injection needs nothing from it, but consuming it keeps the
        # contract uniform and avoids a broken-pipe surprise on a harness that expects it.
        sys.stdin.read()
        diary = find_diary()
        if diary is None:
            return 0  # not a Watchbill tree, or no diary yet — stay silent
        now = extract_now(diary.read_text(encoding="utf-8", errors="replace"))
        if not now:
            return 0  # no ## NOW block to load
        if len(now) > MAX_CHARS:
            now = now[:MAX_CHARS] + "\n\n… (## NOW truncated — read DIARY.md for the rest)"
        context = (
            "SESSION-START RITUAL (Watchbill PROTOCOL.md §2, non-negotiable): the live "
            "state of play from this repo's `DIARY.md` `## NOW` is below. Read it before "
            "acting — do not work from memory. Re-stamp `verified:` on anything you check; "
            "flag anything unverified older than 72 h as STALE. Then check `CLAIMS.md` "
            "before touching a track, open your notebook, and work the one task in front "
            "of you. At session end, refresh `## NOW` and append to `## Log`.\n\n"
            f"{now}"
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }))
    except Exception:
        return 0  # fail-open: never block a session start
    return 0


if __name__ == "__main__":
    sys.exit(main())
