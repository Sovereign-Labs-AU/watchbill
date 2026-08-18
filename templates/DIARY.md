# Diary — the shared record

> Read `## NOW` first, every session. Append to `## Log` at reconcile — dated, tagged,
> append-only forever. Full rules: PROTOCOL.md §1.2.

## NOW

### example-feature — synthetic example, replace me. Class: ACTIVE. verified: 2026-01-01 · waiting-on: —
- One line per live fact. Re-stamp `verified:` when you check it; items unverified >72 h get flagged STALE.
- `Class:` is one word and it is machine-read — ACTIVE / WAITING / STANDING / DONE (§1.2). The
  session-start loader ranks by it when the board outgrows the context budget, so an entry with
  no Class competes for space it may not deserve.

### example-blocked — synthetic example, replace me. Class: WAITING. verified: 2026-01-01 · waiting-on: Operator to rule on the retention window {ASK:retention-window-ruling}
- A blocker that needs someone else's decision carries a slug. When the decision lands, the
  `## Log` entry recording it carries the SAME slug as `{RULED:retention-window-ruling}`:

  ```
  ## Log
  ### 2026-01-11 — [Vendor Model-1] RULED: 90 days {RULED:retention-window-ruling}
  ```

  `scripts/waiting_on.py` then reports this ask as settled — because `## Log` is never loaded
  at session start, and without the token the board keeps asking a question already answered.

## Log

### 2026-01-01 — [ExampleVendor Model-1] (session `s-demo-0001`) — example entry (synthetic)
- Done: what actually happened, with the receipt (file / commit / measured number).
- Decision: `→` markers for decisions, with who made them.
- This section is append-only. Corrections are NEW entries that strike the old claim loudly.
