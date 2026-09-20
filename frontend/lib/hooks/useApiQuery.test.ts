import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useApiQuery } from "./useApiQuery";
import { ApiError } from "@/lib/api/errors";

describe("useApiQuery", () => {
  it("starts loading, then resolves to success with the fetched data", async () => {
    const fetcher = vi.fn().mockResolvedValue(["a", "b"]);
    const { result } = renderHook(() => useApiQuery(fetcher, []));

    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current).toMatchObject({ status: "success", data: ["a", "b"] });
  });

  it("resolves to error with the thrown ApiError", async () => {
    const error = new ApiError("forbidden", "not found, or no access", { status: 404 });
    const fetcher = vi.fn().mockRejectedValue(error);
    const { result } = renderHook(() => useApiQuery(fetcher, []));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current).toMatchObject({ status: "error", error });
  });

  it("refetch() re-runs the fetcher", async () => {
    const fetcher = vi.fn().mockResolvedValue(1);
    const { result } = renderHook(() => useApiQuery(fetcher, []));
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(fetcher).toHaveBeenCalledOnce();

    result.current.refetch();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  });

  it("re-fetches when deps change", async () => {
    const fetcher = vi.fn().mockResolvedValue(1);
    const { result, rerender } = renderHook(({ dep }) => useApiQuery(fetcher, [dep]), {
      initialProps: { dep: "a" },
    });
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());

    rerender({ dep: "b" });
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.status).toBe("success"));
  });
});
