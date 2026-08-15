#!/usr/bin/env python3
"""watchbill_check.py — audit CLAIMS.md: every table, every lease, every guard condition.

Checks BOTH tables (Tracks + Resources) for the three conditions that arm enforcement
(PROTOCOL.md §5), and errors on the malformations that silently disarm it:

  [ERROR] Lease-until cell that does not parse as a bare date on a live-looking row.
          (Prose in that cell breaks date parsing and disarms the guard while the row
          still LOOKS protected — the worst failure mode we have seen in production.)
  [ERROR] Malformed row (wrong cell count) — a row the parser drops is a row the guard
          cannot protect.
  [FLAG]  Expired lease on a row whose text claims live work.
  [FLAG]  Live lease whose Session cell cannot be joined to a heartbeat (guard inert).
  Report: each live resource row printed ARMED or NOT ARMED.

Exit codes: 0 clean · 1 flags only · 2 errors.

Usage:  python3 scripts/watchbill_check.py [CLAIMS.md] [--heartbeats PATH]
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

BARE_DATE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})(\s+\d{1,2}:\d{2})?\s*$")
CLOSED_MARKERS = re.compile(
    r"\b(RELEASED|UNCLAIMED|PARKED|DONE|KILLED|DEAD|SUPERSEDED|TERMINATED|placeholder)\b",
    re.IGNORECASE,
)
LIVE_HINTS = re.compile(r"\b(LIVE|RUNNING|ACTIVE|in progress)\b", re.IGNORECASE)
HEARTBEAT_FRESH_MINUTES = 30

TRACK_COLS = 8      # | Track | Globs | Owner | Session | Agent | Claimed | Lease-until | Task |
RESOURCE_COLS = 7   # | Resource | Match | Owner | Session | Claimed | Lease-until | Note |


def parse_lease(cell: str):
    """A lease cell must be a BARE date. Returns datetime or None."""
    m = BARE_DATE.match(cell or "")
    if not m:
        return None
    fmt = "%Y-%m-%d %H:%M" if m.group(2) else "%Y-%m-%d"
    try:
        return datetime.strptime(cell.strip(), fmt)
    except ValueError:
        return None


def split_row(line: str):
    """Cells of a markdown table row (drops the empty leading/trailing splits)."""
    parts = [c.strip() for c in line.split("|")]
    return parts[1:-1] if len(parts) >= 3 else []


def is_divider(cells):
    return all(re.fullmatch(r":?-{3,}:?", c or "---") for c in cells) if cells else False


def load_heartbeats(path: Path):
    """{session_id: last_active datetime}. Missing file -> empty (everything unjoinable)."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}   # valid JSON that isn't a dict (null, [], 42) is a corrupt store, not a crash
    out = {}
    for sid, rec in raw.items():
        ts = rec.get("last_active") if isinstance(rec, dict) else rec
        try:
            out[sid] = datetime.fromisoformat(str(ts))
        except (TypeError, ValueError):
            continue
    return out


def session_token(cell: str):
    """The guard joins by the FIRST token of the Session cell."""
    return (cell or "").split()[0].strip("`*") if (cell or "").strip() else ""


MIN_JOIN_PREFIX = 6   # a shorter Session token cannot join a heartbeat — too easy to
                      # collide with (or lazily borrow) another session's liveness

def heartbeat_live(token: str, beats: dict, now: datetime):
    for sid, last in beats.items():
        exact = sid == token
        prefix = (len(token) >= MIN_JOIN_PREFIX and sid.startswith(token)) or \
                 (len(sid) >= MIN_JOIN_PREFIX and token.startswith(sid))
        if exact or prefix:
            return (now - last) <= timedelta(minutes=HEARTBEAT_FRESH_MINUTES)
    return False


def row_is_closed(cells):
    joined = " ".join(cells[:-1])  # deliberately exclude the free-text Task/Note column
    return bool(CLOSED_MARKERS.search(joined))


def audit(claims_path: Path, beats_path: Path, now: datetime | None = None):
    now = now or datetime.now()
    beats = load_heartbeats(beats_path)
    errors, flags, report = [], [], []

    lines = claims_path.read_text().splitlines()
    table = None  # None | "tracks" | "resources"
    for n, line in enumerate(lines, 1):
        if not line.strip().startswith("|"):
            continue
        cells = split_row(line)
        if not cells or is_divider(cells):
            continue
        header = [c.lower() for c in cells]
        if header[0] in ("track", "resource"):
            table = "tracks" if header[0] == "track" else "resources"
            continue
        if table is None:
            continue

        want = TRACK_COLS if table == "tracks" else RESOURCE_COLS
        if len(cells) != want:
            errors.append(
                f"line {n}: malformed {table} row ({len(cells)} cells, expected {want}) — "
                f"the parser DROPS this row, so nothing protects it: {cells[0][:60]!r}"
            )
            continue

        name = cells[0]
        session_cell = cells[3]
        lease_cell = cells[6] if table == "tracks" else cells[5]
        closed = row_is_closed(cells)
        lease = parse_lease(lease_cell)

        if closed:
            continue  # released/parked/placeholder rows have no owner to protect — silence is correct

        if lease_cell and lease is None:
            errors.append(
                f"line {n} [{name[:50]}]: Lease-until {lease_cell!r} is not a bare date — "
                "the guard's date parse fails and the block is SILENTLY DISARMED."
            )
            continue
        if lease is None:
            flags.append(f"line {n} [{name[:50]}]: no lease on an open row — confirm owner with the Operator.")
            continue

        token = session_token(session_cell)
        live = heartbeat_live(token, beats, now)
        armed = live and lease > now

        if lease <= now:
            looks_live = bool(LIVE_HINTS.search(" ".join(cells)))
            flags.append(
                f"line {n} [{name[:50]}]: lease EXPIRED {lease.date()}"
                + (" — and the row text claims LIVE work" if looks_live else " — reclaimable / release-due")
            )
        elif not live:
            flags.append(
                f"line {n} [{name[:50]}]: live lease but Session {token!r} joins no fresh "
                "heartbeat — the guard is inert for this row."
            )

        if table == "resources":
            report.append(f"  {'ARMED    ' if armed else 'NOT ARMED'}  {name[:60]}  (lease {lease_cell}, session {token or '—'})")

    return errors, flags, report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("claims", nargs="?", default="CLAIMS.md")
    ap.add_argument("--heartbeats", default=".watchbill/heartbeats.json")
    a = ap.parse_args(argv)

    errors, flags, report = audit(Path(a.claims), Path(a.heartbeats))
    if report:
        print("RESOURCE GUARD STATUS:")
        print("\n".join(report))
    if errors:
        print(f"\nERRORS ({len(errors)}) — enforcement broken, fix now:")
        [print("  [ERROR]", e) for e in errors]
    if flags:
        print(f"\nFLAGS ({len(flags)}) — needs a look:")
        [print("  [FLAG]", f) for f in flags]
    if not errors and not flags:
        print("clean.")
    return 2 if errors else (1 if flags else 0)


if __name__ == "__main__":
    sys.exit(main())
