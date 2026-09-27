from __future__ import annotations

import time

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
