#!/usr/bin/env bash
# Canonical backend validation commands (docs/ROADMAP.md Phase 1.5). Run
# locally after `pip install -e ".[dev]"` (see README.md), and invoked
# verbatim by .github/workflows/ci.yml so local and CI checks never drift
# apart. Mirrors saas-os's own scripts/check-backend.sh shape exactly,
# scoped to this product's own package.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff check =="
ruff check .

echo "== ruff format --check =="
ruff format --check .

echo "== pyright =="
pyright

echo "== pytest =="
pytest

echo "== import-linter (lint-imports) =="
lint-imports
