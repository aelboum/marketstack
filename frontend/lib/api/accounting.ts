// Typed API functions for the minimal Phase 25 Accounting backend
// (`product/accounting/routes.py`, mounted at `/v1/accounting` in
// `product/api/main.py`), built on the UI-1 `request()` foundation --
// mirrors lib/api/approvals.ts.
//
// Deliberately one function: `listOverdueInvoices()`. No other Phase 25
// accounting operation (tax codes, posting, payments, allocations) has a
// frontend surface this phase -- see `product/accounting/routes.py`'s own
// module docstring for why this is the one, minimal exception.
import { request } from "@/lib/api/client";

export type OverdueInvoice = {
  id: string;
  tenant_id: string;
  invoice_number: number | null;
  contact_id: string;
  currency: string;
  status: string;
  due_date: string;
  total: string;
  outstanding_amount: string;
};

export function listOverdueInvoices(tenantId: string): Promise<OverdueInvoice[]> {
  return request<OverdueInvoice[]>(`/v1/accounting/tenants/${tenantId}/invoices/overdue`);
}
