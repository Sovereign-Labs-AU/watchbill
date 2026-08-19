"""Watchbill test suite — including the must-fail fixtures.

The fixtures encode the two traps found in production use (README §"Proven in use"):
  1. prose inside a Lease-until cell silently disarming the guard's date parse;
  2. a malformed row the parser silently DROPS, taking its protection with it.
If `test_broken_lease_fixture_errors` or `test_malformed_row_fixture_errors` ever pass
against a checker that stays quiet, your install cannot catch what it exists to catch.
"""
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from guard import decide, globs_match                     # noqa: E402
from watchbill_check import audit, parse_lease            # noqa: E402
import heartbeat                                          # noqa: E402

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 1, 10, 12, 0)


def beats_file(tmp_path, sessions, fresh=True):
    ts = (NOW - timedelta(minutes=5 if fresh else 300)).isoformat(timespec="seconds")
    p = tmp_path / "heartbeats.json"
    p.write_text(json.dumps({s: {"last_active": ts} for s in sessions}))
    return p


# ---------------------------------------------------------------- lease parsing
def test_bare_dates_parse():
    assert parse_lease("2026-01-10") is not None
    assert parse_lease("2026-01-10 09:30") is not None


def test_prose_in_lease_cell_does_not_parse():
    # THE production trap: a valid date wrapped in prose must NOT parse.
    assert parse_lease("2026-01-10 (renew weekly while the run holds)") is None
    assert parse_lease("PARKED") is None
    assert parse_lease("") is None


# ---------------------------------------------------------------- checker fixtures
def test_clean_fixture_passes(tmp_path):
    errors, flags, report = audit(FIX / "claims_clean.md",
                                  beats_file(tmp_path, ["s-live-0001"]), NOW)
    assert errors == [] and flags == []
    assert any("ARMED" in r and "NOT ARMED" not in r for r in report)


def test_broken_lease_fixture_errors(tmp_path):
    errors, _, _ = audit(FIX / "claims_broken_lease.md",
                         beats_file(tmp_path, ["s-live-0001"]), NOW)
    assert any("SILENTLY DISARMED" in e for e in errors), \
        "the prose-in-lease-cell trap was NOT caught — this install is unsafe"


def test_malformed_row_fixture_errors(tmp_path):
    errors, _, _ = audit(FIX / "claims_malformed_row.md",
                         beats_file(tmp_path, ["s-live-0001"]), NOW)
    assert any("DROPS this row" in e for e in errors), \
        "the dropped-row trap was NOT caught — this install is unsafe"


def test_expired_live_row_flags(tmp_path):
    _, flags, _ = audit(FIX / "claims_expired.md",
                        beats_file(tmp_path, ["s-live-0001"]), NOW)
    assert any("EXPIRED" in f for f in flags)


def test_dead_owner_flags_and_disarms(tmp_path):
    _, flags, report = audit(FIX / "claims_clean.md",
                             beats_file(tmp_path, ["s-live-0001"], fresh=False), NOW)
    assert any("no fresh" in f for f in flags)
    assert any("NOT ARMED" in r for r in report)


def test_released_rows_stay_silent(tmp_path):
    errors, flags, _ = audit(FIX / "claims_released.md",
                             beats_file(tmp_path, []), NOW)
    assert errors == [] and flags == []


# ---------------------------------------------------------------- guard decisions
def test_guard_blocks_live_owner(tmp_path):
    v, why = decide(FIX / "claims_clean.md", beats_file(tmp_path, ["s-live-0001"]),
                    "s-other-9999", "src/example/main.py", NOW)
    assert v == "block" and "Operator" in why


def test_guard_allows_owner_and_unclaimed(tmp_path):
    hb = beats_file(tmp_path, ["s-live-0001"])
    assert decide(FIX / "claims_clean.md", hb, "s-live-0001", "src/example/main.py", NOW)[0] == "allow"
    assert decide(FIX / "claims_clean.md", hb, "s-other-9999", "unrelated/file.txt", NOW)[0] == "allow"


def test_guard_warns_not_blocks_for_dead_owner(tmp_path):
    v, _ = decide(FIX / "claims_clean.md", beats_file(tmp_path, ["s-live-0001"], fresh=False),
                  "s-other-9999", "src/example/main.py", NOW)
    assert v == "warn"  # a dead session must not hold a lock — but the pass is LOUD


def test_guard_fails_open_on_missing_claims(tmp_path):
    v, _ = decide(tmp_path / "nope.md", beats_file(tmp_path, []), "s", "x", NOW)
    assert v == "warn"


def test_glob_semantics():
    assert globs_match("src/example/**", "src/example/deep/file.py")
    assert not globs_match("src/example/**", "src/other/file.py")


# ---------------------------------------------------------------- heartbeat store
def test_heartbeat_stamp_and_survive_corruption(tmp_path, monkeypatch):
    monkeypatch.setattr(heartbeat, "STORE", tmp_path / "hb.json")
    heartbeat.stamp("s-demo-0001")
    assert "s-demo-0001" in heartbeat.load()
    heartbeat.STORE.write_text("{corrupt")
    assert heartbeat.load() == {}          # corruption reads as empty, never crashes
    heartbeat.stamp("s-demo-0002")         # and stamping recovers the store
    assert "s-demo-0002" in heartbeat.load()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ---------------------------------------------------------------- notebook board (adoption-audit LOW-6)
def test_notebook_board_parses_session_and_objective(tmp_path, capsys):
    import notebook_board
    nb = tmp_path / "notebook_2026-01-05_demo.md"
    nb.write_text("**Session:** `s-demo-0001` · **Agent:** Demo\n\n## Objective\nShip the demo feature.\n")
    assert notebook_board.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "s-demo-000" in out and "Ship the demo feature." in out


# ---------------------------------------------------------------- hook adapters (adoption-audit MEDIUM-5)
def test_heartbeat_hook_stamps_from_stdin_json(tmp_path, monkeypatch):
    # The hook must take session_id from STDIN JSON — there is no env var (the fictional
    # env-var wiring left the guard permanently disarmed; adoption audit, 2026-08-15).
    monkeypatch.chdir(tmp_path)
    r = run_hook_cwd("heartbeat_hook.py", {"session_id": "s-hook-0001"}, tmp_path)
    assert r.returncode == 0
    stored = json.loads((tmp_path / ".watchbill/heartbeats.json").read_text())
    assert "s-hook-0001" in stored


def test_heartbeat_hook_never_breaks_the_tool_call(tmp_path):
    for payload in ({}, {"session_id": ""}):
        r = run_hook_cwd("heartbeat_hook.py", payload, tmp_path)
        assert r.returncode == 0
    assert not (tmp_path / ".watchbill/heartbeats.json").exists()  # no empty-id stamp


