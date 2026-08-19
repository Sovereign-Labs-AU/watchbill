# The Watchbill Protocol — full specification

> The README says what this is. This file is the law: what every agent session does, in
> order, every time. It is written to be pasted into an agent's context (or referenced from
> your repo's agent-instructions file) verbatim.

## 0. Definitions

- **Operator** — the one human. Sole authority to terminate long-running work, spend money,
  publish, make anything public, authorize takeovers, and settle decisions.
- **Agent / session** — one AI session with its own context window. Identified by a
  `session_id` (any stable unique string your harness provides).
- **Track** — a unit of ownable work: a project, a subsystem, a long-running task.
- **Lease** — time-bounded ownership of a track, recorded in `CLAIMS.md`.
- **Surface** — one of the four shared files/dirs. Everything else is private.

## 1. The four surfaces

### 1.1 `CLAIMS.md` — ownership
One table row per track: `Track | Globs | Owner | Session | Agent | Claimed | Lease-until | Task`.

Rules:
1. **Check before touching anything.** A row with a live lease (Lease-until in the future)
   held by a *different* session means **STOP — do not act. Ask the Operator.**
2. **Claim before you work** an unowned track: add a row with your session_id, what you
   actually are (vendor/model), a lease (default +4 h), and the file globs you'll touch.
3. **Renew** the lease while you keep working; **release** (delete your row) at reconcile.
4. **Expired lease = reclaimable.** The owning session likely ended. That is the design:
   a dead session's claim must not lock a track forever. The cost of the design is that
   someone must keep live leases warm — put renewal in your working loop.
