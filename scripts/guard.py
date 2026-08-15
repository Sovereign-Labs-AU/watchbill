#!/usr/bin/env python3
"""guard.py — the ownership guard's decision core (vendor-agnostic).

Given an acting session and a target path, answers: BLOCK, WARN, or ALLOW?

  BLOCK — the target is inside another session's claimed globs, AND that owner is
          verifiably live (fresh heartbeat) with a future bare-date lease.
          All three, or no block (PROTOCOL.md §5): a dead session must not hold a lock.
  WARN  — the target is inside a claimed row that fails any arming condition
          (expired / unjoinable / malformed lease). Allowed, but say so.
  ALLOW — unclaimed, or claimed by the acting session itself.

Wire this into your harness's pre-tool-use hook (see hooks/) for write/delete operations.
Fail-open by design: a broken CLAIMS.md must not brick the crew — it warns instead.

Usage:
  python3 scripts/guard.py check --session <id> --path <target> [--claims CLAIMS.md]
Exit codes: 0 allow · 1 warn · 3 block.
"""
import argparse
import fnmatch
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchbill_check import (  # noqa: E402 — single source of parsing truth, so checker and guard cannot drift
    MIN_JOIN_PREFIX, TRACK_COLS, heartbeat_live, is_divider, load_heartbeats,
    parse_lease, row_is_closed, session_token, split_row,
)


def same_session(a: str, b: str) -> bool:
    """Exact match, or a prefix of at least MIN_JOIN_PREFIX chars — the same rule the
    heartbeat join uses. A 1-char Session cell must not own (or match) everything."""
    if not a or not b:
        return False
    if a == b:
        return True
    return (len(a) >= MIN_JOIN_PREFIX and b.startswith(a)) or \
           (len(b) >= MIN_JOIN_PREFIX and a.startswith(b))


def globs_match(globs_cell: str, target: str) -> bool:
    for g in (p.strip() for p in globs_cell.split(";") if p.strip()):
        if fnmatch.fnmatch(target, g) or fnmatch.fnmatch(target, g.rstrip("*") + "*"):
            return True
        if g.endswith("/**") and (target == g[:-3] or target.startswith(g[:-3] + "/")):
            return True
    return False


def decide(claims_path: Path, beats_path: Path, session: str, target: str,
           now: datetime | None = None):
    """Returns (verdict, reason) — verdict in {'allow', 'warn', 'block'}."""
    now = now or datetime.now()
    try:
        lines = claims_path.read_text().splitlines()
    except OSError:
        return "warn", "CLAIMS.md unreadable — fail-open, but fix the file"
    beats = load_heartbeats(beats_path)

    in_table = False
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = split_row(line)
        if not cells or is_divider(cells):
            continue
        if cells[0].lower() in ("track", "resource"):
            in_table = cells[0].lower() == "track"
            continue
        if not in_table or len(cells) != TRACK_COLS or row_is_closed(cells):
            continue
        if not globs_match(cells[1], target):
            continue

        owner = session_token(cells[3])
        if same_session(session, owner):
            return "allow", f"you hold this track ({cells[0][:40]!r})"
        lease = parse_lease(cells[6])
        if lease is None:
            return "warn", f"claimed row {cells[0][:40]!r} has an unparsable lease — guard cannot arm; fix the cell"
        if lease <= now:
            return "warn", f"claimed row {cells[0][:40]!r} lease expired {lease.date()} — reclaimable; confirm with the Operator"
        if not heartbeat_live(owner, beats, now):
            return "warn", f"claimed row {cells[0][:40]!r} owner {owner!r} has no fresh heartbeat — confirm with the Operator"
        return "block", (f"{target!r} is inside {cells[0][:40]!r}, held LIVE by session {owner!r} "
                         f"(lease until {cells[6]}). STOP — ask the Operator.")
    return "allow", "no claim covers this target"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--session", required=True)
    c.add_argument("--path", required=True)
    c.add_argument("--claims", default="CLAIMS.md")
    c.add_argument("--heartbeats", default=".watchbill/heartbeats.json")
    a = ap.parse_args(argv)

    verdict, reason = decide(Path(a.claims), Path(a.heartbeats), a.session, a.path)
    print(f"{verdict.upper()}: {reason}")
    return {"allow": 0, "warn": 1, "block": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
