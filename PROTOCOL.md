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

A second table with the same lease rules covers **resources** (machines, drives, long-running
boxes), bringing them under the same lease discipline. Honest scope: the shipped guard core
enforces **file globs only**; resource rows are **audited** — the checker reports each live row
ARMED or NOT ARMED (§5) — and a shell/host enforcement adapter is deliberately not shipped yet.
Wire your own against `scripts/guard.py`, or rely on the audit.

### 1.2 `DIARY.md` — the shared record
Two sections:
- `## NOW` — only what is *currently* live. Every item carries
  `verified: <date> · waiting-on: <the actual blocker>`. At session start, re-stamp what you
  verify; flag anything unverified older than **72 h** as STALE. Finished work is logged
  first, then removed — nothing silently disappears.
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

1. **Orient** — read `DIARY.md ## NOW`. Re-stamp what you verify; flag stale items.
2. **Check CLAIMS** — live lease held by another session on your target? STOP, ask the
   Operator. Otherwise **claim**.
3. **Open your notebook** — objectives before work.
4. **Work the one task in front of you.** Stay off other sessions' tracks. Renew your lease.
5. **Reconcile** — dated Log entry, refresh NOW, land every notebook line somewhere.
6. **Close out** — delete the spent notebook, release your claim row.

## 3. Conflict arbitration — fact vs decision

When your finding contradicts the record, resolve by *kind*:
- A **fact** (a file's contents, a test result, a measurement) → verify it, then log
  `CONFLICT RESOLVED` with the evidence. Never overwrite the other side's entry.
- A **decision** (a name, an approach, a priority) → do not guess and do not vote. Log
  `CONFLICT — Operator to decide`, flag it in NOW, and wait.

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

## 6. Honest scope

This protocol is **advisory infrastructure with enforcement hooks**, not a sandbox. A
determined or malfunctioning agent can ignore it. What you buy: visible ownership,
authorized handoff, violations that show up, and an append-only record that makes
after-the-fact reconstruction possible. If you need hard isolation, use hard isolation —
underneath this protocol, not instead of it.
