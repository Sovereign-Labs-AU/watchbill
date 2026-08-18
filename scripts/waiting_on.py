#!/usr/bin/env python3
"""waiting_on.py — catch a `## NOW` blocker that `## Log` has already settled.

THE FAILURE THIS EXISTS FOR (production, 2026-08):
a track's NOW entry read `waiting-on: Operator to rule bin/keep on the throwaway scan files`.
The Operator ruled — bin nothing — and the ruling was written into `## Log`. But `## Log` is
never loaded at session start; only `## NOW` is. So the answer sat in the file nobody reads
and the stale instruction sat in the file everybody reads — and the stale instruction said
"bin", pointing at what turned out to be an irreplaceable three-month baseline held in two
copies with no offsite. Its owner struck it within a day. The failure mode is when nobody does.

THE CONVENTION (PROTOCOL.md §1.2):

  ## NOW   ### some-track … waiting-on: Operator to rule bin/keep {ASK:binkeep-scan-files}
  ## Log   ### 2026-01-11 — RULED: keep them, they are the prospect corpus {RULED:binkeep-scan-files}

  {ASK:slug}      this blocker is OPEN       — counted in `## NOW`
  {RULED:slug}    this blocker is RESOLVED   — counted in `## Log`
  {STRUCK:slug …} settled, marked by a non-owner under the settled-clause exception (§3.1)
  slug            lowercase, 2-49 chars, [a-z0-9._-] — strict, so ordinary prose cannot match

A slug in BOTH sections is a contradiction: the board still asks for a decision the record
shows was made. That is the whole check.

★ NAME THE DECISION, NEVER THE ANSWER. A slug outlives the prose around it and travels into
the machine-readable layer, so a conclusion baked into a name is one you will keep re-reading
as fact. Prefer `-ruling`, `-call`, `-triage` over any word that states an outcome.

WHY NOT DETECT THIS FROM THE PROSE: measured against a live 700-line board. Checking whether
file paths named in `## NOW` still exist flagged 204 of 341 candidates on the whole section and
53 on live entries alone — nearly all false (dataset ids, git ranges, remote paths, domains,
`file.py:23` refs, scripts living on other machines) — and cost a 19-second tree walk, far too
slow for a session-start hook. A check that noisy gets routed around. Prose cannot be read
reliably; an explicit token can, and comparing only tokens you were handed cannot misread
anything.

LIMITATIONS, stated rather than hidden:
  1. Opt-in and forward-only — an untagged clause is invisible here. Tag blockers as you post
     them; retrofitting an existing board is rarely worth it.
  2. Sets, not timelines — it cannot tell "ruled, then deliberately re-opened" from "ruled,
     never struck". RE-OPENING A SETTLED BLOCKER NEEDS A NEW SLUG.
  3. It flags; it does not fix. `--strike` is the one narrow exception (§3.1).
  4. Tokens inside fenced code blocks are ignored, so documentation cannot trigger it.

Usage:  python3 scripts/waiting_on.py [DIARY.md] [--strike --by <session-id>]
Exit codes: 0 clean · 1 stale clause found · 2 could not read.
"""
import re
import sys
from pathlib import Path

# lowercase kebab/dot/underscore, 2-49 chars: strict enough that stray prose cannot match
SLUG = r"[a-z0-9][a-z0-9._-]{1,48}"

# CANONICAL MARKERS. The first cut of this convention used `{?slug}` / `{!slug}` — one keystroke
# apart — and it went wrong twice on its first day: a track opened a blocker with the RESOLVED
# marker (silently invisible to the staleness check, the exact failure the convention exists to
# stop), and the author twice typed a bare resolved-token in prose while DOCUMENTING it. Words
# cannot be typo'd into each other, and they read correctly to someone who has never seen the
# convention. The legacy forms still parse so no board breaks mid-migration; they are counted
# and reported so a migration can finish.
OPEN_RE = re.compile(r"\{(?:ASK:|\?)(" + SLUG + r")\}")
DONE_RE = re.compile(r"\{(?:RULED:|!)(" + SLUG + r")\}")
STRUCK_RE = re.compile(r"\{(?:STRUCK:|✔)(" + SLUG + r")[^}]*\}")
LEGACY_RE = re.compile(r"\{[?!✔](" + SLUG + r")")

# Placeholder slugs used when WRITING ABOUT the convention never register. The documentation trap
# is real: it was hit twice in one day while explaining this very mechanism.
RESERVED = {"slug", "example", "foo", "bar", "name", "xxx", "your-slug", "some-slug"}
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
SECTION_RE = re.compile(r"^## +(?P<title>.+?)\s*$", re.MULTILINE)


def find_diary():
    """Locate the adopter's DIARY.md by searching up from cwd. None if there is none."""
    start = Path.cwd().resolve()
    for p in (start, *start.parents):
        if (p / "DIARY.md").is_file():
            return p / "DIARY.md"
    return None


