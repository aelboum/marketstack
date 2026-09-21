import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable } from "./DataTable";
import { Dialog, ConfirmDialog } from "./Dialog";
import { InlineNotice } from "./InlineNotice";

// UI-8: accessibility contracts of the shared primitives. Every domain
// module renders through these, so a fix here is a fix everywhere --
// which is also why they are worth pinning with tests.

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

type Row = { id: string; name: string };
const ROWS: Row[] = [{ id: "1", name: "Acme" }];
const COLUMNS = [{ key: "name", header: "Name", render: (r: Row) => r.name }];

describe("DataTable (UI-8)", () => {
  it("makes the horizontal scroll container keyboard reachable and named", () => {
    render(<DataTable columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} label="Contacts" />);

    // A scrollable region that is not focusable cannot be scrolled by a
    // keyboard-only user on a narrow screen (WCAG 2.1.1).
    const region = screen.getByRole("region", { name: "Contacts" });
    expect(region).toHaveAttribute("tabIndex", "0");
    expect(within(region).getByRole("table")).toBeInTheDocument();
  });

  it("falls back to a generic region name so existing callers stay valid", () => {
    render(<DataTable columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);
    expect(screen.getByRole("region", { name: "Data table" })).toBeInTheDocument();
  });

  it("still exposes real column headers", () => {
    render(<DataTable columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);
    expect(screen.getByRole("columnheader", { name: "Name" })).toHaveAttribute("scope", "col");
  });
});

describe("Dialog focus management (UI-8 regression guard)", () => {
  it("moves focus into the dialog and restores it to the opener on close", () => {
    // The dialog's `open` prop is driven through rerenders, which is how
    // a real caller toggles it.
    const { rerender } = render(
      <>
        <button type="button">Opener</button>
        <Dialog open={false} onClose={vi.fn()} title="Confirm something">
          <button type="button">Inside</button>
        </Dialog>
      </>,
    );

    const opener = screen.getByRole("button", { name: "Opener" });
    opener.focus();
    expect(opener).toHaveFocus();

    rerender(
      <>
        <button type="button">Opener</button>
        <Dialog open onClose={vi.fn()} title="Confirm something">
          <button type="button">Inside</button>
        </Dialog>
      </>,
    );

    // Focus enters the dialog rather than staying behind it.
    expect(screen.getByRole("button", { name: "Inside" })).toHaveFocus();

    rerender(
      <>
        <button type="button">Opener</button>
        <Dialog open={false} onClose={vi.fn()} title="Confirm something">
          <button type="button">Inside</button>
        </Dialog>
      </>,
    );

    // ...and returns to whatever opened it.
    expect(opener).toHaveFocus();
  });

  it("keeps Tab inside the dialog while it is open", async () => {
    const user = userEvent.setup();
    render(
      <>
        <button type="button">Outside</button>
        <Dialog open onClose={vi.fn()} title="Trapped">
          <button type="button">First</button>
          <button type="button">Last</button>
        </Dialog>
      </>,
    );

    const first = screen.getByRole("button", { name: "First" });
    const last = screen.getByRole("button", { name: "Last" });
    const close = screen.getByRole("button", { name: "Close dialog" });
    expect(first).toHaveFocus();

    await user.tab();
    expect(last).toHaveFocus();
    // The close affordance is inside the dialog, so it is part of the
    // cycle rather than an escape from it.
    await user.tab();
    expect(close).toHaveFocus();
    // Wrapping back to the start rather than escaping to "Outside".
    await user.tab();
    expect(first).toHaveFocus();
  });

  it("is labelled by its own title and marked as a modal", () => {
    render(
      <Dialog open onClose={vi.fn()} title="Delete this campaign?" description="Cannot be undone.">
        <button type="button">Inside</button>
      </Dialog>,
    );

    const dialog = screen.getByRole("dialog", { name: "Delete this campaign?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("Cannot be undone.");
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <Dialog open onClose={onClose} title="Escapable">
        <button type="button">Inside</button>
      </Dialog>,
    );

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("offers a named close affordance on a plain dialog (UI-9)", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <Dialog open onClose={onClose} title="Editable">
        <input aria-label="Field" />
      </Dialog>,
    );

    // Previously a plain Dialog had no visible dismiss at all -- only
    // Escape or a backdrop click, neither discoverable.
    const close = screen.getByRole("button", { name: "Close dialog" });
    await user.click(close);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("the close affordance does not steal initial focus from the content (UI-9)", () => {
    render(
      <Dialog open onClose={vi.fn()} title="Editable">
        <input aria-label="Field" />
      </Dialog>,
    );

    // It is rendered last in the DOM and positioned by CSS precisely so
    // the user lands on the field they came to fill in.
    expect(screen.getByLabelText("Field")).toHaveFocus();
  });

  it("ConfirmDialog does not add a second dismiss control beside Cancel (UI-9)", () => {
    render(
      <ConfirmDialog
        open
        title="Delete this?"
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    // Cancel is this dialog's dismiss control, and the one that carries
    // the pending guard -- a "×" alongside it would be both duplicated
    // and able to bypass that guard.
    expect(screen.queryByRole("button", { name: "Close dialog" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("ConfirmDialog disables both actions while the confirmation is pending", () => {
    render(
      <ConfirmDialog
        open
        pending
        title="Cancel this appointment?"
        confirmLabel="Cancel appointment"
        cancelLabel="Keep it"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    // Duplicate-submission protection has to be visible to the user, not
    // only enforced in the hook.
    expect(screen.getByRole("button", { name: "Keep it" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
  });
});

describe("InlineNotice (UI-8)", () => {
  it("announces errors assertively and other notices politely", () => {
    const { rerender } = render(<InlineNotice tone="danger">It failed</InlineNotice>);
    expect(screen.getByRole("alert")).toHaveTextContent("It failed");

    rerender(<InlineNotice tone="success">It worked</InlineNotice>);
    expect(screen.getByRole("status")).toHaveTextContent("It worked");
  });

  it("gives the icon-only dismiss control an accessible name", async () => {
    const onDismiss = vi.fn();
    const user = userEvent.setup();
    render(
      <InlineNotice tone="neutral" onDismiss={onDismiss}>
        Dismissable
      </InlineNotice>,
    );

    const dismiss = screen.getByRole("button", { name: "Dismiss" });
    await user.click(dismiss);
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});
