#!/usr/bin/env bash
# Per-clone hook install: the pre-commit check runs the claims audit + the test suite.
#
# RUN THIS FROM YOUR OWN REPO ROOT, after Quickstart step 1 has copied scripts/ and
# tests/ into it. It refuses to run anywhere else — an earlier version silently
# installed the hook into WATCHBILL'S checkout when run from there, leaving the
# adopter's repo unprotected while printing success (adoption-audit finding HIGH-1).
set -euo pipefail

if [ ! -d .git ]; then
  echo "watchbill: no .git here — run from the root of the repo you are protecting." >&2
  exit 1
fi
if [ ! -f scripts/watchbill_check.py ] || [ ! -d tests ]; then
  echo "watchbill: scripts/ and tests/ not found beside this repo's .git —" >&2
  echo "  complete Quickstart step 1 first (copy scripts/, tests/, hooks/, templates)." >&2
  exit 1
fi

HOOK=.git/hooks/pre-commit
mkdir -p .git/hooks
cat > "$HOOK" <<'HOOKEOF'
#!/usr/bin/env bash
# Watchbill pre-commit: a commit must not freeze a broken ledger or a red suite.
set -e
if [ -f CLAIMS.md ]; then
  python3 scripts/watchbill_check.py CLAIMS.md || {
    rc=$?; if [ "$rc" -ge 2 ]; then echo "watchbill: CLAIMS errors — commit blocked"; exit 1; fi
  }
fi
python3 -m pytest tests/ -q || { echo "watchbill: test suite red — commit blocked"; exit 1; }
# Watchbill's OWN checkout additionally runs the builder's suite (mutation + battle + adoption)
# before a commit: this is the tree releases are cut from, and "48 passed" is not evidence that
# the tests would notice a regression. Adopter repos deliberately skip it — it audits
# Watchbill's instruments, not your project, and it is far too slow for an ordinary commit.
if [ -f templates/CLAIMS.md ] && [ -f tests/builders_suite.sh ] && [ -z "${WATCHBILL_BUILDERS:-}" ]; then
  bash tests/builders_suite.sh || { echo "watchbill: builder's suite NOT CLEAN — commit blocked"; exit 1; }
fi
HOOKEOF
chmod +x "$HOOK"
echo "watchbill: pre-commit hook installed into $(pwd)/.git/hooks/"
if [ -f templates/CLAIMS.md ]; then
  echo "watchbill: note — this looks like the Watchbill SOURCE checkout. If you meant to" >&2
  echo "  protect your own repo, run this from THERE after Quickstart step 1." >&2
fi
