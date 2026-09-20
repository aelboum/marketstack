import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import ClientDetailPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "agency-1", clientId: "c2" }),
}));

const { listClientsMock } = vi.hoisted(() => ({ listClientsMock: vi.fn() }));
vi.mock("@/lib/api/agency", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/agency")>();
  return { ...actual, listClients: listClientsMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("ClientDetailPage", () => {
  it("renders the client's name/id once found inside the agency's client list", async () => {
    listClientsMock.mockResolvedValue([
      { tenant_id: "c1", name: "Other Client" },
      { tenant_id: "c2", name: "Acme Dental" },
    ]);

    render(<ClientDetailPage />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Acme Dental" })).toBeInTheDocument());
    expect(screen.getByText("c2")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Invite a member" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Access & delegation" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Support access" })).toBeInTheDocument();
  });

  it("shows a non-enumerating permission-denied state when clientId isn't in the list", async () => {
    listClientsMock.mockResolvedValue([{ tenant_id: "c1", name: "Other Client" }]);

    render(<ClientDetailPage />);

    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "Invite a member" })).not.toBeInTheDocument();
  });
});
