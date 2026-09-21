import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VersionsPanel } from "./VersionsPanel";
import type { Workflow } from "@/lib/api/automation";
import { ApiError } from "@/lib/api/errors";

const { listVersionsMock, publishVersionMock, createDraftVersionMock, updateDraftVersionMock } =
  vi.hoisted(() => ({
    listVersionsMock: vi.fn(),
    publishVersionMock: vi.fn(),
    createDraftVersionMock: vi.fn(),
    updateDraftVersionMock: vi.fn(),
  }));
vi.mock("@/lib/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/automation")>();
  return {
    ...actual,
    listVersions: listVersionsMock,
    publishVersion: publishVersionMock,
    createDraftVersion: createDraftVersionMock,
    updateDraftVersion: updateDraftVersionMock,
  };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function workflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    id: "w1",
    tenant_id: "t1",
    name: "Test",
    status: "paused",
    current_published_version_id: null,
    created_by_user_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function version(overrides: Record<string, unknown> = {}) {
  return {
    id: "v1",
    tenant_id: "t1",
    workflow_id: "w1",
    version_number: 1,
    status: "draft",
    trigger_type: null,
    trigger_config: {},
    start_step_key: "action",
    steps: [
      {
        step_key: "action",
        type: "action",
        action_type: "create_task",
        action_config: { title: "Follow up" },
        next_step_key: null,
      },
    ],
    created_by_user_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    published_at: null,
    ...overrides,
  };
}

describe("VersionsPanel", () => {
  it("shows 'no version published yet' when the workflow has none", async () => {
    listVersionsMock.mockResolvedValue({ results: [version()], hasMore: false });
    render(<VersionsPanel tenantId="t1" workflowId="w1" workflow={workflow()} />);

    await waitFor(() =>
      expect(screen.getByText(/No version has been published yet/)).toBeInTheDocument(),
    );
  });

  it("summarizes the published version's real trigger and action", async () => {
    listVersionsMock.mockResolvedValue({
      results: [version({ status: "published", trigger_type: "crm.contact.created", published_at: "2026-01-02T00:00:00Z" })],
      hasMore: false,
    });
    render(
      <VersionsPanel
        tenantId="t1"
        workflowId="w1"
        workflow={workflow({ current_published_version_id: "v1" })}
      />,
    );

    await waitFor(() => expect(screen.getByText("A contact is created")).toBeInTheDocument());
    expect(screen.getByText("Create a task")).toBeInTheDocument();
  });

  it("publishing a draft requires confirmation", async () => {
    listVersionsMock.mockResolvedValue({ results: [version()], hasMore: false });
    publishVersionMock.mockResolvedValue(version({ status: "published" }));
    const user = userEvent.setup();

    render(<VersionsPanel tenantId="t1" workflowId="w1" workflow={workflow()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Publish" }));
    expect(publishVersionMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(publishVersionMock).toHaveBeenCalledWith("t1", "w1", "v1"));
  });

  it("editing an existing draft calls updateDraftVersion, never createDraftVersion", async () => {
    listVersionsMock.mockResolvedValue({ results: [version()], hasMore: false });
    updateDraftVersionMock.mockResolvedValue(version());
    const user = userEvent.setup();

    render(<VersionsPanel tenantId="t1" workflowId="w1" workflow={workflow()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Edit" }));

    // Pre-filled from the existing draft.
    expect(screen.getByLabelText("Title")).toHaveValue("Follow up");

    await user.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() =>
      expect(updateDraftVersionMock).toHaveBeenCalledWith(
        "t1",
        "w1",
        "v1",
        expect.objectContaining({ start_step_key: "action" }),
      ),
    );
    expect(createDraftVersionMock).not.toHaveBeenCalled();
  });

  it("with no draft, offers to create one seeded from the published version", async () => {
    listVersionsMock.mockResolvedValue({
      results: [version({ status: "published", published_at: "2026-01-02T00:00:00Z" })],
      hasMore: false,
    });
    createDraftVersionMock.mockResolvedValue(version({ id: "v2", version_number: 2 }));
    const user = userEvent.setup();

    render(
      <VersionsPanel
        tenantId="t1"
        workflowId="w1"
        workflow={workflow({ current_published_version_id: "v1" })}
      />,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Edit" }));

    // Seeded from the published version's action.
    expect(screen.getByLabelText("Title")).toHaveValue("Follow up");
    await user.click(screen.getByRole("button", { name: "Create new draft" }));

    await waitFor(() =>
      expect(createDraftVersionMock).toHaveBeenCalledWith(
        "t1",
        "w1",
        expect.objectContaining({ start_step_key: "action" }),
      ),
    );
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listVersionsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<VersionsPanel tenantId="t1" workflowId="w1" workflow={workflow()} />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