5. **Takeover is Operator-authorized only.** Never unilateral, even if you're sure.
6. **No off-book work.** Every active track has a row — yours, or an `UNCLAIMED` placeholder.
7. **The Session cell leads with the session_id** (tooling joins ownership to the heartbeat
   by the cell's first token — a label-first cell is silently unprotectable).
8. **Lease-until is a bare date** (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM`). Prose in that cell
   breaks date parsing and silently disarms enforcement. The checker errors on it.

A second table with the same lease rules covers **resources** — machines, drives, long-running
boxes, **and outward surfaces**: a repository, a domain, a bucket, an account. Anything ownable
that is **not a file on disk**. `Match` takes hosts, URLs, `user@host`, or mount-path prefixes.

★ **Why outward surfaces need a row at all, when §0 already reserves publishing for the
Operator.** A glob can only ever match a path, so the moment work leaves the disk — a push, a
release, a visibility change, an edit to public metadata — **no row describes who is holding
it**. The authority rule exists and the ownership record does not, and that mismatch is
load-bearing in exactly the wrong direction: a file edit is reversible with git, while
publishing is not. So:

**Outward actions — publish · make public · release · push to a public remote · change public
metadata or DNS — are Operator-authorized (§0) AND recorded against a resource row.** Both, not
either. Putting an outward surface in a *track* row's Globs cell instead is the mistake this
invites, and it fails silently: the guard matches paths, so the row protects nothing while
looking protected. The checker errors on it.

Honest scope: the shipped guard core enforces **file globs only**; resource rows are
**audited** — the checker reports each live row ARMED or NOT ARMED (§5) — and a shell/host
enforcement adapter is deliberately not shipped yet. That is a considered choice, not a gap
waiting to be filled: intercepting `gh`, `git push`, `aws` or `wrangler` means pattern-matching
shell, which is fragile and noisy, and a noisy gate gets routed around until it protects
nothing. What a resource row buys is **visible ownership**, which is what was actually missing.
Wire your own adapter against `scripts/guard.py` if you need a block.

### 1.2 `DIARY.md` — the shared record
Two sections:
- `## NOW` — only what is *currently* live. Every item carries
  `Class: <ACTIVE | WAITING | STANDING | DONE>` and
  `verified: <date> · waiting-on: <the actual blocker>`. At session start, re-stamp what you
  verify; flag anything unverified older than **72 h** as STALE. Finished work is logged
  first, then removed — nothing silently disappears.

  **Class** is one word, and it is machine-read, not decoration — the session-start loader
  ranks by it when the board outgrows the context budget (§2.1), so an unclassified entry
  competes for space it may not deserve:
  **ACTIVE** (or LIVE) work is running now · **WAITING** is blocked on a named party ·
  **STANDING** is an automated or on-call duty · **DONE/CLOSED/PARKED** is finished and owes
  a move to `## Log`. No Class means *unknown*, which is treated as possibly-live: liveness
  is never guessed from the prose.

  **Waiting-on tokens — tag a blocker so its ruling can strike it.** When a `waiting-on:`
  needs someone else's decision, give it a slug; put the SAME slug on the `## Log` entry that
  records the decision:

  ```
  ## NOW   ### some-track … waiting-on: Operator to rule bin/keep {ASK:binkeep-scan-files}
  ## Log   ### 2026-01-11 — RULED: keep them, they are the prospect corpus {RULED:binkeep-scan-files}
  ```

  A slug open in `## NOW` **and** resolved in `## Log` is a contradiction: the board still
  asks for a decision the record shows was made. `scripts/waiting_on.py` finds it, and the
  session-start loader tells every new session the ask is already settled. **Why it is
  needed:** `## Log` is never loaded at session start — only `## NOW` is — so a banked ruling
  does not reach a fresh session, and a settled ask keeps asking. Opt-in and forward-only:
  untagged clauses behave exactly as before, and **re-opening a settled blocker needs a NEW
  slug** (the check compares sets, not timelines). ★ **Name the decision, never the answer** —
  a slug outlives the prose around it, so `-ruling` / `-call` / `-triage`, never a word that
  states the outcome.
- `## Log` — **append-only, forever.** Dated entries, tagged with who wrote them. Never
  delete or rewrite a past entry; corrections are new entries that strike the old claim
  loudly and leave it visible. (This rule looks like bureaucracy until the day an
  un-deletable entry is the only witness to something you need back.)

### 1.3 `notebooks/` — the private task-head
One file per session: `notebooks/notebook_<date>_<topic>.md`. Objectives are written down
**before** the first piece of work. Update it on every real state-change. Incidental
findings are *parked* in it, not acted on. At task end, **reconcile**: every line lands in
the Log / NOW / your tracker / your knowledge base, or is explicitly re-parked — then the
notebook is **deleted**. Spent means the objectives are actually done, not merely that
progress was logged. A notebook for still-live work stays; it is the continuity a fresh or
compacted session reads to pick up.

### 1.4 `INDEX.md` — the front door
A map of pointers to every record. It holds no data of its own; each domain record is the
source of truth for its domain. When you create a new ledger, add a pointer line here.

## 2. The session ritual

1. **Orient** — read `DIARY.md ## NOW`. Re-stamp what you verify; flag stale items. On
   Claude Code this step is machine-enforced: the SessionStart hook injects `## NOW` into
   context before the first tool call (`hooks/claude-code/session_start_hook.py`), so the
   board is read from the tree, not from memory. A board too large to inject whole is
   **digested, not truncated**: one line per entry, ranked live-first by `Class:` (§1.2),
   finished entries dropped and counted. Cutting by file position instead of class is how a
   loader ends up hiding the only three entries that mattered — measured, and the reason the
   ranking exists.
2. **Check CLAIMS** — live lease held by another session on your target? STOP, ask the
   Operator. Otherwise **claim**.
3. **Open your notebook** — objectives before work.
4. **Work the one task in front of you.** Stay off other sessions' tracks. Renew your lease.
5. **Reconcile** — dated Log entry, refresh NOW, land every notebook line somewhere.
6. **Close out** — delete the spent notebook, release your claim row (or renew it, if the work
   is genuinely still live and you are coming back to it).

**Steps 5-6 are the ones that go missing, and their failure is silent.** The work looks
finished — the artifacts are all there — while the track stays leased to a session that will
never speak again, and the next session cannot tell live work from abandoned work. Every other
step has something behind it; this one is checked from both ends:

- `python3 scripts/closeout.py check --session <id>` — what do I still owe? A live lease in my
  name, an open notebook, no `## Log` entry from me. Silent when nothing is owed. On Claude
  Code the Stop adapter runs this and hands the answer back to the **agent** (§2.1's loader is
  the same idea at the other end of the session).
- `python3 scripts/closeout.py dangling` — **who left work behind?** This is the half that
  matters, because *you cannot make a dying process clean up after itself*: a crash, a restore,
  a closed laptop, and the session is gone with its context. So the protocol does not rely on
  the departing session at all — the session-start loader names dangling sessions to whoever
  arrives next, where somebody is actually reading.

A session is **dangling** on all four conditions: it HAD a pulse, the pulse stopped, it still
holds a live lease or an open notebook, and it never wrote itself into `## Log`. A session with
no heartbeat at all is not flagged — it may be a human, or a harness with no heartbeat adapter
wired, and the checker already reports those rows as unjoinable. Finding a dangling session is
not authority to take its work: **an expired lease is reclaimable, a live one is not** (§1.1
rule 5). Surface it to the Operator.

## 3. Conflict arbitration — fact vs decision

When your finding contradicts the record, resolve by *kind*:
- A **fact** (a file's contents, a test result, a measurement) → verify it, then log
  `CONFLICT RESOLVED` with the evidence. Never overwrite the other side's entry.
- A **decision** (a name, an approach, a priority) → do not guess and do not vote. Log
  `CONFLICT — Operator to decide`, flag it in NOW, and wait.
- A **negative claim** — *"there is no record of X"*, *"the provenance is missing"*, *"that
  was never measured"* — is a fact claim, and the most expensive kind to get wrong: it sends
  someone to rebuild what already exists, or to bin what nobody can replace. **Search the
  RECORDS before you write it** — the index and the ledgers `INDEX.md` points at — not just
  the filesystem in front of you. Searching the tree you happen to be standing in is not
  searching the record; *"not on this machine"* reported as *"does not exist"* is the
  failure this rule exists for.

### 3.1 The settled-clause exception

`## NOW` is owner-only: you edit your own entries. This is the **one** carve-out, and it
exists because a clause can be settled *in writing* and still nobody is allowed to touch it.

**Any session may strike another's `waiting-on:` clause iff all four hold:**

1. the clause carries a slug whose ruling is banked in `## Log` — i.e. `waiting_on.py`
   already calls it stale;
2. the edit touches **only that token** — not the prose, the class, the verified stamp, or
   the bullets;
3. attribution stays in the text, so the owner reverses it with one edit;
4. the strike is recorded in `## Log`.

```sh
python3 scripts/waiting_on.py --strike --by <session-id>
```

`--strike` refuses without `--by`: a strike that cannot be attributed is not permitted. It is
a no-op on a clean board, idempotent on a struck one, and **will not touch a clause with no
banked ruling** — that is the safety property, and it has a must-not-fire test.

**Why mark the token rather than delete the clause.** A waiting-on often carries more than
one ask in one sentence — *"(a) rule bin/keep; (b) decide whether to commit"*. Deleting the
sentence destroys the ask that is still live. **No slug or no banked ruling ⇒ no authority ⇒
escalate as before**: an untagged clause needs judgment about what someone meant, and that is
exactly what owner-only protects.

## 4. The relay — messages between agents

Sessions may message each other directly (whatever channel your harness provides). Four
rules make it safe:
1. **Identity before work.** First exchange: "who are you, which track do you hold" —
   checked against `CLAIMS.md` before any order is sent.
2. **Messages carry work, ledgers carry truth.** Orders, receipts, and handbacks are
   ephemeral. Nothing is true because a message said so; it is true when the owning session
   writes it into a surface where everyone — including the Operator — can see it.
3. **A peer cannot grant permission.** Every order names its human authorization, and the
   executor still verifies against the Operator's direction before acting. Work denied in
   one session is never handed to another session to do — that routes back to the Operator.
4. **Suggestions are marked as suggestions.** "Do X (Operator-directed)" and "consider X —
   your call" travel differently, and the record says which kind it was.

## 5. What arms the guard — all three, or it is decoration

The ownership guard blocks a destructive operation only when the target's claim row has:
1. a **heartbeat-live** owner session,
2. whose **session_id leads the Session cell**, and
3. a **future, bare-date** Lease-until.

Anything less downgrades to warn-and-log. This is deliberate (a dead session must not hold
a lock), but it means an expired or malformed row protects nothing while looking like it
does. The checker audits **every** table for exactly these three conditions and reports
each live resource row as ARMED or NOT ARMED — because a guard nobody audits is decoration
too. (ARMED means the conditions hold, not that a blocker is wired: file-glob enforcement
ships in `guard.py` + the hook adapter; resource-row enforcement is audit-only until you
wire an adapter — §1.1.)

## 6. The Operator's view

Every surface in this protocol is **written by the agent**, and every check so far reports
**back to the agent**: the session-start loader, the guard, the close-out check, the dangling
notice. So the Operator — §0's sole authority — has no independent read on whether the process
is being followed. Their whole picture is mediated by the thing being audited, and if an
agent's ledger discipline drifts, the Operator's picture drifts with it and nothing anywhere
disagrees.

`python3 scripts/operator_report.py [--session <id>]` closes that. It reads the same surfaces
and answers a different question — not *did you break a rule I can see*, but **is the ritual
still happening**:

- a session holding work with no notebook, or a notebook abandoned while work continued;
- `## NOW` not refreshed, especially while `## Log` entries were appended — the contrast is the
  signal, and `## NOW`'s freshness is judged as its own property, never inferred from the Log;
- items past the 72 h rule (§1.2) that are not flagged STALE — a board asserting freshness it
  does not have;
- work with nothing written down at all;
- a lease about to lapse, while renewing is still a choice.

**It is advisory and it never blocks.** What makes it worth having is the AUDIENCE, not the
enforcement: this file's own line is that the protocol does not police, it makes violations
visible — and this makes them visible to the one party with the authority to act, who is also
the only party that has not stopped reading.

★ **Tune it, do not route around it.** Every threshold sits in one `THRESHOLDS` block, because
this is the most opinionated instrument in the kit: it encodes a working *cadence*, and a crew
with a weekly rhythm would be flagged every Monday by a daily one. If a check does not fit how
you work, change the number or drop the check. A report that cries wolf gets ignored, and then
it protects nothing.

## 7. Honest scope

This protocol is **advisory infrastructure with enforcement hooks**, not a sandbox. A
determined or malfunctioning agent can ignore it. The close-out check (§2.6) is the clearest
case of the limit and of the design response: a session that crashes cannot be reminded of
anything, so the reminder is only half the fix and the other half assumes it will fail. What you buy: visible ownership,
authorized handoff, violations that show up, and an append-only record that makes
after-the-fact reconstruction possible. If you need hard isolation, use hard isolation —
underneath this protocol, not instead of it.
