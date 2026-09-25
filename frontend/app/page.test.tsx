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

describe("HomePage", () => {
  it("shows a loading state while session status is loading, without dispatching anywhere", () => {
    statusMock.mockReturnValue("loading");
    render(<HomePage />);
    expect(screen.getAllByText("Loading…").length).toBeGreaterThan(0);
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("hands an authenticated session off to the existing tenant-resolution entry point", () => {
    statusMock.mockReturnValue("authenticated");
    render(<HomePage />);
    expect(replaceMock).toHaveBeenCalledTimes(1);
    expect(replaceMock).toHaveBeenCalledWith("/dashboard");
  });

  it("hands an unauthenticated session off to the product-owned sign-in page", () => {
    statusMock.mockReturnValue("unauthenticated");
    render(<HomePage />);
    expect(replaceMock).toHaveBeenCalledTimes(1);
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });
});
