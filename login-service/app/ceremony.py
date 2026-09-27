"""Login-ceremony state: this service's own authentication-in-progress
state, entirely separate from SaaS-OS's `product_session`/
`product_session_login` cookies (never imported, never reused -- ADR-0017).

Follows the same *quality bar* as SaaS-OS's own login-transaction design
(single-use, server-side-bound, short-lived, cookie carries only an opaque
id) without importing any SaaS-OS code -- this is an independent
implementation living in a separate process/container.

Storage: in-memory, per-process. This is the honest limitation of this
implementation: a login-service deployment with more than one replica, or
one that restarts mid-ceremony, needs a shared store (e.g. Redis) instead
of this dict -- not built here (this service has no such dependency yet,
and adding one is a real infrastructure decision, not a default). Local/
single-instance development and a single-container production deployment
are both correctly served by this as-is.

The `session_token` ZITADEL returns from CreateSession/SetSession is a
bearer-equivalent credential for that authentication attempt -- it is
kept ONLY in this server-side store, never sent to the browser in any
form (not a cookie, not a hidden form field, not a response body).
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from dataclasses import dataclass

CEREMONY_COOKIE_NAME = "login_svc_ceremony"
CEREMONY_COOKIE_PATH = "/login-svc"
CEREMONY_TTL_SECONDS = 10 * 60  # matches SaaS-OS's own login-transaction lifetime
# Security audit F-09: a hard cap on the in-memory ceremony store,
# independent of TTL-based expiry -- bounds worst-case memory use under a
# sustained flood of ceremony creation followed by inactivity (expiry
# cleanup alone only reclaims space once CEREMONY_TTL_SECONDS has
# elapsed). Each ceremony is a handful of short strings/floats, so even
# this many resident at once is a trivial amount of memory for a login
# service; conservative rather than tuned to any measured load.
CEREMONY_STORE_MAX_SIZE = 10_000


@dataclass
class Ceremony:
    ceremony_id: str
    auth_request_id: str
    csrf_token: str
    created_at: float
    expires_at: float
    consumed: bool = False
    # Populated once CreateSession succeeds; never leaves this process.
    session_id: str | None = None
    session_token: str | None = None
    user_id: str | None = None
    login_name: str | None = None
    # The single next factor this ceremony is currently waiting on, if any
    # (e.g. "TOTP", "U2F") -- set by the route that just requested it,
    # checked by the route that receives the corresponding submission so a
    # POST to the wrong step is rejected rather than silently accepted.
    pending_factor: str | None = None


class CeremonyStore:
    """Thread-safe in-memory store. A background thread is not started
    automatically -- `purge_expired()` is called opportunistically on
    every access, which is sufficient at this service's expected request
    volume (a login ceremony, not a high-throughput API)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ceremonies: dict[str, Ceremony] = {}

    def _purge_expired_locked(self, now: float) -> None:
        expired = [cid for cid, c in self._ceremonies.items() if c.expires_at <= now or c.consumed]
        for cid in expired:
            del self._ceremonies[cid]

    def _evict_oldest_until_under_max_locked(self) -> None:
        """FIFO eviction by creation order -- relies on `dict` preserving
        insertion order (never reordered by `get()`/`update()`), so the
        first key is always the oldest surviving ceremony. Only ever
        called before the new ceremony is inserted, so it can never evict
        the one currently being created (security audit F-09)."""
        while len(self._ceremonies) >= CEREMONY_STORE_MAX_SIZE:
            oldest_id = next(iter(self._ceremonies))
            del self._ceremonies[oldest_id]

    def start(self, auth_request_id: str) -> Ceremony:
        now = time.time()
        ceremony = Ceremony(
            ceremony_id=secrets.token_urlsafe(32),
            auth_request_id=auth_request_id,
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + CEREMONY_TTL_SECONDS,
        )
        with self._lock:
            self._purge_expired_locked(now)
            self._evict_oldest_until_under_max_locked()
            self._ceremonies[ceremony.ceremony_id] = ceremony
        return ceremony

    def get(self, ceremony_id: str) -> Ceremony | None:
        now = time.time()
        with self._lock:
            self._purge_expired_locked(now)
            ceremony = self._ceremonies.get(ceremony_id)
            if ceremony is None or ceremony.consumed or ceremony.expires_at <= now:
                return None
            return ceremony

    def update(self, ceremony_id: str, **fields: object) -> Ceremony | None:
        with self._lock:
            ceremony = self._ceremonies.get(ceremony_id)
            if ceremony is None:
                return None
            for key, value in fields.items():
                setattr(ceremony, key, value)
            return ceremony

    def consume(self, ceremony_id: str) -> None:
        """Single-use: once called, `get()` never returns this ceremony
        again, even before its natural expiry -- a replayed callback
        attempt (the browser re-submitting the same step, or an attacker
        replaying a captured request) finds nothing to act on."""
        with self._lock:
            ceremony = self._ceremonies.get(ceremony_id)
            if ceremony is not None:
                ceremony.consumed = True

    def verify_csrf(self, ceremony: Ceremony, submitted_token: str | None) -> bool:
        if not submitted_token:
            return False
        return hmac.compare_digest(ceremony.csrf_token, submitted_token)


# Process-wide singleton -- this service's entire authentication state.
store = CeremonyStore()
