import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "./page";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
}));

const { statusMock } = vi.hoisted(() => ({ statusMock: vi.fn() }));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ status: statusMock() }),
}));

vi.mock("@/lib/auth/api", () => ({
  loginUrl: () => "/auth/login",
}));

describe("LoginPage", () => {
  it("shows the product-branded sign-in card when unauthenticated, with no password field", () => {
    statusMock.mockReturnValue("unauthenticated");
    render(<LoginPage />);
    expect(screen.getByText("Product")).toBeInTheDocument();
    expect(screen.getByText("Sign in to continue to your workspace.")).toBeInTheDocument();
    const signIn = screen.getByRole("link", { name: "Sign in" });
    expect(signIn).toHaveAttribute("href", "/auth/login");
    expect(document.querySelector('input[type="password"]')).not.toBeInTheDocument();
    // Never names the identity provider in user-facing copy.
    expect(screen.queryByText(/zitadel/i)).not.toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("shows a loading state, not the sign-in card, while session status is loading", () => {
    statusMock.mockReturnValue("loading");
    render(<LoginPage />);
    expect(screen.queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("sends an already-authenticated visitor straight to the dashboard, never a stale sign-in card", () => {
    statusMock.mockReturnValue("authenticated");
    render(<LoginPage />);
    expect(screen.queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
    expect(replaceMock).toHaveBeenCalledTimes(1);
    expect(replaceMock).toHaveBeenCalledWith("/dashboard");
  });

  it("shows a redirecting transition state on click, without blocking the real navigation", async () => {
    statusMock.mockReturnValue("unauthenticated");
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.click(screen.getByRole("link", { name: "Sign in" }));
    expect(screen.getAllByText("Redirecting to sign in…").length).toBeGreaterThan(0);
  });
});
