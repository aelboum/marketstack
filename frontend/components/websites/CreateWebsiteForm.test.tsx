import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateWebsiteForm } from "./CreateWebsiteForm";
import { ApiError } from "@/lib/api/errors";

const { createWebsiteMock } = vi.hoisted(() => ({ createWebsiteMock: vi.fn() }));
vi.mock("@/lib/api/websites", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/websites")>();
  return { ...actual, createWebsite: createWebsiteMock };
});

describe("CreateWebsiteForm", () => {
  it("disabled until slug and name are filled, then sends slug/name/custom_domain", async () => {
    createWebsiteMock.mockResolvedValue({ id: "w1", slug: "my-site" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<CreateWebsiteForm tenantId="t1" onSaved={onSaved} />);
    expect(screen.getByRole("button", { name: "Create website" })).toBeDisabled();

    await user.type(screen.getByLabelText("Slug"), "my-site");
    await user.type(screen.getByLabelText("Name"), "My Site");
    await user.type(screen.getByLabelText("Custom domain (optional)"), "example.com");
    await user.click(screen.getByRole("button", { name: "Create website" }));

    await waitFor(() =>
      expect(createWebsiteMock).toHaveBeenCalledWith("t1", {
        slug: "my-site",
        name: "My Site",
        custom_domain: "example.com",
      }),
    );
    expect(onSaved).toHaveBeenCalledWith({ id: "w1", slug: "my-site" });
  });

  it("omits custom_domain when left blank", async () => {
    createWebsiteMock.mockResolvedValue({ id: "w1" });
    const user = userEvent.setup();

    render(<CreateWebsiteForm tenantId="t1" onSaved={vi.fn()} />);
    await user.type(screen.getByLabelText("Slug"), "my-site");
    await user.type(screen.getByLabelText("Name"), "My Site");
    await user.click(screen.getByRole("button", { name: "Create website" }));

    await waitFor(() =>
      expect(createWebsiteMock).toHaveBeenCalledWith("t1", {
        slug: "my-site",
        name: "My Site",
        custom_domain: undefined,
      }),
    );
  });

  it("blocks a slug longer than the real 63-character backend limit", async () => {
    const user = userEvent.setup();
    render(<CreateWebsiteForm tenantId="t1" onSaved={vi.fn()} />);

    await user.click(screen.getByLabelText("Slug"));
    await user.paste("x".repeat(64));

    expect(screen.getByText(/63 characters or fewer/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create website" })).toBeDisabled();
  });

  it("shows the backend's own validation error verbatim", async () => {
    createWebsiteMock.mockRejectedValue(
      new ApiError(
        "validation",
        "slug must contain only lowercase letters, digits, and single hyphens (no leading, trailing, or doubled hyphen).",
        { status: 400 },
      ),
    );
    const user = userEvent.setup();

    render(<CreateWebsiteForm tenantId="t1" onSaved={vi.fn()} />);
    await user.type(screen.getByLabelText("Slug"), "Not A Slug");
    await user.type(screen.getByLabelText("Name"), "My Site");
    await user.click(screen.getByRole("button", { name: "Create website" }));

    await waitFor(() =>
      expect(
        screen.getByText(/slug must contain only lowercase letters/),
      ).toBeInTheDocument(),
    );
  });
});
