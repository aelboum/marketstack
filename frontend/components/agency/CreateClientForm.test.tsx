import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateClientForm } from "./CreateClientForm";
import { ApiError } from "@/lib/api/errors";

const { createClientMock } = vi.hoisted(() => ({ createClientMock: vi.fn() }));
vi.mock("@/lib/api/agency", () => ({ createClient: createClientMock }));

describe("CreateClientForm", () => {
  it("disables submit until a name is entered", () => {
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Create client" })).toBeDisabled();
  });

  it("submits, calls onCreated with the real API response, and clears the field", async () => {
    createClientMock.mockResolvedValue({
      tenant_id: "c1",
      name: "Acme",
      agency_tenant_id: "agency-1",
    });
    const onCreated = vi.fn();
    const user = userEvent.setup();
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={onCreated} />);

    await user.type(screen.getByLabelText("New client name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Create client" }));

    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith({
        tenant_id: "c1",
        name: "Acme",
        agency_tenant_id: "agency-1",
      }),
    );
    expect(createClientMock).toHaveBeenCalledWith("agency-1", "Acme");
    expect(screen.getByLabelText("New client name")).toHaveValue("");
  });

  it("shows the backend's validation error and does not call onCreated", async () => {
    createClientMock.mockRejectedValue(new ApiError("validation", "The request was invalid."));
    const onCreated = vi.fn();
    const user = userEvent.setup();
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={onCreated} />);

    await user.type(screen.getByLabelText("New client name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Create client" }));

    await waitFor(() =>
      expect(screen.getByText("The request was invalid.")).toBeInTheDocument(),
    );
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("disables the submit button while the request is in flight (duplicate-submit protection)", async () => {
    let resolveCreate: (() => void) | undefined;
    createClientMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = () =>
            resolve({ tenant_id: "c1", name: "Acme", agency_tenant_id: "agency-1" });
        }),
    );
    const user = userEvent.setup();
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={vi.fn()} />);

    await user.type(screen.getByLabelText("New client name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Create client" }));

    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    expect(createClientMock).toHaveBeenCalledOnce();

    resolveCreate?.();
    await waitFor(() => expect(createClientMock).toHaveBeenCalledOnce());
  });
});
