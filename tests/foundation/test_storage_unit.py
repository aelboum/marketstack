"""`FakeObjectStorage`/`tenant_scoped_key()` (docs/ROADMAP.md Phase 8.3,
`product/foundation/storage.py`). No database, no network -- a plain unit
test, part of the default `pytest` run.
"""

from __future__ import annotations

import uuid

import pytest
from product.foundation.storage import (
    FakeObjectStorage,
    ObjectNotFoundError,
    ObjectStorage,
    ObjectStorageError,
    tenant_scoped_key,
)


def test_fake_object_storage_satisfies_the_protocol() -> None:
    assert isinstance(FakeObjectStorage(), ObjectStorage)


def test_put_get_delete_round_trip() -> None:
    storage = FakeObjectStorage()
    stored = storage.put_object("k1", b"hello")
    assert stored.key == "k1"
    assert stored.size_bytes == 5
    assert storage.get_object("k1") == b"hello"
    storage.delete_object("k1")
    with pytest.raises(ObjectNotFoundError):
        storage.get_object("k1")


def test_get_unknown_key_raises_not_found() -> None:
    storage = FakeObjectStorage()
    with pytest.raises(ObjectNotFoundError):
        storage.get_object("does-not-exist")


def test_delete_unknown_key_raises_not_found() -> None:
    storage = FakeObjectStorage()
    with pytest.raises(ObjectNotFoundError):
        storage.delete_object("does-not-exist")


def test_configured_to_fail_raises_on_every_operation() -> None:
    storage = FakeObjectStorage(fail=True)
    with pytest.raises(ObjectStorageError):
        storage.put_object("k1", b"data")


def test_tenant_scoped_key_prefixes_with_tenant_id() -> None:
    tenant_id = uuid.uuid4()
    key = tenant_scoped_key(tenant_id, "telephony", "recordings", "abc.audio")
    assert key == f"{tenant_id}/telephony/recordings/abc.audio"


def test_tenant_scoped_key_rejects_empty_parts() -> None:
    with pytest.raises(ValueError):
        tenant_scoped_key(uuid.uuid4())


def test_tenant_scoped_key_rejects_path_traversal_part() -> None:
    with pytest.raises(ValueError):
        tenant_scoped_key(uuid.uuid4(), "..")


def test_tenant_scoped_key_rejects_part_containing_slash() -> None:
    with pytest.raises(ValueError):
        tenant_scoped_key(uuid.uuid4(), "a/b")