def run_hook_cwd(script, payload, cwd):
    import subprocess
    return subprocess.run([sys.executable, str(ROOT / "hooks/claude-code" / script)],
                          input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(cwd))


# ---------------------------------------------------------------- session-start loader
NOW_DIARY = (
    "# Diary — the shared record\n\n"
    "## NOW\n\n"
    "### demo-track — Class: ACTIVE. verified: 2026-01-10 · waiting-on: —\n"
    "- The one live fact the next session must not miss.\n\n"
    "## Log\n\n"
    "### 2026-01-10 — [Demo] — must NOT leak into the injected board.\n"
)


def test_session_start_injects_now_block(tmp_path):
    # A DIARY.md with a ## NOW block -> valid SessionStart JSON whose additionalContext
    # carries the NOW content (and stops at the next top-level ## , not the Log).
    (tmp_path / "DIARY.md").write_text(NOW_DIARY)
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0001",
                                               "source": "startup"}, tmp_path)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    ctx = hso["additionalContext"]
    assert "The one live fact the next session must not miss." in ctx
    assert "must NOT leak into the injected board." not in ctx   # stops at ## Log
    assert "PROTOCOL.md" in ctx                                  # ritual reminder rides along


def test_session_start_fails_open_when_no_diary(tmp_path):
    # No DIARY.md at all — the loader stays silent and never blocks the start.
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0002"}, tmp_path)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_session_start_silent_on_empty_now(tmp_path):
    # A diary with a ## NOW heading but no content under it injects nothing.
    (tmp_path / "DIARY.md").write_text("# Diary\n\n## NOW\n\n## Log\n\n### 2026-01-10 — x\n")
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0003"}, tmp_path)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_session_start_truncates_oversized_now(tmp_path):
    import importlib
    sys.path.insert(0, str(ROOT / "hooks/claude-code"))
    ssh = importlib.import_module("session_start_hook")
    big = "## NOW\n" + ("x" * (ssh.MAX_CHARS + 5000)) + "\n## Log\n"
    (tmp_path / "DIARY.md").write_text(big)
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0004"}, tmp_path)
    assert r.returncode == 0
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "truncated" in ctx


def test_session_start_whole_emit_under_harness_inline_limit(tmp_path):
    # Claude Code inlines hook additionalContext only up to 10,000 chars; larger emits
    # are persisted to a file with a ~2KB preview the session never reads past (measured
    # live 2026-08-17: a 12,360-char emit arrived truncated to 2KB). The WHOLE emit —
    # preamble + block + truncation note — must stay under that, worst case, or the
    # loud truncation is replaced by a silent one.
    import importlib
    sys.path.insert(0, str(ROOT / "hooks/claude-code"))
    ssh = importlib.import_module("session_start_hook")
    big = "## NOW\n" + ("x" * (ssh.MAX_CHARS * 3)) + "\n## Log\n"
    (tmp_path / "DIARY.md").write_text(big)
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0005"}, tmp_path)
    assert r.returncode == 0
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert len(ctx) < 10000, "whole emit must land under the harness 10,000-char inline limit"


# ---------------------------------------------------------------- pristine templates (adoption-audit LOW-7)
def test_shipped_templates_audit_clean(tmp_path):
    # A brand-new adopter's FIRST checker run must say "clean." — a kit that flags out of
    # the box teaches people to ignore flags on day one. In an adopter's repo the
    # templates/ dir doesn't exist (its contents were copied to the root) — skip there;
    # the check runs wherever the template source is present.
    src = ROOT / "templates/CLAIMS.md"
    if not src.exists():
        pytest.skip("templates/ not present (adopter copy) — checked in the Watchbill source repo")
    errors, flags, _ = audit(src, tmp_path / "none.json", NOW)
    assert errors == [] and flags == []


# ---------------------------------------------------------------- battle-proof regressions (2026-08-15)
def test_heartbeat_store_nondict_json_reads_empty(tmp_path):
    # Valid JSON that isn't a dict (null / [] / 42) is a corrupt store, not a crash.
    from watchbill_check import load_heartbeats
    for payload in ("null", "[]", "42", '"x"'):
        p = tmp_path / "hb.json"
        p.write_text(payload)
        assert load_heartbeats(p) == {}


def test_hooks_survive_hostile_stdin(tmp_path):
    # Crash-exit-1 is indistinguishable from a real WARN — hooks must fail-open EXPLICITLY.
    import subprocess
    hostile = [b"null", b"[]", b'{"session_id": 42}', b"\xff\xfe garbage",
               b'{"tool_input": "notadict", "session_id": "s-x"}']
    for payload in hostile:
        for script, ok in (("heartbeat_hook.py", (0,)), ("guard_hook.py", (0,)),
                           ("session_start_hook.py", (0,))):
            r = subprocess.run([sys.executable, str(ROOT / "hooks/claude-code" / script)],
                               input=payload, capture_output=True, cwd=str(tmp_path), timeout=10)
            assert r.returncode in ok, (script, payload, r.returncode, r.stderr[-200:])


def test_session_join_requires_min_prefix(tmp_path):
    # A 1-char token must neither borrow liveness nor claim ownership.
    from watchbill_check import heartbeat_live
    from guard import same_session
    beats = {"s-live-0001": NOW}
    assert not heartbeat_live("s", beats, NOW)
    assert heartbeat_live("s-live-0001", beats, NOW)
    assert heartbeat_live("s-live", beats, NOW)          # >= 6 chars: legitimate shortening
    assert not same_session("s", "s-live-0001")
    assert same_session("s-live-0001", "s-live")
    assert same_session("s-1", "s-1")                    # short but EXACT is fine


def test_heartbeat_parallel_stamps_never_crash(tmp_path):
    # 8 processes × 25 stamps against one store: no crash, no torn store (the shared-tmp
    # rename race from the battle-proof gauntlet, locked here).
    import subprocess
    code = (f"import sys; sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
            "import heartbeat, sys as s2; [heartbeat.stamp(s2.argv[1]) for _ in range(25)]")
    procs = [subprocess.Popen([sys.executable, "-c", code, f"s-par-{i:02d}"],
                              cwd=tmp_path, stderr=subprocess.PIPE) for i in range(8)]
    errs = [p.communicate(timeout=30)[1] for p in procs]
    assert all(p.returncode == 0 for p in procs), [e[-200:] for e in errs if e]
    assert all(not e for e in errs), [e[-200:] for e in errs if e]
    json.loads((tmp_path / ".watchbill/heartbeats.json").read_text())


# ================================================================ waiting-on tokens (PROTOCOL.md §1.2, §3.1)
import waiting_on                                        # noqa: E402

