import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReputationPage from "./page";
import { TenantProvider } from "@/lib/tenant/tenant-context";

vi.mock("next/navigation", () => ({ usePathname: () => "/t/t1/reputation" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listReviewRequestsMock, createReviewRequestMock, listReviewsMock, recordReviewMock } =
  vi.hoisted(() => ({
    listReviewRequestsMock: vi.fn(),
    createReviewRequestMock: vi.fn(),
    listReviewsMock: vi.fn(),
    recordReviewMock: vi.fn(),
  }));
vi.mock("@/lib/api/reputation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/reputation")>();
  return {
    ...actual,
    listReviewRequests: listReviewRequestsMock,
    createReviewRequest: createReviewRequestMock,
    listReviews: listReviewsMock,
    recordReview: recordReviewMock,
  };
});
const { listContactsMock } = vi.hoisted(() => ({ listContactsMock: vi.fn() }));
vi.mock("@/lib/api/crm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/crm")>();
  return { ...actual, listContacts: listContactsMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function renderPage() {
  return render(
    <TenantProvider tenantId="t1">
      <ReputationPage />
    </TenantProvider>,
  );
}

describe("ReputationPage", () => {
  it("scopes both lists to the tenant from the route context", async () => {
    listReviewRequestsMock.mockResolvedValue({ results: [], hasMore: false });
    listReviewsMock.mockResolvedValue({ results: [], hasMore: false });
    renderPage();
    await waitFor(() =>
      expect(listReviewRequestsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 }),
    );
    expect(listReviewsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 });
  });

  it("opens the create-request dialog, submits, and reloads the requests list", async () => {
    listReviewRequestsMock.mockResolvedValue({ results: [], hasMore: false });
    listReviewsMock.mockResolvedValue({ results: [], hasMore: false });
    listContactsMock.mockResolvedValue({
      results: [{ id: "c1", first_name: "Ada", last_name: "Lovelace" }],
      hasMore: false,
    });
    createReviewRequestMock.mockResolvedValue({ id: "req1", status: "sent" });
    const user = userEvent.setup();

    renderPage();
    await waitFor(() => expect(listReviewRequestsMock).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("button", { name: "Request a review" }));
    await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Contact"), "c1");
    await user.click(screen.getByRole("button", { name: "Send review request" }));

    await waitFor(() => expect(createReviewRequestMock).toHaveBeenCalled());
    await waitFor(() => expect(listReviewRequestsMock).toHaveBeenCalledTimes(2));
  });

  it("opens the record-review dialog, submits, and reloads the reviews list", async () => {
    listReviewRequestsMock.mockResolvedValue({ results: [], hasMore: false });
    listReviewsMock.mockResolvedValue({ results: [], hasMore: false });
    recordReviewMock.mockResolvedValue({ id: "rev1" });
    const user = userEvent.setup();

    renderPage();
    await waitFor(() => expect(listReviewsMock).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("button", { name: "Record a review" }));
    await user.type(screen.getByLabelText("Author name"), "Jane Doe");
    await user.click(screen.getByRole("button", { name: "Record review" }));

    await waitFor(() => expect(recordReviewMock).toHaveBeenCalled());
    await waitFor(() => expect(listReviewsMock).toHaveBeenCalledTimes(2));
  });
});
