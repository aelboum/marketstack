import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TemplatesPanel } from "./TemplatesPanel";

const { listTemplatesMock, createTemplateMock, updateTemplateMock, deleteTemplateMock, cloneTemplateMock } = vi.hoisted(() => ({
  listTemplatesMock: vi.fn(),
  createTemplateMock: vi.fn(),
  updateTemplateMock: vi.fn(),
  deleteTemplateMock: vi.fn(),
  cloneTemplateMock: vi.fn(),
}));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return {
    ...actual,
    listTemplates: listTemplatesMock,
    createTemplate: createTemplateMock,
    updateTemplate: updateTemplateMock,
    deleteTemplate: deleteTemplateMock,
    cloneTemplate: cloneTemplateMock,
  };
});

describe("TemplatesPanel", () => {
  it("shows an empty state, then creates a template", async () => {
    listTemplatesMock.mockResolvedValue({ results: [], hasMore: false });
    createTemplateMock.mockResolvedValue({ id: "tpl1" });
    const user = userEvent.setup();

    render(<TemplatesPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No templates yet")).toBeInTheDocument());

    await user.type(screen.getByLabelText("Name"), "Promo");
    await user.type(screen.getByPlaceholderText("Template content…"), "Hi there");
    await user.click(screen.getByRole("button", { name: "Create template" }));

    await waitFor(() =>
      expect(createTemplateMock).toHaveBeenCalledWith("t1", {
        name: "Promo",
        template_type: "email_campaign",
        content: "Hi there",
      }),
    );
  });

  it("delete requires confirmation", async () => {
    listTemplatesMock.mockResolvedValue({
      results: [{ id: "tpl1", tenant_id: "t1", name: "Promo", template_type: "email_campaign", content: "Hi", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }],
      hasMore: false,
    });
    deleteTemplateMock.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<TemplatesPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Promo")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteTemplateMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteTemplateMock).toHaveBeenCalledWith("t1", "tpl1"));
  });

  it("clone submits the new name via cloneTemplate", async () => {
    listTemplatesMock.mockResolvedValue({
      results: [{ id: "tpl1", tenant_id: "t1", name: "Promo", template_type: "email_campaign", content: "Hi", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }],
      hasMore: false,
    });
    cloneTemplateMock.mockResolvedValue({ id: "tpl2" });
    const user = userEvent.setup();

    render(<TemplatesPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Promo")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Clone" }));
    await user.click(screen.getByRole("button", { name: "Clone" }));

    await waitFor(() => expect(cloneTemplateMock).toHaveBeenCalledWith("t1", "tpl1", "Promo copy"));
  });
});
