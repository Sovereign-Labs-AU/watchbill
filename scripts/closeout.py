#!/usr/bin/env python3
"""closeout.py — the ritual's last step, and the only one nothing was watching.

PROTOCOL.md §2.5-2.6 says a session reconciles and closes out: dated `## Log` entry, `## NOW`
refreshed, notebook landed and deleted, claim renewed or released. Every OTHER step has
something behind it — the session-start loader opens the board, the guard checks ownership,
the heartbeat measures liveness, the checker audits the rows. The close had nothing, and its
failure is SILENT: the work looks finished because the artifacts exist, while the track stays
leased to a session that will never speak again and the next session cannot tell live work
from abandoned work.

THE SHAPE OF THE FIX — two halves, because they catch different failures:

  1. `check`    — for a session that is still alive: what do I still owe? Answerable, and the
                  agent can act on it. This is the half a Stop hook can drive.
  2. `dangling` — for the sessions that are NOT alive: who left work behind? ★ This is the
                  half that matters most, and the reason the fix cannot be a Stop hook alone.
                  YOU CANNOT MAKE A DYING PROCESS CLEAN UP AFTER ITSELF. A crash, a restore, a
                  closed laptop — the session is gone and its context with it. So the protocol
                  does not rely on the departing session at all: it makes the mess UNMISSABLE
                  TO THE NEXT ONE, at session start, where somebody is actually reading.

WHAT COUNTS AS DANGLING, and why it is narrow: a session that HAD a pulse, whose pulse has
stopped, that still holds a live lease or an unreconciled notebook, and that never wrote itself
into `## Log`. All four. A session with no heartbeat at all is NOT flagged here — it may be a
human, or a harness with no heartbeat adapter wired, and the checker already reports those rows
as unjoinable. A noisy check gets routed around, and then it protects nothing.

Usage:
  python3 scripts/closeout.py check --session <id> [--claims CLAIMS.md] [--diary DIARY.md]
  python3 scripts/closeout.py dangling [--heartbeats .watchbill/heartbeats.json]
Exit codes: 0 nothing owed · 1 obligations or dangling sessions found · 2 could not read.
"""
import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchbill_check import (  # noqa: E402 — one source of parsing truth for checker/guard/closeout
    MIN_JOIN_PREFIX, TRACK_COLS, is_divider, load_heartbeats, parse_lease, row_is_closed,
    session_token, split_row,
)

# A pulse older than this means the session has left the building. Deliberately far longer than
# the guard's 30-minute arming freshness: the guard asks "is this owner live THIS MINUTE", and
# closeout asks "has this session ended without closing out". A long-running babysit stamps
# constantly, so it never trips this; only genuine departure does.
GONE_MINUTES = 240


def joins(a, b):
    """Same session? Exact, or a prefix of at least MIN_JOIN_PREFIX chars either way — the
    same rule the guard and the board use, imported for the constant so the three cannot
    disagree about what 'the same session' means."""
    if not a or not b:
        return False
    if a == b:
        return True
    return ((len(a) >= MIN_JOIN_PREFIX and b.startswith(a)) or
            (len(b) >= MIN_JOIN_PREFIX and a.startswith(b)))


