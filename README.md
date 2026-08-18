# Watchbill

**A plain-text ledger protocol for AI agent crews: many agent sessions — and one human —
sharing a single working tree for months.**

> A *watchbill* is the roster that assigns a ship's crew to their watches — who is on duty,
> for which hours, answerable to the officer of the deck. This one is for AI agents.

Plain markdown and git. A few small scripts. No server, no database, no vendor, no account.
Every rule in it exists because we hit the failure it prevents.

From [Sovereign Labs AU](https://sovereignlabs.com.au). Licensed Apache-2.0.

---

## The problem

Run more than one autonomous agent against a shared body of work and you get three failure
modes, reliably:

1. **Collision** — two agents edit the same thing and silently clobber each other. Neither
   notices. You find out later, from the wreckage.
2. **Encroachment** — an agent wanders into work that was already owned, because nothing said
   so anywhere it would look.
3. **Unseen stalls** — an agent dies or walks away holding work, and nobody notices for days;
   its ownership just sits there, stale and invisible.

A rule ("don't step on each other") doesn't fix this — it relies on perfect memory across
context windows that get compacted and sessions that get restored. The fix is **visible
state**, **time-bounded ownership**, and **a live pulse**, so the safe path is the easy path
and violations *show up* instead of hiding.

## How it works

Five parts. Four are files in your repo; the fifth is the one channel that deliberately
keeps no state.

| Part | What it is |
|---|---|
| `CLAIMS.md` | Who owns which track, on a **time-bounded lease** that expires visibly. Claim before you work; renew while working; release when done. Takeover happens on the Operator's word or not at all. |
| `DIARY.md` | The shared record: a live `## NOW` (heartbeat-stamped, stale-flagged after 72 h) plus an append-only `## Log` that is **never rewritten**. Wins every conflict. |
| `notebooks/` | One private task-head per session: objectives written **before** work starts. At task end it must fully reconcile into the diary — then it is deleted, never hoarded. |
| `INDEX.md` | The front door: pointers only, no data of its own. |
| *the relay* | Ephemeral agent-to-agent messages: work orders, receipts, handbacks. **Carries work, never truth** — nothing is true until an owning agent writes it into a ledger. |

Plus the checkers: a claims auditor, an ownership guard, a heartbeat, a notebook board, a
close-out check, a waiting-on reconciler, and one report written for the Operator rather than
the agent that catches a blocker the log has already settled — shipped with a
test suite whose fixtures are real production traps, built to prove the instruments **catch
what they must catch** (see `tests/fixtures/`), and whose must-NOT-fire tests prove they stay
quiet on the cases they must not touch.

**Truth runs vertically and stays; messages run horizontally and vanish.**

## The two roles

- **The Operator** (the human): sole authority to terminate long work, spend money, publish
  anything, or make anything public. Names owners; settles every decision-class conflict.
- **Agents**: any number of AI sessions, from any vendor, possibly several at once. They
  build, measure, and advise. **No agent pushes, publishes, or spends on its own say-so.**
  Facts they verify; decisions they escalate.

## What this deliberately does not do

**It does not police. It makes violations visible.**

A determined or broken agent can ignore a markdown file — the same way a determined
developer can force-push over your history. We will not pretend otherwise, and you should
distrust any coordination tool that does.

What the protocol buys is different, and in practice it is enough: ownership you can *see*,
leases that expire *visibly*, a log that cannot be quietly rewritten, checkers that flag
what drifted, and a guard hook that blocks the destructive-operation cases it can reach.
When something slips anyway, the append-only record means you can reconstruct exactly what
happened — which is how we once rebuilt a lost artifact months after the code that made it
was deleted: a three-month-old diary entry that no process was allowed to erase was a key
witness to the reconstruction.

## Proven in use, not designed on a whiteboard

This protocol was extracted from a working AI research operation, not invented for release.

- **~90 days** of one human operator + concurrent agent sessions (several at once, more
  than one vendor) sharing a single repository in continuous operation.
- **One audit day**: a scheduled self-audit filed 23 findings; eight were closed the same
  day — each by the agent that owned the surface, routed over the relay, receipts verified
  by the auditor. Zero collisions.
- **One recovery**: a lost artifact was reconstructed months after the code that produced
  it was deleted — a months-old diary entry describing that code, which could not be
  rewritten, served as a key witness alongside two independent lines of evidence. The
  append-only rule acting as forensics.
- **Two traps → fixtures**: the audit found the ownership guard silently disarmed by a
  formatting quirk, and the checker blind to a whole table. Both are now shipped test
  fixtures: the broken cases this repo must always catch.

## Quickstart

Everything below runs **from the root of your own repo** (the one you're protecting —
Watchbill's paths are repo-root-relative). `$WATCHBILL` is wherever you cloned this repo.

1. **Copy the whole kit in** — surfaces, scripts, tests, hooks, the installer, and the law:

   ```sh
   cp -R "$WATCHBILL/templates/." .        # CLAIMS.md DIARY.md INDEX.md notebooks/ .gitignore
   cp -R "$WATCHBILL/scripts" "$WATCHBILL/tests" "$WATCHBILL/hooks" .
   cp "$WATCHBILL/install_hooks.sh" "$WATCHBILL/PROTOCOL.md" .
   ```

   The `templates/.` dot-copy matters: it brings the `.gitignore` that keeps the heartbeat
   store (`.watchbill/` — rewritten on every tool call by every session) out of version
   control. Everything is plain text; read all of it first — it's short.

2. **Install the pre-commit hook**: `./install_hooks.sh` — from *your* repo root. It
   refuses to run where step 1 hasn't landed (no `.git`, or `scripts/`+`tests/` missing),
   always prints the exact `.git/hooks` path it installed into, and warns if you ran it
   from the Watchbill source checkout by mistake — because an earlier version, run from
   there, silently protected the wrong repo while printing success.

3. **Prove the install**: `python3 -m pytest tests/` — the suite must **pass** — `71 passed` in the Watchbill checkout, `69 passed, 2 skipped`
   in your repo (the skip is the template-source check, which lives only in the checkout). Passing means the checker *caught* every must-be-caught fixture — the
   shipped traps are supposed to be caught, not to turn your suite red. To watch a trap
   fire live, put prose inside the `Lease-until` cell of a **live** row in your own
   `CLAIMS.md` — claim a track first, since the shipped rows are all released examples and
   prose in a *closed* row's lease cell is correctly ignored — then run
   `python3 scripts/watchbill_check.py CLAIMS.md`: it must ERROR ("SILENTLY DISARMED").
   If it stays quiet, stop: your install can't catch what it exists to catch.

4. **Put your first session on the bill**: have it read `PROTOCOL.md`, wire the hooks for
   your harness (`hooks/claude-code/README.md` for Claude Code — then verify the heartbeat
   actually stamps: `python3 scripts/heartbeat.py list` after one tool call), claim a track
   in `CLAIMS.md`, and open a notebook. The ritual does the rest.

## How it relates to what exists

Most pieces here have public cousins — agent memory banks remember across sessions, agent
mail servers deliver messages, agent issue trackers queue work, spec-first frameworks put
the plan before the artifact. All good tools; most need a server, a database, or a vendor.
Nobody, as far as we can find, ships the **assembly**: ownership + record + task-head +
pulse in one human-legible, zero-infrastructure protocol — nor these four properties:

- a **heartbeat** that flags stale context instead of letting it rot;
- **settled decisions that strike their own stale asks** — the log is never re-read at session
  start, so a ruling that lands there has to be carried forward mechanically or the board keeps
  asking a question that was answered;
- a **scratchpad that must reconcile and die** instead of accumulating;
- a **close-out that is checked from both ends** — the leaving session is reminded of what it
  still owes, and because a crashed session cannot be reminded of anything, the *next* session
  is told who left work behind;
- **fact-vs-decision arbitration** for conflicting entries (facts get measured, decisions
  go to the human);
- **multi-vendor agents under one human takeover authority**;
- **one instrument that reports to the human, not to the agent** — every surface here is
  written by the agent, so without it the Operator's whole picture of compliance is mediated
  by the thing being audited.

---

*The diary wins on any conflict with this page.*
