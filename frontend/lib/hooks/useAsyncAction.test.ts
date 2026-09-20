import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useAsyncAction } from "./useAsyncAction";
import { ApiError } from "@/lib/api/errors";

describe("useAsyncAction", () => {
  it("goes idle -> pending -> success, and returns the resolved value from run()", async () => {
    const fn = vi.fn().mockResolvedValue({ id: "1" });
    const { result } = renderHook(() => useAsyncAction(fn));

    expect(result.current.state.status).toBe("idle");

    let returned: unknown;
    await act(async () => {
      returned = await result.current.run();
    });

    expect(returned).toEqual({ id: "1" });
    expect(result.current.state).toEqual({ status: "success", data: { id: "1" } });
  });

  it("goes idle -> pending -> error on a rejected ApiError", async () => {
    const error = new ApiError("forbidden", "not found, or no access", { status: 404 });
    const fn = vi.fn().mockRejectedValue(error);
    const { result } = renderHook(() => useAsyncAction(fn));

    await act(async () => {
      await result.current.run();
    });

    expect(result.current.state).toEqual({ status: "error", error });
  });

  it("ignores a second run() while the first is still pending (duplicate-submit guard)", async () => {
    let resolveFirst: (() => void) | undefined;
    const fn = vi.fn().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveFirst = resolve;
        }),
    );
    const { result } = renderHook(() => useAsyncAction(fn));

    act(() => {
      void result.current.run();
    });
    await waitFor(() => expect(result.current.state.status).toBe("pending"));

    act(() => {
      void result.current.run();
    });

    expect(fn).toHaveBeenCalledOnce();

    await act(async () => {
      resolveFirst?.();
    });
  });

  it("reset() returns to idle", async () => {
    const fn = vi.fn().mockResolvedValue("ok");
    const { result } = renderHook(() => useAsyncAction(fn));

    await act(async () => {
      await result.current.run();
    });
    expect(result.current.state.status).toBe("success");

    act(() => result.current.reset());
    expect(result.current.state).toEqual({ status: "idle" });
  });
});
