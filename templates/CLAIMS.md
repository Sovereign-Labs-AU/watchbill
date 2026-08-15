# Claims — live ownership

> Check this file before touching any track. Claim before you work; renew while working;
> release at reconcile. A live lease held by another session = STOP, ask the Operator.
> Full rules: PROTOCOL.md §1.1. Audit: `python3 scripts/watchbill_check.py CLAIMS.md`.

## Tracks

| Track | Globs | Owner | Session | Agent | Claimed | Lease-until | Task |
| --- | --- | --- | --- | --- | --- | --- | --- |
| example-feature (synthetic example — replace me) | src/example/** | Agent | s-demo-0001 (example session) | ExampleVendor Model-1 | 2026-01-01 09:00 | 2026-01-01 13:00 | Build the example feature; release this row at reconcile. |
| example-parked-track (synthetic) | docs/parked/** | — | UNCLAIMED — placeholder so the track is on-book; claim it before working it | — | 2026-01-01 | | Recognized-but-unowned work. |

## Resources (machines, drives, long-running boxes)

> Same lease rules. Resource rows are **AUDITED, not yet enforced**: the checker reports each
> live row as ARMED or NOT ARMED (ARMED = the three guard conditions hold, so an enforcement
> adapter *could* block on it). The shipped guard core covers file globs only — a shell/host
> enforcement adapter is deliberately not shipped yet; wire your own against `scripts/guard.py`
> or rely on the audit. We will not advertise a block we don't ship.

| Resource | Match | Owner | Session | Claimed | Lease-until | Note |
| --- | --- | --- | --- | --- | --- | --- |
| example-build-box (synthetic) | buildbox.local; 10.0.0.99 | Agent | s-demo-0001 (example session) | 2026-01-01 | 2026-01-08 | Long job running here; renew weekly; release when the job lands. Lease-until stays a BARE date — prose in this cell disarms the guard. |