SETTLED = (
    "## NOW\n\n"
    "### some-track — Class: WAITING. verified: 2026-01-10 · "
    "waiting-on: Operator to rule bin/keep {ASK:binkeep-scan-files}\n\n"
    "## Log\n\n"
    "### 2026-01-11 — RULED: keep them {RULED:binkeep-scan-files}\n"
)


def test_waiting_on_flags_a_clause_the_log_already_ruled():
    f = waiting_on.reconcile(SETTLED)
    assert [i["slug"] for i in f["stale"]] == ["binkeep-scan-files"]
    assert "some-track" in f["stale"][0]["entries"][0]


def test_waiting_on_clean_board_is_unmistakably_clean():
    # An open ask with NO ruling is the normal case and must never be flagged — a checker
    # that cries stale on live asks gets routed around.
    open_only = SETTLED.split("## Log")[0] + "## Log\n\n### 2026-01-11 — unrelated entry\n"
    f = waiting_on.reconcile(open_only)
    assert f["stale"] == []
    assert "clean" in waiting_on.format_report(f)


def test_waiting_on_resolved_marker_in_now_is_flagged():
    # {RULED:x} in ## NOW is the resolved marker in the OPEN section: that blocker is
    # invisible to the staleness check, which is the exact failure the convention prevents.
    diary = "## NOW\n\n### t — waiting-on: x {RULED:some-decision-ruling}\n\n## Log\n\n### 2026-01-11 — y\n"
    assert waiting_on.reconcile(diary)["misplaced_resolved_in_now"] == ["some-decision-ruling"]


def test_waiting_on_ignores_fenced_examples_and_placeholders():
    # Documentation must not trigger the convention it documents — twice hit for real.
    doc = ("## NOW\n\n### t — waiting-on: nothing {ASK:slug}\n"
           "```\nwaiting-on: demo {ASK:real-looking-slug}\n```\n\n"
           "## Log\n\n### 2026-01-11 — {RULED:real-looking-slug} {RULED:slug}\n")
    f = waiting_on.reconcile(doc)
    assert f["stale"] == [] and f["counts"]["open"] == 0


def test_waiting_on_does_not_read_nowhere_as_now():
    # Section split walks `## ` headings; a prefix match once parsed the wrong section.
    diary = ("## NOWHERE\n\n### t — waiting-on: x {ASK:decoy-ruling}\n\n"
             "## Log\n\n### 2026-01-11 — {RULED:decoy-ruling}\n")
    assert waiting_on.reconcile(diary)["stale"] == []


def test_strike_must_not_fire_without_a_banked_ruling(tmp_path):
    # THE safety property: no ruling in ## Log => no authority => the file is untouched.
    unruled = "## NOW\n\n### t — waiting-on: Operator {ASK:live-open-ruling}\n\n## Log\n\n### 2026-01-11 — x\n"
    p = tmp_path / "DIARY.md"
    p.write_text(unruled)
    # exit 0 = clean board (the open ask is live, not stale); the property under test is
    # that --strike wrote NOTHING.
    assert waiting_on.main([str(p), "--strike", "--by", "s-striker-01"]) == 0
    assert p.read_text() == unruled


def test_strike_marks_only_the_token_and_never_the_log(tmp_path):
    p = tmp_path / "DIARY.md"
    p.write_text(SETTLED)
    assert waiting_on.main([str(p), "--strike", "--by", "s-striker-01"]) == 0
    out = p.read_text()
    assert "{STRUCK:binkeep-scan-files" in out and "s-striker-01" in out
    assert "Operator to rule bin/keep" in out                  # prose untouched
    assert "Class: WAITING" in out                             # class untouched
    # split on the heading LINE: the strike mark itself contains the words "## Log".
    assert out.split("\n## Log\n")[-1] == SETTLED.split("\n## Log\n")[-1]  # append-only Log byte-identical
    assert waiting_on.main([str(p), "--strike", "--by", "s-striker-01"]) == 0  # idempotent
    assert p.read_text() == out


def test_strike_never_rewrites_the_append_only_log(tmp_path):
    # The Log routinely QUOTES the ask it is ruling on, so the {ASK:...} token appears in
    # BOTH sections. A whole-file replace would rewrite history; the write must be scoped to
    # ## NOW. (The earlier fixture had no ASK token in the Log, so a whole-file replace
    # survived mutation, 2026-08-18.)
    diary = (
        "## NOW\n\n"
        "### some-track — Class: WAITING · waiting-on: Operator {ASK:binkeep-scan-files}\n\n"
        "## Log\n\n"
        "### 2026-01-11 — asked as {ASK:binkeep-scan-files}; RULED keep {RULED:binkeep-scan-files}\n"
    )
    p = tmp_path / "DIARY.md"
    p.write_text(diary)
    assert waiting_on.main([str(p), "--strike", "--by", "s-striker-01"]) == 0
    log_before = diary.split("\n## Log\n")[-1]
    log_after = p.read_text().split("\n## Log\n")[-1]
    assert log_after == log_before, "the append-only Log must be byte-identical after a strike"


def test_strike_function_itself_refuses_an_unruled_clause():
    # The no-ruling gate must live in strike(), not only in main(): strike() is importable,
    # and a caller reaching it directly must not be able to edit another owner's clause.
    # (Mutation 2026-08-18: breaking strike() alone left the whole suite green.)
    unruled = "## NOW\n\n### t — waiting-on: Operator {ASK:live-open-ruling}\n\n## Log\n\n### 2026-01-11 — x\n"
    out, struck = waiting_on.strike(unruled, by="s-striker-01", date="2026-01-12")
    assert struck == []
    assert out == unruled


def test_strike_refuses_without_attribution(tmp_path):
    p = tmp_path / "DIARY.md"
    p.write_text(SETTLED)
    assert waiting_on.main([str(p), "--strike"]) == 2
    assert p.read_text() == SETTLED


# ================================================================ session-start digest (PROTOCOL.md §2.1)
def big_board(n_finished=40, live_last=True):
    """A board too large to inject whole. The one LIVE entry sits LAST in file order —
    exactly where plain truncation loses it."""
    entries = [f"### filler-{i} — Class: DONE. verified: 2026-01-01 · waiting-on: —\n"
               + ("- " + "x" * 300 + "\n") for i in range(n_finished)]
    live = ("### the-live-run — Class: ACTIVE. verified: 2026-01-10 · waiting-on: the run\n"
            "- The one live fact the next session must not miss.\n")
    body = (entries + [live]) if live_last else ([live] + entries)
    return "# Diary\n\n## NOW\n\n" + "\n".join(body) + "\n## Log\n\n### 2026-01-10 — x\n"


def load_hook():
    import importlib
    sys.path.insert(0, str(ROOT / "hooks/claude-code"))
    return importlib.import_module("session_start_hook")


