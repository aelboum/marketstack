"""Marketing: campaigns (email/SMS), audience segmentation, suppression
list, background bulk send (docs/ROADMAP.md Phase 6.1-6.2).

**Tenancy**: the client tenant, same as CRM/Conversations -- see
`product/marketing/models.py`'s own module docstring.

**One of two product modules permitted to depend on another** (the other
being `product.appointments`, added in Phase 7 -- see
`docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`'s own
extension):
`product/marketing/segmentation.py` imports `product.crm.contacts` (CRM's
own published, read-oriented service function) for audience segmentation
-- see `docs/ADR/0005-marketing-and-appointments-depend-on-crm.md` for the
full decision. Marketing and Appointments each depend on CRM
independently and never on each other.
Every other cross-module need (role-permission granting) goes through the
`agency.role_provisioned` event dispatcher, unchanged from the
`product.crm`/`product.conversations` precedent -- `product.marketing`
never imports `product.agency`, `product.conversations`, or any other
product module.

Phase 6.2 (SMS campaigns) and the SMS half of channel support are
deliberately **PARTIAL** -- see `product/marketing/sms.py`'s own module
docstring for exactly what is and is not built, and why.
"""
