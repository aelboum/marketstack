import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("./client", () => ({ request: requestMock }));

import {
  attachTag,
  changeOpportunityStage,
  createCompany,
  createContact,
  createOpportunity,
  createTag,
  defineField,
  deleteContact,
  detachTag,
  getContact,
  getFieldValues,
  importContacts,
  listCompanies,
  listContacts,
  listFieldDefinitions,
  listOpportunities,
  setFieldValue,
  updateContact,
} from "./crm";

describe("crm API functions -- exact request shape sent to the real routes", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("listContacts() -> GET with limit/offset/q/tag and heuristic hasMore", async () => {
    requestMock.mockResolvedValue([{ id: "1" }, { id: "2" }]);
    const result = await listContacts("t1", { limit: 2, offset: 0, q: "jane" });
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/contacts", {
      query: { limit: 2, offset: 0, q: "jane", tag: undefined },
    });
    expect(result.hasMore).toBe(true); // results.length === limit
  });

  it("listContacts() hasMore is false when fewer results than limit come back", async () => {
    requestMock.mockResolvedValue([{ id: "1" }]);
    const result = await listContacts("t1", { limit: 25 });
    expect(result.hasMore).toBe(false);
  });

  it("getContact() -> GET /v1/crm/tenants/{tenantId}/contacts/{id}", async () => {
    requestMock.mockResolvedValue({});
    await getContact("t1", "c1");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/contacts/c1");
  });

  it("createContact() -> POST with the exact CreateContactRequest fields", async () => {
    requestMock.mockResolvedValue({});
    await createContact("t1", { first_name: "Jane", last_name: "Doe", email: "j@example.com" });
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/contacts", {
      method: "POST",
      body: { first_name: "Jane", last_name: "Doe", email: "j@example.com" },
    });
  });

  it("updateContact() -> PATCH", async () => {
    requestMock.mockResolvedValue({});
    await updateContact("t1", "c1", { first_name: "Janet" });
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/contacts/c1", {
      method: "PATCH",
      body: { first_name: "Janet" },
    });
  });

  it("deleteContact() -> DELETE", async () => {
    requestMock.mockResolvedValue(undefined);
    await deleteContact("t1", "c1");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/contacts/c1", { method: "DELETE" });
  });

  it("createCompany() and listCompanies() hit the companies sub-path", async () => {
    requestMock.mockResolvedValue({});
    await createCompany("t1", { name: "Acme" });
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/companies", {
      method: "POST",
      body: { name: "Acme" },
    });

    requestMock.mockResolvedValue([]);
    await listCompanies("t1");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/companies", {
      query: { limit: 25, offset: undefined, q: undefined, tag: undefined },
    });
  });

  it("createOpportunity() sends pipeline/stage/amount fields verbatim", async () => {
    requestMock.mockResolvedValue({});
    await createOpportunity("t1", {
      name: "Big deal",
      pipeline_id: "p1",
      stage_id: "s1",
      amount_decimal: "1500.00",
      amount_currency: "USD",
    });
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/opportunities", {
      method: "POST",
      body: {
        name: "Big deal",
        pipeline_id: "p1",
        stage_id: "s1",
        amount_decimal: "1500.00",
        amount_currency: "USD",
      },
    });
  });

  it("listOpportunities() has no pipeline/stage filter param (none exists on the backend)", async () => {
    requestMock.mockResolvedValue([]);
    await listOpportunities("t1", { q: "deal" });
    const [, options] = requestMock.mock.calls[0];
    expect(Object.keys(options.query)).toEqual(["limit", "offset", "q", "tag"]);
  });

  it("changeOpportunityStage() -> POST .../stage", async () => {
    requestMock.mockResolvedValue({});
    await changeOpportunityStage("t1", "o1", "s2");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/opportunities/o1/stage", {
      method: "POST",
      body: { stage_id: "s2" },
    });
  });

  it("tag create/attach/detach hit the generic entity-scoped paths", async () => {
    requestMock.mockResolvedValue({});
    await createTag("t1", "vip");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/tags", {
      method: "POST",
      body: { name: "vip" },
    });

    await attachTag("t1", "contact", "c1", "tag1");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/contact/c1/tags", {
      method: "POST",
      body: { tag_id: "tag1" },
    });

    await detachTag("t1", "contact", "c1", "tag1");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/contact/c1/tags/tag1", {
      method: "DELETE",
    });
  });

  it("custom field define/list/get/set hit the generic entity-scoped paths", async () => {
    requestMock.mockResolvedValue({});
    await defineField("t1", { entity_type: "contact", name: "source", field_type: "text" });
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/custom-fields", {
      method: "POST",
      body: { entity_type: "contact", name: "source", field_type: "text" },
    });

    requestMock.mockResolvedValue([]);
    await listFieldDefinitions("t1", "contact");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/custom-fields", {
      query: { entity_type: "contact" },
    });

    await getFieldValues("t1", "contact", "c1");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/contact/c1/custom-fields");

    requestMock.mockResolvedValue({});
    await setFieldValue("t1", "contact", "c1", "field1", "west-coast");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/contact/c1/custom-fields", {
      method: "PUT",
      body: { field_definition_id: "field1", value: "west-coast" },
    });
  });

  it("importContacts() -> POST /contact-imports with csv_content", async () => {
    requestMock.mockResolvedValue({ id: "job1", status: "pending" });
    await importContacts("t1", "first_name,last_name\nJane,Doe");
    expect(requestMock).toHaveBeenCalledWith("/v1/crm/tenants/t1/contact-imports", {
      method: "POST",
      body: { csv_content: "first_name,last_name\nJane,Doe" },
    });
  });
});
