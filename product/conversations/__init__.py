"""Unified conversation inbox (docs/ROADMAP.md Phase 5): channel-agnostic
threads/messages (`conversations.threads`/`conversations.messages`),
linked to a `crm.contacts` row (the client tenant's own CRM data --
tenancy mirrors `product/crm/` exactly, see `product/conversations
/models.py`'s own module docstring), assignment, internal notes, and
reusable message templates (5.5). Outbound email sends through
`core.email` directly (`product/conversations/email_sending.py`'s own
docstring explains why not `core.notifications`). SMS/WhatsApp (5.3/5.4)
ship as provider-neutral interfaces only, explicitly PARTIAL pending a
vendor decision this product has not been authorized to make -- see
`product/conversations/sms.py`/`whatsapp.py`.
"""
