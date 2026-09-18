#!/usr/bin/env bash
# Canonical frontend validation commands (docs/ROADMAP.md Phase 1.5/1.6).
# Run locally after `npm install` in frontend/, and invoked verbatim by
# .github/workflows/ci.yml. Mirrors saas-os's own scripts/check-frontend.sh
# shape -- no `npm run test` step yet, unlike saas-os's own: there is no
# component logic in this scaffold to unit-test (docs/ROADMAP.md Phase
# 1.6 built only a login link and an authenticated placeholder page).
set -euo pipefail
cd "$(dirname "$0")/../frontend"

echo "== npm run typecheck =="
npm run typecheck

echo "== npm run lint =="
npm run lint

echo "== npm run build =="
npm run build
