#!/usr/bin/env bash
# Builder's Test Suite for Watchbill — the instruments, audited.
#
# `pytest tests/` proves the code does what the tests say. This proves something the unit
# suite cannot prove about itself: that the tests would NOTICE if the code stopped doing it.
# A green suite is not evidence until you have watched it turn red for the right reason.
#
# It exists because the ad-hoc version of this pass found three tests that passed for the
# WRONG REASON (a ranking test that actually only proved dropping; a strike-scoping test whose
# fixture could not detect a whole-file write; a safety gate tested in the caller but not in
# the function), and one real defect no unit test had reached (an unbounded notice producing a
# 27,749-character session-start emit — 2.8x the harness limit, at which point the session is
# oriented by nothing at all). None of those were visible from "48 passed".
#
#   1. CODE          — the unit suite, and the shipped hooks' CLI behaviour.
#   2. MEASUREMENT   — mutation audit: break each behaviour on a COPY, the suite must go red.
#                      This is the gold-check. A mutant that survives is a blind spot, named.
#   3. BATTLE        — hostile input: empty, binary, unicode, unclosed fences, 2,000 entries.
#                      Invariants: never raise, never block a session, never rewrite ## Log,
#                      never exceed the harness inline limit.
#   4. DATA          — the shipped templates and fixtures are themselves clean input: a kit
#                      that flags on its own first run teaches the adopter to ignore it.
#   5. ADOPTION      — a cold adopter repo: copy, install, run. The Quickstart must survive
#                      someone who has never seen this repo.
#
# Usage:  bash tests/builders_suite.sh          (from the Watchbill repo root)
# Exit 0 = clean on all five. Any failure is loud and names what it was.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
# Recursion guard: the mutation pass runs `pytest tests/` inside COPIES of this repo. If a
# copy's pre-commit hook or suite ever calls back into here, this stops it dead rather than
# forking ten deep.
if [ -n "${WATCHBILL_BUILDERS:-}" ]; then
  echo "builders_suite: already running (recursion guard) — skipping the nested invocation"
  exit 0
fi
export WATCHBILL_BUILDERS=1
ROOT="$(pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAILED=0
say()  { printf '\n=== %s\n' "$*"; }
ok()   { printf '  ok       %s\n' "$*"; }
bad()  { printf '  FAILED   %s\n' "$*"; FAILED=1; }

# ---------------------------------------------------------------- 1. CODE
say "1. CODE — unit suite"
if python3 -m pytest tests/ -q > "$WORK/pytest.txt" 2>&1; then
  ok "$(tail -1 "$WORK/pytest.txt")"
else
  bad "unit suite red:"; sed 's/^/           /' "$WORK/pytest.txt" | tail -20
fi

say "1b. CODE — documented exit codes (0 clean / 1 stale / 2 unreadable)"
printf '## NOW\n{ASK:a-ruling}\n## Log\n{RULED:a-ruling}\n' > "$WORK/stale.md"
check_rc () { # label, want, cmd...
  local label="$1" want="$2"; shift 2
  "$@" >/dev/null 2>&1; local got=$?
  [ "$got" = "$want" ] && ok "$label -> $got" || bad "$label -> $got (want $want)"
}
check_rc "clean board"       0 python3 scripts/waiting_on.py templates/DIARY.md
check_rc "stale clause"      1 python3 scripts/waiting_on.py "$WORK/stale.md"
check_rc "unreadable file"   2 python3 scripts/waiting_on.py "$WORK/nope.md"
check_rc "--strike w/o --by" 2 python3 scripts/waiting_on.py "$WORK/stale.md" --strike
check_rc "closeout check, no --session" 2 python3 scripts/closeout.py check
check_rc "closeout dangling, clean tree"  0 python3 scripts/closeout.py dangling --heartbeats "$WORK/none.json"
check_rc "operator report, no diary"      0 python3 scripts/operator_report.py --root "$WORK"

# ---------------------------------------------------------------- 2. MEASUREMENT (gold-check)
say "2. MEASUREMENT — mutation audit (each mutant MUST turn the suite red)"
mutate () { # label, file, old, new
  local label="$1" file="$2" old="$3" new="$4"
  rm -rf "$WORK/m"; cp -R "$ROOT" "$WORK/m"; rm -rf "$WORK/m/.git"
  if ! python3 - "$WORK/m/$file" "$old" "$new" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1]); s = p.read_text()
if s.count(sys.argv[2]) != 1:
    sys.exit(f"anchor not unique ({s.count(sys.argv[2])} matches) in {p}")