def live_rows(claims_path, now):
    """[(track, session_token)] for rows holding a FUTURE lease. A closed/released row owes
    nothing, and an expired lease is already the checker's business, not the close's."""
    out = []
    try:
        text = Path(claims_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        cells = split_row(line)
        if len(cells) != TRACK_COLS or is_divider(cells) or row_is_closed(cells):
            continue
        lease = parse_lease(cells[6])
        if lease is None or lease <= now:
            continue
        out.append((cells[0].strip(), session_token(cells[3])))
    return out


def notebooks_for(notebooks_dir, session=None):
    """Notebook files, optionally only those whose Session line joins `session`."""
    out = []
    d = Path(notebooks_dir)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("notebook_*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        import re
        m = re.search(r"\*\*Session:\*\*\s*`?([^\s·`]+)", text)
        sid = m.group(1) if m else ""
        if session is None or joins(sid, session):
            out.append((p, sid))
    return out


# `### 2026-01-11 — [Vendor Model-1] (session `s-demo-0001`) — …`: the AUTHOR's id sits in the
# byline at the front of the heading. Everything after that is prose, including one session
# naming another.
BYLINE_CHARS = 110
SHORT_ID = 8        # the form a diary byline realistically carries


def logged(diary_path, session):
    """Did this session WRITE an entry in `## Log`?

    ★ TWO BUGS LIVED HERE, both found only by running it against a REAL board (2026-08-19):

    1. IT MATCHED THE FULL SESSION ID. Heartbeat stores hold the id a harness hands them —
       often a long uuid — while a diary byline realistically carries a short prefix. Full id
       never appears, so EVERY session read as "never logged" and the check reported three
       false positives on a healthy board. Every fixture had used the same id in both places,
       so a green suite could not see it: synthetic data is consistent by construction, and the
       bug lives in the seam it papers over. Now compared on the short prefix.

    2. IT MATCHED ANYWHERE IN `## Log`, so LOGGING A FINDING ERASED IT — the moment a session
       wrote "these sessions left work behind", their ids were in the Log and the next run
       judged them logged. A check silenced by being reported looks like the problem went away.
       Now only a `### ` heading's BYLINE counts, because an entry may run its whole body on
       the heading line.

    Still deliberately weak in the other direction: it proves an entry exists, never that it
    was a good one. No instrument can check that."""
    try:
        text = Path(diary_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    idx = text.find("\n## Log")
    if idx == -1:
        return False
    sid = re.escape((session or "")[:SHORT_ID])
    if not sid:
        return False
    pat = re.compile(r"\(session\s*`?" + sid + r"|\[[^\]]*`" + sid)
    return any(pat.search(ln[:BYLINE_CHARS])
               for ln in text[idx:].splitlines() if ln.startswith("### "))


def check(session, claims_path, notebooks_dir, diary_path, now):
    """What does this session still owe? Empty dict = nothing."""
    held = [t for t, s in live_rows(claims_path, now) if joins(s, session)]
    books = [str(p) for p, _ in notebooks_for(notebooks_dir, session)]
    return {
        "session": session,
        "held_tracks": held,
        "notebooks": books,
        "logged": logged(diary_path, session),
    }


def dangling(claims_path, notebooks_dir, diary_path, beats_path, now):
    """Sessions that left work behind. See the module docstring for why all four conditions."""
    beats = load_heartbeats(Path(beats_path))
    if not beats:
        return []          # no heartbeats wired at all — say nothing rather than flag everyone
    out = []
    held = {}
    for track, sess in live_rows(claims_path, now):
        if sess:
            held.setdefault(sess, []).append(track)
    open_books = {}
    for p, sid in notebooks_for(notebooks_dir):
        if sid:
            open_books.setdefault(sid, []).append(str(p))
    # ★ CANONICALISE FIRST. `CLAIMS.md` may record a full session id while a notebook records a
    # short prefix, so the same session arrives under two keys and would be reported twice — as
    # if two sessions had walked off instead of one. Group on the short prefix, keeping the
    # longest id seen for the heartbeat join.
    merged = {}
    for src, key in ((held, "held_tracks"), (open_books, "notebooks")):
        for sess, vals in src.items():
            short = sess[:SHORT_ID]
            merged.setdefault(short, {"held_tracks": [], "notebooks": [], "full": sess})
            merged[short][key].extend(vals)
            if len(sess) > len(merged[short]["full"]):
                merged[short]["full"] = sess
    for short in sorted(merged):
        sess = merged[short]["full"]
        last = next((v for k, v in beats.items() if joins(k, sess)), None)
        if last is None:
            continue                                   # never had a pulse — not our call
        idle = (now - last).total_seconds() / 60
        if idle < GONE_MINUTES:
            continue                                   # still working
        if logged(diary_path, sess):
            continue                                   # it wrote itself down; the record stands
        out.append({
            "session": sess,
            "idle_minutes": int(idle),
            "held_tracks": merged[short]["held_tracks"],
            "notebooks": merged[short]["notebooks"],
        })
    return out


def render_check(o):
    """The close-out checklist, addressed to the SESSION — imperative, specific, finite."""
    if not o["held_tracks"] and not o["notebooks"]:
        return ""
    lines = [f"CLOSE-OUT NOT DONE for session {o['session']} (PROTOCOL.md §2.5-2.6):"]
    if not o["logged"]:
        lines.append("  - `## Log` has no entry from this session — append a dated one. Nothing "
                     "is true because a session did it; it is true when it is written down.")
    for t in o["held_tracks"]:
        lines.append(f"  - CLAIMS row `{t}` is still leased to you — renew it if the work is "
                     f"live, release it if it is done. A lease nobody renews and nobody releases "
                     f"is how a track goes dark.")
    for nb in o["notebooks"]:
        lines.append(f"  - notebook `{nb}` is open — reconcile every line into the Log / NOW / "
                     f"your tracker, then delete it if its objectives are actually done.")
    lines.append("  - refresh `## NOW`: it holds only what is currently live.")
    return "\n".join(lines)


def render_dangling(items):
    if not items:
        return ""
    lines = [f"{len(items)} session(s) left work behind and never closed out:"]
    for d in items:
        parts = []
        if d["held_tracks"]:
            parts.append("still holds " + ", ".join(d["held_tracks"]))
        if d["notebooks"]:
            n = len(d["notebooks"])
            parts.append(f"{n} unreconciled notebook{'s' if n > 1 else ''}")
        lines.append(f"  - {d['session']}: silent {d['idle_minutes'] // 60}h, "
                     f"{' and '.join(parts)}, and wrote nothing to `## Log`.")
    lines.append("  -> do NOT take these over on your own say-so (PROTOCOL.md §1.1 rule 5). "
                 "Surface them to the Operator; an expired lease is reclaimable, a live one is not.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["check", "dangling"])
    ap.add_argument("--session", default="")
    ap.add_argument("--claims", default="CLAIMS.md")
    ap.add_argument("--diary", default="DIARY.md")
    ap.add_argument("--notebooks", default="notebooks")
    ap.add_argument("--heartbeats", default=".watchbill/heartbeats.json")
    ap.add_argument("--now", default="")     # testing seam
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now) if a.now else datetime.now()
    if a.mode == "check":
        if not a.session.strip():
            print("closeout: check requires --session <id>", file=sys.stderr)
            return 2
        out = render_check(check(a.session.strip(), a.claims, a.notebooks, a.diary, now))
        if not out:
            print(f"closeout: nothing owed by {a.session.strip()}.")
            return 0
        print(out)
        return 1
    items = dangling(a.claims, a.notebooks, a.diary, a.heartbeats, now)
    if not items:
        print("closeout: no dangling sessions.")
        return 0
    print(render_dangling(items))
    return 1


if __name__ == "__main__":
    sys.exit(main())
