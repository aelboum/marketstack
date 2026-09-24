import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import HomePage from "./page";

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

describe("HomePage", () => {
  it("shows the public landing page when unauthenticated", () => {
    statusMock.mockReturnValue("unauthenticated");
    render(<HomePage />);
    expect(screen.getByText("Sign in to continue to your workspace.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/auth/login");
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("shows a loading state, not the landing page, while session status is loading", () => {
    statusMock.mockReturnValue("loading");
    render(<HomePage />);
    expect(screen.queryByText("Sign in to continue to your workspace.")).not.toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("hands an authenticated session off to the existing tenant-resolution entry point, without flashing the landing page", () => {
    statusMock.mockReturnValue("authenticated");
    render(<HomePage />);
    expect(screen.queryByText("Sign in to continue to your workspace.")).not.toBeInTheDocument();
    expect(replaceMock).toHaveBeenCalledTimes(1);
    expect(replaceMock).toHaveBeenCalledWith("/dashboard");
  });
});