p.write_text(s.replace(sys.argv[2], sys.argv[3]))
PY
  then bad "$label — could not apply mutant (anchor drifted; UPDATE THIS SUITE)"; return; fi
  if (cd "$WORK/m" && python3 -m pytest tests/ -q >/dev/null 2>&1); then
    bad "$label — mutant SURVIVED: nothing tests this behaviour"
  else
    ok "$label — killed"
  fi
}

HOOK=hooks/claude-code/session_start_hook.py
WON=scripts/waiting_on.py
NB=scripts/notebook_board.py
CO=scripts/closeout.py
OR=scripts/operator_report.py

mutate "ranking removed (board cut by file order again)" "$HOOK" \
  '    ranked.sort(key=lambda t: t[0])' '    pass'
mutate "dropped-entry count silenced" "$HOOK" \
  '        if rank == 9:
            finished += 1' '        if rank == 9:
            finished += 0'
mutate "unclassified entries treated as finished" "$HOOK" \
  '    return 3' '    return 9'
mutate "emit clamp removed" "$HOOK" \
  '    if len(context) < INLINE_LIMIT - SAFETY_MARGIN:
        return context' '    return context'
mutate "strike writes the whole file (would edit ## Log)" "$WON" \
  '    lo, hi = now_bounds(diary)' '    lo, hi = 0, len(diary)'
mutate "strike ignores the banked-ruling gate" "$WON" \
  '    for item in findings["stale"]:' \
  '    for item in ([{"slug": s} for s in find_open(diary)] if True else findings["stale"]):'
mutate "placeholder slugs register (docs would trigger it)" "$WON" \
  'RESERVED = {"slug", "example", "foo", "bar", "name", "xxx", "your-slug", "some-slug"}' \
  'RESERVED = set()'
mutate "fenced examples no longer ignored" "$WON" \
  '    return FENCE_RE.sub("", text)' '    return text'
mutate "stale notice unbounded again" "$WON" \
  '    shown = stale[:max_slugs]' '    shown = stale'
mutate "close-out fires when nothing is owed (noise)" "$CO" \
  '    if not o["held_tracks"] and not o["notebooks"]:
        return ""' '    if False:
        return ""'
mutate "dangling flags sessions that never had a pulse" "$CO" \
  '        if last is None:
            continue' '        if last is None:
            last = now - timedelta(days=99)'
mutate "dangling ignores whether the session logged" "$CO" \
  '        if logged(diary_path, sess):
            continue' '        pass'
mutate "stop hook loses its loop guard" "hooks/claude-code/stop_hook.py" \
  '        if already_continuing:' '        if False:'
mutate "operator report speaks on a compliant board (noise)" "$OR" \
  '    if not any(d in now_block for d in fresh):' '    if True:'
mutate "operator report ignores an explicit STALE flag" "$OR" \
  '                        if m and "STALE" not in line' '                        if m'
mutate "operator report un-anchors its section match" "$OR" \
  '    m_now = re.search(r"^## NOW", text, re.M)' '    m_now = re.search(r"## NOW", text)'
mutate "operator hook starts blocking the agent" "hooks/claude-code/operator_hook.py" \
  '        out = r.stdout.strip()
        if out:
            print(out)' '        out = r.stdout.strip()
        if out:
            print(out.replace("{", "{\"decision\": \"block\", ", 1))'
mutate "notebook board flags every session" "$NB" \
  '        if any(joins(sid, s) for s in sessions_on_board):
            continue' '        pass'

# ---------------------------------------------------------------- 3. BATTLE
say "3. BATTLE — hostile input against the invariants"
python3 - "$ROOT" <<'PY' || exit_battle=1
import json, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(sys.argv[1]); sys.path.insert(0, str(ROOT / "scripts"))
import waiting_on

