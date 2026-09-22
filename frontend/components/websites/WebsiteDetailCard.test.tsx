import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WebsiteDetailCard } from "./WebsiteDetailCard";
import { ApiError } from "@/lib/api/errors";

const { deleteWebsiteMock, updateWebsiteMock } = vi.hoisted(() => ({
  deleteWebsiteMock: vi.fn(),
  updateWebsiteMock: vi.fn(),
}));
vi.mock("@/lib/api/websites", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/websites")>();
  return { ...actual, deleteWebsite: deleteWebsiteMock, updateWebsite: updateWebsiteMock };
});

const WEBSITE = {
  id: "w1",
  tenant_id: "t1",
  slug: "my-site",
  name: "My Site",
  custom_domain: null,
  created_by_user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("WebsiteDetailCard", () => {
  it("shows the website's own fields, a None badge for no custom domain", () => {
    render(<WebsiteDetailCard tenantId="t1" website={WEBSITE} onChanged={vi.fn()} onDeleted={vi.fn()} />);
    expect(screen.getByText("my-site")).toBeInTheDocument();
    expect(screen.getByText("None")).toBeInTheDocument();
  });

  it("Edit swaps in EditWebsiteForm, Cancel swaps back", async () => {
    const user = userEvent.setup();
    render(<WebsiteDetailCard tenantId="t1" website={WEBSITE} onChanged={vi.fn()} onDeleted={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Name")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
  });

  it("deletes after confirmation, then calls onDeleted", async () => {
    deleteWebsiteMock.mockResolvedValue(undefined);
    const onDeleted = vi.fn();
    const user = userEvent.setup();

    render(<WebsiteDetailCard tenantId="t1" website={WEBSITE} onChanged={vi.fn()} onDeleted={onDeleted} />);
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText("Delete this website?")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete website" }));
    await waitFor(() => expect(deleteWebsiteMock).toHaveBeenCalledWith("t1", "w1"));
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
  });

  it("shows the backend's own error verbatim on a failed delete", async () => {
    deleteWebsiteMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    const user = userEvent.setup();

    render(<WebsiteDetailCard tenantId="t1" website={WEBSITE} onChanged={vi.fn()} onDeleted={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete website" }));

    await waitFor(() =>
      expect(screen.getByText(/not found, or no access/)).toBeInTheDocument(),
    );
  });
});
