#!/usr/bin/env python3
"""operator_report.py — the one instrument that reports to the OPERATOR, not to the agent.

★ WHY THIS EXISTS, and it is a structural argument rather than a trust one: every surface in
this protocol is WRITTEN BY THE AGENT — `CLAIMS.md`, `DIARY.md`, the notebook. Every other
checker reads those surfaces and reports back to the agent: the session-start loader, the
guard, the close-out check, the dangling notice. So the Operator — who §0 names as the sole
authority — has no INDEPENDENT read on whether the process is being followed at all. Their
whole picture is mediated by the thing being audited, and if an agent's ledger discipline
drifts, the Operator's picture drifts with it and nothing anywhere disagrees.

The other gates ask *did you break a rule I can see* — an unclaimed write, a malformed lease,
an unreconciled notebook. This one asks *is the ritual still happening*, and that is exactly
the question where the agent is the unreliable narrator. The case that produced it: a notebook
untouched for three days while ten `## Log` entries were appended, its stated objective long
overtaken by events; `verified:` stamps eight days old with no STALE flag; a full technical
suite green the entire time. Nothing was broken. The ritual had quietly stopped, and every
warning in the system was addressed to the one party that had stopped reading them.

**It is advisory, and it is not a gate.** It blocks nothing and it cannot. What makes it worth
having is the AUDIENCE, not the enforcement — the protocol's own line is "it does not police,
it makes violations visible", and this makes them visible to the person with the authority to
act. See PROTOCOL.md §6.

★ TUNE, DO NOT ROUTE AROUND. Every threshold is in THRESHOLDS below, in one block, because
this is the most opinionated instrument in the kit: it encodes a working CADENCE, and a crew
with a weekly rhythm would be flagged every Monday by a daily one. A noisy check gets routed
around, and then it protects nothing. If a check does not fit how you work, change the number
or drop the check — do not learn to ignore the report.

Its own two worst bugs are worth knowing, because they are this idea's failure mode — an
instrument that misreads and reports the misreading as a finding:
  * it once matched PROSE ABOUT `## NOW` near the top of the diary instead of the section
    itself, and audited 900 characters of documentation;
  * it once only fired when a `## Log` entry existed for TODAY, so a session logging under
    yesterday's date passed silently.
Both are regression-locked. Section matching is line-anchored; the `## NOW` freshness check is
judged as its own property, never inferred from the Log.

Usage:
  python3 scripts/operator_report.py [--session <id>] [--json] [--hook]
Exit codes: 0 compliant (or nothing to judge) · 1 findings · 2 could not read.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from closeout import (  # noqa: E402 — ONE definition of what a session owes, two audiences
    joins, live_rows, logged, notebooks_for,
)

# ---------------------------------------------------------------------------------------
# THRESHOLDS — the whole opinion of this file, in one place. Tune to your crew's cadence.
# ---------------------------------------------------------------------------------------
THRESHOLDS = {
    "notebook_stale_hours": 24,   # a notebook untouched this long while the session works
    "now_refresh_days": 2,        # `## NOW` must carry a line at least this fresh
    "verified_stale_days": 3,     # PROTOCOL.md §1.2's own 72h rule — keep in step with it
    "renew_soon_hours": 4,        # a lease expiring within this wants renew-or-release
    "work_files_threshold": 3,    # this many files touched recently counts as "real work"
    "work_window_hours": 24,
    "walk_cap": 4000,             # never let the "was there work" walk become a tree crawl
}
VERIFIED_RE = re.compile(r"verified:?\s*(\d{4}-\d{2}-\d{2})")
SKIP_DIRS = {".git", ".watchbill", "node_modules", "__pycache__", ".venv", "venv", "notebooks"}
SURFACES = {"DIARY.md", "CLAIMS.md", "INDEX.md"}


def sections(text):
    """(now_block, log_block) — LINE-ANCHORED, and that is not a detail. An unanchored search
    for `## NOW` matches prose ABOUT the rule, which is how this instrument once audited a slab
    of documentation and reported it as state. An instrument that cannot tell a rule from its
    own description is worse than none: it reports confidently about nothing."""
    m_now = re.search(r"^## NOW", text, re.M)
    m_log = re.search(r"^## Log", text, re.M)
    if not (m_now and m_log and m_log.start() > m_now.start()):
        return None, None
    return text[m_now.start():m_log.start()], text[m_log.start():]


def recent_dates(now, days):
    return {(now - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(days)}


def work_happened(root, now, th):
    """Did real work happen? Counted from files actually TOUCHED in the window.

    An earlier version asked git for the repo's uncommitted state, which reports the ENTIRE
    backlog — on a working tree with a long tail that is noise, not this session's work. The
    walk is capped so this can never become the 19-second tree crawl that would get the whole
    report disabled."""
    cutoff = (now - timedelta(hours=th["work_window_hours"])).timestamp()
    seen = touched = 0
    for p in Path(root).rglob("*"):
        if seen > th["walk_cap"] or touched >= th["work_files_threshold"]:
            break
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file() or p.name in SURFACES:
            continue
        seen += 1
        try:
            if p.stat().st_mtime > cutoff:
                touched += 1
        except OSError:
            continue
    return touched


def audit(root, session, now, th=None):
    """[{code, msg}] — empty means compliant. Never raises on odd input."""
    th = th or THRESHOLDS
    root = Path(root)
    out = []
    try:
        text = (root / "DIARY.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out                       # no diary: nothing to judge, and not a finding
    now_block, log_block = sections(text)
    if now_block is None:
        return [{"code": "diary-shape",
                 "msg": "DIARY.md has no line-anchored `## NOW` / `## Log` sections in order"}]

    books = notebooks_for(root / "notebooks", session) if session else []
    working = bool(books) or bool(session and [t for t, s in live_rows(root / "CLAIMS.md", now)
                                               if joins(s, session)])

    # 1. the notebook exists, and is MAINTAINED — scaffolding one and abandoning it is the
    #    commonest drift, and it is invisible from the artifacts (the file is right there).
    if session and working and not books:
        out.append({"code": "no-notebook",
                    "msg": "this session holds work but no notebook declares it — ritual step 3 "
                           "skipped, so nothing records what it set out to do"})
    for p, _ in books:
        try:
            age_h = (now - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() / 3600
        except OSError:
            continue
        if age_h > th["notebook_stale_hours"]:
            out.append({"code": "notebook-stale",
                        "msg": f"notebook {p.name} last written {age_h:.0f}h ago — it is meant to "
                               f"drive the next action, so a stale one is a lie about the plan"})

    # 2. `## NOW` refreshed. Judged as its OWN property: an earlier version only fired when a
    #    Log entry existed for today, so a session logging under yesterday's date slipped by.
    fresh = recent_dates(now, th["now_refresh_days"])
    if not any(d in now_block for d in fresh):
        n_log = sum(log_block.count(f"### {d}") for d in fresh)
        extra = (f" while {n_log} `## Log` entr{'y' if n_log == 1 else 'ies'} were appended in "
                 f"that window" if n_log else "")
        out.append({"code": "now-not-refreshed",
                    "msg": f"`## NOW` carries no line from the last {th['now_refresh_days']} "
                           f"days{extra} — the Log is history, `## NOW` is state, and only state "
                           f"can go stale"})

    # 3. the protocol's own 72h staleness rule (§1.2), applied to the entries that carry a stamp
    unflagged = sorted({m.group(1) for line in now_block.splitlines()
                        for m in [VERIFIED_RE.search(line)]
                        if m and "STALE" not in line
                        and (now - datetime.strptime(m.group(1), "%Y-%m-%d")).days
                        > th["verified_stale_days"]})
    if unflagged:
        out.append({"code": "unflagged-stale",
                    "msg": f"{len(unflagged)} `## NOW` item(s) verified more than "
                           f"{th['verified_stale_days']}d ago ({', '.join(unflagged)}) and not "
                           f"flagged STALE — the board is asserting freshness it does not have"})

    # 4. work with nothing written down. The one finding that does not need a session id.
    if not any(f"### {d}" in log_block for d in fresh):
        touched = work_happened(root, now, th)
        if touched >= th["work_files_threshold"]:
            out.append({"code": "work-not-logged",
                        "msg": f"{touched}+ files edited in the last {th['work_window_hours']}h "
                               f"with no `## Log` entry dated within {th['now_refresh_days']} "
                               f"days — work that is not written down did not happen, as far as "
                               f"anyone else can tell"})

    # 5. the lease this session is working under is about to lapse. Not the checker's job (it
    #    reports rows already expired); this is the warning BEFORE a track silently goes dark.
    if session:
        soon = now + timedelta(hours=th["renew_soon_hours"])
        for track, sess in live_rows(root / "CLAIMS.md", now):
            if not joins(sess, session):
                continue
            from watchbill_check import parse_lease, split_row
            for line in (root / "CLAIMS.md").read_text(errors="replace").splitlines():
                cells = split_row(line)
                if len(cells) == 8 and cells[0].strip() == track:
                    lease = parse_lease(cells[6])
                    if lease and lease <= soon:
                        out.append({"code": "lease-lapsing",
                                    "msg": f"the lease on `{track[:60]}` lapses at {cells[6].strip()} "
                                           f"— renew it or release it; a lapsed lease looks like "
                                           f"an abandoned track to everyone else"})
                    break
    return out


def render(items, session=""):
    who = f" (session {session})" if session else ""
    if not items:
        return (f"RITUAL{who}: compliant — notebook current, `## NOW` refreshed, no unflagged "
                f"stale items, work is logged.")
    head = (f"OPERATOR REPORT{who} — {len(items)} ritual finding"
            f"{'s' if len(items) > 1 else ''} (PROTOCOL.md §6, advisory)")
    body = "\n".join(f"   - {i['msg']}" for i in items)
    return (f"{head}\n{body}\n   -> this is addressed to YOU, not to the agent: every other "
            f"check in this kit reports to the agent, and an agent that has drifted is exactly "
            f"the one that stops reading them.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", default="")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hook", action="store_true", help="Stop-hook mode: read stdin, emit systemMessage")
    ap.add_argument("--now", default="")          # testing seam
    a = ap.parse_args(argv)
    session = a.session.strip()
    try:
        if a.hook:
            raw = sys.stdin.read()
            payload = json.loads(raw) if raw.strip() else {}
            session = str(payload.get("session_id") or "").strip() if isinstance(payload, dict) else ""
        now = datetime.fromisoformat(a.now) if a.now else datetime.now()
        items = audit(a.root, session, now)
    except Exception:
        return 0 if a.hook else 2         # in hook mode it must never disturb a turn
    if a.hook:
        if items:
            print(json.dumps({"systemMessage": render(items, session)}))
        return 0                          # advisory only: it never blocks, ever
    if a.json:
        print(json.dumps(items, indent=1))
    else:
        print(render(items, session))
    return 1 if items else 0


if __name__ == "__main__":
    sys.exit(main())
