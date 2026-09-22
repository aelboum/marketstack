import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("./client", () => ({ request: requestMock }));

import { listSnapshots } from "./templates";

describe("templates API functions -- exact request shape sent to the real routes", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("listSnapshots() -> GET /v1/templates/tenants/{tenantId}/snapshots", async () => {
    requestMock.mockResolvedValue([]);
    await listSnapshots("agency-1");
    expect(requestMock).toHaveBeenCalledWith("/v1/templates/tenants/agency-1/snapshots");
  });
});
