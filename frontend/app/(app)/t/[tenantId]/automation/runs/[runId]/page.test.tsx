import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import AutomationRunDetailPage from "./page";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1", runId: "r1" }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { getRunMock, listRunStepsMock } = vi.hoisted(() => ({
  getRunMock: vi.fn(),
  listRunStepsMock: vi.fn(),
}));
vi.mock("@/lib/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/automation")>();
  return { ...actual, getRun: getRunMock, listRunSteps: listRunStepsMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const RUN = {
  id: "r1",
  tenant_id: "tenant-1",
  workflow_id: "w1",
  workflow_version_id: "v1",
  status: "completed",
  actor_user_id: "u1",
  temporal_workflow_id: null,
  current_step_key: null,
  waiting_for_event_type: null,
  error: null,
  created_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:01Z",
  completed_at: "2026-01-01T00:00:02Z",
};

describe("AutomationRunDetailPage", () => {
  it("renders the real run and links back to its owning automation", async () => {
    getRunMock.mockResolvedValue(RUN);
    listRunStepsMock.mockResolvedValue([]);

    render(<AutomationRunDetailPage />);

    await waitFor(() => expect(screen.getByText("completed")).toBeInTheDocument());
    expect(getRunMock).toHaveBeenCalledWith("tenant-1", "r1");
    expect(screen.getByRole("link", { name: /Back to automation/ })).toHaveAttribute(
      "href",
      "/t/tenant-1/automation/w1",
    );
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    getRunMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<AutomationRunDetailPage />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("shows the session-expired state on a 401", async () => {
    getRunMock.mockRejectedValue(new ApiError("unauthorized", "session expired", { status: 401 }));
    render(<AutomationRunDetailPage />);
    await waitFor(() => expect(screen.getByText("Your session has expired")).toBeInTheDocument());
  });
});
