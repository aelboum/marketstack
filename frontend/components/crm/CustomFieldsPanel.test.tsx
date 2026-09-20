import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CustomFieldsPanel } from "./CustomFieldsPanel";

const { listFieldDefinitionsMock, getFieldValuesMock, setFieldValueMock, defineFieldMock } = vi.hoisted(
  () => ({
    listFieldDefinitionsMock: vi.fn(),
    getFieldValuesMock: vi.fn(),
    setFieldValueMock: vi.fn(),
    defineFieldMock: vi.fn(),
  }),
);
vi.mock("@/lib/api/crm", () => ({
  listFieldDefinitions: listFieldDefinitionsMock,
  getFieldValues: getFieldValuesMock,
  setFieldValue: setFieldValueMock,
  defineField: defineFieldMock,
}));

describe("CustomFieldsPanel", () => {
  it("renders a definition with its current value and saves a new one", async () => {
    listFieldDefinitionsMock.mockResolvedValue([
      { id: "f1", tenant_id: "t1", entity_type: "contact", name: "lead_source", field_type: "text", created_at: "" },
    ]);
    getFieldValuesMock.mockResolvedValue([
      { id: "v1", field_definition_id: "f1", entity_type: "contact", entity_id: "c1", value: "referral" },
    ]);
    setFieldValueMock.mockResolvedValue({ id: "v1", field_definition_id: "f1", entity_type: "contact", entity_id: "c1", value: "ads" });
    const user = userEvent.setup();

    render(<CustomFieldsPanel tenantId="t1" entityType="contact" entityId="c1" />);

    await waitFor(() => expect(screen.getByText("lead_source")).toBeInTheDocument());
    const valueInput = screen.getByLabelText("Value");
    expect(valueInput).toHaveValue("referral");

    await user.clear(valueInput);
    await user.type(valueInput, "ads");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(setFieldValueMock).toHaveBeenCalledWith("t1", "contact", "c1", "f1", "ads"),
    );
  });

  it("defines a new field", async () => {
    listFieldDefinitionsMock.mockResolvedValue([]);
    getFieldValuesMock.mockResolvedValue([]);
    defineFieldMock.mockResolvedValue({
      id: "f2",
      tenant_id: "t1",
      entity_type: "contact",
      name: "budget",
      field_type: "number",
      created_at: "",
    });
    const user = userEvent.setup();

    render(<CustomFieldsPanel tenantId="t1" entityType="contact" entityId="c1" />);
    await waitFor(() => expect(screen.getByText(/No custom fields defined/)).toBeInTheDocument());

    await user.type(screen.getByLabelText("New field name"), "budget");
    await user.click(screen.getByRole("button", { name: "Define field" }));

    await waitFor(() =>
      expect(defineFieldMock).toHaveBeenCalledWith("t1", {
        entity_type: "contact",
        name: "budget",
        field_type: "text",
      }),
    );
  });
});
