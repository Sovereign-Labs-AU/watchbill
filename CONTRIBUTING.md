# Contributing to Watchbill

Read [`PROTOCOL.md`](PROTOCOL.md) first. It is short, and it is the thing being maintained —
the scripts only exist to make its rules visible.

Everything here is plain markdown and stdlib Python. `pytest` is the only dependency, and only
for the tests. If a change needs a package, a server or an account, it belongs in a different
project: an adopter's whole install is "copy some files in".

## The bar

Every rule in this repo exists because someone hit the failure it prevents, and every check
here has been watched fail for the right reason. Four things are asked of a change:

**1. A must-catch test AND a must-not-fire test.** Both, for any check. The first proves the
instrument can see; the second proves it stays quiet on the cases it must not touch. The
second is usually the load-bearing one: a check that flags everything is not strict, it is
noise, and a noisy check gets routed around until it protects nothing. Say in the test *why*
the quiet case must stay quiet.

**2. A mutant in `tests/builders_suite.sh`.** Break your new behaviour on a copy and require
the suite to go red:

```sh
bash tests/builders_suite.sh      # code · mutation · battle · data · cold-adopter
```

A green suite is not evidence until you have watched it fail. Three tests in this repo once
passed for the wrong reason, and only mutation found them.

⚠️ **Make sure the mutant actually changes behaviour.** Two mutants here once survived not
because the tests were weak but because they had been rewritten to something equivalent. *A
mutant that changes no behaviour proves nothing about the test that survives it* — check that
it fails before you trust that it passes.

**3. Fixtures that carry the disagreements real data has.** A suite built only from synthetic
fixtures is internally consistent by construction, so it cannot see a mismatch between two
real sources that disagree — one file holding a full session id while another holds a short
prefix, for instance. That is a real bug this repo shipped. If two sources can disagree about
a format, put the disagreement in a fixture, and run your change against a real board once and
read the output line by line before you open a pull request.

**4. Claims in the docs that a test can check, where a test can check them.** The README states
the suite's size and a test asserts it, because that number is how an adopter tells a good
install from a broken one, and a stale one makes those indistinguishable.

## Non-negotiables

- **Hooks fail open.** Any error, any missing file: print nothing, exit 0. A coordination tool
  must never be the reason a session cannot start, or cannot end.
- **Never advertise a block that is not shipped.** Enforcement reach is stated honestly in
  PROTOCOL.md §7, including what is audit-only. Widening the claim is a bigger change than
  widening the code.
- **`## Log` is append-only, in the protocol and in the tooling.** Anything that writes to a
  diary must be scoped so it cannot touch history — that has been a real bug here.
- **Nothing takes ownership on its own say-so.** Tools surface and report; a live lease
  transfers on the Operator's word (§1.1 rule 5). Surfacing is not claiming.

## Style

Comments explain *why*, and are worth their length when they carry a failure someone paid for.
Where a line exists because of a specific bug, say which bug — that is what stops it being
"simplified" back into the bug six months later. Match the surrounding voice: plain, specific,
no adjectives doing work that evidence should do.

## Pull requests

CI runs the unit suite on Python 3.10–3.13 plus the builder's suite; both must be green. In the
description, say **what failure the change prevents** — not what the code does, which the diff
already says.

Bug reports are welcome as issues. A report that includes the board (redacted as you like) that
produced the wrong behaviour is worth ten that describe it.

## Scope

Watchbill is coordination and record-keeping for agent crews: ownership, the shared record, the
private task-head, the pulse, and the checks over them. Build discipline, model or data
tooling, and anything vendor-specific beyond a thin hook adapter live outside it.

The maintainers are conservative about surface area. A change that adds a rule should also
delete one, or show the failure that the extra rule prevents.
