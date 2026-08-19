# Claims — live ownership

> Check this file before touching any track. Claim before you work; renew while working;
> release at reconcile. A live lease held by another session = STOP, ask the Operator.
> Full rules: PROTOCOL.md §1.1. Audit: `python3 scripts/watchbill_check.py CLAIMS.md`.

## Tracks

| Track | Globs | Owner | Session | Agent | Claimed | Lease-until | Task |
| --- | --- | --- | --- | --- | --- | --- | --- |
| example-feature (synthetic — RELEASED example) | src/example/** | — | RELEASED — synthetic example row; outcome would be in the diary | — | 2026-01-01 09:00 | | A LIVE claim fills the cells as: track · globs · Agent · your-session-id (label) · vendor model · claimed date · future BARE-date lease · task. Never put a literal pipe character inside a cell — it splits the row and the parser drops it (the checker errors on that). |
| example-parked-track (synthetic) | docs/parked/** | — | UNCLAIMED — placeholder so the track is on-book; claim it before working it | — | 2026-01-01 | | Recognized-but-unowned work. |

## Resources (machines, drives, long-running boxes)

> Same lease rules. Resource rows are **AUDITED, not yet enforced**: the checker reports each
> live row as ARMED or NOT ARMED (ARMED = the three guard conditions hold, so an enforcement
> adapter *could* block on it). The shipped guard core covers file globs only — a shell/host
> enforcement adapter is deliberately not shipped yet; wire your own against `scripts/guard.py`
> or rely on the audit. We will not advertise a block we don't ship.

| Resource | Match | Owner | Session | Claimed | Lease-until | Note |
| --- | --- | --- | --- | --- | --- | --- |
| example-build-box (synthetic — RELEASED example) | buildbox.local; 10.0.0.99 | — | RELEASED — synthetic example row | 2026-01-01 | | A live resource row carries a real session id + a future BARE date (prose in the Lease-until cell disarms the guard — the checker errors on it). |
| example-public-repo (synthetic — RELEASED example) | https://github.com/example-org/example-repo | — | RELEASED — synthetic example row | 2026-01-01 | | An OUTWARD SURFACE: a repo, domain, bucket or account. Not a file, so no glob can cover it — publishing, releasing and metadata edits are Operator-authorized AND recorded here (PROTOCOL.md §1.1). |