def strip_fences(text):
    """Drop fenced code blocks so documentation EXAMPLES never register as real tokens —
    this file's own docstring and PROTOCOL.md both contain samples."""
    return FENCE_RE.sub("", text)


def split_sections(diary):
    """Return (now_text, log_text) by walking `## ` headings — NOT by substring search, so
    `## NOWHERE` is never read as `## NOW`. Either may be empty; a diary missing a section is
    not an error, it just yields nothing to compare. First occurrence of each wins."""
    bounds = [(m.group("title").strip(), m.end(), m.start()) for m in SECTION_RE.finditer(diary)]
    out = {"NOW": "", "Log": ""}
    for i, (title, body_start, _) in enumerate(bounds):
        if title not in out or out[title]:
            continue
        body_end = bounds[i + 1][2] if i + 1 < len(bounds) else len(diary)
        out[title] = diary[body_start:body_end]
    return out["NOW"], out["Log"]


def now_bounds(diary):
    """Character span of the `## NOW` body — the ONLY region `strike()` may write to."""
    bounds = [(m.group("title").strip(), m.end(), m.start()) for m in SECTION_RE.finditer(diary)]
    for i, (title, body_start, _) in enumerate(bounds):
        if title == "NOW":
            body_end = bounds[i + 1][2] if i + 1 < len(bounds) else len(diary)
            return body_start, body_end
    return 0, 0                      # no NOW section => nothing is writable


def _entry_of(now, pos):
    """The `### ` entry header a token sits under, so a finding names its track, not a line no."""
    idx = now[:pos].rfind("\n### ")
    if idx == -1:
        return "(no entry header)"
    line = now[idx + 5:].split("\n", 1)[0].replace("**", "").strip()
    return (line[:90] + "…") if len(line) > 90 else line


def find_open(now):
    """slug -> the entry header(s) that opened it. A list: two tracks may claim one slug."""
    out = {}
    for m in OPEN_RE.finditer(now):
        if m.group(1) in RESERVED:
            continue
        out.setdefault(m.group(1), []).append(_entry_of(now, m.start()))
    return out


def find_resolved(log):
    return {m.group(1) for m in DONE_RE.finditer(log) if m.group(1) not in RESERVED}


def reconcile(diary):
    """Compare the two sets. Returns findings; never raises on odd input."""
    now, log = split_sections(strip_fences(diary))
    opened = find_open(now)
    resolved = find_resolved(log)
    stale = sorted(s for s in opened if s in resolved)
    # {RULED:x} written into ## NOW is the RESOLVED marker in the OPEN section. The cost is
    # silent: that blocker is invisible to this check and can go stale undetected — the exact
    # failure the convention exists to stop. Seen on day one, on another track's first use.
    misplaced = sorted({m.group(1) for m in DONE_RE.finditer(now) if m.group(1) not in RESERVED}
                       - set(opened))
    legacy = sorted({m.group(1) for m in LEGACY_RE.finditer(now + log) if m.group(1) not in RESERVED})
    return {
        "stale": [{"slug": s, "entries": opened[s]} for s in stale],
        "misplaced_resolved_in_now": misplaced,
        "legacy_markers": legacy,
        "orphan_rulings": sorted(resolved - set(opened)),
        # Ambiguity is TWO DIFFERENT ENTRIES claiming one slug. Repeating a token inside one
        # entry (header plus a bullet restating it) is normal authoring, not a conflict.
        "duplicate_opens": sorted(s for s, e in opened.items() if len(set(e)) > 1),
        "counts": {"open": len(opened), "resolved": len(resolved)},
    }


def strike(diary, by, date):
    """Mark every STALE clause as struck. Returns (new_text, slugs struck).

    THE SETTLED-CLAUSE EXCEPTION (PROTOCOL.md §3.1): `## NOW` is otherwise owner-only. This is
    the one carve-out, and it is deliberately the smallest possible edit:

      * it only ever touches a clause already PROVEN stale — open in `## NOW`, ruled in
        `## Log`. No ruling, no authority, no strike.
      * it rewrites ONE TOKEN. Not the prose, the class, the verified stamp, or the bullets. A
        waiting-on often carries several asks in one sentence ("(a) rule bin/keep; (b) decide
        whether to commit"), so excising prose would destroy an ask that is still live.
      * it leaves attribution in the text, so the strike is auditable and the owner reverses it
        with one edit.

    Idempotent: a struck token is no longer OPEN, so a second run finds nothing to do."""
    findings = reconcile(diary)
    struck = []
    # SCOPED TO `## NOW`. This was once a whole-file replace, so a `{?slug}` sitting in `## Log`
    # was rewritten too — and `## Log` is APPEND-ONLY, the permanent record. Detection was always
    # section-aware; only the WRITE was not, which is the classic shape: the check is careful,
    # the mutation is not. The strike must never touch history.
    lo, hi = now_bounds(diary)
    now_text, before, after = diary[lo:hi], diary[:lo], diary[hi:]
    for item in findings["stale"]:
        slug = item["slug"]
        mark = "{STRUCK:" + slug + " " + date + " by " + by + " — ruled in ## Log}"
        for token in ("{ASK:" + slug + "}", "{?" + slug + "}"):   # canonical first, then legacy
            if token in now_text:
                now_text = now_text.replace(token, mark)
                struck.append(slug)
                break
    return before + now_text + after, struck


