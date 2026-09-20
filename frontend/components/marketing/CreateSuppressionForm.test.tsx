import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateSuppressionForm } from "./CreateSuppressionForm";

const { createSuppressionMock, listContactsMock } = vi.hoisted(() => ({
  createSuppressionMock: vi.fn(),
  listContactsMock: vi.fn(),
}));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return { ...actual, createSuppression: createSuppressionMock };
});
vi.mock("@/lib/api/crm", () => ({ listContacts: listContactsMock }));

describe("CreateSuppressionForm", () => {
  it("disabled until a contact is picked via search, then creates with channel/reason", async () => {
    listContactsMock.mockResolvedValue({
      results: [{ id: "c1", first_name: "Jane", last_name: "Doe", email: "jane@example.com" }],
      hasMore: false,
    });
    createSuppressionMock.mockResolvedValue({ id: "s1" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<CreateSuppressionForm tenantId="t1" onSaved={onSaved} />);
    expect(screen.getByRole("button", { name: "Add suppression" })).toBeDisabled();

    await user.type(screen.getByLabelText("Search contacts"), "Jane");
    await waitFor(() => expect(screen.getByText(/Jane Doe/)).toBeInTheDocument());
    await user.click(screen.getByText(/Jane Doe/));

    await user.selectOptions(screen.getByLabelText("Channel"), "sms");
    await user.selectOptions(screen.getByLabelText("Reason"), "bounced");
    await user.click(screen.getByRole("button", { name: "Add suppression" }));

    await waitFor(() =>
      expect(createSuppressionMock).toHaveBeenCalledWith("t1", { contact_id: "c1", channel: "sms", reason: "bounced" }),
    );
    expect(onSaved).toHaveBeenCalledOnce();
  });
});
