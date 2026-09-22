import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("./client", () => ({ request: requestMock }));

import {
  BLOCK_TYPES,
  createPage,
  createWebsite,
  deletePage,
  deleteWebsite,
  getPage,
  getWebsite,
  listPages,
  listWebsites,
  publishPage,
  unpublishPage,
  updatePage,
  updateWebsite,
} from "./websites";

describe("websites API functions -- exact request shape sent to the real routes", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("BLOCK_TYPES is exactly the five real backend block types", () => {
    expect(BLOCK_TYPES).toEqual(["heading", "paragraph", "image", "button", "spacer"]);
  });

  it("createWebsite() -> POST with slug/name/custom_domain", async () => {
    requestMock.mockResolvedValue({ id: "w1" });
    await createWebsite("t1", { slug: "my-site", name: "My Site", custom_domain: "example.com" });
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/websites", {
      method: "POST",
      body: { slug: "my-site", name: "My Site", custom_domain: "example.com" },
    });
  });

  it("listWebsites() -> GET with limit/offset only (no filter exists on this endpoint)", async () => {
    requestMock.mockResolvedValue([{ id: "w1" }]);
    const result = await listWebsites("t1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/websites", {
      query: { limit: 25, offset: 0 },
    });
    expect(result.hasMore).toBe(false);
  });

  it("getWebsite() -> GET /websites/{id}", async () => {
    requestMock.mockResolvedValue({});
    await getWebsite("t1", "w1");
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/websites/w1");
  });

  it("updateWebsite() -> PATCH with name/custom_domain", async () => {
    requestMock.mockResolvedValue({});
    await updateWebsite("t1", "w1", { name: "New Name" });
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/websites/w1", {
      method: "PATCH",
      body: { name: "New Name" },
    });
  });

  it("updateWebsite() -> forwards clear_custom_domain as its own explicit field", async () => {
    requestMock.mockResolvedValue({});
    await updateWebsite("t1", "w1", { clear_custom_domain: true });
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/websites/w1", {
      method: "PATCH",
      body: { clear_custom_domain: true },
    });
  });

  it("deleteWebsite() -> DELETE /websites/{id}", async () => {
    requestMock.mockResolvedValue(undefined);
    await deleteWebsite("t1", "w1");
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/websites/w1", {
      method: "DELETE",
    });
  });

  it("createPage() -> POST under the website, with slug/title/content_blocks", async () => {
    requestMock.mockResolvedValue({ id: "p1" });
    await createPage("t1", "w1", {
      slug: "home",
      title: "Home",
      content_blocks: [{ type: "heading", text: "Welcome", level: 1 }],
    });
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/websites/w1/pages", {
      method: "POST",
      body: { slug: "home", title: "Home", content_blocks: [{ type: "heading", text: "Welcome", level: 1 }] },
    });
  });

  it("listPages() -> GET under the website, limit/offset only", async () => {
    requestMock.mockResolvedValue([{ id: "p1" }]);
    const result = await listPages("t1", "w1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/websites/w1/pages", {
      query: { limit: 25, offset: 0 },
    });
    expect(result.hasMore).toBe(false);
  });

  it("getPage() -> GET /pages/{id} (flat, not nested under website)", async () => {
    requestMock.mockResolvedValue({});
    await getPage("t1", "p1");
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/pages/p1");
  });

  it("updatePage() -> PATCH /pages/{id} with title/content_blocks", async () => {
    requestMock.mockResolvedValue({});
    await updatePage("t1", "p1", { title: "New Title" });
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/pages/p1", {
      method: "PATCH",
      body: { title: "New Title" },
    });
  });

  it("deletePage() -> DELETE /pages/{id}", async () => {
    requestMock.mockResolvedValue(undefined);
    await deletePage("t1", "p1");
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/pages/p1", {
      method: "DELETE",
    });
  });

  it("publishPage() -> POST /pages/{id}/publish, no body", async () => {
    requestMock.mockResolvedValue({ status: "published" });
    await publishPage("t1", "p1");
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/pages/p1/publish", {
      method: "POST",
    });
  });

  it("unpublishPage() -> POST /pages/{id}/unpublish, no body", async () => {
    requestMock.mockResolvedValue({ status: "draft" });
    await unpublishPage("t1", "p1");
    expect(requestMock).toHaveBeenCalledWith("/v1/websites/tenants/t1/pages/p1/unpublish", {
      method: "POST",
    });
  });

  it("hasMore is true when a page returns exactly `limit` results", async () => {
    requestMock.mockResolvedValue(Array.from({ length: 25 }, (_, i) => ({ id: `w${i}` })));
    const result = await listWebsites("t1", { limit: 25, offset: 0 });
    expect(result.hasMore).toBe(true);
  });
});
