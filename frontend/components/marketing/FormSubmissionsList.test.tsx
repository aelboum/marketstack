import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FormSubmissionsList } from "./FormSubmissionsList";
import { ApiError } from "@/lib/api/errors";

const { listFormSubmissionsMock } = vi.hoisted(() => ({ listFormSubmissionsMock: vi.fn() }));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return { ...actual, listFormSubmissions: listFormSubmissionsMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("FormSubmissionsList", () => {
  it("renders visitor-supplied submitted_data as plain text, never as HTML", async () => {
    listFormSubmissionsMock.mockResolvedValue({
      results: [
        {
          id: "sub1",
          tenant_id: "t1",
          form_id: "f1",
          contact_id: null,
          submitted_data: { name: "<img src=x onerror=alert(1)>", email: "a@example.com" },
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      hasMore: false,
    });
    const { container } = render(<FormSubmissionsList tenantId="t1" formId="f1" />);

    await waitFor(() => expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument());
    expect(container.querySelector("img")).not.toBeInTheDocument();
  });

  it("shows an empty state with no submissions", async () => {
    listFormSubmissionsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<FormSubmissionsList tenantId="t1" formId="f1" />);
    await waitFor(() => expect(screen.getByText("No submissions yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listFormSubmissionsMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<FormSubmissionsList tenantId="t1" formId="f1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
