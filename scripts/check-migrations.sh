#!/usr/bin/env bash
# Migration bootstrap gate (docs/ROADMAP.md Phase 1.2/1.5, extended by
# Phase 2.1/2.3/2.4's own migrations, by Phase 7.1-7.2's own
# appointments.* migrations, including an empirical check that
# btree_gist and the double-booking-prevention EXCLUDE constraint on
# appointments.appointments really exist post-migration, not just the
# schema/table names, by Phase 8.1-8.3's own telephony.* migrations,
# including an empirical check that the partial unique index dedup-ing
# telephony.calls by (tenant_id, provider_name, provider_call_id) really
# exists, and by Phase 10.2's own automation.* migrations: proves a clean,
# disposable PostgreSQL database can be taken from nothing to both
# migration histories at head via the real two-step path
# (scripts/bootstrap-db.py) -- never the developer's own persistent `db`
# container, never production.
#
# Starts its own throwaway postgres:16-alpine container (mirrors saas-os's
# own CI `migrations` job precedent), runs the two-role init script
# (deploy/db-init/01-create-app-role.sh) via the official image's
# /docker-entrypoint-initdb.d hook, runs scripts/bootstrap-db.py against
# it, asserts the expected schemas/version tables exist, then always tears
# the container down (trap, so a failed assertion still cleans up).
set -euo pipefail
cd "$(dirname "$0")/.."

CONTAINER_NAME="product-migration-check-$$"
HOST_PORT="${MIGRATION_CHECK_PG_PORT:-55432}"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== starting disposable postgres:16-alpine =="
docker run --rm -d --name "$CONTAINER_NAME" \
  -e POSTGRES_USER=product \
  -e POSTGRES_PASSWORD=ci-only-placeholder \
  -e POSTGRES_DB=product \
  -e APP_DB_USER=product_app \
  -e APP_DB_PASSWORD=ci-only-app-placeholder \
  -p "${HOST_PORT}:5432" \
  -v "$(pwd -W 2>/dev/null || pwd)/deploy/db-init:/docker-entrypoint-initdb.d" \
  postgres:16-alpine >/dev/null
# `pwd -W` (Git Bash only) prints the native Windows drive-letter path --
# required here because Docker Desktop's volume-mount arg parsing on
# Windows does not reliably translate a plain MSYS POSIX path
# (`/c/Users/...`) combined with a `:`-separated container path; a POSIX
# path silently produced an EMPTY mount once during development of this
# script (the init script never ran, role creation silently skipped, no
# error at the `docker run` step itself). `|| pwd` keeps this portable to
# a non-Git-Bash `bash` (Linux CI) where `-W` does not exist.

echo "== waiting for postgres to accept connections (init scripts included) =="
# The official postgres image starts twice on a brand-new volume: once on
# a Unix socket only, to run /docker-entrypoint-initdb.d/ (our two-role
# init script), then a second time listening on TCP for real traffic.
# `pg_isready` against the container's own socket can observe the FIRST
# ("accepting connections") startup, before the init script has actually
# run -- the exact race that silently skipped role creation once during
# development of this script. Waiting for the "ready to accept
# connections" log line to appear twice is what actually proves the init
# scripts ran and the final, externally-reachable server is up.
for _ in $(seq 1 60); do
  ready_count=$(docker logs "$CONTAINER_NAME" 2>&1 | grep -c "database system is ready to accept connections" || true)
  if [ "$ready_count" -ge 2 ]; then
    break
  fi
  sleep 1
done
# Re-checking via `grep -q` here (rather than reusing $ready_count from the
# loop above) previously caused a false failure under `set -o pipefail`:
# `-q` closes its input on the first match, and if `docker logs` was still
# writing when that happened, the pipe closing sent it SIGPIPE -- a
# non-zero exit that pipefail then blamed on this check, even though the
# ready lines were already present (confirmed by the diagnostic dump one
# line below always showing them). $ready_count was already computed
# without truncating the pipe (`grep -c` drains all of it), so reuse it.
[ "$ready_count" -ge 2 ] || {
  echo "postgres never became ready" >&2
  docker logs "$CONTAINER_NAME" >&2
  exit 1
}

