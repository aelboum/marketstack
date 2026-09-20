"""Object/file storage abstraction (docs/ROADMAP.md Phase 8.3;
`docs/RESPONSIBILITY-MATRIX.md` "Object/file storage" row).

**Why this lives here, not in `saas-os`**: confirmed by direct inspection
-- no `infra/storage` module exists in `saas-os` today, no boto3/S3/MinIO
dependency anywhere in it. This is domain-agnostic plumbing (a
tenant-namespaced object store) the Responsibility Matrix already flags as
"a strong future Category B candidate" -- built here, in
`product/foundation/`, as a thin `Protocol` over an S3-compatible backend,
kept narrow enough to propose upstream later. `product/telephony
/recordings.py` (Phase 8.3) is this Protocol's first real consumer.

**Provider-neutral, mirrors `core/email/provider.py::EmailProvider`'s
exact shape** -- a `@runtime_checkable Protocol`, one real in-memory
`FakeObjectStorage` implementation of it. `docs/RISKS-AND-OPEN-QUESTIONS.md`
item 6 does not name an object-storage vendor at all (only SMS/WhatsApp/
telephony/calendar-sync are listed as still-open provider decisions), but
the same underlying problem applies transitively: no S3-compatible
account/bucket/credentials exist in this environment to configure a real
adapter against, and `docs/INTEGRATIONS.md`'s own credential-handling
section requires every adapter's credentials to flow through
`infra.secrets`, never be hardcoded. Per this phase's own explicit
instruction (implement the provider boundary; use a Fake for deterministic
tests; document the limitation; never fabricate production-looking fake
success), only the Protocol + Fake are built here -- no concrete
`S3ObjectStorage` adapter, no boto3 dependency added, mirroring
`product/appointments/calendar_sync.py`'s identical "interface + fake
only" precedent exactly.

**Tenant-namespaced keys are this module's one real invariant**:
`tenant_scoped_key()` is the only sanctioned way to build a storage key --
every key is prefixed `{tenant_id}/...`, the same isolation pattern
`saas-os` `docs/MULTI-TENANCY.md` section 4 documents conceptually for
storage paths/buckets namespaced by tenant_id. No caller constructs a raw
key string by hand.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class ObjectStorageError(RuntimeError):
    """Raised by an `ObjectStorage` implementation on failure -- mirrors
    `core.email.errors.EmailProviderError`'s own normalized-error
    discipline (never a raw transport/SDK exception)."""


class ObjectNotFoundError(ObjectStorageError):
    """Raised by `get_object()`/`delete_object()` for a key that does not
    exist. Deliberately a subclass of `ObjectStorageError`, not a bare
    `KeyError` -- callers catch storage failures uniformly."""


def tenant_scoped_key(tenant_id: uuid.UUID, *parts: str) -> str:
    """The one sanctioned way to build a storage key -- always
    `{tenant_id}/{parts...}`, joined with `/`. `parts` must be non-empty,
    plain path segments (no leading/trailing slash, no `..`) -- this is a
    narrow builder, not a general path-sanitization utility; callers pass
    already-known-safe identifiers (a UUID, a fixed literal), never
    caller-supplied strings."""
    if not parts:
        raise ValueError("tenant_scoped_key() requires at least one part.")
    for part in parts:
        if not part or part in (".", "..") or "/" in part:
            raise ValueError(f"invalid storage key part: {part!r}")
    return "/".join((str(tenant_id), *parts))


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int


@runtime_checkable
class ObjectStorage(Protocol):
    def put_object(self, key: str, data: bytes) -> StoredObject: ...

    def get_object(self, key: str) -> bytes: ...

    def delete_object(self, key: str) -> None: ...


@dataclass
class FakeObjectStorage:
    """An in-memory `ObjectStorage` -- no network access, no credentials.
    Mirrors `core.email.provider.FakeEmailProvider`'s identical role: a
    real, genuine implementation any test can run against, not a mock
    bolted onto internals."""

    fail: bool = False
    _objects: dict[str, bytes] = field(default_factory=dict)

    def put_object(self, key: str, data: bytes) -> StoredObject:
        if self.fail:
            raise ObjectStorageError("FakeObjectStorage configured to fail")
        self._objects[key] = data
        return StoredObject(key=key, size_bytes=len(data))

    def get_object(self, key: str) -> bytes:
        if self.fail:
            raise ObjectStorageError("FakeObjectStorage configured to fail")
        try:
            return self._objects[key]
        except KeyError:
            raise ObjectNotFoundError(f"no object stored at key {key!r}") from None

    def delete_object(self, key: str) -> None:
        if self.fail:
            raise ObjectStorageError("FakeObjectStorage configured to fail")
        try:
            del self._objects[key]
        except KeyError:
            raise ObjectNotFoundError(f"no object stored at key {key!r}") from None


__all__ = [
    "ObjectStorage",
    "ObjectStorageError",
    "ObjectNotFoundError",
    "StoredObject",
    "FakeObjectStorage",
    "tenant_scoped_key",
]