def test_oversized_board_keeps_the_live_entry_that_truncation_would_lose(tmp_path):
    # THE measured defect: cutting by file position dropped every live entry on a real
    # real working board. Ranking by Class must keep the live one even when it is last.
    #
    # Every filler here is WAITING — i.e. KEPT, not dropped — so the live entry can only
    # survive if the digest RANKS. An earlier version of this test used DONE fillers, which
    # are excluded outright: it passed with the sort deleted (caught by mutation, 2026-08-18).
    fillers = "".join(
        f"### waiting-entry-{i:03d} — Class: WAITING. verified: 2026-01-10 · "
        f"waiting-on: the Operator to rule on item {i:03d} of the backlog\n- detail\n"
        for i in range(120))
    live = ("### the-live-run — Class: ACTIVE. verified: 2026-01-10 · waiting-on: the run\n"
            "- The one live fact the next session must not miss.\n")
    (tmp_path / "DIARY.md").write_text("# Diary\n\n## NOW\n\n" + fillers + live
                                       + "\n## Log\n\n### 2026-01-10 — x\n")
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0006"}, tmp_path)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "more entries" in ctx, "board must be big enough to force elision, or this proves nothing"
    assert "the-live-run" in ctx
    assert "waiting-entry-119" not in ctx     # ranked out, though it sits ABOVE the live one


def test_oversized_board_drops_finished_entries_but_says_how_many(tmp_path):
    # A cap that hides how much it hid reads as "that was everything".
    (tmp_path / "DIARY.md").write_text(big_board(n_finished=40))
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0007"}, tmp_path)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "filler-0" not in ctx
    assert "+40 entries marked DONE/CLOSED/PARKED" in ctx


def test_digest_emit_stays_under_the_harness_inline_limit(tmp_path):
    # Same limit as the whole-board mode: a digest that overflows is silently persisted
    # to a file the session never reads past.
    huge = "# Diary\n\n## NOW\n\n" + "\n".join(
        f"### entry-{i} — Class: ACTIVE. verified: 2026-01-10 · waiting-on: —\n- {'y' * 200}\n"
        for i in range(300)) + "\n## Log\n\n### 2026-01-10 — x\n"
    (tmp_path / "DIARY.md").write_text(huge)
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0008"}, tmp_path)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert len(ctx) < 10000
    assert "more entries" in ctx           # says what it elided


def test_small_board_is_still_injected_whole(tmp_path):
    # Digesting is the fallback, never the default: nothing beats the real board.
    (tmp_path / "DIARY.md").write_text(NOW_DIARY)
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0009"}, tmp_path)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "The one live fact the next session must not miss." in ctx


def test_session_start_carries_the_settled_ask_notice(tmp_path):
    # The whole point of the tokens: ## Log is never loaded, so the ruling must ride in here.
    (tmp_path / "DIARY.md").write_text(SETTLED)
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0010"}, tmp_path)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "already RULED" in ctx and "binkeep-scan-files" in ctx


def test_unclassified_entry_is_kept_not_guessed_dead(tmp_path):
    # No Class means UNKNOWN. Dropping it would be guessing liveness from prose.
    board = ("# Diary\n\n## NOW\n\n"
             + "".join(f"### done-{i} — Class: DONE\n- {'x' * 400}\n" for i in range(30))
             + "### mystery-entry — no class here at all\n- something\n"
             + "\n## Log\n\n### 2026-01-10 — x\n")
    (tmp_path / "DIARY.md").write_text(board)
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0011"}, tmp_path)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "mystery-entry" in ctx


def test_many_settled_asks_cannot_blow_the_inline_limit(tmp_path):
    """FOUND BY FUZZING, 2026-08-18: a board with 1,000 settled waiting-on asks produced a
    27,749-character emit — 2.8x the harness's inline limit, at which point the harness swaps
    the whole board for a ~2KB file preview and the session is oriented by nothing at all. The
    notice was unbounded, so the failure scaled with the number of settled asks: the boards
    that most needed the notice were the ones it would have blinded. Fixed in two places (a
    capped notice, and a clamp on the finished emit) and locked here."""
    board = ("# Diary\n\n## NOW\n\n"
             + "".join(f"### t{i} — Class: ACTIVE · waiting-on: x {{ASK:slug{i}-ruling}}\n"
                       for i in range(1000))
             + "\n## Log\n\n"
             + "".join(f"### 2026-01-11 — ruled {{RULED:slug{i}-ruling}}\n" for i in range(1000)))
    (tmp_path / "DIARY.md").write_text(board)
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0012"}, tmp_path)
    assert r.returncode == 0
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert len(ctx) < 10000, f"emit was {len(ctx)} chars — the harness would hide the whole board"
    assert "already RULED" in ctx and "and 994 more" in ctx   # bounded, and says what it elided


def test_notice_is_bounded_but_never_silent():
    import waiting_on as w
    board = ("## NOW\n" + "".join(f"{{ASK:s{i}-ruling}}\n" for i in range(50))
             + "## Log\n" + "".join(f"{{RULED:s{i}-ruling}}\n" for i in range(50)))
    line = w.stale_notice(board)
    assert len(line) < 400 and "50 waiting-on" in line and "44 more" in line


def test_emit_clamp_is_a_hard_invariant_not_an_estimate():
    """The size limit is ENFORCED at the exit, not only computed at the entrances. The budget
    arithmetic is careful, but it is arithmetic over parts that can each surprise you — which
    is exactly how the 27,749-char emit happened. Tested directly because, with the parts
    behaving, nothing else reaches this branch: an untested safety net is decoration."""
    ssh = load_hook()
    clamped = ssh.clamp("x" * 50000)
    assert len(clamped) < 10000 and "capped" in clamped
    assert ssh.clamp("short enough") == "short enough"     # must not touch what already fits


# ================================================================ notebook board anomaly (PROTOCOL.md §1.3)
def test_board_names_a_working_session_with_no_notebook(tmp_path, capsys):
    import notebook_board
    nb = tmp_path / "notebook_2026-01-05_demo.md"
    nb.write_text("**Session:** `s-demo-0001`\n\n## Objective\nShip the demo feature.\n")
    store = beats_file(tmp_path, ["s-demo-0001", "s-ghost-0002"])
    store.write_text(json.dumps({s: {"last_active": datetime.now().isoformat(timespec="seconds")}
                                 for s in ("s-demo-0001", "s-ghost-0002")}))
    notebook_board.main([str(tmp_path), "--heartbeats", str(store)])
    out = capsys.readouterr().out
    assert "ANOMALY" in out and "s-ghost-00" in out
    assert out.count("ANOMALY") == 1        # the notebooked session must NOT be flagged


