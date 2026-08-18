#!/usr/bin/env python3
"""Claude Code SessionStart adapter — loads DIARY.md `## NOW` into context.

The protocol's session ritual (PROTOCOL.md §2.1) opens with **Orient**: read
`DIARY.md ## NOW` before acting — do not work from memory. The guard and heartbeat
adapters enforce the *rest* of the ritual (ownership, liveness) but nothing loaded the
live state of play at session start, so that first step relied on the agent remembering
to do it. This closes the gap: it reads `## NOW` from the adopter's DIARY.md and injects
it straight into the model's context via the SessionStart hook, so the board is in front
of the session before its first tool call.

TWO MODES, because a board that has been working for months outgrows the harness's
context budget:

  * `## NOW` fits the budget  -> inject it whole. Nothing is better than the real board.
  * `## NOW` is too big       -> inject a DIGEST: one line per entry (its `### ` header,
    which carries title + Class + verified + waiting-on), RANKED LIVE-FIRST, with
    finished/parked entries dropped and counted.

★ WHY THE RANKING IS NOT COSMETIC (measured 2026-08-18 against a real 77-entry board):
plain truncation cuts in FILE order, so what a fresh session sees is whatever happens to
sit at the top of the file. On that board it emitted 4 entries of 77 — and ALL THREE
live production runs were among the 73 it dropped. Truncation silently inverted the
hook's whole purpose: the session was oriented by the least urgent thing on the board.
File order is authoring history; it is not priority. So when the board does not fit, cut
by CLASS, never by position — and say how many were cut.

Reads the hook JSON from stdin (session_id, for parity with the other adapters — the
injection itself needs nothing from it). Emits Claude Code SessionStart JSON on stdout:
  {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}

FAIL-OPEN: any error, or no DIARY.md / no `## NOW` — print nothing, exit 0. A context
loader must never block a session start (there may be no diary yet, or the tree may not
be a Watchbill repo at all).
"""
import json
import re
import sys
from pathlib import Path

# CALIBRATION (measured 2026-08-17): Claude Code inlines hook output only up to 10,000
# characters — anything larger is silently persisted to a file with a ~2KB preview, so
# the session does NOT see it. The WHOLE emit (preamble + body + notes) must stay under
# that, or the loud truncation here is replaced by a silent one there.
INLINE_LIMIT = 10000
SAFETY_MARGIN = 200      # JSON escaping and multi-byte characters cost more than len() shows
MAX_CHARS = 9000         # hard cap on the body, whatever the preamble leaves room for
HEADER_CAP = 170         # per-entry header truncation in digest mode

# `### Some track — … Class: ACTIVE. verified: … · waiting-on: …`
CLASS_RE = re.compile(r"Class:\s*([^.·|]*)", re.IGNORECASE)
DATED_HEADER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\b")


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


def liveness_rank(header):
    """Order entries by how much a fresh session needs them: running work first, then
    blocked-on-the-Operator, then standing duties, then unclassified. Explicitly
    finished/parked entries rank last and are DROPPED from the digest — they belong in
    `## Log`, and until they move there they must not crowd live work out of the budget.

    An entry with no `Class:` is UNKNOWN, not dead: it sorts after classified-live work
    but is still shown. Guessing liveness from prose is exactly the unreliable reading
    this protocol avoids elsewhere."""
    m = CLASS_RE.search(header)
    cls = (m.group(1) if m else "").upper()
    if any(w in cls for w in ("ACTIVE", "LIVE", "HELD")):
        return 0
    if "WAITING" in cls or "BLOCKED" in cls or "STALLED" in cls:
        return 1
    if "STANDING" in cls:
        return 2
    if any(w in cls for w in ("DONE", "CLOSED", "PARKED", "KILLED", "SUPERSEDED")):
        return 9
    return 3


def entry_headers(now):
    """Compact digest lines for `## NOW`: each entry's `### ` header only, ranked live-first
    (stable within a rank, so file order is preserved among equals). Returns
    (ranked lines, count of finished/parked entries excluded)."""
    ranked = []
    finished = 0
    for ln in now.splitlines():
        if not ln.startswith("### "):
            continue
        body = ln[4:].lstrip()
        # Skip dated Log-style entries that accumulate inside NOW — a live entry is a
        # thematic header, not a retrospective.
        if DATED_HEADER_RE.match(body):
            continue
        h = body.replace("**", "").strip()
        if not h:
            continue
        rank = liveness_rank(h)
        if rank == 9:
            finished += 1
            continue
        if len(h) > HEADER_CAP:
            h = h[:HEADER_CAP].rstrip() + "…"
        ranked.append((rank, "- " + h))
    ranked.sort(key=lambda t: t[0])       # stable: file order preserved within a rank
    return [h for _, h in ranked], finished


def build_digest(headers, finished, budget):
    """Pack entry headers up to `budget` chars, newest rank first; name what was elided.
    A cap that hides how much it hid reads as 'that was everything' — so both the elided
    count and the finished-but-not-logged count are stated."""
    kept = []
    total = 0
    for h in headers:
        if total + len(h) + 1 > budget:
            kept.append(f"… (+{len(headers) - len(kept)} more entries — read DIARY.md ## NOW)")
            break
        kept.append(h)
        total += len(h) + 1
    if finished:
        kept.append(f"(+{finished} entries marked DONE/CLOSED/PARKED still sit in ## NOW — "
                    "overdue their move to ## Log)")
    return "\n".join(kept)