export ENVIRONMENT=test
export REDIS_URL="redis://127.0.0.1:6379/0"
export APP_DB_USER=product_app
export MIGRATIONS_DATABASE_URL="postgresql+psycopg://product:ci-only-placeholder@localhost:${HOST_PORT}/product"  # pragma: allowlist secret
export DATABASE_URL="postgresql+psycopg://product_app:ci-only-app-placeholder@localhost:${HOST_PORT}/product"  # pragma: allowlist secret

echo "== bootstrap: saas-os core migrations, then this product's own =="
python scripts/bootstrap-db.py

echo "== asserting expected schemas and version tables exist =="
python - <<'PYEOF'
import os

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["MIGRATIONS_DATABASE_URL"])
with engine.connect() as conn:
    saas_os_version = conn.execute(
        text("SELECT version_num FROM alembic_version_saas_os")
    ).scalar_one()
    assert saas_os_version, "saas-os's own alembic_version_saas_os is empty"

    # This product's own alembic_version table -- since Phase 10.2
    # (docs/ROADMAP.md), head is 0036_automation_workflow_runs
    # (thirty-six real migrations: foundation.tenant_settings,
    # white_label.*, twelve crm.* tables, three conversations.* tables,
    # seven marketing.* tables/alterations, five appointments.* tables,
    # five telephony.* tables, plus two automation.* tables -- workflows,
    # workflow_runs (the idempotency-ledger table)).
    product_version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert product_version == "0036_automation_workflow_runs", (
        f"expected product migrations at head 0036_automation_workflow_runs, "
        f"got {product_version!r}"
    )

    schema_rows = conn.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname = ANY(:names)"),
        {
            "names": [
                "core",
                "control_plane",
                "self_learning",
                "foundation",
                "white_label",
                "crm",
                "conversations",
                "marketing",
                "appointments",
                "telephony",
                "automation",
            ]
        },
    ).all()
    crm_table_rows = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'crm' ORDER BY tablename")
    ).all()
    conversations_table_rows = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'conversations' ORDER BY tablename")
    ).all()
    marketing_table_rows = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'marketing' ORDER BY tablename")
    ).all()
    appointments_table_rows = conn.execute(
        text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'appointments' ORDER BY tablename"
        )
    ).all()
    telephony_table_rows = conn.execute(
        text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'telephony' ORDER BY tablename"
        )
    ).all()
    btree_gist_rows = conn.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'btree_gist'")
    ).all()
    exclude_constraint_rows = conn.execute(
        text(
            "SELECT conname FROM pg_constraint WHERE conname = "
            "'ex_appointments_appointments_no_overlap_confirmed'"
        )
    ).all()
    telephony_calls_unique_index_rows = conn.execute(
        text(
            "SELECT indexname FROM pg_indexes WHERE indexname = "
            "'uq_telephony_calls_tenant_provider_call'"
        )
    ).all()
    automation_table_rows = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'automation' ORDER BY tablename")
    ).all()
    automation_run_dedup_index_rows = conn.execute(
        text(
            "SELECT conname FROM pg_constraint WHERE conname = "
            "'uq_automation_workflow_runs_tenant_workflow_dedup'"
        )
    ).all()
