#!/usr/bin/env python3
"""Claude Code Stop adapter — the Operator's view of ritual compliance.

Deliberately a SEPARATE adapter from `stop_hook.py`, though both fire on Stop, because they
address different people and that is the entire point of this one:

  * `stop_hook.py`   -> the AGENT. "You still owe a Log entry and a lease decision." Actionable
                        by the party receiving it, so it may block and ask for the work.
  * `operator_hook.py` -> the OPERATOR, via `systemMessage`. "The ritual has stopped happening."
                        Never blocks, never argues with the agent, and never asks the agent to
                        grade itself — every other check in the kit already reports to the
                        agent, and an agent that has drifted is exactly the one that has
                        stopped reading them.

Wire either, both, or neither. Both are silent when there is nothing to say.

FAIL-OPEN and NEVER BLOCKING: any error -> print nothing, exit 0. An advisory report that can
delay or break a turn would be traded away the first time it was inconvenient.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main():
    try:
        raw = sys.stdin.read()
        r = subprocess.run(
            [sys.executable, str(REPO / "scripts/operator_report.py"), "--hook"],
            input=raw, capture_output=True, text=True, cwd=str(Path.cwd()), timeout=10)
        out = r.stdout.strip()
        if out:
            print(out)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
