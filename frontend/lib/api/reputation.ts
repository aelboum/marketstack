// Typed API functions for the Phase 12 Reputation backend
// (`product/reputation/routes.py`, prefix `/v1/reputation`), built on the
// UI-1 `request()` foundation -- UI-11 adds no second HTTP client.
//
// **Backend dependency: this router is not yet mounted.**
// `product/reputation/routes.py`'s own module docstring, and
// `product/reputation/__init__.py`'s own module docstring, both say so
// explicitly: `product/api/main.py` does not `include_router()` this
// router (or call its purge-participant `register()`, or import its
// `event_handlers` module) yet -- that three-line wiring is a documented
// follow-up, deliberately not applied this phase because `product/api/
// main.py` was an explicitly protected file for UI-11 (an unrelated
// dev-auth-bypass change already in the working tree). Every function
// below is written against the router's real, stable, already-tested
// contract (`tests/reputation/*.py` exercises the service layer directly)
// -- nothing here is invented -- but the HTTP path itself returns 404
// through the running application until that follow-up lands. See this
// phase's own implementation/audit report.
//
// Deliberately absent, because the backend has none:
//   - no update/delete on a `Review` or `ReviewResponse` -- the router
//     defines create/list/get only;
//   - no provider configuration/status endpoint -- `product/reputation/
//     providers.py`'s own module docstring: Phase 12.2 (a real provider
//     adapter) is deliberately deferred, `resolve_provider()` returns
//     `None` for every provider by design. `PROVIDERS` below is `["manual"]`
//     only, matching `ck_reputation_reviews_provider`;
//   - no channel other than `"email"` -- `ck_reputation_review_requests_channel`;
//   - no way to edit `ReviewRequest.message` after sending, and no way to
//     re-send a `failed`/`cancelled` request -- the lifecycle
//     (`product/reputation/review_requests.py`'s own module docstring) has
//     no such transition;
//   - no search/filter on `listReviews` -- the backend route takes
//     `limit`/`offset` only. `listReviewRequests` accepts `contact_id`
//     because the route defines that one filter and no other.

import { request } from "@/lib/api/client";

export type RequestChannel = "email";

/** `product/reputation/models.py::REQUEST_CHANNELS`. */
export const REQUEST_CHANNELS: RequestChannel[] = ["email"];

export type RequestStatus = "pending" | "sent" | "failed" | "cancelled" | "fulfilled";

export type ReviewRequest = {
  id: string;
  tenant_id: string;
  contact_id: string;
  channel: RequestChannel;
  status: RequestStatus;
  failure_reason: string | null;
  requested_by_user_id: string;
  sent_at: string | null;
  cancelled_at: string | null;
  fulfilled_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Provider = "manual";

/** `product/reputation/models.py::REVIEW_PROVIDERS`. */
export const PROVIDERS: Provider[] = ["manual"];

export type ReviewStatus = "new" | "responded";

export type Review = {
  id: string;
  tenant_id: string;
  review_request_id: string | null;
  provider: Provider;
  external_review_id: string | null;
  rating: number;
  author_name: string;
  body: string | null;
  status: ReviewStatus;
  received_at: string;
  recorded_by_user_id: string;
  created_at: string;
  updated_at: string;
};

export type ReviewResponseRecord = {
  id: string;
  tenant_id: string;
  review_id: string;
  body: string;
  posted_by_user_id: string;
  created_at: string;
};

export type Page<T> = {
  results: T[];
  /** Heuristic only (`results.length === limit`) -- every list endpoint
   * here returns a plain array, never a total count. */
  hasMore: boolean;
};

function toPage<T>(results: T[], limit: number): Page<T> {
  return { results, hasMore: results.length === limit };
}

/** `product/reputation/pagination.py::DEFAULT_PAGE_SIZE`. */
const DEFAULT_LIMIT = 25;

// --- Review requests -----------------------------------------------------

export type CreateReviewRequestInput = {
  contact_id: string;
  channel?: RequestChannel;
  message?: string | null;
};

/** `POST .../review-requests`. Send is synchronous on the backend -- the
 * returned row already reflects `sent` or `failed`, never a lingering
 * `pending` a caller would need to poll for
 * (`product/reputation/review_requests.py`'s own module docstring). */
export function createReviewRequest(
  tenantId: string,
  input: CreateReviewRequestInput,
): Promise<ReviewRequest> {
  return request<ReviewRequest>(`/v1/reputation/tenants/${tenantId}/review-requests`, {
    method: "POST",
    body: input,
  });
}

export function listReviewRequests(
  tenantId: string,
  params: { contactId?: string; limit?: number; offset?: number } = {},
): Promise<Page<ReviewRequest>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<ReviewRequest[]>(`/v1/reputation/tenants/${tenantId}/review-requests`, {
    query: { contact_id: params.contactId, limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function getReviewRequest(tenantId: string, requestId: string): Promise<ReviewRequest> {
  return request<ReviewRequest>(
    `/v1/reputation/tenants/${tenantId}/review-requests/${requestId}`,
  );
}

/** `POST .../review-requests/{id}/cancel`. Only valid while `status ===
 * "sent"` -- the backend rejects any other transition with a 400
 * (`ReputationValidationError`). */
export function cancelReviewRequest(
  tenantId: string,
  requestId: string,
): Promise<ReviewRequest> {
  return request<ReviewRequest>(
    `/v1/reputation/tenants/${tenantId}/review-requests/${requestId}/cancel`,
    { method: "POST" },
  );
}

// --- Reviews ---------------------------------------------------------------

export type RecordReviewInput = {
  rating: number;
  author_name: string;
  body?: string | null;
  provider?: Provider;
  review_request_id?: string | null;
};

/** `POST .../reviews`. This UI only ever records `provider: "manual"` --
 * see this module's own docstring. Linking `review_request_id` marks that
 * request `fulfilled` server-side. */
export function recordReview(tenantId: string, input: RecordReviewInput): Promise<Review> {
  return request<Review>(`/v1/reputation/tenants/${tenantId}/reviews`, {
    method: "POST",
    body: { provider: "manual", ...input },
  });
}

export function listReviews(
  tenantId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<Review>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<Review[]>(`/v1/reputation/tenants/${tenantId}/reviews`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function getReview(tenantId: string, reviewId: string): Promise<Review> {
  return request<Review>(`/v1/reputation/tenants/${tenantId}/reviews/${reviewId}`);
}

// --- Review responses --------------------------------------------------------

/** `POST .../reviews/{id}/responses`. Flips the review's own `status` to
 * `"responded"` server-side -- callers should refetch the review after
 * this succeeds rather than assume its prior status still holds. */
export function createReviewResponse(
  tenantId: string,
  reviewId: string,
  input: { body: string },
): Promise<ReviewResponseRecord> {
  return request<ReviewResponseRecord>(
    `/v1/reputation/tenants/${tenantId}/reviews/${reviewId}/responses`,
    { method: "POST", body: input },
  );
}

export function listReviewResponses(
  tenantId: string,
  reviewId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<ReviewResponseRecord>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<ReviewResponseRecord[]>(
    `/v1/reputation/tenants/${tenantId}/reviews/${reviewId}/responses`,
    { query: { limit, offset: params.offset ?? 0 } },
  ).then((results) => toPage(results, limit));
}
