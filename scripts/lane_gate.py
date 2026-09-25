#!/usr/bin/env python3
"""Lane gate: a `## NOW` entry is born with its markers, or it is not committed.

    python3 scripts/lane_gate.py                  # pre-commit: the STAGED DIARY.md vs HEAD
    python3 scripts/lane_gate.py --worktree       # the file on disk vs HEAD (a manual check)
    python3 scripts/lane_gate.py --file NEW [--base OLD]   # two explicit files (tests, audits)

Exit: 0 clean (or nothing to check) · 1 a new/edited entry lacks a marker (BLOCK) · 2 could not run.

THE FAILURE THIS EXISTS FOR (measured on a real working board): the markers were a
convention, written down and agreed, and never enforced. Months later about half the board's
entries carried no `Class:` and no `waiting-on:`, and every tool that drains the board (the
waiting-on reconciler, the staleness check, the loader's ranking) reads those markers. The
unmarked half could not drain by construction. They were not stale; they were invisible, and
every sweep reported green about the half it could see.

THE RULE: an entry that is NEW or EDITED in this commit carries BOTH `Class:` and
`waiting-on:`, in its heading or in a bullet beneath it. Entries already in HEAD are left
alone: a board adopting Watchbill mid-flight is not blocked until someone backfills it
whole. Touch an entry and you mark it, so the board converges one edit at a time.
"Edited" means the heading text changed, and that is deliberate: a heading is where an
entry's state lives, so an entry whose state was just rewritten is the one to mark.

SCOPE, deliberately narrow so it is not routed around: only when DIARY.md is staged; only
`## NOW` (`## Log` is append-only history and is never read here); dated `### YYYY-MM-DD`
headings inside `## NOW` are Log-style notes, not entries, and are skipped, exactly as the
session-start loader skips them.

LIMITATION, stated: the marker test is a substring match, so an entry whose prose merely
MENTIONS the words passes. A stricter pattern raises false positives on boards that carry
the markers in a bullet rather than the heading, and a noisy gate gets routed around. An
entry that talks about markers instead of carrying them is someone defeating the gate on
purpose, which `git commit --no-verify` already allows, visibly.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

DATED = re.compile(r"^\W{0,4}\d{4}-\d{2}-\d{2}\b")
CLASS = re.compile(r"Class:", re.IGNORECASE)
WAITING = re.compile(r"waiting-on:", re.IGNORECASE)


def entries(diary):
    """[(heading, block)] for each `### ` entry inside `## NOW`. The block is the heading plus
    its lines up to the next `### ` or top-level `## `."""
    out, inside, head, block = [], False, None, []
    for ln in diary.splitlines():
        if ln.startswith("## "):
            if head is not None:
                out.append((head, "\n".join(block)))
                head, block = None, []
            inside = ln.startswith("## NOW")
            continue
        if not inside:
            continue
        if ln.startswith("### "):
            if head is not None:
                out.append((head, "\n".join(block)))
            body = ln[4:].strip()
            head, block = (None, []) if DATED.match(body) else (body, [ln])
        elif head is not None:
            block.append(ln)
    if head is not None:
        out.append((head, "\n".join(block)))
    return out


def key(heading):
    return re.sub(r"\s+", " ", heading.replace("**", "")).strip()


def unmarked_new(new_diary, base_diary):
    """Headings of entries that are new or edited relative to `base_diary` and lack a marker.
    Each item is (heading, missing) where missing names what is absent."""
    known = {key(h) for h, _ in entries(base_diary or "")}
    bad = []
    for h, block in entries(new_diary):
        if key(h) in known:
            continue
        missing = [name for name, rx in (("Class:", CLASS), ("waiting-on:", WAITING)) if not rx.search(block)]
        if missing:
            bad.append((h, missing))
    return bad


def git_show(spec):
    r = subprocess.run(["git", "show", spec], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--worktree", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--base")
    a = ap.parse_args(argv)
    try:
        if a.file:
            new = Path(a.file).read_text(encoding="utf-8", errors="replace")
            base = Path(a.base).read_text(encoding="utf-8", errors="replace") if a.base else ""
        else:
            if not a.worktree:
                staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                                        capture_output=True, text=True, check=True).stdout.split()
                if "DIARY.md" not in staged:
                    return 0                                  # nothing of ours is being committed
            new = Path("DIARY.md").read_text(encoding="utf-8") if a.worktree else git_show(":DIARY.md")
            if new is None:
                return 0                                      # DIARY.md staged for deletion
            base = git_show("HEAD:DIARY.md") or ""           # first commit of a diary: all new
    except Exception as exc:  # noqa: BLE001
        print(f"lane_gate: could not run: {exc!r}", file=sys.stderr)
        return 2
    bad = unmarked_new(new, base)
    if not bad:
        return 0
    print(f"LANE GATE: {len(bad)} new or edited `## NOW` entr{'y lacks' if len(bad) == 1 else 'ies lack'} "
          "a marker (PROTOCOL.md §1.2). An entry without `Class:` and `waiting-on:` is invisible to "
          "every tool that drains the board.", file=sys.stderr)
    for h, missing in bad:
        print(f"   ### {h[:120]}\n       missing: {', '.join(missing)}", file=sys.stderr)
    print("Add them in the heading or a bullet beneath it. A deliberate exception is "
          "`git commit --no-verify`, and it is visible.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
