import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkflowsList } from "./WorkflowsList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listWorkflowsMock } = vi.hoisted(() => ({ listWorkflowsMock: vi.fn() }));
vi.mock("@/lib/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/automation")>();
  return { ...actual, listWorkflows: listWorkflowsMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function workflow(overrides: Record<string, unknown> = {}) {
  return {
    id: "w1",
    tenant_id: "t1",
    name: "Welcome new contacts",
    status: "active",
    current_published_version_id: "v1",
    created_by_user_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

describe("WorkflowsList", () => {
  it("shows loading, then real automations linked to their detail page", async () => {
    listWorkflowsMock.mockResolvedValue({ results: [workflow()], hasMore: false });

    render(<WorkflowsList tenantId="t1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Welcome new contacts")).toBeInTheDocument());
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Welcome new contacts/ })).toHaveAttribute(
      "href",
      "/t/t1/automation/w1",
    );
  });

  it("distinguishes a workflow with no published version instead of guessing its trigger/action", async () => {
    listWorkflowsMock.mockResolvedValue({
      results: [workflow({ id: "w2", name: "Unpublished", current_published_version_id: null })],
      hasMore: false,
    });
    render(<WorkflowsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Draft only")).toBeInTheDocument());
  });

  it("shows an empty state with no automations", async () => {
    listWorkflowsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<WorkflowsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No automations yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listWorkflowsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<WorkflowsList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("paginates via Previous/Next using limit/offset, never a fabricated total", async () => {
    listWorkflowsMock.mockResolvedValue({
      results: Array.from({ length: 25 }, (_, i) => workflow({ id: `w${i}`, name: `Automation ${i}` })),
      hasMore: true,
    });
    const user = userEvent.setup();
    render(<WorkflowsList tenantId="t1" />);
    await waitFor(() =>
      expect(listWorkflowsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 }),
    );

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(listWorkflowsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 25 }),
    );
  });
});
