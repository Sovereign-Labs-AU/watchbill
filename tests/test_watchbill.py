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
