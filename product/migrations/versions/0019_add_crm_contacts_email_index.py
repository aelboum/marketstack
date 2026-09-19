"""add index on crm.contacts.email

Revision ID: 0019_crm_contacts_email_index
Revises: 0018_marketing_recipients
Create Date: 2026-09-21 00:00:05.000000

docs/ROADMAP.md Phase 6.3: `product/crm/contacts.py
::create_or_update_contact_from_trusted_source()` (added in this same
phase, for the public form-submission use case) does a lookup-by-email
that is now a real, repeated query path -- not just an occasional one --
so an index is added here. Deliberately does NOT add a uniqueness
constraint on `email`: a tenant may legitimately hold more than one
contact sharing an email address (e.g. a shared household/team inbox),
and the roadmap does not require enforcing otherwise.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_crm_contacts_email_index"
down_revision: str | Sequence[str] | None = "0018_marketing_recipients"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_crm_contacts_email", "contacts", ["email"], schema="crm")


def downgrade() -> None:
    op.drop_index("ix_crm_contacts_email", table_name="contacts", schema="crm")
