import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SuppressionsList } from "./SuppressionsList";
import { ApiError } from "@/lib/api/errors";

const { listSuppressionsMock, deleteSuppressionMock } = vi.hoisted(() => ({
  listSuppressionsMock: vi.fn(),
  deleteSuppressionMock: vi.fn(),
}));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return { ...actual, listSuppressions: listSuppressionsMock, deleteSuppression: deleteSuppressionMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("SuppressionsList", () => {
  it("shows real suppressions", async () => {
    listSuppressionsMock.mockResolvedValue({
      results: [{ id: "s1", tenant_id: "t1", contact_id: "ct1", channel: "email", reason: "unsubscribed", created_at: "2026-01-01T00:00:00Z" }],
      hasMore: false,
    });
    render(<SuppressionsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("ct1")).toBeInTheDocument());
    expect(screen.getByText("unsubscribed")).toBeInTheDocument();
  });

  it("shows an empty state with no suppressions", async () => {
    listSuppressionsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<SuppressionsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No suppressions yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listSuppressionsMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<SuppressionsList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("deletion requires confirmation, then calls deleteSuppression and refetches", async () => {
    listSuppressionsMock.mockResolvedValue({
      results: [{ id: "s1", tenant_id: "t1", contact_id: "ct1", channel: "sms", reason: "manual", created_at: "2026-01-01T00:00:00Z" }],
      hasMore: false,
    });
    deleteSuppressionMock.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<SuppressionsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("ct1")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(deleteSuppressionMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(deleteSuppressionMock).toHaveBeenCalledWith("t1", "s1"));
  });
});
