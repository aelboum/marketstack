import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateWorkflowForm } from "./CreateWorkflowForm";
import { ApiError } from "@/lib/api/errors";

const { createWorkflowMock } = vi.hoisted(() => ({ createWorkflowMock: vi.fn() }));
vi.mock("@/lib/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/automation")>();
  return { ...actual, createWorkflow: createWorkflowMock };
});

describe("CreateWorkflowForm", () => {
  it("disabled until name and the required action fields are filled, then builds a single action step", async () => {
    createWorkflowMock.mockResolvedValue({
      workflow: { id: "w1", name: "Welcome" },
      version: { id: "v1" },
    });
    const onCreated = vi.fn();
    const user = userEvent.setup();

    render(<CreateWorkflowForm tenantId="t1" onCreated={onCreated} />);
    expect(screen.getByRole("button", { name: "Create automation" })).toBeDisabled();

    await user.type(screen.getByLabelText("Name"), "Welcome");
    await user.selectOptions(screen.getByLabelText(/Trigger/), "crm.contact.created");
    // Default action is "Create a task" -- fill its required field.
    await user.type(screen.getByLabelText("Title"), "Follow up");
    await user.click(screen.getByRole("button", { name: "Create automation" }));

    await waitFor(() =>
      expect(createWorkflowMock).toHaveBeenCalledWith("t1", {
        name: "Welcome",
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
        trigger_type: "crm.contact.created",
      }),
    );
    expect(onCreated).toHaveBeenCalledWith({
      workflow: { id: "w1", name: "Welcome" },
      version: { id: "v1" },
    });
  });

  it("defaults trigger_type to null -- manual-start-only is a real, valid workflow", async () => {
    createWorkflowMock.mockResolvedValue({ workflow: {}, version: {} });
    const user = userEvent.setup();

    render(<CreateWorkflowForm tenantId="t1" onCreated={vi.fn()} />);
    await user.type(screen.getByLabelText("Name"), "Manual only");
    await user.type(screen.getByLabelText("Title"), "Task");
    await user.click(screen.getByRole("button", { name: "Create automation" }));

    await waitFor(() => expect(createWorkflowMock).toHaveBeenCalled());
    const [, body] = createWorkflowMock.mock.calls[0];
    expect(body.trigger_type).toBeNull();
  });

  it("blocks a name longer than the real 255-character backend limit", async () => {
    const user = userEvent.setup();
    render(<CreateWorkflowForm tenantId="t1" onCreated={vi.fn()} />);

    await user.click(screen.getByLabelText("Name"));
    await user.paste("x".repeat(256));

    expect(screen.getByText(/255 characters or fewer/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create automation" })).toBeDisabled();
  });

  it("shows the backend's own validation error verbatim", async () => {
    createWorkflowMock.mockRejectedValue(
      new ApiError("validation", "trigger_type must be one of the supported event types.", {
        status: 400,
      }),
    );
    const user = userEvent.setup();

    render(<CreateWorkflowForm tenantId="t1" onCreated={vi.fn()} />);
    await user.type(screen.getByLabelText("Name"), "Broken");
    await user.type(screen.getByLabelText("Title"), "Task");
    await user.click(screen.getByRole("button", { name: "Create automation" }));

    await waitFor(() =>
      expect(
        screen.getByText("trigger_type must be one of the supported event types."),
      ).toBeInTheDocument(),
    );
  });
});
