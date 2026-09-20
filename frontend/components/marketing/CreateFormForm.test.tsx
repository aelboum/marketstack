import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateFormForm } from "./CreateFormForm";

const { createFormMock } = vi.hoisted(() => ({ createFormMock: vi.fn() }));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return { ...actual, createForm: createFormMock };
});

describe("CreateFormForm", () => {
  it("disabled until name and at least one named field, submits filtered field list", async () => {
    createFormMock.mockResolvedValue({ id: "f1" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<CreateFormForm tenantId="t1" onSaved={onSaved} />);
    expect(screen.getByRole("button", { name: "Create form" })).toBeDisabled();

    await user.type(screen.getByLabelText("Form name"), "Newsletter");
    await user.type(screen.getByPlaceholderText("Field name"), "email");
    const [fieldTypeSelect] = screen.getAllByRole("combobox");
    await user.selectOptions(fieldTypeSelect, "email");
    await user.click(screen.getByLabelText("Required"));

    await user.click(screen.getByRole("button", { name: "Create form" }));

    await waitFor(() =>
      expect(createFormMock).toHaveBeenCalledWith("t1", {
        name: "Newsletter",
        fields: [{ name: "email", field_type: "email", required: true }],
      }),
    );
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("Add field / Remove field manage the dynamic row list", async () => {
    createFormMock.mockResolvedValue({ id: "f1" });
    const user = userEvent.setup();
    render(<CreateFormForm tenantId="t1" onSaved={vi.fn()} />);

    expect(screen.getAllByPlaceholderText("Field name")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Add field" }));
    expect(screen.getAllByPlaceholderText("Field name")).toHaveLength(2);

    const removeButtons = screen.getAllByRole("button", { name: "Remove" });
    await user.click(removeButtons[0]);
    expect(screen.getAllByPlaceholderText("Field name")).toHaveLength(1);
  });
});
