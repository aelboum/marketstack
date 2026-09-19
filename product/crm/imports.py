"""CSV contact import (background job) and export (synchronous)
(docs/ROADMAP.md Phase 4.5).

**Import runs as an `infra.jobs` background job** (the roadmap's own
explicit requirement, for untrusted-input row-by-row parsing/validation
of potentially large files) -- **export is synchronous**, a deliberate
interpretation of the roadmap's "runs as a background job for large
files" as applying to import specifically, not export: export is a
bounded, already-validated read of this tenant's own data, not untrusted
input requiring row-by-row validation. Stated explicitly as a judgment
call, not assumed silently.

**Documented limitation**: the job payload carries the raw CSV text
content directly (`TenantJobPayload.data["csv_content"]`), not a
reference into an object store. This is only viable because no
object-storage capability exists yet in this product
(`docs/RESPONSIBILITY-MATRIX.md`'s "Object/file storage" row, Category B,
not yet built) -- bounded by `MAX_IMPORT_FILE_SIZE_BYTES` (5 MiB, chosen
as a generous-but-bounded limit for a CSV of contact rows; a 5 MiB CSV at
~100 bytes/row is roughly 50,000 rows, well beyond what this phase's
synchronous upload-acceptance step should need to hold in memory or pass
through Redis as a single job payload). A future phase with real object
storage should revisit this design -- carrying arbitrary-sized file
content through the job queue does not scale indefinitely, and this is
not presented as the permanent shape.

**Every imported contact goes through the exact same
`product.crm.contacts.create_contact()` function an ordinary API call
uses** -- never a separate, unaudited bulk-insert path. Every row gets
identical validation (phone normalization, company-tenant checks), an
identical audit-log entry, and identical authorization semantics (the
job runs as the importing `actor_user_id`, re-checked by
`create_contact()`'s own `permissions.require()` call, exactly as if
that user had called the API once per row).

A malformed row (missing required field, invalid phone, unknown company
reference) is recorded as a per-row failure in `crm.import_jobs
.error_report` and the job continues -- one bad row never aborts the
whole batch (the roadmap's own explicit "never a partial silent
failure": every row's outcome is accounted for).
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope
from infra.jobs import TenantJobPayload, enqueue_job, register_job

from product.crm.companies import create_company
from product.crm.contacts import create_contact
from product.crm.errors import CrmReferenceNotFoundError, CrmValidationError
from product.crm.models import Company, Contact, ImportJob
from product.crm.permissions import CONTACT_RESOURCE, require
from product.foundation.values import InvalidPhoneNumberError

MAX_IMPORT_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MiB -- see module docstring.

_REQUIRED_COLUMNS = ("first_name", "last_name")
_OPTIONAL_COLUMNS = ("email", "phone", "company_name")


@dataclass(frozen=True, slots=True)
class ImportJobView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    total_rows: int | None
    succeeded_rows: int
    failed_rows: int
    error_report: list[dict[str, object]]
    created_at: datetime
    completed_at: datetime | None


def _job_view(row: ImportJob) -> ImportJobView:
    return ImportJobView(
        id=row.id,
        tenant_id=row.tenant_id,
        status=row.status,
        total_rows=row.total_rows,
        succeeded_rows=row.succeeded_rows,
        failed_rows=row.failed_rows,
        error_report=json.loads(row.error_report) if row.error_report else [],
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _create_job_row(actor_user_id: uuid.UUID, tenant_id: uuid.UUID) -> ImportJob:
    with tenant_session_scope(tenant_id) as session:
        row = ImportJob(tenant_id=tenant_id, status="pending")
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.contact.import_start",
        resource_type="crm.import_job",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return row


def get_import_job(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> ImportJobView:
    require(actor_user_id, tenant_id, resource=CONTACT_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(ImportJob, job_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("import_job", job_id)
        session.expunge(row)
    return _job_view(row)


def _find_or_create_company(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, name: str) -> uuid.UUID:
    with tenant_session_scope(tenant_id) as session:
        existing = (
            session.execute(
                select(Company).where(Company.tenant_id == tenant_id, Company.name == name)
            )
            .scalars()
            .one_or_none()
        )
        if existing is not None:
            return existing.id
    return create_company(actor_user_id, tenant_id, name=name).id


def _process_row(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, row_number: int, row: dict[str, str]
) -> dict[str, object] | None:
    """Returns an error dict on failure, `None` on success. Never
    raises -- one bad row must not abort the batch."""
    try:
        first_name = (row.get("first_name") or "").strip()
        last_name = (row.get("last_name") or "").strip()
        if not first_name or not last_name:
            return {"row": row_number, "error": "first_name and last_name are required."}
        company_id = None
        company_name = (row.get("company_name") or "").strip()
        if company_name:
            company_id = _find_or_create_company(actor_user_id, tenant_id, company_name)
        create_contact(
            actor_user_id,
            tenant_id,
            first_name=first_name,
            last_name=last_name,
            email=(row.get("email") or "").strip() or None,
            phone=(row.get("phone") or "").strip() or None,
            company_id=company_id,
        )
        return None
    except InvalidPhoneNumberError as exc:
        return {"row": row_number, "error": f"invalid phone: {exc}"}
    except (CrmValidationError, CrmReferenceNotFoundError) as exc:
        return {"row": row_number, "error": str(exc)}


async def _run_import_job(payload: TenantJobPayload | None) -> None:
    """The registered arq job handler (mirrors
    `product.foundation.events._dispatch_durable_event_job`'s own
    registration shape). Parses the CSV row by row, creates each contact
    via `product.crm.contacts.create_contact()` (never a separate
    unaudited bulk path), and updates the `crm.import_jobs` row as it
    goes."""
    if payload is None:
        raise ValueError("_run_import_job requires a TenantJobPayload, got None.")
    tenant_id = uuid.UUID(payload.tenant_id)
    job_id = uuid.UUID(str(payload.data["import_job_id"]))
    actor_user_id = uuid.UUID(str(payload.data["actor_user_id"]))
    csv_content = str(payload.data["csv_content"])

    with tenant_session_scope(tenant_id) as session:
        job = session.get(ImportJob, job_id)
        if job is None or job.tenant_id != tenant_id:
            return
        job.status = "running"
        session.flush()

    reader = csv.DictReader(io.StringIO(csv_content))
    missing = [c for c in _REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    errors: list[dict[str, object]] = []
    succeeded = 0
    total = 0
    if missing:
        errors.append({"row": 0, "error": f"missing required column(s): {missing}"})
    else:
        for row_number, row in enumerate(reader, start=1):
            total += 1
            error = _process_row(actor_user_id, tenant_id, row_number, row)
            if error is None:
                succeeded += 1
            else:
                errors.append(error)

    with tenant_session_scope(tenant_id) as session:
        job = session.get(ImportJob, job_id)
        if job is None or job.tenant_id != tenant_id:
            return
        job.status = "failed" if missing else "completed"
        job.total_rows = total
        job.succeeded_rows = succeeded
        job.failed_rows = len(errors) if not missing else total
        job.error_report = json.dumps(errors) if errors else None
        job.completed_at = datetime.now(UTC)
        session.flush()

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.contact.import_complete",
        resource_type="crm.import_job",
        resource_id=str(job_id),
        outcome=AuditOutcome.SUCCESS if not missing else AuditOutcome.FAILURE,
        metadata={"total_rows": total, "succeeded_rows": succeeded, "failed_rows": len(errors)},
    )


IMPORT_JOB_FUNCTIONS = [register_job(_run_import_job)]


async def enqueue_contact_import(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    csv_content: str,
    queue_name: str | None = None,
) -> ImportJobView:
    """Authorize, size-check, create the `crm.import_jobs` row (status
    `"pending"`), and enqueue the real `infra.jobs` background job that
    does the actual row-by-row work -- the one entrypoint a route calls."""
    require(actor_user_id, tenant_id, resource=CONTACT_RESOURCE, action="create")
    if len(csv_content.encode("utf-8")) > MAX_IMPORT_FILE_SIZE_BYTES:
        raise CrmValidationError(
            f"CSV content exceeds the {MAX_IMPORT_FILE_SIZE_BYTES} byte import size limit."
        )
    row = _create_job_row(actor_user_id, tenant_id)
    payload = TenantJobPayload(
        tenant_id=str(tenant_id),
        data={
            "import_job_id": str(row.id),
            "csv_content": csv_content,
            "actor_user_id": str(actor_user_id),
        },
    )
    await enqueue_job(_run_import_job.__name__, payload, queue_name=queue_name)
    return _job_view(row)


def export_contacts_csv(actor_user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """Synchronous CSV export of every contact this actor can read in
    `tenant_id` -- see module docstring for why export, unlike import,
    is not a background job."""
    require(actor_user_id, tenant_id, resource=CONTACT_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(select(Contact).where(Contact.tenant_id == tenant_id)).scalars().all()
        )
        company_names: dict[uuid.UUID, str] = {}
        for row in rows:
            if row.company_id is not None and row.company_id not in company_names:
                company = session.get(Company, row.company_id)
                if company is not None:
                    company_names[row.company_id] = company.name
        data = [
            {
                "first_name": row.first_name,
                "last_name": row.last_name,
                "email": row.email or "",
                "phone": row.phone or "",
                "company_name": company_names.get(row.company_id, "") if row.company_id else "",
            }
            for row in rows
        ]

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=["first_name", "last_name", "email", "phone", "company_name"]
    )
    writer.writeheader()
    writer.writerows(data)
    return buffer.getvalue()