CASES = {
    "empty": "",
    "whitespace only": "   \n\n  ",
    "no sections": "# title\nprose {ASK:whatever-ruling}\n",
    "NOW after Log": "## Log\n{RULED:x-ruling}\n## NOW\n{ASK:x-ruling}\n",
    "duplicate NOW sections": "## NOW\n{ASK:d-ruling}\n## NOW\n{ASK:d-ruling}\n## Log\n{RULED:d-ruling}\n",
    "unclosed fence": "## NOW\n```\n{ASK:a-ruling}\n## Log\n{RULED:a-ruling}\n",
    "null bytes": "## NOW\n\x00{ASK:n-ruling}\x00\n## Log\n{RULED:n-ruling}\n",
    "unicode + RTL override": "## NOW\n### track ⏳ {ASK:e-ruling} ‮\n## Log\n{RULED:e-ruling}\n",
    "token inside a heading": "## NOW\n### {ASK:h-ruling} — Class: ACTIVE\n## Log\n{RULED:h-ruling}\n",
    "malformed braces": "## NOW\n{ASK:} {ASK:UPPER} {ASK:-bad} {ASK:ok-ruling\n## Log\n{RULED:ok-ruling}\n",
    "200k of filler": "## NOW\n" + "x" * 200000 + "{ASK:b-ruling}\n## Log\n{RULED:b-ruling}\n",
    "2000 entries + 2000 settled asks":
        "## NOW\n" + "".join(f"### t{i} — Class: ACTIVE {{ASK:s{i}-ruling}}\n- {'z' * 200}\n"
                             for i in range(2000))
        + "## Log\n" + "".join(f"{{RULED:s{i}-ruling}}\n" for i in range(2000)),
    "binary": "\x00\x01\x02�" * 200,
}
PAYLOADS = ['{"session_id":"s-fuzz"}', "", "not json", '{"session_id":null}', "[]"]
bad = 0
for name, text in CASES.items():
    try:
        waiting_on.format_report(waiting_on.reconcile(text))
        out, _ = waiting_on.strike(text, by="s-fuzz-0001", date="2026-01-12")
    except Exception as e:
        print(f"  FAILED   reconcile/strike raised on {name}: {type(e).__name__}: {e}"); bad = 1; continue
    if "\n## Log\n" in text and out.split("\n## Log\n")[-1] != text.split("\n## Log\n")[-1]:
        print(f"  FAILED   strike REWROTE the append-only ## Log on {name}"); bad = 1; continue
    with tempfile.TemporaryDirectory() as d:
        Path(d, "DIARY.md").write_text(text, errors="replace")
        for payload in PAYLOADS:
            r = subprocess.run([sys.executable, str(ROOT / "hooks/claude-code/session_start_hook.py")],
                               input=payload, capture_output=True, text=True, cwd=d)
            if r.returncode != 0:
                print(f"  FAILED   hook exited {r.returncode} on {name} / {payload!r}"); bad = 1; break
            if r.stdout.strip():
                ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
                if len(ctx) >= 10000:
                    print(f"  FAILED   emit {len(ctx)} chars on {name} — over the inline limit"); bad = 1; break
        else:
            print(f"  ok       {name}")
sys.exit(bad)
PY
[ "${exit_battle:-0}" = 1 ] && bad "battle pass found a broken invariant"

# ---------------------------------------------------------------- 4. DATA
say "4. DATA — the shipped surfaces are clean input"
python3 scripts/watchbill_check.py templates/CLAIMS.md > "$WORK/claims.txt" 2>&1
if grep -q "clean" "$WORK/claims.txt"; then ok "templates/CLAIMS.md audits clean"
else bad "templates/CLAIMS.md does not audit clean:"; sed 's/^/           /' "$WORK/claims.txt"; fi

if python3 scripts/waiting_on.py templates/DIARY.md | grep -q "clean"; then
  ok "templates/DIARY.md reconciles clean (its example ask is open, not contradicted)"
else bad "templates/DIARY.md does not reconcile clean"; fi

# The fixtures are TIME-ANCHORED (fixed 2026-01 dates) and joined against a synthetic
# heartbeat store, so they are driven through audit() with the frozen clock — exactly as the
# unit tests do. Running the bare CLI against them reads TODAY's date and flags every lease as
# expired, which says nothing about whether the trap still fires. (That mistake was made here
# first, and it is the same shape as every instrument failure in this house: the reading was
# real, the instrument was pointed at the wrong thing.)
python3 - <<'PYDATA' || bad "a shipped fixture is no longer the trap it claims to be"
import json, sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, "scripts")
from watchbill_check import audit
NOW = datetime(2026, 1, 10, 12, 0)
beats = Path("/tmp/.wb_builders_beats.json")
beats.write_text(json.dumps({"s-live-0001": {
    "last_active": (NOW - timedelta(minutes=5)).isoformat(timespec="seconds")}}))
MUST_CATCH = {"claims_broken_lease.md", "claims_malformed_row.md", "claims_expired.md"}
bad = 0
for f in sorted(Path("tests/fixtures").glob("*.md")):
    errors, flags, _ = audit(f, beats, NOW)
    caught = bool(errors or flags)
    want = f.name in MUST_CATCH
    if caught == want:
        print(f"  ok       {f.name} — {'caught' if want else 'quiet'}, as it must be")
    else:
        bad = 1
        print(f"  FAILED   {f.name} — {'MUST-CATCH but the checker stayed quiet' if want else 'must be QUIET but it fired'}")
sys.exit(bad)
PYDATA

