"""Marketing: campaigns (email/SMS), audience segmentation, suppression
list, background bulk send (docs/ROADMAP.md Phase 6.1-6.2).

**Tenancy**: the client tenant, same as CRM/Conversations -- see
`product/marketing/models.py`'s own module docstring.

**The one product module permitted to depend on another**:
`product/marketing/segmentation.py` imports `product.crm.contacts` (CRM's
own published, read-oriented service function) for audience segmentation
-- see `docs/ADR/0005-marketing-depends-on-crm.md` for the full decision.
Every other cross-module need (role-permission granting) goes through the
`agency.role_provisioned` event dispatcher, unchanged from the
`product.crm`/`product.conversations` precedent -- `product.marketing`
never imports `product.agency`, `product.conversations`, or any other
product module.

Phase 6.2 (SMS campaigns) and the SMS half of channel support are
deliberately **PARTIAL** -- see `product/marketing/sms.py`'s own module
docstring for exactly what is and is not built, and why.
"""