def format_report(f):
    lines = []
    stale = f["stale"]
    if stale:
        lines.append(f"{len(stale)} STALE waiting-on clause(s) — `## Log` already ruled these:")
        for item in stale:
            lines.append(f"    {{ASK:{item['slug']}}}  on: {item['entries'][0]}")
            for extra in item["entries"][1:]:
                lines.append(f"        also on: {extra}")
        lines.append("    -> the ruling is banked; strike the clause (its owner, the Operator, "
                     "or --strike).")
    for slug in f["misplaced_resolved_in_now"]:
        lines.append(f"WARN  {{RULED:{slug}}} is in ## NOW — that is the RESOLVED marker in the "
                     f"OPEN section. Did you mean {{ASK:{slug}}}? As written, this blocker is "
                     f"INVISIBLE to the staleness check.")
    if f["legacy_markers"]:
        lines.append(f"note  {len(f['legacy_markers'])} legacy {{?}}/{{!}} marker(s) still in use — "
                     "the canonical forms are {ASK:slug} and {RULED:slug}: "
                     + ", ".join(f["legacy_markers"]))
    if f["orphan_rulings"]:
        lines.append("note  rulings with no open clause (typo, or already struck): "
                     + ", ".join(f["orphan_rulings"]))
    if f["duplicate_opens"]:
        lines.append("note  slug opened by more than one entry (ambiguous owner): "
                     + ", ".join(f["duplicate_opens"]))
    # The summary ALWAYS prints, under any warnings: an advisory note about orphan rulings must
    # never be mistaken for "there are stale clauses". Clean has to be unmistakably clean.
    c = f["counts"]
    head = "STALE" if stale else "clean"
    lines.append(f"waiting-on reconcile: {head} — {c['open']} open, {c['resolved']} resolved, "
                 f"{len(stale)} stale.")
    return "\n".join(lines)


NOTICE_MAX_SLUGS = 6   # a notice that lists everything is not a notice, it is a second board


def stale_notice(diary, max_slugs=NOTICE_MAX_SLUGS):
    """One compact line for the session-start digest. Empty when clean — the digest must stay
    silent unless there is something to say. Never raises: this is an extra, not a dependency.

    BOUNDED, and that is not tidiness. This line is injected into a context window with a hard
    size limit; an unbounded list of slugs is an unbounded line. Fuzzing a board with 1,000
    settled asks produced a 27,749-character emit — three times the harness's inline limit, at
    which point the whole board is silently persisted to a file the session never reads. The
    failure scaled with the number of settled asks, so the boards most in need of the notice
    were the ones it would have blinded."""
    try:
        stale = reconcile(diary)["stale"]
    except Exception:
        return ""
    if not stale:
        return ""
    shown = stale[:max_slugs]
    slugs = ", ".join("{ASK:" + i["slug"] + "}" for i in shown)
    if len(stale) > len(shown):
        slugs += f", … and {len(stale) - len(shown)} more"
    return (f"NOTE — {len(stale)} waiting-on clause(s) in ## NOW were already RULED in ## Log "
            f"({slugs}). Treat them as settled, not as a live ask; the owner or the Operator "
            f"strikes them (PROTOCOL.md §3.1).")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    do_strike = "--strike" in argv
    by = ""
    for i, a in enumerate(argv):
        if a == "--by" and i + 1 < len(argv):
            by = argv[i + 1]
    positional = [a for a in argv if not a.startswith("--") and a != by]
    if do_strike and not by:
        print("waiting_on: --strike requires --by <session-id> — a strike that cannot be "
              "attributed is not permitted (PROTOCOL.md §3.1)", file=sys.stderr)
        return 2
    path = Path(positional[0]) if positional else find_diary()
    if path is None:
        print("waiting_on: no DIARY.md found", file=sys.stderr)
        return 2
    try:
        diary = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"waiting_on: cannot read {path}: {e}", file=sys.stderr)
        return 2
    findings = reconcile(diary)
    print(format_report(findings))
    if do_strike and findings["stale"]:
        from datetime import date as _date
        new_text, struck = strike(diary, by=by, date=_date.today().isoformat())
        if struck:
            path.write_text(new_text, encoding="utf-8")
            print(f"\nstruck {len(struck)} settled clause(s) by {by}: " + ", ".join(struck))
            print("    the prose is UNCHANGED — only the token is marked. Record the strike in "
                  "`## Log`, and leave the tidy-up to the entry's owner.")
        return 0
    return 1 if findings["stale"] else 0


if __name__ == "__main__":
    sys.exit(main())
