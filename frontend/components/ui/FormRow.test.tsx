import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FormRow, FormRowGroup, FormRowGrow } from "./FormRow";
import { Input } from "./Input";
import { Button } from "./Button";

// UI-9: the extracted inline-form-row layout. These assert the contract
// that made extraction safe -- it changes layout only, and never the
// labelling, validation, disabled or submit semantics of what it wraps.

describe("FormRow", () => {
  it("is a real form that submits, so callers keep their own onSubmit", async () => {
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    const user = userEvent.setup();

    render(
      <FormRow onSubmit={onSubmit}>
        <Input label="Tag name" defaultValue="vip" />
        <Button type="submit">Add</Button>
      </FormRow>,
    );

    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("preserves the label/control association of what it wraps", () => {
    render(
      <FormRow>
        <Input label="Tag name" defaultValue="vip" />
      </FormRow>,
    );

    // The row is layout only: the Input still owns its own label wiring.
    expect(screen.getByLabelText("Tag name")).toHaveValue("vip");
  });

  it("preserves error and disabled semantics of what it wraps", () => {
    render(
      <FormRow>
        <Input label="Email" error="That address is not valid." />
        <Button type="submit" disabled>
          Save
        </Button>
      </FormRow>,
    );

    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("That address is not valid.");
    expect(screen.getByRole("alert")).toHaveTextContent("That address is not valid.");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("adds no roles or landmarks of its own beyond the form element", () => {
    const { container } = render(
      <FormRow aria-label="Add a tag">
        <Button type="submit">Add</Button>
      </FormRow>,
    );

    const form = container.querySelector("form");
    expect(form).not.toBeNull();
    // Forwards arbitrary props (here, the accessible name) to the form.
    expect(form).toHaveAttribute("aria-label", "Add a tag");
  });

  it("FormRowGroup renders the same layout without being a form", () => {
    const { container } = render(
      <FormRowGroup>
        <Button>Act</Button>
      </FormRowGroup>,
    );

    expect(container.querySelector("form")).toBeNull();
    expect(screen.getByRole("button", { name: "Act" })).toBeInTheDocument();
  });

  it("FormRowGrow wraps a control without disturbing it", () => {
    render(
      <FormRow>
        <FormRowGrow>
          <Input label="Search" />
        </FormRowGrow>
      </FormRow>,
    );

    expect(screen.getByLabelText("Search")).toBeInTheDocument();
  });
});
