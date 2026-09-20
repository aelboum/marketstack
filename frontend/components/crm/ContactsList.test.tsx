import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ContactsList } from "./ContactsList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listContactsMock } = vi.hoisted(() => ({ listContactsMock: vi.fn() }));
vi.mock("@/lib/api/crm", () => ({ listContacts: listContactsMock }));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("ContactsList", () => {
  it("shows loading, then real contacts from the API", async () => {
    listContactsMock.mockResolvedValue({
      results: [
        { id: "c1", first_name: "Jane", last_name: "Doe", email: "jane@example.com", phone: null, company_id: null },
      ],
      hasMore: false,
    });

    render(<ContactsList tenantId="tenant-1" />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    expect(screen.getByText("jane@example.com")).toBeInTheDocument();
  });

  it("shows an empty state with no contacts", async () => {
    listContactsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<ContactsList tenantId="tenant-1" />);
    await waitFor(() => expect(screen.getByText("No contacts yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on a 403/404", async () => {
    listContactsMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<ContactsList tenantId="tenant-1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("links each contact row to its detail page", async () => {
    listContactsMock.mockResolvedValue({
      results: [{ id: "c1", first_name: "Jane", last_name: "Doe", email: null, phone: null, company_id: null }],
      hasMore: false,
    });
    render(<ContactsList tenantId="tenant-1" />);
    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Jane Doe" })).toHaveAttribute(
      "href",
      "/t/tenant-1/crm/contacts/c1",
    );
  });
});
