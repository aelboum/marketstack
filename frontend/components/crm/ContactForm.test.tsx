import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ContactForm } from "./ContactForm";
import { ApiError } from "@/lib/api/errors";

const { createContactMock, updateContactMock } = vi.hoisted(() => ({
  createContactMock: vi.fn(),
  updateContactMock: vi.fn(),
}));
vi.mock("@/lib/api/crm", () => ({
  createContact: createContactMock,
  updateContact: updateContactMock,
}));

describe("ContactForm", () => {
  it("create mode: disabled until first and last name are filled", () => {
    render(<ContactForm tenantId="t1" onSaved={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Create contact" })).toBeDisabled();
  });

  it("create mode: submits and calls onSaved with the real response", async () => {
    createContactMock.mockResolvedValue({ id: "c1", first_name: "Jane", last_name: "Doe" });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    render(<ContactForm tenantId="t1" onSaved={onSaved} />);

    await user.type(screen.getByLabelText("First name"), "Jane");
    await user.type(screen.getByLabelText("Last name"), "Doe");
    await user.click(screen.getByRole("button", { name: "Create contact" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ id: "c1", first_name: "Jane", last_name: "Doe" }));
    expect(createContactMock).toHaveBeenCalledWith("t1", {
      first_name: "Jane",
      last_name: "Doe",
      email: null,
      phone: null,
    });
  });

  it("edit mode: pre-fills from the existing contact and calls updateContact", async () => {
    updateContactMock.mockResolvedValue({ id: "c1", first_name: "Janet", last_name: "Doe" });
    const user = userEvent.setup();
    render(
      <ContactForm
        tenantId="t1"
        contact={{
          id: "c1",
          tenant_id: "t1",
          first_name: "Jane",
          last_name: "Doe",
          email: null,
          phone: null,
          company_id: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }}
        onSaved={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("First name")).toHaveValue("Jane");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("First name"));
    await user.type(screen.getByLabelText("First name"), "Janet");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateContactMock).toHaveBeenCalledWith("t1", "c1", expect.objectContaining({ first_name: "Janet" })));
  });

  it("shows the backend validation error on failure", async () => {
    createContactMock.mockRejectedValue(new ApiError("validation", "The request was invalid."));
    const user = userEvent.setup();
    render(<ContactForm tenantId="t1" onSaved={vi.fn()} />);

    await user.type(screen.getByLabelText("First name"), "Jane");
    await user.type(screen.getByLabelText("Last name"), "Doe");
    await user.click(screen.getByRole("button", { name: "Create contact" }));

    await waitFor(() => expect(screen.getByText("The request was invalid.")).toBeInTheDocument());
  });
});
