// F-05 (Login Service security audit): product logout must invoke both
// SaaS-OS's /auth/logout and the Login Service's /login-svc/logout.
// Mocks the global `fetch` boundary directly (lib/api/client.test.ts's
// own established pattern for anything that calls `fetch()`), not the
// `./api` module itself -- these tests exercise `logout()`'s real
// behavior, not a restatement of it.

import { afterEach, describe, expect, it, vi } from "vitest";
import { logout } from "./api";
import { ApiError } from "@/lib/api/errors";

type FetchCall = { url: string; init?: RequestInit };

function stubFetch(handler: (call: FetchCall) => Response) {
  const calls: FetchCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return handler({ url, init });
    }),
  );
  return calls;
}

function jsonResponse(body: unknown, init: { status?: number; headers?: HeadersInit } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
}

function noContentResponse(status = 204) {
  return new Response(null, { status });
}

describe("logout()", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("invokes both /auth/logout and /login-svc/logout", async () => {
    const calls = stubFetch(() => noContentResponse());

    await logout();

    const paths = calls.map((c) => new URL(c.url).pathname).sort();
    expect(paths).toEqual(["/auth/logout", "/login-svc/logout"]);
  });

  it("calls both endpoints with POST and credentials included", async () => {
    const calls = stubFetch(() => noContentResponse());

    await logout();

    for (const call of calls) {
      expect(call.init?.method).toBe("POST");
      expect(call.init?.credentials).toBe("include");
    }
  });

  it("never sets an explicit Cookie header -- cookie attachment is left to the browser's own Path-scoped jar", async () => {
    const calls = stubFetch(() => noContentResponse());

    await logout();

    for (const call of calls) {
      const headers = call.init?.headers;
      const hasCookieHeader =
        headers instanceof Headers
          ? headers.has("Cookie")
          : Object.keys((headers as Record<string, string>) ?? {}).some(
              (key) => key.toLowerCase() === "cookie",
            );
      expect(hasCookieHeader).toBe(false);
    }
  });

  it("still resolves when the Login Service session is already absent (idempotent)", async () => {
    stubFetch((call) => {
      if (new URL(call.url).pathname === "/login-svc/logout") {
        // The real Login Service is itself idempotent and returns 204
        // even with no session cookie -- but even a hypothetical error
        // response here must not surface as a logout() failure.
        return noContentResponse();
      }
      return noContentResponse();
    });

    await expect(logout()).resolves.toBeUndefined();
  });

  it("does not throw when the Login Service call fails at the network level", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (new URL(url).pathname === "/login-svc/logout") {
          throw new TypeError("network error");
        }
        return noContentResponse();
      }),
    );

    await expect(logout()).resolves.toBeUndefined();
  });

  it("still calls /login-svc/logout even when /auth/logout fails, and still propagates the SaaS-OS failure", async () => {
    const calls = stubFetch((call) => {
      if (new URL(call.url).pathname === "/auth/logout") {
        return jsonResponse({ detail: "no session" }, { status: 401 });
      }
      return noContentResponse();
    });

    await expect(logout()).rejects.toMatchObject({ kind: "unauthorized" } satisfies Partial<ApiError>);

    const paths = calls.map((c) => new URL(c.url).pathname).sort();
    expect(paths).toEqual(["/auth/logout", "/login-svc/logout"]);
  });

  it("preserves existing SaaS-OS /auth/logout behavior: a successful call resolves cleanly", async () => {
    stubFetch(() => noContentResponse());

    await expect(logout()).resolves.toBeUndefined();
  });
});