schemas_present = {row[0] for row in schema_rows}
expected = {
    "core",
    "control_plane",
    "self_learning",
    "foundation",
    "white_label",
    "crm",
    "conversations",
    "marketing",
    "appointments",
    "telephony",
    "automation",
}
assert schemas_present == expected, f"expected {expected}, got {schemas_present}"
crm_tables_present = {row[0] for row in crm_table_rows}
expected_crm_tables = {
    "companies",
    "contacts",
    "pipelines",
    "pipeline_stages",
    "opportunities",
    "tasks",
    "notes",
    "custom_field_definitions",
    "custom_field_values",
    "tags",
    "entity_tags",
    "import_jobs",
}
assert crm_tables_present == expected_crm_tables, (
    f"expected crm tables {expected_crm_tables}, got {crm_tables_present}"
)
conversations_tables_present = {row[0] for row in conversations_table_rows}
expected_conversations_tables = {"threads", "messages", "message_templates"}
assert conversations_tables_present == expected_conversations_tables, (
    f"expected conversations tables {expected_conversations_tables}, "
    f"got {conversations_tables_present}"
)
marketing_tables_present = {row[0] for row in marketing_table_rows}
expected_marketing_tables = {
    "campaigns",
    "suppressions",
    "campaign_recipients",
    "forms",
    "form_submissions",
    "templates",
    "recipient_tracking_tokens",
}
assert marketing_tables_present == expected_marketing_tables, (
    f"expected marketing tables {expected_marketing_tables}, got {marketing_tables_present}"
)
appointments_tables_present = {row[0] for row in appointments_table_rows}
expected_appointments_tables = {
    "calendars",
    "availability_rules",
    "appointments",
    "booking_links",
    "appointment_manage_tokens",
}
assert appointments_tables_present == expected_appointments_tables, (
    f"expected appointments tables {expected_appointments_tables}, "
    f"got {appointments_tables_present}"
)
telephony_tables_present = {row[0] for row in telephony_table_rows}
expected_telephony_tables = {
    "phone_numbers",
    "phone_number_routing_targets",
    "calls",
    "call_events",
    "call_recordings",
}
assert telephony_tables_present == expected_telephony_tables, (
    f"expected telephony tables {expected_telephony_tables}, "
    f"got {telephony_tables_present}"
)
assert len(btree_gist_rows) == 1, (
    "expected the btree_gist extension to be installed (required for the "
    "appointments.appointments EXCLUDE constraint's GiST index on calendar_id)"
)
assert len(exclude_constraint_rows) == 1, (
    "expected the double-booking-prevention EXCLUDE constraint "
    "'ex_appointments_appointments_no_overlap_confirmed' to exist on "
    "appointments.appointments"
)
assert len(telephony_calls_unique_index_rows) == 1, (
    "expected the partial unique index 'uq_telephony_calls_tenant_provider_call' "
    "to exist on telephony.calls"
)
automation_tables_present = {row[0] for row in automation_table_rows}
expected_automation_tables = {"workflows", "workflow_runs"}
assert automation_tables_present == expected_automation_tables, (
    f"expected automation tables {expected_automation_tables}, "
    f"got {automation_tables_present}"
)
assert len(automation_run_dedup_index_rows) == 1, (
    "expected the unique constraint "
    "'uq_automation_workflow_runs_tenant_workflow_dedup' to exist on "
    "automation.workflow_runs"
)

print(
    f"OK: saas-os core migrations at {saas_os_version}; "
    f"product migrations at {product_version}; schemas present: {sorted(schemas_present)}; "
    f"crm tables present: {sorted(crm_tables_present)}; "
    f"conversations tables present: {sorted(conversations_tables_present)}; "
    f"marketing tables present: {sorted(marketing_tables_present)}; "
    f"appointments tables present: {sorted(appointments_tables_present)}; "
    f"telephony tables present: {sorted(telephony_tables_present)}; "
    f"automation tables present: {sorted(automation_tables_present)}; "
    f"btree_gist installed: {len(btree_gist_rows) == 1}; "
    f"double-booking EXCLUDE constraint present: {len(exclude_constraint_rows) == 1}; "
    f"telephony calls unique index present: {len(telephony_calls_unique_index_rows) == 1}; "
    f"automation run dedup constraint present: {len(automation_run_dedup_index_rows) == 1}"
)
PYEOF

echo "== migration bootstrap gate: PASS =="
