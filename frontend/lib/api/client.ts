// Product API client foundation (UI-1, docs/ROADMAP.md UI Track).
//
// This is the one place a request reaches the Product backend from. Every
// later UI phase (UI-2 CRM, UI-3 Conversations, ...) is expected to build
// its own typed request functions on top of `request()` below rather than
// calling `fetch()` directly -- keeps error handling, credential
// attachment, and base-URL resolution in one place.
//
// Architecture constraints this file is written against
// (docs/ARCHITECTURE.md §6.1 -- non-negotiable):
//   - talks to the Product REST API only, never a database, never
//     `saas-os` code;
//   - never independently decides an action is allowed -- a 401/403/404
//     from the backend is surfaced as-is (via ApiError) for the caller to
//     render, never swallowed or reinterpreted as a client-side "allowed".
//
// Known, currently-undecided backend/infrastructure gap (documented here,
// not worked around): the backend (product/api/main.py, built on
// saas-os's api.platform.build_platform_app()) mounts no CORS middleware,
// and this frontend calls it cross-origin (frontend :3000, backend :8000
// in local dev -- see docker-compose.yml's own comment: "no reverse proxy
// exists yet in this repository"). A cross-origin `fetch(..., {credentials:
// "include"})` call needs the backend to send
// `Access-Control-Allow-Origin: <frontend origin>` +
// `Access-Control-Allow-Credentials: true`, which it does not today. This
// client is written the same way the existing Phase 1.6
// `app/dashboard/page.tsx` already was (credentialed fetch straight to
// NEXT_PUBLIC_API_URL) so it is a drop-in, not a new incompatible
// pattern -- it will work as soon as a narrowly-scoped backend CORS
// configuration is added (or a reverse proxy is introduced), and reports
// as a clear `network` ApiError until then rather than failing silently.
// This is flagged as a deferred backend-adjacent item in UI-1's final
// report, not fixed here.

import { API_BASE_URL } from "@/lib/api/config";
import { ApiError, classifyErrorStatus, type ApiValidationDetail } from "@/lib/api/errors";

export type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
};

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(path.replace(/^\//, ""), `${API_BASE_URL}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function parseErrorBody(
  response: Response,
): Promise<string | ApiValidationDetail[] | null> {
  try {
    const body = (await response.json()) as { detail?: string | ApiValidationDetail[] };
    return body.detail ?? null;
  } catch {
    return null;
  }
}

/**
 * The single fetch entrypoint every Product API call goes through.
 * Resolves with the parsed JSON body, or throws `ApiError`.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = buildUrl(path, options.query);

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      credentials: "include",
      signal: options.signal,
      headers: options.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw cause;
    }
    throw new ApiError(
      "network",
      "Could not reach the Product backend. It may be offline, or the request was blocked (see the CORS note in lib/api/client.ts).",
      { status: null },
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  if (!response.ok) {
    const detail = await parseErrorBody(response);
    const kind = classifyErrorStatus(response.status);
    const retryAfterHeader = response.headers.get("Retry-After");
    throw new ApiError(kind, describeError(kind, detail), {
      status: response.status,
      detail,
      retryAfterSeconds: retryAfterHeader ? Number(retryAfterHeader) : null,
    });
  }

  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.includes("application/json")) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function describeError(kind: string, detail: string | ApiValidationDetail[] | null): string {
  if (typeof detail === "string") return detail;
  switch (kind) {
    case "unauthorized":
      return "Your session has expired. Please sign in again.";
    case "forbidden":
      return "Not found, or you don't have access to it.";
    case "rate_limited":
      return "Too many requests. Please try again shortly.";
    case "validation":
      return "The request was invalid.";
    default:
      return "Something went wrong talking to the backend.";
  }
}
