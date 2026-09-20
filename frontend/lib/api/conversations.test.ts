import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("./client", () => ({ request: requestMock }));

import {
  assignThread,
  createMessage,
  createTemplate,
  createThread,
  deleteThread,
  getThread,
  listMessages,
  listTemplates,
  listThreads,
  sendEmail,
  updateThreadChannel,
} from "./conversations";

describe("conversations API functions -- exact request shape sent to the real routes", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("listThreads() -> GET with limit/offset only (no q/channel/status -- none exist on the backend)", async () => {
    requestMock.mockResolvedValue([{ id: "1" }]);
    const result = await listThreads("t1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/conversations/tenants/t1/threads", {
      query: { limit: 25, offset: 0 },
    });
    expect(result.hasMore).toBe(false);
  });

  it("getThread() -> GET /threads/{id}", async () => {
    requestMock.mockResolvedValue({});
    await getThread("t1", "th1");
    expect(requestMock).toHaveBeenCalledWith("/v1/conversations/tenants/t1/threads/th1");
  });

  it("createThread() -> POST with contact_id/channel", async () => {
    requestMock.mockResolvedValue({});
    await createThread("t1", { contact_id: "c1", channel: "email" });
    expect(requestMock).toHaveBeenCalledWith("/v1/conversations/tenants/t1/threads", {
      method: "POST",
      body: { contact_id: "c1", channel: "email" },
    });
  });

  it("updateThreadChannel() -> PATCH", async () => {
    requestMock.mockResolvedValue({});
    await updateThreadChannel("t1", "th1", "sms");
    expect(requestMock).toHaveBeenCalledWith("/v1/conversations/tenants/t1/threads/th1", {
      method: "PATCH",
      body: { channel: "sms" },
    });
  });

  it("deleteThread() -> DELETE", async () => {
    requestMock.mockResolvedValue(undefined);
    await deleteThread("t1", "th1");
    expect(requestMock).toHaveBeenCalledWith("/v1/conversations/tenants/t1/threads/th1", {
      method: "DELETE",
    });
  });

  it("assignThread() -> POST /assign with assignee_user_id", async () => {
    requestMock.mockResolvedValue({});
    await assignThread("t1", "th1", "u1");
    expect(requestMock).toHaveBeenCalledWith("/v1/conversations/tenants/t1/threads/th1/assign", {
      method: "POST",
      body: { assignee_user_id: "u1" },
    });
  });

  it("listMessages() -> GET .../messages with limit/offset", async () => {
    requestMock.mockResolvedValue([]);
    await listMessages("t1", "th1", { limit: 50, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/conversations/tenants/t1/threads/th1/messages",
      { query: { limit: 50, offset: 0 } },
    );
  });

  it("createMessage() (internal note / manual log) -> POST .../messages, never a send", async () => {
    requestMock.mockResolvedValue({});
    await createMessage("t1", "th1", { direction: "outbound", is_internal_note: true, body: "note" });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/conversations/tenants/t1/threads/th1/messages",
      { method: "POST", body: { direction: "outbound", is_internal_note: true, body: "note" } },
    );
  });

  it("sendEmail() -> POST .../send-email -- the one real delivery operation", async () => {
    requestMock.mockResolvedValue({});
    await sendEmail("t1", "th1", { to_email: "a@example.com", subject: "Hi", body: "Body" });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/conversations/tenants/t1/threads/th1/send-email",
      { method: "POST", body: { to_email: "a@example.com", subject: "Hi", body: "Body" } },
    );
  });

  it("template create/list hit the tenant-wide templates path", async () => {
    requestMock.mockResolvedValue({});
    await createTemplate("t1", { name: "Welcome", body: "Hi there" });
    expect(requestMock).toHaveBeenCalledWith("/v1/conversations/tenants/t1/templates", {
      method: "POST",
      body: { name: "Welcome", body: "Hi there" },
    });

    requestMock.mockResolvedValue([]);
    await listTemplates("t1");
    expect(requestMock).toHaveBeenCalledWith("/v1/conversations/tenants/t1/templates");
  });
});
