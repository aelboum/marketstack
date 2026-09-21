import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProfileSettingsPanel } from "./ProfileSettingsPanel";

vi.mock("next/navigation", () => ({ usePathname: () => "/t/t1/settings/profile" }));

const { useSessionMock } = vi.hoisted(() => ({ useSessionMock: vi.fn() }));
vi.mock("@/lib/auth/session-context", () => ({ useSession: useSessionMock }));

function session(overrides: Record<string, unknown> = {}) {
  return {
    status: "authenticated",
    user: { user_id: "user-123" },
    refresh: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    markSessionExpired: vi.fn(),
    ...overrides,
  };
}

describe("ProfileSettingsPanel", () => {
  it("shows the real signed-in user id and no editable profile fields", () => {
    useSessionMock.mockReturnValue(session());
    render(<ProfileSettingsPanel />);

    expect(screen.getByText("user-123")).toBeInTheDocument();
    expect(screen.getByText("Signed in")).toBeInTheDocument();
    // /auth/me returns only user_id -- there is nothing else to edit, so
    // the panel offers no profile form rather than one that saves nowhere.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText(/not editable here/)).toBeInTheDocument();
  });

  it("shows a loading state while the session is still being established", () => {
    useSessionMock.mockReturnValue(session({ status: "loading", user: null }));
    render(<ProfileSettingsPanel />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeDisabled();
  });

  it("shows a signed-out state rather than an error panel when unauthenticated", () => {
    useSessionMock.mockReturnValue(session({ status: "unauthenticated", user: null }));
    render(<ProfileSettingsPanel />);

    expect(screen.getByText(/You are not signed in/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeDisabled();
  });

  it("re-checks the session through the shared session context", async () => {
    const state = session();
    useSessionMock.mockReturnValue(state);
    const user = userEvent.setup();

    render(<ProfileSettingsPanel />);
    await user.click(screen.getByRole("button", { name: "Re-check session" }));

    expect(state.refresh).toHaveBeenCalledOnce();
  });

  it("requires confirmation before signing out", async () => {
    const state = session();
    useSessionMock.mockReturnValue(state);
    const user = userEvent.setup();

    render(<ProfileSettingsPanel />);
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(state.logout).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(state.logout).toHaveBeenCalledOnce());
  });

  it("cancelling the sign-out dialog never ends the session", async () => {
    const state = session();
    useSessionMock.mockReturnValue(state);
    const user = userEvent.setup();

    render(<ProfileSettingsPanel />);
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Stay signed in" }));

    expect(state.logout).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
