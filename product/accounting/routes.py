"""The minimal Accounting API (docs/ROADMAP.md Phase 25), mounted under
`/v1/accounting` in `product/api/main.py`.

**Scope discipline**: exactly one route -- a tenant's overdue customer
invoices -- the one real accounting condition the Phase 25 Definition of
Done requires a real Command Center consumer for
(`frontend/components/today/AttentionSection.tsx`'s own
`OverdueInvoicesLine`). No other Phase 25 read/write surface is exposed
over HTTP this phase; every other accounting operation (creating tax
codes, posting invoices/bills, recording payments, allocating) is
service-layer-only, mirroring `product/accounting/journal.py`'s own
"no routes at all" precedent from Phase 24 -- this module is the single,
deliberate, minimal exception, not a reopening of that precedent.

**Ingress dependency choice / non-enumeration**: identical reasoning to
`product/approvals/routes.py`'s own module docstring -- every route uses
`api.dependencies.get_current_actor`, and `AccountingAccessDeniedError`
maps to the same non-enumerating `404` shape as any other not-found."""

from __future__ import annotations

import uuid

from api.dependencies import get_current_actor
from api.errors import not_found
from fastapi import APIRouter, Depends

from product.accounting.errors import AccountingAccessDeniedError
from product.accounting.invoices import InvoiceView, list_invoices

router = APIRouter(prefix="/v1/accounting", tags=["accounting"])


def _invoice_summary_dict(view: InvoiceView) -> dict[str, object]:
    return {
        "id": str(view.id),
        "tenant_id": str(view.tenant_id),
        "invoice_number": view.invoice_number,
        "contact_id": str(view.contact_id),
        "currency": view.currency,
        "status": view.status,
        "due_date": view.due_date.isoformat(),
        "total": str(view.total),
        "outstanding_amount": str(view.outstanding_amount),
    }


@router.get("/tenants/{tenant_id}/invoices/overdue")
def list_overdue_invoices_route(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID = Depends(get_current_actor),
) -> list[dict[str, object]]:
    try:
        views = list_invoices(actor_id, tenant_id, overdue_only=True)
    except AccountingAccessDeniedError:
        raise not_found("resource") from None
    return [_invoice_summary_dict(v) for v in views]


__all__ = ["router"]
