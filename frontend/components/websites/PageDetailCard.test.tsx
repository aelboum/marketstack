import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PageDetailCard } from "./PageDetailCard";
import { ApiError } from "@/lib/api/errors";
import type { WebsitePage } from "@/lib/api/websites";

const { updatePageMock, publishPageMock, unpublishPageMock, deletePageMock } = vi.hoisted(() => ({
  updatePageMock: vi.fn(),
  publishPageMock: vi.fn(),
  unpublishPageMock: vi.fn(),
  deletePageMock: vi.fn(),
}));
vi.mock("@/lib/api/websites", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/websites")>();
  return {
    ...actual,
    updatePage: updatePageMock,
    publishPage: publishPageMock,
    unpublishPage: unpublishPageMock,
    deletePage: deletePageMock,
  };
});

function page(overrides: Partial<WebsitePage> = {}): WebsitePage {
  return {
    id: "p1",
    tenant_id: "t1",
    website_id: "w1",
    slug: "home",
    title: "Home",
    status: "draft",
    content_blocks: [],
    published_at: null,
    created_by_user_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("PageDetailCard", () => {
  it("shows Publish for a draft page, Unpublish for a published one", () => {
    const { rerender } = render(
      <PageDetailCard tenantId="t1" page={page()} onChanged={vi.fn()} onDeleted={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument();

    rerender(
      <PageDetailCard
        tenantId="t1"
        page={page({ status: "published", published_at: "2026-02-01T00:00:00Z" })}
        onChanged={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Unpublish" })).toBeInTheDocument();
    expect(screen.getByText(/Last published/)).toBeInTheDocument();
  });

  it("publishing calls publishPage and reports the updated page", async () => {
    publishPageMock.mockResolvedValue(page({ status: "published" }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<PageDetailCard tenantId="t1" page={page()} onChanged={onChanged} onDeleted={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(publishPageMock).toHaveBeenCalledWith("t1", "p1"));
    expect(onChanged).toHaveBeenCalledWith(page({ status: "published" }));
  });

  it("Save draft sends the current title and content blocks", async () => {
    updatePageMock.mockResolvedValue(page({ title: "New Title" }));
    const onChanged = vi.fn();
    const user = userEvent.setup();

    render(<PageDetailCard tenantId="t1" page={page()} onChanged={onChanged} onDeleted={vi.fn()} />);
    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "New Title");
    await user.selectOptions(screen.getByLabelText("Block type to add"), "spacer");
    await user.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() =>
      expect(updatePageMock).toHaveBeenCalledWith("t1", "p1", {
        title: "New Title",
        content_blocks: [{ type: "spacer" }],
      }),
    );
  });

  it("deletes after confirmation, then calls onDeleted", async () => {
    deletePageMock.mockResolvedValue(undefined);
    const onDeleted = vi.fn();
    const user = userEvent.setup();

    render(<PageDetailCard tenantId="t1" page={page()} onChanged={vi.fn()} onDeleted={onDeleted} />);
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete page" }));

    await waitFor(() => expect(deletePageMock).toHaveBeenCalledWith("t1", "p1"));
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
  });

  it("shows the backend's own error verbatim on a failed publish", async () => {
    publishPageMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    const user = userEvent.setup();

    render(<PageDetailCard tenantId="t1" page={page()} onChanged={vi.fn()} onDeleted={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(screen.getByText(/not found, or no access/)).toBeInTheDocument());
  });
});
