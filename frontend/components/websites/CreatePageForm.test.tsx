import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreatePageForm } from "./CreatePageForm";
import { ApiError } from "@/lib/api/errors";

const { createPageMock } = vi.hoisted(() => ({ createPageMock: vi.fn() }));
vi.mock("@/lib/api/websites", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/websites")>();
  return { ...actual, createPage: createPageMock };
});

describe("CreatePageForm", () => {
  it("disabled until slug and title are filled, then sends slug/title", async () => {
    createPageMock.mockResolvedValue({ id: "p1", title: "Home" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<CreatePageForm tenantId="t1" websiteId="w1" onSaved={onSaved} />);
    expect(screen.getByRole("button", { name: "Create page" })).toBeDisabled();

    await user.type(screen.getByLabelText("Slug"), "home");
    await user.type(screen.getByLabelText("Title"), "Home");
    await user.click(screen.getByRole("button", { name: "Create page" }));

    await waitFor(() =>
      expect(createPageMock).toHaveBeenCalledWith("t1", "w1", { slug: "home", title: "Home" }),
    );
    expect(onSaved).toHaveBeenCalledWith({ id: "p1", title: "Home" });
  });

  it("blocks a title longer than the real 255-character backend limit", async () => {
    const user = userEvent.setup();
    render(<CreatePageForm tenantId="t1" websiteId="w1" onSaved={vi.fn()} />);

    await user.click(screen.getByLabelText("Title"));
    await user.paste("x".repeat(256));

    expect(screen.getByText(/255 characters or fewer/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create page" })).toBeDisabled();
  });

  it("shows the backend's own validation error verbatim", async () => {
    createPageMock.mockRejectedValue(
      new ApiError("validation", "title must not be empty.", { status: 400 }),
    );
    const user = userEvent.setup();

    render(<CreatePageForm tenantId="t1" websiteId="w1" onSaved={vi.fn()} />);
    await user.type(screen.getByLabelText("Slug"), "home");
    await user.type(screen.getByLabelText("Title"), "Home");
    await user.click(screen.getByRole("button", { name: "Create page" }));

    await waitFor(() => expect(screen.getByText("title must not be empty.")).toBeInTheDocument());
  });
});
