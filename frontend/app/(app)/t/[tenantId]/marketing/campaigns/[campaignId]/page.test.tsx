import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CampaignDetailPage from "./page";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1", campaignId: "c1" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const {
  getCampaignMock,
  sendCampaignMock,
  cancelCampaignMock,
  deleteCampaignMock,
  listCampaignRecipientsMock,
  listTemplatesMock,
} = vi.hoisted(() => ({
  getCampaignMock: vi.fn(),
  sendCampaignMock: vi.fn(),
  cancelCampaignMock: vi.fn(),
  deleteCampaignMock: vi.fn(),
  listCampaignRecipientsMock: vi.fn(),
  listTemplatesMock: vi.fn(),
}));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return {
    ...actual,
    getCampaign: getCampaignMock,
    sendCampaign: sendCampaignMock,
    cancelCampaign: cancelCampaignMock,
    deleteCampaign: deleteCampaignMock,
    listCampaignRecipients: listCampaignRecipientsMock,
    listTemplates: listTemplatesMock,
  };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function draftCampaign(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "c1",
    tenant_id: "tenant-1",
    name: "Spring launch",
    channel: "email",
    status: "draft",
    subject: "Hi",
    body: "Body",
    segment_query: "",
    template_id: null,
    click_target_url: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("CampaignDetailPage", () => {
  it("draft campaign: shows Send, Edit, Delete but not Cancel send", async () => {
    getCampaignMock.mockResolvedValue(draftCampaign());
    listCampaignRecipientsMock.mockResolvedValue({ results: [], hasMore: false });
    listTemplatesMock.mockResolvedValue({ results: [], hasMore: false });

    render(<CampaignDetailPage />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Spring launch" })).toBeInTheDocument());

    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel send" })).not.toBeInTheDocument();
  });

  it("sending campaign: shows Cancel send only, no Send/Edit/Delete", async () => {
    getCampaignMock.mockResolvedValue(draftCampaign({ status: "sending" }));
    listCampaignRecipientsMock.mockResolvedValue({ results: [], hasMore: false });
    listTemplatesMock.mockResolvedValue({ results: [], hasMore: false });

    render(<CampaignDetailPage />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Spring launch" })).toBeInTheDocument());

    expect(screen.getByRole("button", { name: "Cancel send" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("sent campaign: no lifecycle actions at all", async () => {
    getCampaignMock.mockResolvedValue(draftCampaign({ status: "sent" }));
    listCampaignRecipientsMock.mockResolvedValue({ results: [], hasMore: false });
    listTemplatesMock.mockResolvedValue({ results: [], hasMore: false });

    render(<CampaignDetailPage />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Spring launch" })).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel send" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("send requires confirmation before calling sendCampaign", async () => {
    getCampaignMock.mockResolvedValue(draftCampaign());
    listCampaignRecipientsMock.mockResolvedValue({ results: [], hasMore: false });
    listTemplatesMock.mockResolvedValue({ results: [], hasMore: false });
    sendCampaignMock.mockResolvedValue({ campaign_id: "c1", recipient_count: 5, suppressed_count: 2, job_id: "j1" });
    const user = userEvent.setup();

    render(<CampaignDetailPage />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Spring launch" })).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(sendCampaignMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Send" }));

    await waitFor(() => expect(sendCampaignMock).toHaveBeenCalledWith("tenant-1", "c1"));
    await waitFor(() => expect(screen.getByText(/Sending to 5 recipient/)).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    getCampaignMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<CampaignDetailPage />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
