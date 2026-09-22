import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("./client", () => ({ request: requestMock }));

import { approveApproval, executeApproval, getApproval, listApprovals, rejectApproval } from "./approvals";

describe("approvals API functions -- exact request shape sent to the real routes", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("listApprovals() -> GET with optional status filter", async () => {
    requestMock.mockResolvedValue([{ id: "a1" }]);
    const result = await listApprovals("t1", { status: "pending" });
    expect(requestMock).toHaveBeenCalledWith("/v1/approvals/tenants/t1/approvals", {
      query: { status_filter: "pending" },
    });
    expect(result).toEqual([{ id: "a1" }]);
  });

  it("listApprovals() -> GET with no filter when status is omitted", async () => {
    requestMock.mockResolvedValue([]);
    await listApprovals("t1");
    expect(requestMock).toHaveBeenCalledWith("/v1/approvals/tenants/t1/approvals", {
      query: { status_filter: undefined },
    });
  });

  it("getApproval() -> GET /approvals/{id}", async () => {
    requestMock.mockResolvedValue({});
    await getApproval("t1", "a1");
    expect(requestMock).toHaveBeenCalledWith("/v1/approvals/tenants/t1/approvals/a1");
  });

  it("approveApproval() -> POST /approvals/{id}/approve", async () => {
    requestMock.mockResolvedValue({});
    await approveApproval("t1", "a1");
    expect(requestMock).toHaveBeenCalledWith("/v1/approvals/tenants/t1/approvals/a1/approve", {
      method: "POST",
    });
  });

  it("rejectApproval() -> POST /approvals/{id}/reject", async () => {
    requestMock.mockResolvedValue({});
    await rejectApproval("t1", "a1");
    expect(requestMock).toHaveBeenCalledWith("/v1/approvals/tenants/t1/approvals/a1/reject", {
      method: "POST",
    });
  });

  it("executeApproval() -> POST /approvals/{id}/execute", async () => {
    requestMock.mockResolvedValue({});
    await executeApproval("t1", "a1");
    expect(requestMock).toHaveBeenCalledWith("/v1/approvals/tenants/t1/approvals/a1/execute", {
      method: "POST",
    });
  });
});
