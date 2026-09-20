import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SessionProvider, useSession } from "./session-context";
import { ApiError } from "@/lib/api/errors";

const { getCurrentUserMock, logoutMock } = vi.hoisted(() => ({
  getCurrentUserMock: vi.fn(),
  logoutMock: vi.fn(),
}));

vi.mock("./api", () => ({
  getCurrentUser: getCurrentUserMock,
  logout: logoutMock,
}));

function Probe() {
  const { status, user, logout, markSessionExpired } = useSession();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="user">{user?.user_id ?? "none"}</span>
      <button onClick={() => logout()}>logout</button>
      <button onClick={() => markSessionExpired()}>expire</button>
    </div>
  );
}

describe("SessionProvider", () => {
  beforeEach(() => {
    getCurrentUserMock.mockReset();
    logoutMock.mockReset();
  });

  it("starts in 'loading' and moves to 'authenticated' once /auth/me resolves", async () => {
    getCurrentUserMock.mockResolvedValue({ user_id: "user-1" });

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );

    expect(screen.getByTestId("status")).toHaveTextContent("loading");

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("user")).toHaveTextContent("user-1");
  });

  it("moves to 'unauthenticated' when /auth/me rejects with a 401 ApiError", async () => {
    getCurrentUserMock.mockRejectedValue(new ApiError("unauthorized", "no session", { status: 401 }));

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("logout() ends the session locally even if the backend call fails", async () => {
    getCurrentUserMock.mockResolvedValue({ user_id: "user-1" });
    logoutMock.mockRejectedValue(new ApiError("server", "boom", { status: 500 }));
    const user = userEvent.setup();

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await user.click(screen.getByText("logout"));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
  });

  it("markSessionExpired() flips an authenticated session to unauthenticated", async () => {
    getCurrentUserMock.mockResolvedValue({ user_id: "user-1" });
    const user = userEvent.setup();

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await act(async () => {
      await user.click(screen.getByText("expire"));
    });

    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");
  });
});
