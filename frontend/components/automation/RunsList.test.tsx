import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RunsList } from "./RunsList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listRunsMock } = vi.hoisted(() => ({ listRunsMock: vi.fn() }));
vi.mock("@/lib/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/automation")>();
  return { ...actual, listRuns: listRunsMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function run(overrides: Record<string, unknown> = {}) {
  return {
    id: "r1",
    tenant_id: "t1",
    workflow_id: "w1",
    workflow_version_id: "v1",
    status: "completed",
    actor_user_id: "u1",
    temporal_workflow_id: "temporal-internal-id-should-not-render",
    current_step_key: null,
    waiting_for_event_type: null,
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:01Z",
    completed_at: "2026-01-01T00:00:02Z",
    ...overrides,
  };
}

describe("RunsList", () => {
  it("shows real runs linked to run detail, and never renders the raw Temporal id", async () => {
    listRunsMock.mockResolvedValue({ results: [run()], hasMore: false });
    render(<RunsList tenantId="t1" workflowId="w1" />);

    await waitFor(() => expect(screen.getByText("completed")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /completed/ })).toHaveAttribute(
      "href",
      "/t/t1/automation/runs/r1",
    );
    expect(screen.queryByText("temporal-internal-id-should-not-render")).not.toBeInTheDocument();
  });

  it("shows an empty state with no runs", async () => {
    listRunsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<RunsList tenantId="t1" workflowId="w1" />);
    await waitFor(() => expect(screen.getByText("No runs yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listRunsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<RunsList tenantId="t1" workflowId="w1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("shows a run that has not started as 'Not yet started' rather than a blank cell", async () => {
    listRunsMock.mockResolvedValue({
      results: [run({ status: "queued", started_at: null, completed_at: null })],
      hasMore: false,
    });
    render(<RunsList tenantId="t1" workflowId="w1" />);
    await waitFor(() => expect(screen.getByText("Not yet started")).toBeInTheDocument());
  });
});
