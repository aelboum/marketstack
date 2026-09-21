import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AutomationDetailPage from "./page";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1", workflowId: "w1" }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { getWorkflowMock, listVersionsMock, listRunsMock, startRunMock } = vi.hoisted(() => ({
  getWorkflowMock: vi.fn(),
  listVersionsMock: vi.fn(),
  listRunsMock: vi.fn(),
  startRunMock: vi.fn(),
}));
vi.mock("@/lib/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/automation")>();
  return {
    ...actual,
    getWorkflow: getWorkflowMock,
    listVersions: listVersionsMock,
    listRuns: listRunsMock,
    startRun: startRunMock,
  };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const WORKFLOW = {
  id: "w1",
  tenant_id: "tenant-1",
  name: "Welcome automation",
  status: "paused",
  current_published_version_id: null,
  created_by_user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("AutomationDetailPage", () => {
  it("renders the real workflow once fetched by id", async () => {
    getWorkflowMock.mockResolvedValue(WORKFLOW);
    listVersionsMock.mockResolvedValue({ results: [], hasMore: false });
    listRunsMock.mockResolvedValue({ results: [], hasMore: false });

    render(<AutomationDetailPage />);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Welcome automation" })).toBeInTheDocument(),
    );
    expect(getWorkflowMock).toHaveBeenCalledWith("tenant-1", "w1");
  });

  it("disables Run now with no published version, and explains why", async () => {
    getWorkflowMock.mockResolvedValue(WORKFLOW);
    listVersionsMock.mockResolvedValue({ results: [], hasMore: false });
    listRunsMock.mockResolvedValue({ results: [], hasMore: false });

    render(<AutomationDetailPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled());
    expect(screen.getByText(/Publish a version before running/)).toBeInTheDocument();
  });

  it("starting a run shows a link to it and reloads the runs list", async () => {
    getWorkflowMock.mockResolvedValue({ ...WORKFLOW, current_published_version_id: "v1" });
    listVersionsMock.mockResolvedValue({ results: [], hasMore: false });
    listRunsMock.mockResolvedValue({ results: [], hasMore: false });
    startRunMock.mockResolvedValue({ id: "r1", workflow_id: "w1", status: "queued" });
    const user = userEvent.setup();

    render(<AutomationDetailPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Run now" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Run now" }));

    await waitFor(() => expect(startRunMock).toHaveBeenCalledWith("tenant-1", "w1"));
    expect(screen.getByRole("link", { name: "View it" })).toHaveAttribute(
      "href",
      "/t/tenant-1/automation/runs/r1",
    );
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    getWorkflowMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<AutomationDetailPage />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
