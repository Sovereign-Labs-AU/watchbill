"""Watchbill test suite — including the must-fail fixtures.

The fixtures encode the two traps found in production use (README §"Proven in use"):
  1. prose inside a Lease-until cell silently disarming the guard's date parse;
  2. a malformed row the parser silently DROPS, taking its protection with it.
If `test_broken_lease_fixture_errors` or `test_malformed_row_fixture_errors` ever pass
against a checker that stays quiet, your install cannot catch what it exists to catch.
"""
import json
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
