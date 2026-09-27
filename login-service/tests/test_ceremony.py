from __future__ import annotations

import time

from app import ceremony as ceremony_module
from app.ceremony import CeremonyStore


def test_start_creates_unconsumed_unexpired_ceremony():
    store = CeremonyStore()
    ceremony = store.start("V2_abc")
    assert store.get(ceremony.ceremony_id) is not None
    assert ceremony.auth_request_id == "V2_abc"
    assert ceremony.csrf_token


def test_unknown_ceremony_id_returns_none():
    store = CeremonyStore()
    assert store.get("does-not-exist") is None


def test_expired_ceremony_is_not_returned():
    store = CeremonyStore()
    ceremony = store.start("V2_abc")
    ceremony.expires_at = time.time() - 1
    assert store.get(ceremony.ceremony_id) is None


def test_consume_makes_ceremony_unusable_single_use():
    store = CeremonyStore()
    ceremony = store.start("V2_abc")
    store.consume(ceremony.ceremony_id)
    assert store.get(ceremony.ceremony_id) is None


def test_replayed_get_after_consume_still_none():
    store = CeremonyStore()
    ceremony = store.start("V2_abc")
    store.consume(ceremony.ceremony_id)
    # Simulate a replay attempt hitting the store again.
    assert store.get(ceremony.ceremony_id) is None
    assert store.get(ceremony.ceremony_id) is None


def test_update_mutates_stored_fields():
    store = CeremonyStore()
    ceremony = store.start("V2_abc")
    store.update(ceremony.ceremony_id, session_id="sid", session_token="tok")
    updated = store.get(ceremony.ceremony_id)
    assert updated is not None
    assert updated.session_id == "sid"
    assert updated.session_token == "tok"


def test_verify_csrf_matches_only_exact_token():
    store = CeremonyStore()
    ceremony = store.start("V2_abc")
    assert store.verify_csrf(ceremony, ceremony.csrf_token) is True
    assert store.verify_csrf(ceremony, "wrong-token") is False
    assert store.verify_csrf(ceremony, None) is False


# --- F-09: bounded ceremony store --------------------------------------------


def test_store_holds_ceremonies_up_to_the_configured_maximum(monkeypatch):
    monkeypatch.setattr(ceremony_module, "CEREMONY_STORE_MAX_SIZE", 3)
    store = CeremonyStore()
    created = [store.start(f"V2_{i}") for i in range(3)]
    for ceremony in created:
        assert store.get(ceremony.ceremony_id) is not None
    assert len(store._ceremonies) == 3


def test_adding_beyond_the_maximum_evicts_the_oldest_entry(monkeypatch):
    monkeypatch.setattr(ceremony_module, "CEREMONY_STORE_MAX_SIZE", 3)
    store = CeremonyStore()
    first, second, third = (store.start(f"V2_{i}") for i in range(3))

    # Exceeds the configured max of 3 -- the oldest (`first`) must be evicted.
    fourth = store.start("V2_3")

    assert store.get(first.ceremony_id) is None
    assert store.get(second.ceremony_id) is not None
    assert store.get(third.ceremony_id) is not None
    assert store.get(fourth.ceremony_id) is not None
    assert len(store._ceremonies) == 3


def test_newest_ceremony_is_never_evicted_even_at_capacity(monkeypatch):
    monkeypatch.setattr(ceremony_module, "CEREMONY_STORE_MAX_SIZE", 1)
    store = CeremonyStore()
    first = store.start("V2_first")
    second = store.start("V2_second")

    assert store.get(first.ceremony_id) is None
    # The just-created ceremony is always retrievable, never the one
    # evicted to make room for itself.
    assert store.get(second.ceremony_id) is not None
    assert len(store._ceremonies) == 1


def test_expiry_cleanup_still_works_alongside_the_size_bound(monkeypatch):
    monkeypatch.setattr(ceremony_module, "CEREMONY_STORE_MAX_SIZE", 10)
    store = CeremonyStore()
    stale = store.start("V2_stale")
    stale.expires_at = time.time() - 1

    fresh = store.start("V2_fresh")

    # Expired-but-not-yet-evicted entries are purged on the next access,
    # independent of the size bound.
    assert store.get(stale.ceremony_id) is None
    assert store.get(fresh.ceremony_id) is not None
    assert stale.ceremony_id not in store._ceremonies


def test_consume_single_use_semantics_unaffected_by_size_bound(monkeypatch):
    monkeypatch.setattr(ceremony_module, "CEREMONY_STORE_MAX_SIZE", 10)
    store = CeremonyStore()
    ceremony = store.start("V2_abc")
    store.consume(ceremony.ceremony_id)
    assert store.get(ceremony.ceremony_id) is None
    # A second consume() call, and a second get(), have no further effect.
    store.consume(ceremony.ceremony_id)
    assert store.get(ceremony.ceremony_id) is None
