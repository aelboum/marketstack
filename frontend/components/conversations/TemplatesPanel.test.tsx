import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TemplatesPanel } from "./TemplatesPanel";

const { listTemplatesMock, createTemplateMock, deleteTemplateMock } = vi.hoisted(() => ({
  listTemplatesMock: vi.fn(),
  createTemplateMock: vi.fn(),
  deleteTemplateMock: vi.fn(),
}));
vi.mock("@/lib/api/conversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/conversations")>();
  return {
    ...actual,
    listTemplates: listTemplatesMock,
    createTemplate: createTemplateMock,
    deleteTemplate: deleteTemplateMock,
  };
});

describe("TemplatesPanel", () => {
  it("creates a new template", async () => {
    listTemplatesMock.mockResolvedValue([]);
    createTemplateMock.mockResolvedValue({
      id: "tpl1",
      tenant_id: "t1",
      name: "Welcome",
      channel: null,
      body: "Hi!",
      created_at: "",
      updated_at: "",
    });
    const user = userEvent.setup();

    render(<TemplatesPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No templates yet")).toBeInTheDocument());

    await user.type(screen.getByLabelText("Name"), "Welcome");
    await user.type(screen.getByPlaceholderText("Template body…"), "Hi!");
    await user.click(screen.getByRole("button", { name: "Create template" }));

    await waitFor(() =>
      expect(createTemplateMock).toHaveBeenCalledWith("t1", { name: "Welcome", body: "Hi!", channel: null }),
    );
  });

  it("deletes a template after confirmation", async () => {
    listTemplatesMock.mockResolvedValue([
      { id: "tpl1", tenant_id: "t1", name: "Welcome", channel: "email", body: "Hi!", created_at: "", updated_at: "" },
    ]);
    deleteTemplateMock.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<TemplatesPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Welcome")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteTemplateMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteTemplateMock).toHaveBeenCalledWith("t1", "tpl1"));
  });
});
