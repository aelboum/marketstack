import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("./client", () => ({ request: requestMock }));

import {
  cancelCampaign,
  cloneTemplate,
  createCampaign,
  createForm,
  createSuppression,
  createTemplate,
  deleteCampaign,
  deleteForm,
  deleteSuppression,
  deleteTemplate,
  getCampaign,
  getForm,
  getTemplate,
  listCampaignRecipients,
  listCampaigns,
  listForms,
  listFormSubmissions,
  listSuppressions,
  listTemplates,
  sendCampaign,
  updateCampaign,
  updateTemplate,
} from "./marketing";

describe("marketing API functions -- exact request shape sent to the real routes", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("listCampaigns() -> GET with limit/offset only (no q/channel/status -- none exist on the backend)", async () => {
    requestMock.mockResolvedValue([{ id: "1" }]);
    const result = await listCampaigns("t1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/campaigns", {
      query: { limit: 25, offset: 0 },
    });
    expect(result.hasMore).toBe(false);
  });

  it("getCampaign() -> GET /campaigns/{id}", async () => {
    requestMock.mockResolvedValue({});
    await getCampaign("t1", "c1");
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/campaigns/c1");
  });

  it("createCampaign() -> POST with the create fields", async () => {
    requestMock.mockResolvedValue({});
    await createCampaign("t1", { name: "Launch", channel: "email", body: "Hi" });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/campaigns", {
      method: "POST",
      body: { name: "Launch", channel: "email", body: "Hi" },
    });
  });

  it("updateCampaign() -> PATCH, no channel/segmentation fields (create-only on the real route)", async () => {
    requestMock.mockResolvedValue({});
    await updateCampaign("t1", "c1", { name: "New name" });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/campaigns/c1", {
      method: "PATCH",
      body: { name: "New name" },
    });
  });

  it("deleteCampaign() -> DELETE", async () => {
    requestMock.mockResolvedValue(undefined);
    await deleteCampaign("t1", "c1");
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/campaigns/c1", {
      method: "DELETE",
    });
  });

  it("sendCampaign() -> POST /send -- the one real delivery operation", async () => {
    requestMock.mockResolvedValue({ campaign_id: "c1", recipient_count: 3, suppressed_count: 1, job_id: "j1" });
    await sendCampaign("t1", "c1");
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/campaigns/c1/send", {
      method: "POST",
    });
  });

  it("cancelCampaign() -> POST /cancel", async () => {
    requestMock.mockResolvedValue({});
    await cancelCampaign("t1", "c1");
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/campaigns/c1/cancel", {
      method: "POST",
    });
  });

  it("listCampaignRecipients() -> GET .../recipients with limit/offset", async () => {
    requestMock.mockResolvedValue([]);
    await listCampaignRecipients("t1", "c1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/campaigns/c1/recipients", {
      query: { limit: 25, offset: 0 },
    });
  });

  it("listSuppressions() -> GET with limit/offset", async () => {
    requestMock.mockResolvedValue([]);
    await listSuppressions("t1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/suppressions", {
      query: { limit: 25, offset: 0 },
    });
  });

  it("createSuppression() -> POST with contact_id/channel/reason", async () => {
    requestMock.mockResolvedValue({});
    await createSuppression("t1", { contact_id: "ct1", channel: "email", reason: "manual" });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/suppressions", {
      method: "POST",
      body: { contact_id: "ct1", channel: "email", reason: "manual" },
    });
  });

  it("deleteSuppression() -> DELETE", async () => {
    requestMock.mockResolvedValue(undefined);
    await deleteSuppression("t1", "s1");
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/suppressions/s1", {
      method: "DELETE",
    });
  });

  it("forms: create/list/get/delete hit the tenant-wide forms path, no update endpoint exists", async () => {
    requestMock.mockResolvedValue({});
    await createForm("t1", { name: "Newsletter", fields: [{ name: "email", field_type: "email", required: true }] });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/forms", {
      method: "POST",
      body: { name: "Newsletter", fields: [{ name: "email", field_type: "email", required: true }] },
    });

    requestMock.mockResolvedValue([]);
    await listForms("t1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/forms", {
      query: { limit: 25, offset: 0 },
    });

    requestMock.mockResolvedValue({});
    await getForm("t1", "f1");
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/forms/f1");

    requestMock.mockResolvedValue(undefined);
    await deleteForm("t1", "f1");
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/forms/f1", { method: "DELETE" });
  });

  it("listFormSubmissions() -> GET .../forms/{id}/submissions with limit/offset", async () => {
    requestMock.mockResolvedValue([]);
    await listFormSubmissions("t1", "f1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/forms/f1/submissions", {
      query: { limit: 25, offset: 0 },
    });
  });

  it("templates: full CRUD plus clone", async () => {
    requestMock.mockResolvedValue({});
    await createTemplate("t1", { name: "Promo", template_type: "email_campaign", content: "Hi" });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/templates", {
      method: "POST",
      body: { name: "Promo", template_type: "email_campaign", content: "Hi" },
    });

    requestMock.mockResolvedValue([]);
    await listTemplates("t1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/templates", {
      query: { limit: 25, offset: 0 },
    });

    requestMock.mockResolvedValue({});
    await getTemplate("t1", "tpl1");
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/templates/tpl1");

    requestMock.mockResolvedValue({});
    await updateTemplate("t1", "tpl1", { content: "New body" });
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/templates/tpl1", {
      method: "PATCH",
      body: { content: "New body" },
    });

    requestMock.mockResolvedValue(undefined);
    await deleteTemplate("t1", "tpl1");
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/templates/tpl1", { method: "DELETE" });

    requestMock.mockResolvedValue({});
    await cloneTemplate("t1", "tpl1", "Promo copy");
    expect(requestMock).toHaveBeenCalledWith("/v1/marketing/tenants/t1/templates/tpl1/clone", {
      method: "POST",
      body: { new_name: "Promo copy" },
    });
  });
});
