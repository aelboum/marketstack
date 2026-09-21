import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrandingSettingsPanel } from "./BrandingSettingsPanel";

vi.mock("next/navigation", () => ({ usePathname: () => "/t/t1/settings/branding" }));

describe("BrandingSettingsPanel", () => {
  it("states that branding is not configurable instead of offering a form", () => {
    render(<BrandingSettingsPanel />);

    expect(screen.getByRole("heading", { level: 2, name: "Branding" })).toBeInTheDocument();
    expect(screen.getAllByText("Not available yet").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/nothing to save/i).length).toBeGreaterThan(0);
  });

  it("renders no inputs at all -- there is no endpoint to save to", () => {
    const { container } = render(<BrandingSettingsPanel />);

    // The core guarantee: no form control exists anywhere in this panel,
    // so nothing can collect a value that would be silently discarded.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save|upload|apply/i })).not.toBeInTheDocument();
    expect(container.querySelector("input")).toBeNull();
    expect(container.querySelector("form")).toBeNull();
  });

  it("covers custom domain as a separate unavailable capability", () => {
    render(<BrandingSettingsPanel />);
    expect(screen.getByRole("heading", { level: 2, name: "Custom domain" })).toBeInTheDocument();
  });

  it("names the exact missing endpoints so the gap is actionable", () => {
    render(<BrandingSettingsPanel />);

    expect(
      screen.getByText(/GET \/v1\/white-label\/tenants\/\{tenant_id\}\/branding/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/GET \/v1\/white-label\/tenants\/\{tenant_id\}\/domains/),
    ).toBeInTheDocument();
  });

  it("does not imply TLS provisioning exists", () => {
    render(<BrandingSettingsPanel />);

    expect(screen.getByText(/TLS provisioning is explicitly out of scope/)).toBeInTheDocument();
    // Nothing anywhere offers to issue or manage a certificate.
    expect(screen.queryByRole("button", { name: /certificate|provision|verify/i })).not.toBeInTheDocument();
  });
});
