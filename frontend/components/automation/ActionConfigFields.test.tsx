import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ActionConfigFields, cleanActionConfig, isActionConfigComplete } from "./ActionConfigFields";

const { listPipelinesMock, listStagesMock } = vi.hoisted(() => ({
  listPipelinesMock: vi.fn(),
  listStagesMock: vi.fn(),
}));
vi.mock("@/lib/api/crm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/crm")>();
  return { ...actual, listPipelines: listPipelinesMock, listStages: listStagesMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("ActionConfigFields", () => {
  it("create_task: shows only the real backend fields (title required, description optional)", () => {
    render(
      <ActionConfigFields tenantId="t1" actionType="create_task" config={{}} onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText("Title")).toBeInTheDocument();
    expect(screen.getByLabelText("Description")).toBeInTheDocument();
    expect(screen.queryByLabelText("To")).not.toBeInTheDocument();
  });

  it("update_contact: all four fields optional, and explains where the contact comes from", () => {
    render(
      <ActionConfigFields tenantId="t1" actionType="update_contact" config={{}} onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText("First name")).toBeInTheDocument();
    expect(screen.getByLabelText("Last name")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Phone")).toBeInTheDocument();
    expect(screen.getByText(/Applies to the contact from the event/)).toBeInTheDocument();
  });

  it("move_opportunity: builds a real pipeline -> stage picker from the CRM API, not a raw text field", async () => {
    listPipelinesMock.mockResolvedValue([{ id: "p1", tenant_id: "t1", name: "Sales", is_default: true, created_at: "" }]);
    listStagesMock.mockResolvedValue([
      { id: "s1", pipeline_id: "p1", name: "Negotiation", position: 0, is_won: false, is_lost: false },
    ]);
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(
      <ActionConfigFields tenantId="t1" actionType="move_opportunity" config={{}} onChange={onChange} />,
    );

    await waitFor(() => expect(screen.getByRole("option", { name: "Sales" })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Pipeline"), "p1");
    await waitFor(() => expect(screen.getByRole("option", { name: "Negotiation" })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Target stage *"), "s1");

    expect(onChange).toHaveBeenLastCalledWith({ to_stage_id: "s1" });
  });

  it("send_email: to/subject/body all required", () => {
    render(
      <ActionConfigFields tenantId="t1" actionType="send_email" config={{}} onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText("To")).toBeRequired();
    expect(screen.getByLabelText("Subject")).toBeRequired();
    // The multiline field's accessible name includes the required
    // marker text ("Body *"), unlike the single-line `Input` fields
    // above, which pass `required` as a real attribute instead.
    expect(screen.getByLabelText("Body *")).toBeRequired();
  });

  it("send_webhook: explains the real https/public-host constraint", () => {
    render(
      <ActionConfigFields tenantId="t1" actionType="send_webhook" config={{}} onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText("URL")).toHaveAttribute("type", "url");
    expect(screen.getByText(/must be an https URL on a public host/i)).toBeInTheDocument();
  });
});

describe("isActionConfigComplete", () => {
  it("create_task requires a title", () => {
    expect(isActionConfigComplete("create_task", {})).toBe(false);
    expect(isActionConfigComplete("create_task", { title: "Follow up" })).toBe(true);
  });

  it("update_contact has no required field (a no-op update is a valid choice)", () => {
    expect(isActionConfigComplete("update_contact", {})).toBe(true);
  });

  it("move_opportunity requires to_stage_id", () => {
    expect(isActionConfigComplete("move_opportunity", {})).toBe(false);
    expect(isActionConfigComplete("move_opportunity", { to_stage_id: "s1" })).toBe(true);
  });

  it("send_email requires to/subject/body", () => {
    expect(isActionConfigComplete("send_email", { to: "a@example.com" })).toBe(false);
    expect(
      isActionConfigComplete("send_email", { to: "a@example.com", subject: "Hi", body: "Body" }),
    ).toBe(true);
  });

  it("send_webhook requires url", () => {
    expect(isActionConfigComplete("send_webhook", {})).toBe(false);
    expect(isActionConfigComplete("send_webhook", { url: "https://example.com" })).toBe(true);
  });
});

describe("cleanActionConfig", () => {
  it("drops blank fields the user never touched", () => {
    expect(cleanActionConfig({ title: "Follow up", description: "" })).toEqual({
      title: "Follow up",
    });
  });
});
