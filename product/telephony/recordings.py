"""Call recording metadata + retention (docs/ROADMAP.md Phase 8.3).

**Service-layer only -- no route exposes any function here** (see
`product/telephony/__init__.py`'s own module docstring): Phase 8.3's own
roadmap Checkpoint requires "dedicated security review before recordings
are enabled for any real tenant," and this pass's own `TelephonyProvider`
never actually produces a real recording (no vendor selected). This module
still ships a complete, real, tested implementation -- storage via
`product.foundation.storage.ObjectStorage` (Protocol + Fake, identical
"no real vendor" treatment), retention-window purge that actually deletes
both the object and its metadata row, not just hides it.

**`telephony.call_recording` is its own, separate RBAC resource** -- never
implied by `telephony.call:read` (`product/telephony/permissions.py`'s own
docstring: "who can listen to a recording is an RBAC permission, not
implicit from general call-history access").

**Retention is mandatory, not optional** -- every stored recording carries
a `retention_expires_at`; `purge_expired_recordings()` is the enforcement
mechanism (this phase's own explicit requirement: "a recording past its
retention window is actually deleted, not just hidden"). No scheduled/
cron mechanism calls it automatically -- the identical, disclosed SaaS-OS
capability gap `product/appointments/reminders.py`'s own module docstring
already documents (no deferred-job scheduling, no tenant-enumeration
primitive) applies unchanged here; this is a real, correct, on-demand,
per-tenant sweep, not a global cron loop pretending to be one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.foundation.storage import ObjectStorage, tenant_scoped_key
from product.telephony.errors import TelephonyReferenceNotFoundError
from product.telephony.models import Call, CallRecording
from product.telephony.permissions import CALL_RECORDING_RESOURCE, require


@dataclass(frozen=True, slots=True)
class CallRecordingView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    call_id: uuid.UUID
    storage_key: str
    duration_seconds: int | None
    retention_expires_at: datetime
    created_at: datetime


def _to_view(row: CallRecording) -> CallRecordingView:
    return CallRecordingView(
        id=row.id,
        tenant_id=row.tenant_id,
        call_id=row.call_id,
        storage_key=row.storage_key,
        duration_seconds=row.duration_seconds,
        retention_expires_at=row.retention_expires_at,
        created_at=row.created_at,
    )


def store_call_recording(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    call_id: uuid.UUID,
    *,
    data: bytes,
    duration_seconds: int | None,
    retention_expires_at: datetime,
    storage: ObjectStorage,
) -> CallRecordingView:
    require(actor_user_id, tenant_id, resource=CALL_RECORDING_RESOURCE, action="create")
    with tenant_session_scope(tenant_id) as session:
        call = session.get(Call, call_id)
        if call is None or call.tenant_id != tenant_id:
            raise TelephonyReferenceNotFoundError("call", call_id)

        recording_id = uuid.uuid4()
        storage_key = tenant_scoped_key(
            tenant_id, "telephony", "recordings", str(call_id), f"{recording_id}.audio"
        )
        storage.put_object(storage_key, data)

        row = CallRecording(
            id=recording_id,
            tenant_id=tenant_id,
            call_id=call_id,
            storage_key=storage_key,
            duration_seconds=duration_seconds,
            retention_expires_at=retention_expires_at,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="telephony.call_recording.store",
        resource_type="telephony.call_recording",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        # Identifiers/duration only -- never the recording bytes, storage
        # key, or any transcript, per this phase's own PII/audit
        # discipline.
        metadata={"call_id": str(call_id)},
    )
    return _to_view(row)


def get_call_recording(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    recording_id: uuid.UUID,
    *,
    storage: ObjectStorage,
) -> tuple[CallRecordingView, bytes]:
    require(actor_user_id, tenant_id, resource=CALL_RECORDING_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(CallRecording, recording_id)
        if row is None or row.tenant_id != tenant_id:
            raise TelephonyReferenceNotFoundError("call_recording", recording_id)
        session.expunge(row)
    data = storage.get_object(row.storage_key)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="telephony.call_recording.access",
        resource_type="telephony.call_recording",
        resource_id=str(recording_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"call_id": str(row.call_id)},
    )
    return _to_view(row), data


def purge_expired_recordings(tenant_id: uuid.UUID, *, storage: ObjectStorage, now: datetime) -> int:
    """Deletes every `CallRecording` (object + metadata row) whose
    `retention_expires_at` is at/before `now` -- real deletion, never a
    soft "hidden" flag, per this phase's own explicit retention-enforcement
    requirement. Returns the number of recordings purged. System-actor
    audited (mirrors `product/appointments/reminders.py::send_due_reminders()`'s
    own per-tenant sweep shape); no `actor_user_id`/permission check --
    this is a maintenance sweep, not a user-initiated read/write."""
    with tenant_session_scope(tenant_id) as session:
        expired = (
            session.execute(
                select(CallRecording).where(
                    CallRecording.tenant_id == tenant_id,
                    CallRecording.retention_expires_at <= now,
                )
            )
            .scalars()
            .all()
        )
        purged_ids: list[uuid.UUID] = []
        for row in expired:
            storage.delete_object(row.storage_key)
            purged_ids.append(row.id)
            session.delete(row)
        session.flush()

    if purged_ids:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.SYSTEM,
            action="telephony.call_recording.purge_expired",
            resource_type="telephony.call_recording",
            resource_id=str(tenant_id),
            outcome=AuditOutcome.SUCCESS,
            metadata={"purged_count": len(purged_ids)},
        )
    return len(purged_ids)


__all__ = [
    "CallRecordingView",
    "get_call_recording",
    "purge_expired_recordings",
    "store_call_recording",
]
