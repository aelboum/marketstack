import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  LoadingState,
  EmptyState,
  ErrorState,
  PermissionDeniedState,
  UnauthorizedState,
} from "./states";

describe("reusable state components", () => {
  it("LoadingState announces itself via role=status", () => {
    render(<LoadingState label="Loading contacts…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading contacts…");
  });

  it("EmptyState renders a title, description, and optional action", () => {
    render(<EmptyState title="No contacts yet" description="Add your first contact." action={<button>Add contact</button>} />);
    expect(screen.getByText("No contacts yet")).toBeInTheDocument();
    expect(screen.getByText("Add your first contact.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add contact" })).toBeInTheDocument();
  });

  it("ErrorState uses role=alert and calls onRetry when the retry button is clicked", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorState description="Could not load contacts." onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Could not load contacts.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("PermissionDeniedState never claims to know whether the resource exists (backend non-enumeration)", () => {
    render(<PermissionDeniedState />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Not found, or you don't have access");
    expect(alert.textContent?.toLowerCase()).not.toMatch(/you do not have permission/);
  });

  it("UnauthorizedState calls onSignIn when its action is clicked", async () => {
    const onSignIn = vi.fn();
    const user = userEvent.setup();
    render(<UnauthorizedState onSignIn={onSignIn} />);

    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(onSignIn).toHaveBeenCalledOnce();
  });
});
