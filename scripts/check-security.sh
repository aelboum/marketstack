#!/usr/bin/env bash
# Dependency vulnerability scan + secret scan (docs/ROADMAP.md Phase 1.5:
# "dependency vulnerability scan (pip-audit) and secret scan
# (detect-secrets) present from day one", mirroring saas-os's own Phase
# 1.4). Needs the optional `security` extra (pip-audit, detect-secrets),
# not installed by `pip install -e ".[dev]"` alone -- see README.md.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== pip-audit (Python dependency vulnerabilities) =="
pip-audit

if [ -d frontend/node_modules ]; then
  echo "== npm audit (frontend dependency vulnerabilities) =="
  (cd frontend && npm audit --audit-level=high)
else
  echo "== npm audit skipped: frontend/node_modules not installed (run npm install in frontend/ first) =="
fi

echo "== detect-secrets (repository secret scan, tracked files only, against .secrets.baseline) =="
tracked_files="$(git ls-files)"
if [ -z "$tracked_files" ]; then
  echo "no git-tracked files yet (nothing staged/committed) -- nothing to scan"
else
  # shellcheck disable=SC2086
  detect-secrets-hook --baseline .secrets.baseline $tracked_files
fi