def stale_waiting_on(diary_text):
    """One line naming `## NOW` blockers that `## Log` has already ruled — empty when clean.

    `## Log` is never loaded at session start, so a ruling banked there does not reach a
    fresh session; only `## NOW` does. Defensive by construction: any failure returns ""
    so the digest still ships — this is an extra, never a dependency."""
    try:
        here = str(Path(__file__).resolve().parents[2] / "scripts")
        if here not in sys.path:
            sys.path.insert(0, here)
        import waiting_on
        return waiting_on.stale_notice(diary_text)
    except Exception:
        return ""


def dangling_notice():
    """One line naming sessions that left work behind and never closed out.

    ★ This is the half of the close-out fix that does NOT depend on the departing session. A
    crashed or restored session cannot be made to clean up after itself, so the mess is
    surfaced HERE, at the start of the next session, where somebody is actually reading.
    Bounded and fail-open like everything else on this path."""
    try:
        here = str(Path(__file__).resolve().parents[2] / "scripts")
        if here not in sys.path:
            sys.path.insert(0, here)
        import closeout
        from datetime import datetime
        items = closeout.dangling("CLAIMS.md", "notebooks", "DIARY.md",
                                  ".watchbill/heartbeats.json", datetime.now())
        if not items:
            return ""
        shown = items[:3]
        names = ", ".join(f"{d['session']} ({d['idle_minutes'] // 60}h silent)" for d in shown)
        more = f", and {len(items) - len(shown)} more" if len(items) > len(shown) else ""
        return (f"NOTE — {len(items)} session(s) left work behind without closing out: {names}"
                f"{more}. Their tracks are still leased and nothing was written to `## Log`. "
                f"Do NOT take a live lease over on your own say-so — surface it to the Operator "
                f"(PROTOCOL.md §1.1 rule 5, §2.6).")
    except Exception:
        return ""


PREAMBLE_WHOLE = (
    "SESSION-START RITUAL (Watchbill PROTOCOL.md §2, non-negotiable): the live state of "
    "play from this repo's `DIARY.md` `## NOW` is below. Read it before acting — do not "
    "work from memory. Re-stamp `verified:` on anything you check; flag anything "
    "unverified older than 72 h as STALE. Then check `CLAIMS.md` before touching a track, "
    "open your notebook, and work the one task in front of you. At session end, refresh "
    "`## NOW` and append to `## Log`.\n\n"
)

PREAMBLE_DIGEST = (
    "SESSION-START RITUAL (Watchbill PROTOCOL.md §2, non-negotiable). `## NOW` is too "
    "large to inject whole, so below is one line per entry — header only, ranked "
    "live-first. READ the full `## NOW` in DIARY.md before acting; do not work from "
    "memory. Re-stamp `verified:` on anything you check; flag anything unverified older "
    "than 72 h as STALE. Entries marked WAITING are not yours to advance without the "
    "Operator's word. Then check `CLAIMS.md`, open your notebook, and work the one task "
    "in front of you. At session end, refresh `## NOW` and append to `## Log`.\n\n"
)


def clamp(context):
    """LAST-RESORT INVARIANT: whatever the parts did, the emit is under the harness limit.

    The budget arithmetic above is careful, but it is arithmetic over parts that can each be
    surprising — a fuzzed board with 1,000 settled waiting-on asks produced a 27,749-char emit
    because the appended notice was unbounded, and an over-limit emit is not truncated loudly,
    it is silently swapped for a ~2KB file preview. So the size is ENFORCED at the exit, not
    only computed at the entrances."""
    if len(context) < INLINE_LIMIT - SAFETY_MARGIN:
        return context
    return (context[:INLINE_LIMIT - SAFETY_MARGIN - 80]
            + "\n\n… (emit capped — read DIARY.md ## NOW for the rest)")


def build_context(now, *extras):
    """Whole board if it fits; otherwise the ranked digest. `extras` are the appended notices
    (settled asks, dangling sessions); they are counted against the budget BEFORE the body is
    sized, because an appendage that is not budgeted for is how a 27,749-character emit
    happened once already."""
    stale = "\n\n".join(e for e in extras if e)
    for preamble, digest_mode in ((PREAMBLE_WHOLE, False), (PREAMBLE_DIGEST, True)):
        # Budget is derived from THIS emit's preamble, not hardcoded: a preamble edit must
        # not be able to push the whole emit over the harness limit without a test noticing.
        budget = min(MAX_CHARS, INLINE_LIMIT - len(preamble) - len(stale) - SAFETY_MARGIN)
        if not digest_mode:
            if len(now) <= budget:
                return clamp(preamble + now + (("\n\n" + stale) if stale else ""))
            continue
        headers, finished = entry_headers(now)
        if headers:
            body = build_digest(headers, finished, budget)
        else:
            # No `### ` entries at all (a free-form board): fall back to a loud truncation.
            body = now[:budget] + "\n\n… (## NOW truncated — read DIARY.md for the rest)"
        return clamp(preamble + body + (("\n\n" + stale) if stale else ""))


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
        text = diary.read_text(encoding="utf-8", errors="replace")
        now = extract_now(text)
        if not now:
            return 0  # no ## NOW block to load
        context = build_context(now, stale_waiting_on(text), dangling_notice())
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
