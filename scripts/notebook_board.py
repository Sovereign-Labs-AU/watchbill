#!/usr/bin/env python3
"""notebook_board.py — who is working on what: every notebook's session, objective, freshness.

A working session with NO notebook (heartbeat present, nothing on this board) has no
written task-head — that is the anomaly this board exists to surface, so the board
DETECTS it rather than leaving you to eyeball two outputs side by side. It loads the
heartbeat store, joins it to the notebooks by session id, and names any live session
that has not written down its objectives (PROTOCOL.md §1.3, §2.3).

The join is the same one the guard and the checker use (exact id, or a prefix of at
least MIN_JOIN_PREFIX characters) — imported, not re-implemented, so the three cannot
drift apart on what "the same session" means.

Usage:  python3 scripts/notebook_board.py [notebooks_dir] [--heartbeats PATH]
Exit codes: 0 always — this is a board, not a gate.
"""
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchbill_check import (  # noqa: E402 — one source of join truth for board, guard and checker
    MIN_JOIN_PREFIX, load_heartbeats,
)

SESSION_RE = re.compile(r"\*\*Session:\*\*\s*`?([^\s·`]+)")
STALE_HOURS = 12
DEFAULT_STORE = Path(".watchbill/heartbeats.json")
# A session is "working now" for board purposes on a much looser clock than the guard's
# arming check: the guard asks "is this owner live THIS MINUTE", the board asks "has this
# session been active recently enough that its missing notebook is a real anomaly".
WORKING_MINUTES = 120


def parse(text):
    session = (SESSION_RE.search(text) or [None, "—"])[1]
    objective = "—"
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## objective"):
            body = [l.strip() for l in lines[i + 1:i + 4] if l.strip() and not l.startswith("#")]
            if body:
                objective = body[0][:90]
            break
    return session, objective


def joins(a, b):
    """Same session? Exact id, or a prefix of at least MIN_JOIN_PREFIX chars either way —
    a notebook usually records a short id while the harness stamps the full one."""
    if not a or not b:
        return False
    if a == b:
        return True
    return ((len(a) >= MIN_JOIN_PREFIX and b.startswith(a)) or
            (len(b) >= MIN_JOIN_PREFIX and a.startswith(b)))


def unnotebooked(sessions_on_board, beats, now):
    """Live sessions with no notebook — the anomaly. Returns [(session_id, minutes idle)]."""
    out = []
    for sid, last in sorted(beats.items()):
        idle = (now - last).total_seconds() / 60
        if idle > WORKING_MINUTES:
            continue                       # not working now; a missing notebook says nothing
        if any(joins(sid, s) for s in sessions_on_board):
            continue
        out.append((sid, idle))
    return out


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    store = DEFAULT_STORE
    if "--heartbeats" in argv:
        i = argv.index("--heartbeats")
        if i + 1 < len(argv):
            store = Path(argv[i + 1])
            del argv[i:i + 2]
    root = Path(argv[0] if argv else "notebooks")
    books = sorted(root.glob("notebook_*.md"), key=lambda p: -p.stat().st_mtime)
    now = time.time()
    on_board = []
    if not books:
        print(f"no notebooks in {root}/ — a working session should have one (PROTOCOL.md §1.3)")
    for p in books:
        age_h = (now - p.stat().st_mtime) / 3600
        mark = "fresh" if age_h < 1 else ("live " if age_h < STALE_HOURS else "COLD ")
        session, objective = parse(p.read_text())
        on_board.append(session)
        print(f"  {mark} [{session[:10]:10s}] {p.stem[9:]:34.34s} {objective}  ({age_h:.1f}h)")
    beats = load_heartbeats(store)
    missing = unnotebooked(on_board, beats, datetime.now())
    if missing:
        print()
        for sid, idle in missing:
            print(f"  ANOMALY  [{sid[:10]:10s}] working ({idle:.0f} min since last tool call) "
                  f"with NO notebook — no written task-head (PROTOCOL.md §1.3)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
