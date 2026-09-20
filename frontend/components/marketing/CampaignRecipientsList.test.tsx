import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { CampaignRecipientsList } from "./CampaignRecipientsList";
import { ApiError } from "@/lib/api/errors";

const { listCampaignRecipientsMock } = vi.hoisted(() => ({ listCampaignRecipientsMock: vi.fn() }));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return { ...actual, listCampaignRecipients: listCampaignRecipientsMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("CampaignRecipientsList", () => {
  it("shows real recipients, read-only (no actions column)", async () => {
    listCampaignRecipientsMock.mockResolvedValue({
      results: [{ id: "r1", campaign_id: "c1", contact_id: "ct1", status: "sent", sent_at: "2026-01-01T00:00:00Z", error: null }],
      hasMore: false,
    });
    render(<CampaignRecipientsList tenantId="t1" campaignId="c1" />);
    await waitFor(() => expect(screen.getByText("ct1")).toBeInTheDocument());
    expect(screen.getByText("sent")).toBeInTheDocument();
  });

  it("shows an empty state with no recipients", async () => {
    listCampaignRecipientsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<CampaignRecipientsList tenantId="t1" campaignId="c1" />);
    await waitFor(() => expect(screen.getByText("No recipients yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listCampaignRecipientsMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<CampaignRecipientsList tenantId="t1" campaignId="c1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
