import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImportExportPanel } from "./ImportExportPanel";

const { importContactsMock, getImportJobMock, exportContactsCsvMock } = vi.hoisted(() => ({
  importContactsMock: vi.fn(),
  getImportJobMock: vi.fn(),
  exportContactsCsvMock: vi.fn(),
}));
vi.mock("@/lib/api/crm", () => ({
  importContacts: importContactsMock,
  getImportJob: getImportJobMock,
  exportContactsCsv: exportContactsCsvMock,
}));

describe("ImportExportPanel", () => {
  it("submits pasted CSV content and shows the returned job status", async () => {
    importContactsMock.mockResolvedValue({
      id: "job1",
      tenant_id: "t1",
      status: "completed",
      total_rows: 2,
      succeeded_rows: 2,
      failed_rows: 0,
      error_report: null,
      created_at: "",
      completed_at: "2026-01-01T00:00:00Z",
    });
    const user = userEvent.setup();

    render(<ImportExportPanel tenantId="t1" />);

    await user.type(screen.getByPlaceholderText(/first_name,last_name/), "first_name,last_name\nJane,Doe");
    await user.click(screen.getByRole("button", { name: "Import" }));

    await waitFor(() => expect(importContactsMock).toHaveBeenCalledWith("t1", "first_name,last_name\nJane,Doe"));
    await waitFor(() => expect(screen.getByText("completed")).toBeInTheDocument());
    expect(screen.getByText(/2 succeeded, 0 failed/)).toBeInTheDocument();
  });

  it("disables submit and warns when content exceeds the real 5 MB backend limit", async () => {
    const user = userEvent.setup();
    render(<ImportExportPanel tenantId="t1" />);

    const textarea = screen.getByPlaceholderText(/first_name,last_name/);
    // Simulate an over-limit paste directly (typing 5MB+ char-by-char
    // would be impractically slow for a test).
    const overLimitContent = "x".repeat(5 * 1024 * 1024 + 10);
    await user.click(textarea);
    // fireEvent avoids per-character typing for a multi-MB string.
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(textarea, { target: { value: overLimitContent } });

    expect(screen.getByText(/exceeds the 5 MB import limit/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
    expect(importContactsMock).not.toHaveBeenCalled();
  });

  it("exports and triggers a client-side download of the real CSV response", async () => {
    exportContactsCsvMock.mockResolvedValue("first_name,last_name\nJane,Doe\n");
    const createObjectURL = vi.fn().mockReturnValue("blob:mock");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    // jsdom has no real navigation -- clicking a real <a href="blob:...">
    // otherwise logs an async "Not implemented: navigation" error after
    // this test finishes. Stubbing the click avoids that noise; the
    // assertions below only care that the download was *prepared*
    // (createObjectURL called with the real export response), not that
    // jsdom actually navigated.
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();

    render(<ImportExportPanel tenantId="t1" />);
    await user.click(screen.getByRole("button", { name: "Download CSV" }));

    await waitFor(() => expect(exportContactsCsvMock).toHaveBeenCalledWith("t1"));
    expect(createObjectURL).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalledOnce();
    clickSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});