# ---------------------------------------------------------------- 5. ADOPTION
say "5. ADOPTION — cold adopter: copy, install, prove"
A="$WORK/adopter"; mkdir -p "$A"
( cd "$A" && git init -q . ) || bad "git init failed"
cp -R "$ROOT/templates/." "$A/" 2>/dev/null
cp -R "$ROOT/scripts" "$ROOT/tests" "$ROOT/hooks" "$A/" 2>/dev/null
cp "$ROOT/install_hooks.sh" "$ROOT/PROTOCOL.md" "$A/" 2>/dev/null
if (cd "$A" && ./install_hooks.sh > "$WORK/install.txt" 2>&1); then
  [ -x "$A/.git/hooks/pre-commit" ] && ok "pre-commit hook installed into the ADOPTER's .git" \
    || bad "installer reported success but no executable hook landed"
else bad "install_hooks.sh failed:"; sed 's/^/           /' "$WORK/install.txt"; fi
if (cd "$A" && python3 -m pytest tests/ -q > "$WORK/adopter_pytest.txt" 2>&1); then
  line="$(tail -1 "$WORK/adopter_pytest.txt")"; ok "adopter suite: $line"
  count="$(echo "$line" | grep -oE '^[0-9]+ passed, [0-9]+ skipped')"
  if [ -n "$count" ] && grep -q "$count" README.md; then
    ok "README states the adopter count correctly ($count)"
  else
    bad "README's adopter count does not match reality ($line)"
  fi
else bad "adopter suite red:"; sed 's/^/           /' "$WORK/adopter_pytest.txt" | tail -20; fi

# A trap must fire in the ADOPTER's own repo, or the install cannot catch what it exists to
# catch. Note the pristine template has only RELEASED/UNCLAIMED rows, and prose in a CLOSED
# row's lease cell is correctly NOT an error — so the trap needs a LIVE row first. (A cold
# adopter following README step 3 literally on the untouched file sees silence and cannot tell
# a good install from a broken one; the README wording was fixed for exactly this.)
LIVEROW='| trap-track | src/trap/** | Human | s-trap-000001 | Model-1 | 2026-01-01 | 2099-01-01 | LIVE work, deliberately live for this check |'
python3 - "$A/CLAIMS.md" "$LIVEROW" <<'PYADD'
import sys
from pathlib import Path
p = Path(sys.argv[1]); lines = p.read_text().splitlines()
for i, ln in enumerate(lines):
    if ln.count("|") == 9 and set(ln.replace("|", "").replace(" ", "")) <= {"-", ":"}:
        lines.insert(i + 1, sys.argv[2])          # right under the Tracks divider
        break
else:
    sys.exit("no Tracks divider found")
p.write_text("\n".join(lines) + "\n")
PYADD
[ $? = 0 ] || bad "trap SETUP failed: could not insert the live row (the check after it would be vacuous)"
# NOTE: capture, then grep. Under `set -o pipefail` a pipeline takes the RIGHTMOST non-zero
# status, and the checker exits non-zero BY DESIGN when it finds something — so
# `checker | grep -q ERROR` reports the checker's exit, not the grep's, and inverts both
# verdicts. It made this trap look broken while the must-not-fire check above passed
# vacuously. The instrument was misreading; the code under test was fine all along.
(cd "$A" && python3 scripts/watchbill_check.py CLAIMS.md > "$WORK/trap_ok.txt" 2>&1)
if grep -qi "ERROR" "$WORK/trap_ok.txt"; then
  bad "a well-formed LIVE row must NOT error — the trap would be firing for the wrong reason"
else
  ok "a well-formed live row stays quiet (must-not-fire)"
fi
python3 - "$A/CLAIMS.md" <<'PYTRAP'
import sys
from pathlib import Path
p = Path(sys.argv[1]); lines = p.read_text().splitlines()
for i, ln in enumerate(lines):
    if "trap-track" in ln:
        cells = ln.split("|"); cells[7] = " when the sprint ends "   # prose where a date must be
        lines[i] = "|".join(cells); break
else:
    sys.exit("trap row vanished")
p.write_text("\n".join(lines) + "\n")
PYTRAP
[ $? = 0 ] || bad "trap SETUP failed: could not put prose in the lease cell"
(cd "$A" && python3 scripts/watchbill_check.py CLAIMS.md > "$WORK/trap_fired.txt" 2>&1)
if grep -qi "ERROR" "$WORK/trap_fired.txt"; then
  ok "prose in a live row's Lease-until cell ERRORs in the adopter's repo (README step 3)"
else
  bad "the README tells adopters this must ERROR, and it did not:"; sed 's/^/           /' "$WORK/trap_fired.txt"
fi

say "RESULT"
[ $FAILED = 0 ] && { echo "  CLEAN — code, measurement, battle, data, adoption."; exit 0; }
echo "  NOT CLEAN — see FAILED lines above."; exit 1
