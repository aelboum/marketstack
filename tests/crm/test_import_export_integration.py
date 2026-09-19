"""CSV import (background job) and export (docs/ROADMAP.md Phase 4.5).
Real disposable Postgres (+ Redis for the subprocess-worker test). Marked
`integration`, excluded from the default `pytest` run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from arq import create_pool
from arq.connections import RedisSettings
from infra.jobs import TenantJobPayload
from product.agency.provisioning import provision_agency, provision_client
from product.crm.contacts import create_contact
from product.crm.errors import CrmAccessDeniedError
from product.crm.imports import (
    _run_import_job,
    enqueue_contact_import,
    export_contacts_csv,
    get_import_job,
)

from tests.crm._cleanup import cleanup_tenant_tree, cleanup_users, make_user

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

_REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agency_and_client(owner_id):
    agency = provision_agency(owner_id, _name("agency"))
    client = provision_client(owner_id, agency.tenant_id, _name("client"))
    return agency, client


async def _run_job_inline(
    job_id: uuid.UUID, tenant_id: uuid.UUID, csv_content: str, actor_id: uuid.UUID
) -> None:
    """Runs `_run_import_job()` directly, in-process -- used by the tests
    below that only need to prove the row-processing logic itself
    (round-trip, malformed rows), not the durability-across-a-process-
    boundary claim (that is `test_import_job_runs_in_a_real_separate_worker_process`'s
    own, separate job)."""
    payload = TenantJobPayload(
        tenant_id=str(tenant_id),
        data={
            "import_job_id": str(job_id),
            "csv_content": csv_content,
            "actor_user_id": str(actor_id),
        },
    )
    await _run_import_job(payload)


async def test_export_then_reimport_round_trips() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        create_contact(
            owner.id, client.tenant_id, first_name="Ada", last_name="Lovelace", email="ada@ex.com"
        )
        create_contact(
            owner.id, client.tenant_id, first_name="Grace", last_name="Hopper", email="grace@ex.com"
        )
        csv_text = export_contacts_csv(owner.id, client.tenant_id)
        assert "Ada" in csv_text and "Grace" in csv_text

        owner2 = make_user()
        agency2, client2 = _agency_and_client(owner2.id)
        try:
            job = await enqueue_contact_import(owner2.id, client2.tenant_id, csv_content=csv_text)
            await _run_job_inline(job.id, client2.tenant_id, csv_text, owner2.id)

            final = get_import_job(owner2.id, client2.tenant_id, job.id)
            assert final.status == "completed"
            assert final.succeeded_rows == 2
            assert final.failed_rows == 0

            from product.crm.contacts import list_contacts

            reimported = list_contacts(owner2.id, client2.tenant_id)
            assert {c.first_name for c in reimported} == {"Ada", "Grace"}
            assert {c.email for c in reimported} == {"ada@ex.com", "grace@ex.com"}
        finally:
            cleanup_tenant_tree(client2.tenant_id, agency2.tenant_id)
            cleanup_users(owner2.id)
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_malformed_rows_are_individually_reported_valid_rows_still_succeed() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        csv_content = (
            "first_name,last_name,email,phone\n"
            "Ada,Lovelace,ada@ex.com,+15551234567\n"
            ",MissingFirstName,x@ex.com,\n"  # invalid: no first_name
            "Grace,Hopper,grace@ex.com,not-a-phone\n"  # invalid: bad phone
            "Charles,Babbage,,\n"  # valid: only required fields
        )
        job = await enqueue_contact_import(owner.id, client.tenant_id, csv_content=csv_content)
        await _run_job_inline(job.id, client.tenant_id, csv_content, owner.id)

        final = get_import_job(owner.id, client.tenant_id, job.id)
        assert final.status == "completed"
        assert final.total_rows == 4
        assert final.succeeded_rows == 2
        assert final.failed_rows == 2
        assert len(final.error_report) == 2
        assert {e["row"] for e in final.error_report} == {2, 3}

        from product.crm.contacts import list_contacts

        surviving = list_contacts(owner.id, client.tenant_id)
        assert {c.first_name for c in surviving} == {"Ada", "Charles"}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)


async def test_import_authorization_denied_for_unrelated_actor() -> None:
    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    stranger = make_user()
    try:
        with pytest.raises(CrmAccessDeniedError):
            await enqueue_contact_import(
                stranger.id, client.tenant_id, csv_content="first_name,last_name\nA,B\n"
            )
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id, stranger.id)


_WORKER_SUBPROCESS_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import os

    from infra.jobs import build_worker
    from product.crm.imports import IMPORT_JOB_FUNCTIONS

    async def main() -> None:
        worker = build_worker(
            IMPORT_JOB_FUNCTIONS, burst=True, queue_name=os.environ["IMPORT_TEST_QUEUE_NAME"]
        )
        try:
            await worker.main()
        finally:
            await worker.close()

    asyncio.run(main())
    """
)


async def test_import_job_runs_in_a_real_separate_worker_process() -> None:
    """Mirrors `tests/foundation/test_events_durable_integration.py`'s own
    real-subprocess-worker proof shape: this test process only ever
    enqueues -- a genuinely separate Python subprocess, connecting to the
    same real disposable Postgres via the inherited `DATABASE_URL`/
    `MIGRATIONS_DATABASE_URL` environment, is what actually runs the job
    and creates the contact row."""
    try:
        pool = await create_pool(RedisSettings.from_dsn(_REDIS_URL))
        await pool.ping()
        await pool.aclose()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable at the configured REDIS_URL: {exc}.")

    owner = make_user()
    agency, client = _agency_and_client(owner.id)
    try:
        queue_name = f"phase4-import-{uuid.uuid4().hex[:8]}"
        csv_content = "first_name,last_name,email\nSubprocess,Contact,sub@ex.com\n"
        job = await enqueue_contact_import(
            owner.id, client.tenant_id, csv_content=csv_content, queue_name=queue_name
        )
        assert job.status == "pending"

        subprocess_env = {
            **os.environ,
            "REDIS_URL": _REDIS_URL,
            "ENVIRONMENT": "test",
            "IMPORT_TEST_QUEUE_NAME": queue_name,
        }
        result = subprocess.run(
            [sys.executable, "-c", _WORKER_SUBPROCESS_SCRIPT],
            cwd=Path(__file__).resolve().parents[2],
            env=subprocess_env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"worker subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        final = get_import_job(owner.id, client.tenant_id, job.id)
        assert final.status == "completed"
        assert final.succeeded_rows == 1

        from product.crm.contacts import list_contacts

        created = list_contacts(owner.id, client.tenant_id)
        assert {c.first_name for c in created} == {"Subprocess"}
    finally:
        cleanup_tenant_tree(client.tenant_id, agency.tenant_id)
        cleanup_users(owner.id)
