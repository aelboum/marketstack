import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FormsList } from "./FormsList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listFormsMock } = vi.hoisted(() => ({ listFormsMock: vi.fn() }));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return { ...actual, listForms: listFormsMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("FormsList", () => {
  it("shows real forms, linking to the detail page", async () => {
    listFormsMock.mockResolvedValue({
      results: [{ id: "f1", tenant_id: "t1", name: "Newsletter", form_token: "tok1", fields: [{ name: "email", field_type: "email", required: true }], created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }],
      hasMore: false,
    });
    render(<FormsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Newsletter")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Newsletter/ })).toHaveAttribute("href", "/t/t1/marketing/forms/f1");
  });

  it("shows an empty state with no forms", async () => {
    listFormsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<FormsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No forms yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listFormsMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<FormsList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
