#!/usr/bin/env bash
# Canonical frontend validation commands (docs/ROADMAP.md Phase 1.5/1.6,
# extended by the UI Track's UI-1). Run locally after `npm install` in
# frontend/, and invoked verbatim by .github/workflows/ci.yml. Mirrors
# saas-os's own scripts/check-frontend.sh shape -- including its
# `npm run test` step, added here once UI-1 gave this scaffold its first
# real component/lib logic to unit-test (Phase 1.6 was a login link and
# an authenticated placeholder page only, with nothing worth testing yet).
set -euo pipefail
cd "$(dirname "$0")/../frontend"

echo "== npm run typecheck =="
npm run typecheck

echo "== npm run lint =="
npm run lint

echo "== npm run test =="
npm run test

echo "== npm run build =="
npm run build
