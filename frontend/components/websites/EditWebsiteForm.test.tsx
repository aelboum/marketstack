import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EditWebsiteForm } from "./EditWebsiteForm";
import { ApiError } from "@/lib/api/errors";

const { updateWebsiteMock } = vi.hoisted(() => ({ updateWebsiteMock: vi.fn() }));
vi.mock("@/lib/api/websites", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/websites")>();
  return { ...actual, updateWebsite: updateWebsiteMock };
});

const WEBSITE = {
  id: "w1",
  tenant_id: "t1",
  slug: "my-site",
  name: "My Site",
  custom_domain: "example.com",
  created_by_user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("EditWebsiteForm", () => {
  it("pre-fills from the website, and saves a changed name/domain", async () => {
    updateWebsiteMock.mockResolvedValue({ ...WEBSITE, name: "New Name" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<EditWebsiteForm tenantId="t1" website={WEBSITE} onSaved={onSaved} onCancel={vi.fn()} />);
    expect(screen.getByLabelText("Name")).toHaveValue("My Site");
    expect(screen.getByLabelText("Custom domain")).toHaveValue("example.com");

    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "New Name");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(updateWebsiteMock).toHaveBeenCalledWith("t1", "w1", {
        name: "New Name",
        custom_domain: "example.com",
      }),
    );
    expect(onSaved).toHaveBeenCalledWith({ ...WEBSITE, name: "New Name" });
  });

  it("checking 'Remove the custom domain' disables the field and sends clear_custom_domain", async () => {
    updateWebsiteMock.mockResolvedValue({ ...WEBSITE, custom_domain: null });
    const user = userEvent.setup();

    render(<EditWebsiteForm tenantId="t1" website={WEBSITE} onSaved={vi.fn()} onCancel={vi.fn()} />);
    await user.click(screen.getByLabelText("Remove the custom domain"));
    expect(screen.getByLabelText("Custom domain")).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(updateWebsiteMock).toHaveBeenCalledWith("t1", "w1", {
        name: "My Site",
        clear_custom_domain: true,
      }),
    );
  });

  it("Cancel calls onCancel without saving", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(<EditWebsiteForm tenantId="t1" website={WEBSITE} onSaved={vi.fn()} onCancel={onCancel} />);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
    expect(updateWebsiteMock).not.toHaveBeenCalled();
  });

  it("shows the backend's own validation error verbatim", async () => {
    updateWebsiteMock.mockRejectedValue(
      new ApiError("validation", "name must not be empty.", { status: 400 }),
    );
    const user = userEvent.setup();
    render(<EditWebsiteForm tenantId="t1" website={WEBSITE} onSaved={vi.fn()} onCancel={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.getByText("name must not be empty.")).toBeInTheDocument());
  });
});
