import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TagsPanel } from "./TagsPanel";

const { listTagsForEntityMock, listTagsMock, attachTagMock, detachTagMock, createTagMock } = vi.hoisted(
  () => ({
    listTagsForEntityMock: vi.fn(),
    listTagsMock: vi.fn(),
    attachTagMock: vi.fn(),
    detachTagMock: vi.fn(),
    createTagMock: vi.fn(),
  }),
);
vi.mock("@/lib/api/crm", () => ({
  listTagsForEntity: listTagsForEntityMock,
  listTags: listTagsMock,
  attachTag: attachTagMock,
  detachTag: detachTagMock,
  createTag: createTagMock,
}));

describe("TagsPanel", () => {
  it("renders attached tags and detaches one on click", async () => {
    listTagsForEntityMock.mockResolvedValue([{ id: "tag1", tenant_id: "t1", name: "vip", created_at: "" }]);
    listTagsMock.mockResolvedValue([{ id: "tag1", tenant_id: "t1", name: "vip", created_at: "" }]);
    detachTagMock.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<TagsPanel tenantId="t1" entityType="contact" entityId="c1" />);

    await waitFor(() => expect(screen.getByText("vip")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Remove tag vip" }));

    await waitFor(() => expect(detachTagMock).toHaveBeenCalledWith("t1", "contact", "c1", "tag1"));
  });

  it("creates and attaches a new tag", async () => {
    listTagsForEntityMock.mockResolvedValue([]);
    listTagsMock.mockResolvedValue([]);
    createTagMock.mockResolvedValue({ id: "tag2", tenant_id: "t1", name: "hot-lead", created_at: "" });
    attachTagMock.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<TagsPanel tenantId="t1" entityType="contact" entityId="c1" />);
    await waitFor(() => expect(screen.getByText("No tags yet.")).toBeInTheDocument());

    await user.type(screen.getByLabelText("New tag"), "hot-lead");
    await user.click(screen.getByRole("button", { name: "Create & attach" }));

    await waitFor(() => expect(createTagMock).toHaveBeenCalledWith("t1", "hot-lead"));
    expect(attachTagMock).toHaveBeenCalledWith("t1", "contact", "c1", "tag2");
  });
});
