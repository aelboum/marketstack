import { afterEach, describe, expect, it, vi } from "vitest";
import { request } from "./client";
import { ApiError } from "./errors";

function mockFetchOnce(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  const fullResponse = {
    ok: response.ok ?? true,
    status: response.status ?? 200,
    headers: response.headers ?? new Headers(),
    json: response.json ?? (async () => ({})),
  } as Response;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => fullResponse),
  );
}

describe("request()", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the parsed JSON body on success", async () => {
    mockFetchOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "Content-Type": "application/json" }),
      json: async () => ({ user_id: "abc-123" }),
    });

    const result = await request<{ user_id: string }>("/auth/me");
    expect(result).toEqual({ user_id: "abc-123" });
  });

  it("throws an ApiError with kind 'unauthorized' on 401", async () => {
    mockFetchOnce({
      ok: false,
      status: 401,
      headers: new Headers(),
      json: async () => ({ detail: "Not authenticated." }),
    });

    await expect(request("/auth/me")).rejects.toMatchObject({
      kind: "unauthorized",
      status: 401,
    } satisfies Partial<ApiError>);
  });

  it("treats a 403 and a tenant-scoped 404 identically as 'forbidden' (backend non-enumeration convention)", async () => {
    mockFetchOnce({ ok: false, status: 403, headers: new Headers(), json: async () => ({}) });
    await expect(request("/v1/crm/tenants/x/contacts")).rejects.toMatchObject({
      kind: "forbidden",
    });

    mockFetchOnce({ ok: false, status: 404, headers: new Headers(), json: async () => ({}) });
    await expect(request("/v1/crm/tenants/x/contacts/1")).rejects.toMatchObject({
      kind: "forbidden",
    });
  });

  it("maps 422 to a validation ApiError carrying the field-level detail", async () => {
    const detail = [{ loc: ["body", "email"], msg: "invalid", type: "value_error" }];
    mockFetchOnce({ ok: false, status: 422, headers: new Headers(), json: async () => ({ detail }) });

    await expect(request("/v1/crm/tenants/x/contacts")).rejects.toMatchObject({
      kind: "validation",
      detail,
    });
  });

  it("maps 429 to rate_limited and carries Retry-After", async () => {
    mockFetchOnce({
      ok: false,
      status: 429,
      headers: new Headers({ "Retry-After": "12" }),
      json: async () => ({ detail: "Too many requests." }),
    });

    await expect(request("/v1/crm/tenants/x/contacts")).rejects.toMatchObject({
      kind: "rate_limited",
      retryAfterSeconds: 12,
    });
  });

  it("wraps a network-level failure (e.g. a CORS rejection) as an ApiError with kind 'network'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    await expect(request("/auth/me")).rejects.toMatchObject({ kind: "network" });
  });
});
