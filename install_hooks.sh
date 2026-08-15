#!/usr/bin/env bash
# Per-clone hook install: the pre-commit check runs the claims audit + the test suite.
set -euo pipefail
cd "$(dirname "$0")"
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
HOOKEOF
chmod +x "$HOOK"
echo "watchbill: pre-commit hook installed."
