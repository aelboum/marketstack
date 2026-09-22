// Typed API functions for the Phase 29 Approval Inbox backend
// (`product/approvals/routes.py`, mounted at `/v1/approvals` in
// `product/api/main.py`), built on the UI-1 `request()` foundation --
// mirrors lib/api/{crm,appointments,automation}.ts.
//
// Every field below is business-language-ready already at the wire
// level (`action_label`/`status_label`/`reason`), not something this
// file has to translate itself -- `product/approvals/labels.py` is
// where that translation lives, once, on the backend, so every future
// client (this one, a future mobile app, ...) sees the same labels.
import { request } from "@/lib/api/client";

/** The five real values `control_plane.approval_requests.status` can
 * hold (`control_plane/approvals/models.py`'s own docstring) -- there is
 * no `"failed"` value: a failed execution reverts to `"approved"` so a
 * retry remains possible. */
export type ApprovalStatus = "pending" | "approved" | "rejected" | "executing" | "executed";

export type Approval = {
  id: string;
  tenant_id: string;
  tool_key: string;
  action_label: string;
  status: ApprovalStatus;
  status_label: string;
  reason: string;
  proposer_user_id: string;
  approver_user_id: string | null;
  created_at: string;
  decided_at: string | null;
  can_decide: boolean;
  can_execute: boolean;
};

export function listApprovals(
  tenantId: string,
  params: { status?: ApprovalStatus } = {},
): Promise<Approval[]> {
  return request<Approval[]>(`/v1/approvals/tenants/${tenantId}/approvals`, {
    query: { status_filter: params.status },
  });
}

export function getApproval(tenantId: string, approvalId: string): Promise<Approval> {
  return request<Approval>(`/v1/approvals/tenants/${tenantId}/approvals/${approvalId}`);
}

export function approveApproval(tenantId: string, approvalId: string): Promise<Approval> {
  return request<Approval>(
    `/v1/approvals/tenants/${tenantId}/approvals/${approvalId}/approve`,
    { method: "POST" },
  );
}

export function rejectApproval(tenantId: string, approvalId: string): Promise<Approval> {
  return request<Approval>(
    `/v1/approvals/tenants/${tenantId}/approvals/${approvalId}/reject`,
    { method: "POST" },
  );
}

/** Only meaningful once `Approval.can_execute` is true (`status ===
 * "approved"`) -- a separate step from `approveApproval()`, never
 * automatic, mirroring `control_plane.approvals.execute_approved()`'s
 * own explicit propose -> approve -> execute contract exactly. */
export function executeApproval(tenantId: string, approvalId: string): Promise<Approval> {
  return request<Approval>(
    `/v1/approvals/tenants/${tenantId}/approvals/${approvalId}/execute`,
    { method: "POST" },
  );
}
