#!/usr/bin/env python3
"""notebook_board.py — who is working on what: every notebook's session, objective, freshness.

A working session with NO notebook (heartbeat present, nothing on this board) has no
written task-head — that is the anomaly this board exists to surface.

Usage:  python3 scripts/notebook_board.py [notebooks_dir]
"""
import re
import sys
import time
from pathlib import Path

SESSION_RE = re.compile(r"\*\*Session:\*\*\s*`?([^\s·`]+)")
STALE_HOURS = 12


def parse(text: str):
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


def main(argv=None):
    root = Path((argv or sys.argv[1:] or ["notebooks"])[0])
    books = sorted(root.glob("notebook_*.md"), key=lambda p: -p.stat().st_mtime)
    if not books:
        print(f"no notebooks in {root}/ — a working session should have one (PROTOCOL.md §1.3)")
        return 0
    now = time.time()
    for p in books:
        age_h = (now - p.stat().st_mtime) / 3600
        mark = "fresh" if age_h < 1 else ("live " if age_h < STALE_HOURS else "COLD ")
        session, objective = parse(p.read_text())
        print(f"  {mark} [{session[:10]:10s}] {p.stem[9:]:34.34s} {objective}  ({age_h:.1f}h)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
