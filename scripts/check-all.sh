#!/usr/bin/env bash
# Runs every fast, deterministic canonical check: backend + frontend +
# security (dependency vulnerability scan + secret scan). See
# check-backend.sh, check-frontend.sh, check-security.sh -- this script
# adds no checks of its own. Mirrors saas-os's own scripts/check-all.sh.
#
# Deliberately does NOT run check-docker.sh, check-migrations.sh, or
# check-integration.sh: all three need a running Docker daemon and take
# tens of seconds to minutes, unlike everything else here. Run them
# separately (also run by CI's `docker` / `migrations` / `integration`
# jobs).
set -euo pipefail
DIR="$(dirname "$0")"

"$DIR/check-backend.sh"
"$DIR/check-frontend.sh"
"$DIR/check-security.sh"
