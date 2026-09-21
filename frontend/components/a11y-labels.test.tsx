import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { TemplatesPanel as ConversationsTemplatesPanel } from "./conversations/TemplatesPanel";
import { TemplatesPanel as MarketingTemplatesPanel } from "./marketing/TemplatesPanel";
import { CreateFormForm } from "./marketing/CreateFormForm";
import { MessageComposer } from "./conversations/MessageComposer";
import { ImportExportPanel } from "./crm/ImportExportPanel";

// UI-8: every control that previously had no accessible name. These are
// the cases a screen-reader user could reach but not identify -- a
// textarea announced as "edit text, blank", or a select with no name at
// all. Each assertion here fails if the label is ever removed again.

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

const { convListTemplatesMock } = vi.hoisted(() => ({ convListTemplatesMock: vi.fn() }));
vi.mock("@/lib/api/conversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/conversations")>();
  return { ...actual, listTemplates: convListTemplatesMock };
});

const { mktListTemplatesMock } = vi.hoisted(() => ({ mktListTemplatesMock: vi.fn() }));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return { ...actual, listTemplates: mktListTemplatesMock };
});

describe("form controls have accessible names (UI-8)", () => {
  it("conversations: the create-template body textarea is named", async () => {
    convListTemplatesMock.mockResolvedValue([]);
    render(<ConversationsTemplatesPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByLabelText("Template body")).toBeInTheDocument());
  });

  it("conversations: an existing template's edit textarea is named after that template", async () => {
    convListTemplatesMock.mockResolvedValue([
      { id: "tpl1", tenant_id: "t1", name: "Welcome", body: "Hi", channel: null },
    ]);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    render(<ConversationsTemplatesPanel tenantId="t1" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Welcome" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Edit" }));

    // Named per template, so a panel listing several does not present
    // several identically named editors.
    expect(screen.getByLabelText("Body of template Welcome")).toBeInTheDocument();
  });

  it("marketing: template content textareas are named", async () => {
    mktListTemplatesMock.mockResolvedValue({ results: [], hasMore: false });
    render(<MarketingTemplatesPanel tenantId="t1" />);

    await waitFor(() => expect(screen.getByLabelText("Template content")).toBeInTheDocument());
  });

  it("marketing: each dynamic form-field row names both of its controls", () => {
    render(<CreateFormForm tenantId="t1" onSaved={vi.fn()} />);

    expect(screen.getByLabelText("Field 1 name")).toBeInTheDocument();
    expect(screen.getByLabelText("Field 1 type")).toBeInTheDocument();
  });

  it("conversations: the internal-note textarea is named, not just placeholdered", () => {
    convListTemplatesMock.mockResolvedValue([]);
    render(<MessageComposer tenantId="t1" threadId="th1" channel="sms" onSent={vi.fn()} />);

    // A placeholder disappears as soon as the user types and is not a
    // label; this must be a real accessible name.
    expect(screen.getByLabelText("Internal note")).toBeInTheDocument();
  });

  it("crm: the CSV import textarea is named", () => {
    render(<ImportExportPanel tenantId="t1" />);
    expect(screen.getByLabelText("CSV content")).toBeInTheDocument();
  });
});

describe("state is not conveyed by colour alone (UI-8)", () => {
  it("conversations: the selected composer tab reports its pressed state", () => {
    convListTemplatesMock.mockResolvedValue([]);
    render(<MessageComposer tenantId="t1" threadId="th1" channel="email" onSent={vi.fn()} />);

    // Previously the active tab differed only by button colour.
    const tabs = screen.getAllByRole("button", { name: "Send email" });
    expect(tabs[0]).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Internal note" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
