#!/usr/bin/env python3
"""heartbeat.py — the live pulse. Sessions stamp; checkers and the guard read.

Store: .watchbill/heartbeats.json  →  {session_id: {"last_active": iso8601}}

Wire `stamp` into your harness so it fires on every tool call / turn (see hooks/).
A session that stops stamping goes stale in minutes — which is the point: liveness is
measured, never asserted.

Usage:
  python3 scripts/heartbeat.py stamp <session_id>
  python3 scripts/heartbeat.py list
"""
import json
import sys
from datetime import datetime
from pathlib import Path

STORE = Path(".watchbill/heartbeats.json")


def load():
    try:
        return json.loads(STORE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def stamp(session_id: str):
    beats = load()
    beats[session_id] = {"last_active": datetime.now().isoformat(timespec="seconds")}
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(beats, indent=1, sort_keys=True))
    tmp.replace(STORE)  # atomic — a torn write must not corrupt the pulse everyone reads


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in ("stamp", "list"):
        print(__doc__)
        return 2
    if argv[0] == "stamp":
        if len(argv) < 2 or not argv[1].strip():
            print("stamp requires a session_id")
            return 2
        stamp(argv[1].strip())
        return 0
    for sid, rec in sorted(load().items()):
        print(f"{sid}  {rec.get('last_active', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
