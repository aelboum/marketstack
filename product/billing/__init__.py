"""Agency-sells-to-client entitlement mapping and reseller plan/pricing
UI, built over the installed saas-os core.billing (this platform's own
SaaS revenue mechanism -- Plan/Subscription/Invoice/Payment there is
never confused with product.accounting's tenant-own-customer invoicing;
see docs/ACCOUNTING-SCOPE.md, "The One Mistake to Avoid").

docs/ROADMAP.md Phase 13. `product.billing` MAY NOT depend on any other
product module (it never needed one -- unlike `product.reputation`'s
narrow `product.crm` edge, `docs/ADR/0010-...`, resale/subscription
operations only ever need `core.billing`/`core.tenancy`, both always-
allowed SaaS-OS dependencies); no other product module may depend on
`product.billing` either. See `docs/ADR/0012
-resale-billing-ownership-model.md` for the full commercial-ownership
model (plan owner / subscription owner / entitlement recipient) and the
SaaS-OS boundary this module observes.

**This module's router (`product/billing/routes.py::router`), purge
participant (`product/billing/purge.py::register`), and event-handler
module (`product/billing/event_handlers.py`, whose
`agency.role_provisioned` subscription only takes effect once imported)
are NOT wired into `product/api/main.py`** -- identical situation to
`product/reputation/__init__.py`'s own module docstring:
`product/api/main.py` was an explicitly protected, pre-existing
uncommitted local change (an unrelated dev-auth-bypass addition) that this
phase's own instructions required to remain untouched. The exact
follow-up diff:

    from product.billing import event_handlers as _billing_event_handlers  # noqa: F401
    from product.billing.purge import register as register_billing_purge_participant
    from product.billing.routes import router as billing_router
    ...
    app.include_router(billing_router)
    ...
    register_billing_purge_participant()

Until that follow-up lands, this module's service functions
(`product/billing/resale_plans.py`, `product/billing/subscriptions.py`)
are fully functional and tested directly, but: the HTTP API is not
reachable through the running application, `billing.resale_plans` rows
are not purged when a tenant is deleted, and the `owner`/`member`
permission grants in `event_handlers.py` are not automatically
provisioned for a newly-created role.
"""
