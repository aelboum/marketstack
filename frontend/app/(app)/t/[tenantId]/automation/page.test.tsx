import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AutomationPage from "./page";
import { TenantProvider } from "@/lib/tenant/tenant-context";

vi.mock("next/navigation", () => ({ usePathname: () => "/t/t1/automation" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listWorkflowsMock, createWorkflowMock } = vi.hoisted(() => ({
  listWorkflowsMock: vi.fn(),
  createWorkflowMock: vi.fn(),
}));
vi.mock("@/lib/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/automation")>();
  return { ...actual, listWorkflows: listWorkflowsMock, createWorkflow: createWorkflowMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function renderPage() {
  return render(
    <TenantProvider tenantId="t1">
      <AutomationPage />
    </TenantProvider>,
  );
}

describe("AutomationPage", () => {
  it("scopes the workflow list to the tenant from the route context", async () => {
    listWorkflowsMock.mockResolvedValue({ results: [], hasMore: false });
    renderPage();
    await waitFor(() => expect(listWorkflowsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 }));
  });

  it("creating an automation closes the dialog and reloads the list", async () => {
    listWorkflowsMock.mockResolvedValue({ results: [], hasMore: false });
    createWorkflowMock.mockResolvedValue({ workflow: { id: "w1" }, version: { id: "v1" } });
    const user = userEvent.setup();

    renderPage();
    await waitFor(() => expect(screen.getByText("No automations yet")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "New automation" }));
    const dialog = screen.getByRole("dialog", { name: "New automation" });

    await user.type(within(dialog).getByLabelText("Name"), "Welcome");
    await user.type(within(dialog).getByLabelText("Title"), "Task");
    await user.click(within(dialog).getByRole("button", { name: "Create automation" }));

    await waitFor(() => expect(createWorkflowMock).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // Reload after create -- called with the same query twice (initial + reload).
    expect(listWorkflowsMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
