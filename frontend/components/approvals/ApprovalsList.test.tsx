import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ApprovalsList } from "./ApprovalsList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const { listApprovalsMock } = vi.hoisted(() => ({ listApprovalsMock: vi.fn() }));
vi.mock("@/lib/api/approvals", () => ({ listApprovals: listApprovalsMock }));

describe("ApprovalsList", () => {
  it("renders business-language columns from real data, not raw tool_key/status", async () => {
    listApprovalsMock.mockResolvedValue([
      {
        id: "a1",
        tool_key: "ai.crm.qualify_lead",
        action_label: "Lead kwalificeren",
        status: "pending",
        status_label: "Wacht op goedkeuring",
        created_at: "2026-06-10T09:00:00Z",
      },
    ]);

    render(<ApprovalsList tenantId="t1" />);

    await waitFor(() => expect(screen.getByText("Lead kwalificeren")).toBeInTheDocument());
    expect(screen.getByText("Wacht op goedkeuring")).toBeInTheDocument();
    expect(screen.queryByText("ai.crm.qualify_lead")).not.toBeInTheDocument();
    expect(screen.queryByText("pending")).not.toBeInTheDocument();

    const row = screen.getByText("Lead kwalificeren").closest("tr");
    expect(row?.querySelector("a")).toHaveAttribute("href", "/t/t1/approvals/a1");
  });

  it("shows an honest, business-language empty state -- never a fabricated approval", async () => {
    listApprovalsMock.mockResolvedValue([]);

    render(<ApprovalsList tenantId="t1" />);

    await waitFor(() =>
      expect(screen.getByText("Er zijn momenteel geen acties die op goedkeuring wachten.")).toBeInTheDocument(),
    );
  });

  it("shows a recoverable error state on API failure, never an empty state disguised as success", async () => {
    listApprovalsMock.mockRejectedValue(new ApiError("server", "Something broke."));

    render(<ApprovalsList tenantId="t1" />);

    await waitFor(() => expect(screen.getByText("Something broke.")).toBeInTheDocument());
  });
});