def test_board_does_not_flag_a_session_that_stopped_working(tmp_path, capsys):
    # Must-not-fire: an idle/finished session with no notebook is not an anomaly.
    import notebook_board
    (tmp_path / "notebook_2026-01-05_demo.md").write_text("**Session:** `s-demo-0001`\n")
    store = tmp_path / "heartbeats.json"
    old = (datetime.now() - timedelta(hours=9)).isoformat(timespec="seconds")
    store.write_text(json.dumps({"s-ghost-0002": {"last_active": old}}))
    notebook_board.main([str(tmp_path), "--heartbeats", str(store)])
    assert "ANOMALY" not in capsys.readouterr().out


# ================================================================ the docs must match the instrument
def test_readme_states_the_real_suite_size():
    """The README's Quickstart step 3 IS the adopter's prove-the-install step: if the stated
    count has drifted from reality, a good install is indistinguishable from a broken one and
    the reader cannot tell which they have. This was a real defect (the README said `22 passed`
    while the suite ran 27, five tests after a hardening commit), so the number is now checked
    against the suite rather than remembered by whoever last edited it."""
    if not (ROOT / "README.md").exists():
        # The Quickstart does not copy README.md into an adopter repo, so this check lives
        # only in the Watchbill checkout — like the template-source check. Reading it
        # unconditionally turned every adopter's suite RED, which is the opposite of the
        # defect this test exists to prevent (caught by the builder's suite, 2026-08-18).
        pytest.skip("README.md not present (adopter copy) — checked in the Watchbill source repo")
    total = sum(len(re.findall(r"^def test_", f.read_text(), re.M))
                for f in sorted((ROOT / "tests").glob("test_*.py")))
    readme = (ROOT / "README.md").read_text()
    assert f"`{total} passed`" in readme, f"README must state `{total} passed` for the checkout"
    # Two tests skip in an adopter repo: the template-source check and this one.
    assert f"`{total - 2} passed, 2 skipped`" in readme, \
        f"README must state `{total - 2} passed, 2 skipped` for an adopter repo"


def test_release_gate_is_wired_only_in_the_source_checkout(tmp_path):
    """The builder's suite must gate WATCHBILL's own commits (this is the tree releases are cut
    from) and must NOT gate an adopter's — it audits our instruments, not their project, and it
    is far too slow for an ordinary commit. Both halves are asserted, because a gate that fires
    everywhere gets disabled and a gate that fires nowhere is decoration."""
    installer = (ROOT / "install_hooks.sh").read_text()
    assert "tests/builders_suite.sh" in installer
    assert "templates/CLAIMS.md" in installer.split("bash tests/builders_suite.sh")[0], \
        "the builder's-suite step must be conditional on being the source checkout"


# ================================================================ close-out (PROTOCOL.md §2.5-2.6)
import closeout                                          # noqa: E402

