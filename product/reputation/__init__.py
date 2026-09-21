"""Reputation management: review requests, tracking, responses,
review-related automation hooks (docs/ROADMAP.md Phase 12). Product-specific;
review-platform integrations (Google Business Profile, etc.) stay
adapter-isolated in `product/reputation/providers.py`, deliberately
deferred -- see that module's own docstring.

`product.reputation` MAY depend on `product.crm` (one narrow,
one-directional read, `docs/ADR/0010-reputation-depends-on-crm.md`) --
never any other product module, and no other product module may depend on
`product.reputation`.

**This module's router (`product/reputation/routes.py::router`), purge
participant (`product/reputation/purge.py::register`), and event-handler
module (`product/reputation/event_handlers.py`, whose
`agency.role_provisioned` subscription only takes effect once imported)
are NOT wired into `product/api/main.py`** -- every other module's
identical wiring lives there (router `include_router()`, purge-participant
`register()` call, and a `from product.<module> import event_handlers as
_..._event_handlers  # noqa: F401` import), but `product/api/main.py` was
an explicitly protected, pre-existing uncommitted local change for this
phase (an unrelated dev-auth-bypass addition) that this phase's own
instructions required to remain untouched. See this phase's own
implementation/audit report for the exact three-line diff a follow-up
change must apply to `product/api/main.py` to complete this wiring:

    from product.reputation import event_handlers as _reputation_event_handlers  # noqa: F401
    from product.reputation.purge import register as register_reputation_purge_participant
    from product.reputation.routes import router as reputation_router
    ...
    app.include_router(reputation_router)
    ...
    register_reputation_purge_participant()

Until that follow-up lands, this module's service functions
(`product/reputation/review_requests.py`, `product/reputation/reviews.py`,
`product/reputation/responses.py`) are fully functional and tested
directly (as every other module's own service-layer test suite already
does), but: the HTTP API is not reachable through the running application,
`reputation.*` rows are not purged when a tenant is deleted, and the
`owner`/`member` permission grants in `event_handlers.py` are not
automatically provisioned for a newly-created role.
"""
