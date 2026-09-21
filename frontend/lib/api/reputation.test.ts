import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("./client", () => ({ request: requestMock }));

import {
  PROVIDERS,
  REQUEST_CHANNELS,
  cancelReviewRequest,
  createReviewRequest,
  createReviewResponse,
  getReview,
  getReviewRequest,
  listReviewRequests,
  listReviewResponses,
  listReviews,
  recordReview,
} from "./reputation";

describe("reputation API functions -- exact request shape sent to the real Phase 12 routes", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("REQUEST_CHANNELS is exactly the one real channel the backend accepts", () => {
    expect(REQUEST_CHANNELS).toEqual(["email"]);
  });

  it("PROVIDERS is exactly the one real provider the backend accepts", () => {
    expect(PROVIDERS).toEqual(["manual"]);
  });

  it("createReviewRequest() -> POST /review-requests with contact_id/channel/message", async () => {
    requestMock.mockResolvedValue({ id: "r1" });
    await createReviewRequest("t1", { contact_id: "c1", channel: "email", message: "Thanks!" });
    expect(requestMock).toHaveBeenCalledWith("/v1/reputation/tenants/t1/review-requests", {
      method: "POST",
      body: { contact_id: "c1", channel: "email", message: "Thanks!" },
    });
  });

  it("listReviewRequests() -> GET with contact_id/limit/offset", async () => {
    requestMock.mockResolvedValue([{ id: "r1" }]);
    const result = await listReviewRequests("t1", { contactId: "c1", limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/reputation/tenants/t1/review-requests", {
      query: { contact_id: "c1", limit: 25, offset: 0 },
    });
    expect(result.hasMore).toBe(false);
  });

  it("listReviewRequests() default limit/offset with no contact filter", async () => {
    requestMock.mockResolvedValue([]);
    await listReviewRequests("t1");
    expect(requestMock).toHaveBeenCalledWith("/v1/reputation/tenants/t1/review-requests", {
      query: { contact_id: undefined, limit: 25, offset: 0 },
    });
  });

  it("getReviewRequest() -> GET /review-requests/{id}", async () => {
    requestMock.mockResolvedValue({});
    await getReviewRequest("t1", "r1");
    expect(requestMock).toHaveBeenCalledWith("/v1/reputation/tenants/t1/review-requests/r1");
  });

  it("cancelReviewRequest() -> POST /review-requests/{id}/cancel, no body", async () => {
    requestMock.mockResolvedValue({});
    await cancelReviewRequest("t1", "r1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/reputation/tenants/t1/review-requests/r1/cancel",
      { method: "POST" },
    );
  });

  it("recordReview() -> POST /reviews, always sends provider 'manual'", async () => {
    requestMock.mockResolvedValue({ id: "rev1" });
    await recordReview("t1", { rating: 5, author_name: "Jane Doe", body: "Great!" });
    expect(requestMock).toHaveBeenCalledWith("/v1/reputation/tenants/t1/reviews", {
      method: "POST",
      body: { provider: "manual", rating: 5, author_name: "Jane Doe", body: "Great!" },
    });
  });

  it("recordReview() forwards review_request_id when linking to a request", async () => {
    requestMock.mockResolvedValue({ id: "rev1" });
    await recordReview("t1", { rating: 4, author_name: "Jo", review_request_id: "req1" });
    expect(requestMock).toHaveBeenCalledWith("/v1/reputation/tenants/t1/reviews", {
      method: "POST",
      body: { provider: "manual", rating: 4, author_name: "Jo", review_request_id: "req1" },
    });
  });

  it("listReviews() -> GET with limit/offset only (no filter on this endpoint)", async () => {
    requestMock.mockResolvedValue([{ id: "rev1" }]);
    const result = await listReviews("t1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/reputation/tenants/t1/reviews", {
      query: { limit: 25, offset: 0 },
    });
    expect(result.hasMore).toBe(false);
  });

  it("getReview() -> GET /reviews/{id}", async () => {
    requestMock.mockResolvedValue({});
    await getReview("t1", "rev1");
    expect(requestMock).toHaveBeenCalledWith("/v1/reputation/tenants/t1/reviews/rev1");
  });

  it("createReviewResponse() -> POST /reviews/{id}/responses with body", async () => {
    requestMock.mockResolvedValue({ id: "resp1" });
    await createReviewResponse("t1", "rev1", { body: "Thanks for the feedback!" });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/reputation/tenants/t1/reviews/rev1/responses",
      { method: "POST", body: { body: "Thanks for the feedback!" } },
    );
  });

  it("listReviewResponses() -> GET /reviews/{id}/responses with limit/offset", async () => {
    requestMock.mockResolvedValue([{ id: "resp1" }]);
    const result = await listReviewResponses("t1", "rev1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/reputation/tenants/t1/reviews/rev1/responses",
      { query: { limit: 25, offset: 0 } },
    );
    expect(result.hasMore).toBe(false);
  });

  it("hasMore is true when a page returns exactly `limit` results", async () => {
    requestMock.mockResolvedValue(Array.from({ length: 25 }, (_, i) => ({ id: `rev${i}` })));
    const result = await listReviews("t1", { limit: 25, offset: 0 });
    expect(result.hasMore).toBe(true);
  });
});
