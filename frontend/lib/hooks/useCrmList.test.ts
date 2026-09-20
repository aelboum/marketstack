import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useCrmList } from "./useCrmList";
import type { ListResult } from "@/lib/api/crm";

function page(results: { id: string }[], limit: number): ListResult<{ id: string }> {
  return { results, hasMore: results.length === limit };
}

describe("useCrmList", () => {
  it("fetches page 1 on mount, with q/tag empty", async () => {
    const fetcher = vi.fn().mockResolvedValue(page([{ id: "1" }], 25));
    const { result } = renderHook(() => useCrmList(fetcher, "tenant-1"));

    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(fetcher).toHaveBeenCalledWith("tenant-1", { limit: 25, offset: 0, q: "", tag: "" });
  });

  it("nextPage()/prevPage() move the offset by one page", async () => {
    const fetcher = vi.fn().mockResolvedValue(page(Array(25).fill({ id: "x" }), 25));
    const { result } = renderHook(() => useCrmList(fetcher, "tenant-1"));
    await waitFor(() => expect(result.current.status).toBe("success"));

    act(() => result.current.nextPage());
    await waitFor(() => expect(result.current.offset).toBe(25));

    act(() => result.current.prevPage());
    await waitFor(() => expect(result.current.offset).toBe(0));
  });

  it("prevPage() never goes negative", async () => {
    const fetcher = vi.fn().mockResolvedValue(page([], 25));
    const { result } = renderHook(() => useCrmList(fetcher, "tenant-1"));
    await waitFor(() => expect(result.current.status).toBe("success"));

    act(() => result.current.prevPage());
    expect(result.current.offset).toBe(0);
  });

  it("changing the tag filter resets the offset back to 0", async () => {
    const fetcher = vi.fn().mockResolvedValue(page(Array(25).fill({ id: "x" }), 25));
    const { result } = renderHook(() => useCrmList(fetcher, "tenant-1"));
    await waitFor(() => expect(result.current.status).toBe("success"));

    act(() => result.current.nextPage());
    await waitFor(() => expect(result.current.offset).toBe(25));

    act(() => result.current.setTag("vip"));
    await waitFor(() => expect(result.current.offset).toBe(0));
  });
});
