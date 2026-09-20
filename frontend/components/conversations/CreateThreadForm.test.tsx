import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateThreadForm } from "./CreateThreadForm";

const { createThreadMock, listContactsMock } = vi.hoisted(() => ({
  createThreadMock: vi.fn(),
  listContactsMock: vi.fn(),
}));
vi.mock("@/lib/api/conversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/conversations")>();
  return { ...actual, createThread: createThreadMock };
});
vi.mock("@/lib/api/crm", () => ({ listContacts: listContactsMock }));

describe("CreateThreadForm", () => {
  it("disabled until a contact is chosen, then creates with the selected contact/channel", async () => {
    listContactsMock.mockResolvedValue({
      results: [{ id: "c1", first_name: "Jane", last_name: "Doe" }],
      hasMore: false,
    });
    createThreadMock.mockResolvedValue({ id: "th1", contact_id: "c1", channel: "sms" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<CreateThreadForm tenantId="t1" onSaved={onSaved} />);
    await waitFor(() => expect(screen.getByRole("option", { name: "Jane Doe" })).toBeInTheDocument());

    expect(screen.getByRole("button", { name: "Create conversation" })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText("Contact"), "c1");
    await user.selectOptions(screen.getByLabelText("Channel"), "sms");
    await user.click(screen.getByRole("button", { name: "Create conversation" }));

    await waitFor(() =>
      expect(createThreadMock).toHaveBeenCalledWith("t1", { contact_id: "c1", channel: "sms" }),
    );
    expect(onSaved).toHaveBeenCalledWith({ id: "th1", contact_id: "c1", channel: "sms" });
  });
});
