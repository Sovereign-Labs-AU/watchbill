# Adoption audit — 2026-08-15

> Before release, a deliberately *fresh* agent session — no knowledge of how Watchbill was
> built, forbidden from reading its build history — was handed nothing but the repo and told
> to follow the Quickstart literally in a virgin repository, then verify every safety claim.
> This is its report, lightly anonymized, findings preserved in full. We ship it because a
> protocol about visible state should have visibly-stated flaws — and their fixes.

**Original verdict: WOULD NOT — as written.** A literal cold adopter stopped dead at
Quickstart step 2. The mechanics underneath held — every safety claim the auditor could
test behaved exactly as documented — but the instructions failed on their own.
**Every finding below was fixed the same day; the corrected Quickstart was then replayed
end-to-end in a fresh virgin repo and passed at every step.**

Time measured: ~6 minutes of reading + 92 seconds of commands from first copy to first
passing suite and accepted commit — including the failed install paths that became
findings.

## Findings and resolutions

| # | Sev | Finding (auditor's words, condensed) | Resolution |
|---|---|---|---|
| 1 | HIGH | Quickstart step 2 could not work as written: `install_hooks.sh` wasn't in the copy list (exit 127 from the adopter's repo), and run from Watchbill's checkout it silently installed the hook into *Watchbill's own* `.git` while printing success — wrong-target silent success. | Installer now refuses to run where the kit hasn't landed, always prints the exact `.git/hooks` path it wrote, and warns when run from the source checkout. Step 1's copy list is complete and copy-pasteable. |
| 2 | HIGH | The generated hook runs `pytest tests/` — but `tests/` was never in the copy list, so the adopter's *first commit* was blocked by their own new hook. | `tests/` (and `hooks/`, `PROTOCOL.md`, the installer) are in the step-1 copy list; the replay's first commit passes through the gate. |
| 3 | MED | Copy list omitted `PROTOCOL.md` and `hooks/` (which must sit at a specific depth for the adapter's relative imports). | In the copy list, with the depth preserved by `cp -R`. |
| 4 | MED | No `.gitignore` shipped: `.watchbill/` (the heartbeat store, rewritten on every tool call by every session) would be committed — permanent dirt plus merge conflicts on the one file everyone writes. | A `.gitignore` ships in the templates and arrives via the dot-copy; the replay confirms `.watchbill/` stays untracked. |
| 5 | **CRIT** | The documented heartbeat wiring used an environment variable that **does not exist**. The auditor then verified it on a **live headless harness session** with the exact shipped wiring: the stamp errored inside the real hook, the store was never created, and therefore the guard's block **never arms for any adopter** — every foreign write degrades to a warn — while the install looks fully wired. (The guard adapter itself was unaffected: the hook's stdin JSON does carry `session_id`, confirmed in the same live capture.) | Heartbeat wiring rewritten as a stdin-JSON adapter (`heartbeat_hook.py`) — the stable documented interface, mirroring the guard adapter; independently recommended by the auditor and validated by its live capture. Two new tests; the docs now tell adopters to *verify the first stamp lands* (`heartbeat.py list`), because a wired-but-never-stamping install is invisible otherwise — which is exactly how this one nearly shipped. |
| 6 | LOW | README claimed all four instruments ship "each with tests"; the notebook board had none. | Board test added; claim wording now matches the suite. |
| 7 | LOW | The pristine templates flagged on first checker run (expired synthetic leases) — teaching adopters to ignore flags on day one. | Synthetic rows are now closed-marker examples; a pristine install audits `clean.`, and a regression test keeps it that way. |
| 8 | LOW | "Must-fail fixtures — if the broken-lease fixture doesn't fail, stop" read backwards: on a healthy install the suite *passes*. | Reworded to the real contract — must-**be-caught** — with a live-trap recipe so adopters can watch the checker error on their own file. |
| 9 | INFO | Everything assumes cwd = repo root; nowhere stated. | Stated, in the Quickstart and the hooks doc. |
| 10 | INFO | The shipped guard wiring covers Write/Edit only; destructive shell commands are outside its reach. | Already consistent with PROTOCOL's honest-scope wording; now stated explicitly in the hooks doc as well. |
| 11 | INFO | The provenance claims (~90 days, the audit day, the recovery) are unverifiable from the repo alone — trust-based, though clearly framed as history. The one claim checkable from the repo (two traps → fixtures) checked out fully. | Acknowledged; that is the nature of provenance. The claims are pinned to internal receipts on the operation's side. |

## What the auditor verified and found solid

The checker caught **both trap classes injected into the auditor's own file**, not just its
fixtures (prose-lease → error, malformed row → error, exit 2 both). The pre-commit gate
blocked a broken ledger and correctly let flag-only states through. The guard's decision
table held in both directions — owner allow / stranger-vs-live block / stale-heartbeat and
expired-lease warn-not-block — with exact exit codes, and the hook adapter's stream
contract behaved precisely as documented, including fail-open on malformed input. The
heartbeat store survived deliberate corruption. Suite: all green, stock Python + pytest,
fractions of a second.

## The finding about the finding

The most dangerous defect (heartbeat wiring, #5) was invisible to the people who built
and security-scrubbed this repo — two prior adversarial passes missed it — and obvious to
the first stranger who actually *followed the instructions*. That is the entire argument
for adoption audits, and for the rule this protocol repeats about its own checkers:
**prove the instrument can fail before trusting what it tells you.**
