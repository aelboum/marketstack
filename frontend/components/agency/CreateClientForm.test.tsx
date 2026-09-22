import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateClientForm } from "./CreateClientForm";
import { ApiError } from "@/lib/api/errors";

const { createClientMock } = vi.hoisted(() => ({ createClientMock: vi.fn() }));
vi.mock("@/lib/api/agency", () => ({ createClient: createClientMock }));

const { listSnapshotsMock } = vi.hoisted(() => ({ listSnapshotsMock: vi.fn() }));
vi.mock("@/lib/api/templates", () => ({ listSnapshots: listSnapshotsMock }));

function setDefaultMocks() {
  listSnapshotsMock.mockResolvedValue([]);
}

describe("CreateClientForm", () => {
  it("disables submit until a name is entered", () => {
    setDefaultMocks();
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Klantbedrijf aanmaken" })).toBeDisabled();
  });

  it("submits, calls onCreated with the real API response, and clears the field", async () => {
    setDefaultMocks();
    createClientMock.mockResolvedValue({
      tenant_id: "c1",
      name: "Acme",
      agency_tenant_id: "agency-1",
      provisioning_status: "completed",
      setup_error: null,
    });
    const onCreated = vi.fn();
    const user = userEvent.setup();
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={onCreated} />);

    await user.type(screen.getByLabelText("Naam van het klantbedrijf"), "Acme");
    await user.click(screen.getByRole("button", { name: "Klantbedrijf aanmaken" }));

    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith({
        tenant_id: "c1",
        name: "Acme",
        agency_tenant_id: "agency-1",
        provisioning_status: "completed",
        setup_error: null,
      }),
    );
    expect(createClientMock).toHaveBeenCalledWith("agency-1", "Acme", undefined);
    expect(screen.getByLabelText("Naam van het klantbedrijf")).toHaveValue("");
  });

  it("shows the backend's validation error and does not call onCreated", async () => {
    setDefaultMocks();
    createClientMock.mockRejectedValue(new ApiError("validation", "The request was invalid."));
    const onCreated = vi.fn();
    const user = userEvent.setup();
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={onCreated} />);

    await user.type(screen.getByLabelText("Naam van het klantbedrijf"), "Acme");
    await user.click(screen.getByRole("button", { name: "Klantbedrijf aanmaken" }));

    await waitFor(() =>
      expect(screen.getByText("The request was invalid.")).toBeInTheDocument(),
    );
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("disables the submit button while the request is in flight (duplicate-submit protection)", async () => {
    setDefaultMocks();
    let resolveCreate: (() => void) | undefined;
    createClientMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = () =>
            resolve({
              tenant_id: "c1",
              name: "Acme",
              agency_tenant_id: "agency-1",
              provisioning_status: "completed",
              setup_error: null,
            });
        }),
    );
    const user = userEvent.setup();
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={vi.fn()} />);

    await user.type(screen.getByLabelText("Naam van het klantbedrijf"), "Acme");
    await user.click(screen.getByRole("button", { name: "Klantbedrijf aanmaken" }));

    expect(screen.getByRole("button", { name: "Aanmaken…" })).toBeDisabled();
    expect(createClientMock).toHaveBeenCalledOnce();

    resolveCreate?.();
    await waitFor(() => expect(createClientMock).toHaveBeenCalledOnce());
  });

  it("offers no business-setup step when the agency has no snapshots -- an honest empty state, not an empty dropdown", async () => {
    setDefaultMocks();
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={vi.fn()} />);
    await waitFor(() => expect(listSnapshotsMock).toHaveBeenCalledWith("agency-1"));
    expect(screen.queryByText("Bedrijfsopzet toepassen (optioneel)")).not.toBeInTheDocument();
  });

  it("offers real business setups to apply, and submits the chosen one", async () => {
    listSnapshotsMock.mockResolvedValue([
      { id: "snap-1", tenant_id: "agency-1", name: "Standaard opzet", description: null, schema_version: 1, included_domains: ["crm.pipelines"], created_by_user_id: "u1", created_at: "2026-01-01T00:00:00Z" },
    ]);
    createClientMock.mockResolvedValue({
      tenant_id: "c1",
      name: "Acme",
      agency_tenant_id: "agency-1",
      provisioning_status: "completed",
      setup_error: null,
    });
    const user = userEvent.setup();
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText("Bedrijfsopzet toepassen (optioneel)")).toBeInTheDocument(),
    );
    await user.type(screen.getByLabelText("Naam van het klantbedrijf"), "Acme");
    await user.selectOptions(screen.getByLabelText("Bedrijfsopzet toepassen (optioneel)"), "snap-1");
    await user.click(screen.getByRole("button", { name: "Klantbedrijf aanmaken" }));

    await waitFor(() =>
      expect(createClientMock).toHaveBeenCalledWith("agency-1", "Acme", "snap-1"),
    );
  });

  it("represents a partial failure honestly: the client exists, the setup did not apply", async () => {
    setDefaultMocks();
    createClientMock.mockResolvedValue({
      tenant_id: "c1",
      name: "Acme",
      agency_tenant_id: "agency-1",
      provisioning_status: "setup_failed",
      setup_error: "SnapshotNotFoundError",
    });
    const onCreated = vi.fn();
    const user = userEvent.setup();
    render(<CreateClientForm agencyTenantId="agency-1" onCreated={onCreated} />);

    await user.type(screen.getByLabelText("Naam van het klantbedrijf"), "Acme");
    await user.click(screen.getByRole("button", { name: "Klantbedrijf aanmaken" }));

    await waitFor(() =>
      expect(screen.getByText(/kon niet worden toegepast/)).toBeInTheDocument(),
    );
    // The client was still created -- the caller (the clients list) must
    // still refresh, never treated as a failed creation.
    expect(onCreated).toHaveBeenCalledWith(
      expect.objectContaining({ tenant_id: "c1", provisioning_status: "setup_failed" }),
    );
  });
});
