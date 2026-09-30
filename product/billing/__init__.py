"""Agency-sells-to-client entitlement mapping and reseller plan/pricing
UI, built over the installed saas-os core.billing (this platform's own
SaaS revenue mechanism -- Plan/Subscription/Invoice/Payment there is
never confused with product.accounting's tenant-own-customer invoicing;
see docs/ACCOUNTING-SCOPE.md, "The One Mistake to Avoid").

docs/ROADMAP.md Phase 13. `product.billing` MAY NOT depend on any other
product module (it never needed one -- unlike `product.reputation`'s
narrow `product.crm` edge, `docs/ADR/0010-...`, resale/subscription
operations only ever need `core.billing`/`core.tenancy`/`core.usage`, all
always-allowed SaaS-OS dependencies); no other product module may depend
on `product.billing` either. See `docs/ADR/0012
-resale-billing-ownership-model.md` for the full commercial-ownership
model (plan owner / subscription owner / entitlement recipient) and the
SaaS-OS boundary this module observes. `core.usage` joined this module's
dependency set for the SaaS entitlement-enforcement follow-up
(`product/billing/resale_plans.py::create_resale_plan()`'s own module
docstring) -- `core.billing.require_entitlement()`/`core.usage
.consume_quota()`, both already-built, already-tested SaaS-OS mechanisms
no product code called before that follow-up.

**This module's router (`product/billing/routes.py::router`), purge
participant (`product/billing/purge.py::register`), and event-handler
module (`product/billing/event_handlers.py`, whose
`agency.role_provisioned` subscription takes effect once imported) are
wired into `product/api/main.py`** (docs/ROADMAP.md Phase 13 API
exposure follow-up) -- the exact diff this module's own docstring
previously described as pending:

    from product.billing import event_handlers as _billing_event_handlers  # noqa: F401
    from product.billing.purge import register as register_billing_purge_participant
    from product.billing.routes import router as billing_router
    ...
    app.include_router(billing_router)
    ...
    register_billing_purge_participant()

`product/reputation/__init__.py` documents the identical, still-pending
gap for its own router/purge/event-handler wiring -- unrelated to and
unchanged by this follow-up, which touches `product.billing`'s own
wiring only.
"""
