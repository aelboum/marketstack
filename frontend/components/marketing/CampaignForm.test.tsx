import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CampaignForm } from "./CampaignForm";
import { ApiError } from "@/lib/api/errors";

const { createCampaignMock, updateCampaignMock, listTemplatesMock } = vi.hoisted(() => ({
  createCampaignMock: vi.fn(),
  updateCampaignMock: vi.fn(),
  listTemplatesMock: vi.fn(),
}));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return {
    ...actual,
    createCampaign: createCampaignMock,
    updateCampaign: updateCampaignMock,
    listTemplates: listTemplatesMock,
  };
});

describe("CampaignForm", () => {
  it("create mode: disabled until name/body filled, submits with channel and audience fields", async () => {
    listTemplatesMock.mockResolvedValue({ results: [], hasMore: false });
    createCampaignMock.mockResolvedValue({ id: "c1", name: "Launch" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<CampaignForm tenantId="t1" onSaved={onSaved} />);

    expect(screen.getByRole("button", { name: "Create campaign" })).toBeDisabled();

    await user.type(screen.getByLabelText("Name"), "Launch");
    await user.selectOptions(screen.getByLabelText("Channel"), "sms");
    await user.type(screen.getByLabelText("Body"), "Body text");
    await user.click(screen.getByRole("button", { name: "Create campaign" }));

    await waitFor(() =>
      expect(createCampaignMock).toHaveBeenCalledWith("t1", {
        name: "Launch",
        channel: "sms",
        body: "Body text",
        subject: null,
        segment_q: null,
        segment_tag: null,
        template_id: null,
        click_target_url: null,
      }),
    );
    expect(onSaved).toHaveBeenCalledWith({ id: "c1", name: "Launch" });
  });

  it("edit mode: channel is read-only text, no segmentation fields, submits via updateCampaign", async () => {
    listTemplatesMock.mockResolvedValue({ results: [], hasMore: false });
    updateCampaignMock.mockResolvedValue({ id: "c1", name: "Renamed" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(
      <CampaignForm
        tenantId="t1"
        campaign={{
          id: "c1",
          tenant_id: "t1",
          name: "Launch",
          channel: "email",
          status: "draft",
          subject: "Hi",
          body: "Body",
          segment_query: "",
          template_id: null,
          click_target_url: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }}
        onSaved={onSaved}
      />,
    );

    expect(screen.queryByLabelText("Channel")).not.toBeInTheDocument();
    expect(screen.getByText(/Channel: email/)).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "Renamed");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(updateCampaignMock).toHaveBeenCalledWith("t1", "c1", {
        name: "Renamed",
        subject: "Hi",
        body: "Body",
        template_id: null,
        click_target_url: null,
        update_click_target_url: true,
      }),
    );
    expect(onSaved).toHaveBeenCalledWith({ id: "c1", name: "Renamed" });
  });

  it("shows the backend error on failure", async () => {
    listTemplatesMock.mockResolvedValue({ results: [], hasMore: false });
    createCampaignMock.mockRejectedValue(
      new ApiError("validation", "cannot be edited once it has left 'draft' status"),
    );
    const user = userEvent.setup();

    render(<CampaignForm tenantId="t1" onSaved={vi.fn()} />);
    await user.type(screen.getByLabelText("Name"), "Launch");
    await user.type(screen.getByLabelText("Body"), "Body text");
    await user.click(screen.getByRole("button", { name: "Create campaign" }));

    await waitFor(() =>
      expect(screen.getByText("cannot be edited once it has left 'draft' status")).toBeInTheDocument(),
    );
  });
});