CLAIMS_LIVE = (
    "| Track | Globs | Owner | Session | Agent | Claimed | Lease-until | Task |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    "| the-track | src/** | Human | s-worker-0001 | Model-1 | 2026-01-09 | 2026-01-20 | LIVE work |\n"
)
DIARY_NO_ENTRY = "## NOW\n\n### x — Class: ACTIVE\n\n## Log\n\n### 2026-01-09 — somebody else\n"


def workspace(tmp_path, claims=CLAIMS_LIVE, diary=DIARY_NO_ENTRY, notebook_session=None):
    (tmp_path / "CLAIMS.md").write_text(claims)
    (tmp_path / "DIARY.md").write_text(diary)
    (tmp_path / "notebooks").mkdir(exist_ok=True)
    if notebook_session:
        (tmp_path / "notebooks" / "notebook_2026-01-09_x.md").write_text(
            f"**Session:** `{notebook_session}`\n\n## Objective\nDo the thing.\n")
    return tmp_path


def test_check_names_every_obligation_and_nothing_else(tmp_path):
    w = workspace(tmp_path, notebook_session="s-worker-0001")
    o = closeout.check("s-worker-0001", w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", NOW)
    assert o["held_tracks"] == ["the-track"] and len(o["notebooks"]) == 1 and o["logged"] is False
    text = closeout.render_check(o)
    assert "`## Log` has no entry" in text and "the-track" in text and "notebook" in text


def test_check_is_silent_for_a_session_that_owes_nothing(tmp_path):
    # MUST-NOT-FIRE: a session holding no track and no notebook must produce no output at all,
    # or the reminder becomes noise on every single stop and gets turned off.
    w = workspace(tmp_path)
    o = closeout.check("s-passerby-9999", w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", NOW)
    assert closeout.render_check(o) == ""


def test_check_still_asks_for_the_lease_after_the_log_is_written(tmp_path):
    logged = DIARY_NO_ENTRY.replace("somebody else", "[Model-1] (session `s-worker-0001`) done")
    w = workspace(tmp_path, diary=logged)
    text = closeout.render_check(
        closeout.check("s-worker-0001", w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", NOW))
    assert "`## Log` has no entry" not in text     # it logged
    assert "still leased to you" in text           # but the row is still held


def test_dangling_needs_all_four_conditions(tmp_path):
    w = workspace(tmp_path, notebook_session="s-worker-0001")
    beats = tmp_path / "hb.json"
    gone = (NOW - timedelta(hours=9)).isoformat(timespec="seconds")
    beats.write_text(json.dumps({"s-worker-0001": {"last_active": gone}}))
    found = closeout.dangling(w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", beats, NOW)
    assert [d["session"] for d in found] == ["s-worker-0001"]
    assert "left work behind" in closeout.render_dangling(found)

    # (a) still stamping -> not dangling, it is just working
    beats.write_text(json.dumps({"s-worker-0001": {
        "last_active": (NOW - timedelta(minutes=5)).isoformat(timespec="seconds")}}))
    assert closeout.dangling(w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", beats, NOW) == []

    # (b) gone BUT it wrote itself into ## Log -> the record stands, nothing dangles.
    # NOTE: this must be a real BYLINE. It used to say "s-worker-0001 closed" in the entry body,
    # which passed only because logged() matched anywhere in the Log — the bug that let a
    # session be marked logged by being MENTIONED (2026-08-19).
    beats.write_text(json.dumps({"s-worker-0001": {"last_active": gone}}))
    w2 = workspace(tmp_path,
                   diary=DIARY_NO_ENTRY.replace("### 2026-01-09 — somebody else",
                                                "### 2026-01-09 — [Model-1] (session `s-worker-0001`) closed out"),
                   notebook_session="s-worker-0001")
    assert closeout.dangling(w2 / "CLAIMS.md", w2 / "notebooks", w2 / "DIARY.md", beats, NOW) == []


def test_dangling_says_nothing_when_no_heartbeats_are_wired(tmp_path):
    # MUST-NOT-FIRE: without a heartbeat adapter every row would look abandoned. A check that
    # flags everything protects nothing — the checker already reports unjoinable rows.
    w = workspace(tmp_path, notebook_session="s-worker-0001")
    empty = tmp_path / "none.json"
    assert closeout.dangling(w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", empty, NOW) == []


def test_dangling_ignores_released_and_expired_rows(tmp_path):
    # A released row owes nothing; an expired lease is already the checker's business. Neither
    # is a close-out failure, and reporting them here would double-flag.
    claims = CLAIMS_LIVE.replace("| 2026-01-20 | LIVE work |", "| 2026-01-01 | LIVE work |")
    w = workspace(tmp_path, claims=claims)
    beats = tmp_path / "hb.json"
    beats.write_text(json.dumps({"s-worker-0001": {
        "last_active": (NOW - timedelta(hours=9)).isoformat(timespec="seconds")}}))
    assert closeout.dangling(w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", beats, NOW) == []


def test_stop_hook_blocks_once_then_never_traps_the_session(tmp_path):
    w = workspace(tmp_path, notebook_session="s-worker-0001")
    r = run_hook_cwd("stop_hook.py", {"session_id": "s-worker-0001"}, w)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["decision"] == "block" and "CLOSE-OUT NOT DONE" in out["reason"]

    # LOOP GUARD: on the turn it already caused, it must NOT block again — a reminder that
    # re-fires on its own continuation is a trap the agent cannot leave to do the work.
    r2 = run_hook_cwd("stop_hook.py", {"session_id": "s-worker-0001",
                                       "stop_hook_active": True}, w)
    out2 = json.loads(r2.stdout)
    assert "decision" not in out2 and "systemMessage" in out2


def test_stop_hook_is_silent_and_harmless_when_nothing_is_owed(tmp_path):
    w = workspace(tmp_path)
    for payload in ({"session_id": "s-passerby-9999"}, {}, {"session_id": ""}, {"session_id": None}):
        r = run_hook_cwd("stop_hook.py", payload, w)
        assert r.returncode == 0 and r.stdout.strip() == ""


def test_session_start_surfaces_a_dangling_session(tmp_path):
    # The half that does not depend on the departing session: the next one is told.
    w = workspace(tmp_path, notebook_session="s-worker-0001")
    (w / ".watchbill").mkdir(exist_ok=True)
    (w / ".watchbill/heartbeats.json").write_text(json.dumps({"s-worker-0001": {
        "last_active": (datetime.now() - timedelta(hours=9)).isoformat(timespec="seconds")}}))
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-next-0002"}, w)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "left work behind" in ctx and "s-worker-0001" in ctx
    assert "own say-so" in ctx          # and it must not invite a unilateral takeover


def test_dangling_ignores_a_session_that_never_had_a_pulse(tmp_path):
    """MUST-NOT-FIRE, and distinct from the no-heartbeats-at-all case: the store is populated
    by OTHER sessions, and the row's owner simply never stamped. That owner may be a human, or
    a harness with no heartbeat adapter wired — the checker already reports such rows as
    unjoinable, and guessing 'abandoned' from an absence would flag them forever. (The
    empty-store test does not reach this branch: mutation caught it surviving, 2026-08-18.)"""
    w = workspace(tmp_path, notebook_session="s-worker-0001")
    beats = tmp_path / "hb.json"
    beats.write_text(json.dumps({"s-somebody-else-0009": {
        "last_active": (NOW - timedelta(minutes=5)).isoformat(timespec="seconds")}}))
    assert closeout.dangling(w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", beats, NOW) == []


# ================================================================ the Operator's view (PROTOCOL.md §6)
import operator_report                                    # noqa: E402


def board(tmp_path, now_line=None, log_line=None, claims=None):
    """A minimal, COMPLIANT tree. Each test breaks exactly one thing — so a finding can only
    come from the thing that test broke."""
    today = NOW.strftime("%Y-%m-%d")
    (tmp_path / "DIARY.md").write_text(
        "# Diary\n\n## NOW\n\n"
        + (now_line or f"### live-track — Class: ACTIVE. verified: {today} · waiting-on: —\n- fact\n")
        + "\n## Log\n\n"
        + (log_line or f"### {today} — [Model-1] (session `s-worker-0001`) did the thing\n"))
    (tmp_path / "CLAIMS.md").write_text(claims if claims is not None else CLAIMS_LIVE)
    (tmp_path / "notebooks").mkdir(exist_ok=True)
    nb = tmp_path / "notebooks" / "notebook_2026-01-10_x.md"
    nb.write_text("**Session:** `s-worker-0001`\n\n## Objective\nDo the thing.\n")
    import os
    os.utime(nb, (NOW.timestamp(), NOW.timestamp()))
    return tmp_path


def test_operator_report_is_silent_on_a_compliant_board(tmp_path):
    # MUST-NOT-FIRE, and it is the load-bearing test for this whole file: an advisory report
    # that speaks when nothing is wrong is noise, and noise gets switched off.
    w = board(tmp_path)
    assert operator_report.audit(w, "s-worker-0001", NOW) == []
    assert "compliant" in operator_report.render([])


def test_operator_report_catches_the_abandoned_notebook(tmp_path):
    import os
    w = board(tmp_path)
    nb = w / "notebooks" / "notebook_2026-01-10_x.md"
    old = (NOW - timedelta(hours=72)).timestamp()
    os.utime(nb, (old, old))
    codes = [i["code"] for i in operator_report.audit(w, "s-worker-0001", NOW)]
    assert codes == ["notebook-stale"]


def test_operator_report_judges_now_freshness_on_its_own(tmp_path):
    """The bug that let this instrument pass a drifted session: it only fired when a `## Log`
    entry existed for TODAY, so logging under yesterday's date slipped through. `## NOW`'s
    freshness is its own property — and the finding must SAY how many Log entries were appended
    while the board sat still, because that contrast is the actual signal."""
    stale_now = "### live-track — Class: ACTIVE. verified: 2020-01-01 · waiting-on: —\n- fact\n"
    w = board(tmp_path, now_line=stale_now)
    items = operator_report.audit(w, "s-worker-0001", NOW)
    codes = [i["code"] for i in items]
    assert "now-not-refreshed" in codes and "unflagged-stale" in codes
    msg = next(i["msg"] for i in items if i["code"] == "now-not-refreshed")
    assert "1 `## Log` entry were appended" in msg or "1 `## Log` entry was" in msg or "entr" in msg


def test_operator_report_respects_an_explicit_stale_flag(tmp_path):
    # MUST-NOT-FIRE: an item already marked STALE has been dealt with honestly. Flagging it
    # again punishes the exact behaviour the protocol asks for.
    flagged = ("### live-track — Class: ACTIVE. verified: 2020-01-01 STALE — unverified since "
               "2020-01-01 · waiting-on: —\n- fact\n"
               f"### other — Class: ACTIVE. verified: {NOW.strftime('%Y-%m-%d')}\n- fact\n")
    w = board(tmp_path, now_line=flagged)
    assert [i["code"] for i in operator_report.audit(w, "s-worker-0001", NOW)] == []


def test_operator_report_catches_work_with_nothing_logged(tmp_path):
    w = board(tmp_path, log_line="### 2020-01-01 — an ancient entry\n")
    for i in range(5):
        (w / f"file{i}.py").write_text("x = 1\n")
    codes = [i["code"] for i in operator_report.audit(w, "s-worker-0001", NOW)]
    assert "work-not-logged" in codes


def test_operator_report_does_not_call_an_idle_repo_unlogged(tmp_path):
    # MUST-NOT-FIRE: no Log entry AND no work is a quiet week, not a drifted session.
    w = board(tmp_path, log_line="### 2020-01-01 — an ancient entry\n")
    import os
    old = (NOW - timedelta(days=30)).timestamp()
    for p in (w / "CLAIMS.md", w / "notebooks" / "notebook_2026-01-10_x.md"):
        os.utime(p, (old, old))
    codes = [i["code"] for i in operator_report.audit(w, "s-worker-0001", NOW)]
    assert "work-not-logged" not in codes


def test_operator_report_warns_before_a_lease_lapses_not_after(tmp_path):
    # The checker already reports rows that HAVE expired. This is the warning beforehand —
    # the point at which renewing is still a choice.
    soon = (NOW + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    claims = CLAIMS_LIVE.replace("| 2026-01-20 |", f"| {soon} |")
    w = board(tmp_path, claims=claims)
    codes = [i["code"] for i in operator_report.audit(w, "s-worker-0001", NOW)]
    assert "lease-lapsing" in codes
    # ...and a comfortable lease must NOT be nagged about
    w2 = board(tmp_path, claims=CLAIMS_LIVE)
    assert "lease-lapsing" not in [i["code"] for i in operator_report.audit(w2, "s-worker-0001", NOW)]


def test_operator_report_is_line_anchored_against_prose_about_the_rule(tmp_path):
    """The bug that made this instrument audit 900 characters of documentation: an unanchored
    search matched PROSE ABOUT `## NOW` before the section itself. An instrument that cannot
    tell a rule from its own description reports confidently about nothing."""
    today = NOW.strftime("%Y-%m-%d")
    (tmp_path / "DIARY.md").write_text(
        "# Diary\n\n> Read the `## NOW` section first; `## Log` is append-only.\n"
        "> Items in `## NOW` carry verified: 2020-01-01 as an example of the format.\n\n"
        f"## NOW\n\n### t — Class: ACTIVE. verified: {today}\n- fact\n\n"
        f"## Log\n\n### {today} — entry\n")
    (tmp_path / "CLAIMS.md").write_text(CLAIMS_LIVE)
    (tmp_path / "notebooks").mkdir(exist_ok=True)
    assert operator_report.audit(tmp_path, "", NOW) == []


def test_operator_report_thresholds_are_tunable_not_hardcoded(tmp_path):
    # The stated escape hatch must actually work: a crew with a weekly cadence changes the
    # number instead of learning to ignore the report.
    import os
    w = board(tmp_path)
    nb = w / "notebooks" / "notebook_2026-01-10_x.md"
    old = (NOW - timedelta(hours=72)).timestamp()
    os.utime(nb, (old, old))
    loose = dict(operator_report.THRESHOLDS, notebook_stale_hours=24 * 7)
    assert [i["code"] for i in operator_report.audit(w, "s-worker-0001", NOW, loose)] == []


def today_board(tmp_path, **kw):
    """The hook runs in a SUBPROCESS, which cannot see the frozen test clock — so a hook test
    must build its tree against the real one. (Built against the frozen clock first, and the
    'silent when compliant' test failed for that reason alone: the fixture was seven months
    stale, not the code.)"""
    real = datetime.now()
    today = real.strftime("%Y-%m-%d")
    kw.setdefault("now_line", f"### live-track — Class: ACTIVE. verified: {today} · waiting-on: —\n- fact\n")
    kw.setdefault("log_line", f"### {today} — [Model-1] (session `s-worker-0001`) did the thing\n")
    w = board(tmp_path, **kw)
    import os
    os.utime(w / "notebooks" / "notebook_2026-01-10_x.md", (real.timestamp(), real.timestamp()))
    return w


def test_operator_hook_reports_to_the_operator_and_never_blocks(tmp_path):
    w = today_board(tmp_path, log_line="### 2020-01-01 — ancient\n",
                    now_line="### t — Class: ACTIVE. verified: 2020-01-01\n- fact\n")
    r = run_hook_cwd("operator_hook.py", {"session_id": "s-worker-0001"}, w)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert "systemMessage" in out and "addressed to YOU" in out["systemMessage"]
    assert "decision" not in out, "the Operator's view is advisory — it must never block"


def test_operator_hook_is_silent_when_the_ritual_is_being_followed(tmp_path):
    w = today_board(tmp_path)
    r = run_hook_cwd("operator_hook.py", {"session_id": "s-worker-0001"}, w)
    assert r.returncode == 0 and r.stdout.strip() == ""


# ================================================================ outward surfaces (PROTOCOL.md §1.1)
def test_url_in_a_track_globs_cell_errors(tmp_path):
    """MUST-CATCH: a glob can only match a path, so a repo/domain/bucket in a track row's Globs
    cell is a row that looks protected and is not — the same silent-disarm class as prose in a
    Lease-until cell, and the mistake that adding outward surfaces invites."""
    errors, flags, _ = audit(FIX / "claims_wrong_table.md", beats_file(tmp_path, ["s-live-0001"]), NOW)
    assert any("protects nothing while looking protected" in e for e in errors)
    assert any("Resources table" in e for e in errors)


def test_a_real_outward_surface_row_is_audited_like_any_other(tmp_path):
    # A URL in the RESOURCES table is correct, and must arm exactly like a host row does.
    claims = tmp_path / "CLAIMS.md"
    claims.write_text(
        "| Track | Globs | Owner | Session | Agent | Claimed | Lease-until | Task |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| the-track | src/** | Human | s-live-0001 | Model-1 | 2026-01-09 | 2026-01-20 | live |\n"
        "\n## Resources\n\n"
        "| Resource | Match | Owner | Session | Claimed | Lease-until | Note |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| public repo | https://github.com/example-org/example-repo | Human | s-live-0001 | 2026-01-09 | 2026-01-20 | outward |\n")
    errors, flags, report = audit(claims, beats_file(tmp_path, ["s-live-0001"]), NOW)
    assert errors == [] and flags == []
    assert any("ARMED" in r and "NOT ARMED" not in r and "public repo" in r for r in report)


def test_a_file_glob_in_a_resource_row_is_flagged(tmp_path):
    # The mirror-image mistake: a path pattern filed as a resource, where nothing will use it.
    claims = tmp_path / "CLAIMS.md"
    claims.write_text(
        "## Resources\n\n"
        "| Resource | Match | Owner | Session | Claimed | Lease-until | Note |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| mis-filed | src/**; docs/** | Human | s-live-0001 | 2026-01-09 | 2026-01-20 | live |\n")
    _, flags, _ = audit(claims, beats_file(tmp_path, ["s-live-0001"]), NOW)
    assert any("belong in the Tracks table" in f for f in flags)


def test_ordinary_globs_and_hosts_are_never_flagged(tmp_path):
    """MUST-NOT-FIRE, and the load-bearing test of the pair: `src/**` is not a URL and
    `buildbox.local` is not a glob. A check that cannot tell them apart makes every row noisy,
    and a noisy checker is one nobody reads."""
    errors, flags, _ = audit(FIX / "claims_clean.md", beats_file(tmp_path, ["s-live-0001"]), NOW)
    assert errors == [] and flags == []


# ================================================================ the board's own errors get a reader
BROKEN_CLAIMS = (
    "| Track | Globs | Owner | Session | Agent | Claimed | Lease-until | Task |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    "| t | src/** | Human | s-live-0001 | Model-1 | 2026-01-09 | when the sprint ends | LIVE |\n")


def test_session_start_names_structural_claims_errors(tmp_path):
    """The gap: the checker is run by whoever remembers, plus a pre-commit hook that only fires
    for commits touching claims code — so an error made by a session that never touches it sits
    unread, while the row protects nothing and looks protected. Measured: one sat a full day."""
    (tmp_path / "DIARY.md").write_text(NOW_DIARY)
    (tmp_path / "CLAIMS.md").write_text(BROKEN_CLAIMS)
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0013"}, tmp_path)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "STRUCTURAL ERROR" in ctx and "watchbill_check.py" in ctx
    assert "Operator's call" in ctx      # naming it is not licence to rewrite another's row


def test_session_start_is_silent_on_a_structurally_clean_board(tmp_path):
    """MUST-NOT-FIRE, and the load-bearing half: ERRORS only. A live board carries standing
    FLAGs — expired leases, releases pending a decision — and repeating those every session
    start is noise, after which the line is ignored entirely."""
    (tmp_path / "DIARY.md").write_text(NOW_DIARY)
    (tmp_path / "CLAIMS.md").write_text(FIX.joinpath("claims_expired.md").read_text())  # FLAGs, no ERRORs
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0014"}, tmp_path)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "STRUCTURAL ERROR" not in ctx


def test_session_start_survives_having_no_claims_file_at_all(tmp_path):
    # Fail-open: a repo mid-adoption has a diary and no CLAIMS.md yet.
    (tmp_path / "DIARY.md").write_text(NOW_DIARY)
    r = run_hook_cwd("session_start_hook.py", {"session_id": "s-start-0015"}, tmp_path)
    assert r.returncode == 0 and "STRUCTURAL ERROR" not in r.stdout


def test_operator_report_carries_the_boards_own_errors(tmp_path):
    w = board(tmp_path, claims=BROKEN_CLAIMS)
    codes = [i["code"] for i in operator_report.audit(w, "s-worker-0001", NOW)]
    assert "claims-structural-error" in codes
    # ...and a clean board must not raise it
    w2 = board(tmp_path, claims=CLAIMS_LIVE)
    assert "claims-structural-error" not in [i["code"] for i in operator_report.audit(w2, "s-worker-0001", NOW)]


def test_being_named_by_another_session_is_not_logging(tmp_path):
    """★ REGRESSION (2026-08-19): logged() matched the id ANYWHERE in `## Log`, so the moment a
    session wrote "these sessions left work behind", their ids were in the Log and the next run
    judged them logged and said nothing. A check silenced by being reported looks like the
    problem went away."""
    named = DIARY_NO_ENTRY.replace(
        "### 2026-01-09 — somebody else",
        "### 2026-01-09 — [Model-1] (session `s-auditor-9`) — s-worker-0001 left work behind")
    w = workspace(tmp_path, diary=named, notebook_session="s-worker-0001")
    beats = tmp_path / "hb.json"
    beats.write_text(json.dumps({"s-worker-0001": {
        "last_active": (NOW - timedelta(hours=9)).isoformat(timespec="seconds")}}))
    found = closeout.dangling(w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", beats, NOW)
    assert [d["session"] for d in found] == ["s-worker-0001"]


def test_the_id_forms_in_the_real_sources_disagree_and_that_is_the_seam(tmp_path):
    """★ THE BUG A GREEN SUITE COULD NOT SEE, because every fixture used the same id in both
    files. Real sources disagree: a heartbeat store holds whatever id the harness hands it —
    often a long uuid — while a diary byline carries a short prefix and a notebook may carry
    either. logged() compared the FULL id against the Log, never matched, and reported three
    false positives on a healthy production board. The disagreement now lives in the fixture."""
    full = "s-worker-0001-aaaa-bbbb-cccc-dddddddddddd"
    claims = CLAIMS_LIVE.replace("s-worker-0001", full)          # CLAIMS: the long id
    diary = DIARY_NO_ENTRY.replace(                              # DIARY: the short byline
        "### 2026-01-09 — somebody else",
        "### 2026-01-09 — [Model-1] (session `s-worker`) — closed out properly")
    w = workspace(tmp_path, claims=claims, diary=diary, notebook_session="s-worker")  # notebook: short
    beats = tmp_path / "hb.json"
    beats.write_text(json.dumps({full: {
        "last_active": (NOW - timedelta(hours=9)).isoformat(timespec="seconds")}}))
    found = closeout.dangling(w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", beats, NOW)
    assert found == [], f"a session that logged under a SHORT byline must not be called dangling: {found}"


def test_one_session_under_two_id_forms_is_reported_once(tmp_path):
    """★ REGRESSION: CLAIMS held the full id and the notebook the short one, so the same session
    was reported TWICE — as if two had walked off instead of one."""
    full = "s-worker-0001-aaaa-bbbb-cccc-dddddddddddd"
    w = workspace(tmp_path, claims=CLAIMS_LIVE.replace("s-worker-0001", full),
                  notebook_session="s-worker")
    beats = tmp_path / "hb.json"
    beats.write_text(json.dumps({full: {
        "last_active": (NOW - timedelta(hours=9)).isoformat(timespec="seconds")}}))
    found = closeout.dangling(w / "CLAIMS.md", w / "notebooks", w / "DIARY.md", beats, NOW)
    assert len(found) == 1, f"one session, one finding: {found}"
    assert found[0]["held_tracks"] and found[0]["notebooks"]   # both surfaces merged into it
