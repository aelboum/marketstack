"""Snapshot capture/apply: cloning supported tenant configuration
(docs/ROADMAP.md Phase 14). Product-specific; the mechanism reuses the
installed saas-os `infra.db`'s ordinary tenant-scoped write path.

Implements the single domain concept the roadmap actually defines --
**snapshot** (a named, immutable bundle of one tenant's configuration,
appliable to another) -- not a separate, independently-versioned
"Template" catalog; see `docs/ADR/0013
-templates-snapshot-scope-and-crm-dependency.md`. Only CRM
pipelines/stages are implemented as the exportable/appliable
configuration domain in this phase (the same ADR's own "Decision 1"
inventory table); every other domain the roadmap names (Marketing forms/
templates, Appointments calendars, Automation workflows, Websites pages)
is deferred, documented, not silently omitted.

`product.templates` MAY depend on `product.crm` (one narrow,
one-directional read/write, via `product.crm.pipelines`'s own published
functions only) -- never any other product module; no other product
module may depend on `product.templates`.

**This module's router (`product/templates/routes.py::router`), purge
participant (`product/templates/purge.py::register`), and event-handler
module (`product/templates/event_handlers.py`, whose
`agency.role_provisioned` subscription only takes effect once imported)
are NOT wired into `product/api/main.py`** -- identical situation to
`product/reputation/__init__.py`'s/`product/billing/__init__.py`'s own
module docstrings: `product/api/main.py` was an explicitly protected,
pre-existing uncommitted local change (an unrelated dev-auth-bypass
addition) that this phase's own instructions required to remain
untouched. The exact follow-up diff:

    from product.templates import event_handlers as _templates_event_handlers  # noqa: F401
    from product.templates.purge import register as register_templates_purge_participant
    from product.templates.routes import router as templates_router
    ...
    app.include_router(templates_router)
    ...
    register_templates_purge_participant()

Until that follow-up lands, this module's service functions
(`product/templates/snapshots.py`) are fully functional and tested
directly, but: the HTTP API is not reachable through the running
application, `templates.snapshots` rows are not purged when a tenant is
deleted, and the `owner`/`member` permission grants in
`event_handlers.py` are not automatically provisioned for a newly-created
role.
"""
