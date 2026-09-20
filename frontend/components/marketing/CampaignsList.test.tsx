import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CampaignsList } from "./CampaignsList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listCampaignsMock } = vi.hoisted(() => ({ listCampaignsMock: vi.fn() }));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return { ...actual, listCampaigns: listCampaignsMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("CampaignsList", () => {
  it("shows loading, then real campaigns", async () => {
    listCampaignsMock.mockResolvedValue({
      results: [
        {
          id: "c1",
          tenant_id: "t1",
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
        },
      ],
      hasMore: false,
    });

    render(<CampaignsList tenantId="t1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Spring launch")).toBeInTheDocument());
    expect(screen.getByText("email")).toBeInTheDocument();
    expect(screen.getByText("draft")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Spring launch/ })).toHaveAttribute(
      "href",
      "/t/t1/marketing/campaigns/c1",
    );
  });

  it("shows an empty state with no campaigns", async () => {
    listCampaignsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<CampaignsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No campaigns yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listCampaignsMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<CampaignsList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("paginates via Previous/Next using limit/offset, never a fabricated total", async () => {
    listCampaignsMock.mockResolvedValue({
      results: Array.from({ length: 25 }, (_, i) => ({
        id: `c${i}`,
        tenant_id: "t1",
        name: `Campaign ${i}`,
        channel: "sms",
        status: "draft",
        subject: null,
        body: "Body",
        segment_query: "",
        template_id: null,
        click_target_url: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      })),
      hasMore: true,
    });
    const user = userEvent.setup();
    render(<CampaignsList tenantId="t1" />);
    await waitFor(() => expect(listCampaignsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 }));

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(listCampaignsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 25 }));
  });
});
