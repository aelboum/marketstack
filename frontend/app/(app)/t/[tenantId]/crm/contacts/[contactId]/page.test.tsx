import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import ContactDetailPage from "./page";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1", contactId: "c1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

const { getContactMock } = vi.hoisted(() => ({ getContactMock: vi.fn() }));
vi.mock("@/lib/api/crm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/crm")>();
  return { ...actual, getContact: getContactMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("ContactDetailPage", () => {
  it("renders the real contact once fetched by id", async () => {
    getContactMock.mockResolvedValue({
      id: "c1",
      tenant_id: "tenant-1",
      first_name: "Jane",
      last_name: "Doe",
      email: "jane@example.com",
      phone: null,
      company_id: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    render(<ContactDetailPage />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Jane Doe" })).toBeInTheDocument());
    expect(getContactMock).toHaveBeenCalledWith("tenant-1", "c1");
  });

  it("shows the non-enumerating permission-denied state on a 403/404, never a distinguishing message", async () => {
    getContactMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));

    render(<ContactDetailPage />);

    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
