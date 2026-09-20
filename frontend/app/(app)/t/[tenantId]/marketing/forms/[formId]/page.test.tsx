import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FormDetailPage from "./page";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1", formId: "f1" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { getFormMock, deleteFormMock, listFormSubmissionsMock } = vi.hoisted(() => ({
  getFormMock: vi.fn(),
  deleteFormMock: vi.fn(),
  listFormSubmissionsMock: vi.fn(),
}));
vi.mock("@/lib/api/marketing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/marketing")>();
  return {
    ...actual,
    getForm: getFormMock,
    deleteForm: deleteFormMock,
    listFormSubmissions: listFormSubmissionsMock,
  };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("FormDetailPage", () => {
  it("renders read-only fields and the public submit URL, no edit control exists", async () => {
    getFormMock.mockResolvedValue({
      id: "f1",
      tenant_id: "tenant-1",
      name: "Newsletter",
      form_token: "tok-123",
      fields: [{ name: "email", field_type: "email", required: true }],
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    listFormSubmissionsMock.mockResolvedValue({ results: [], hasMore: false });

    render(<FormDetailPage />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Newsletter" })).toBeInTheDocument());

    expect(screen.getAllByText("email").length).toBeGreaterThan(0);
    expect(screen.getByText(/tok-123/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("delete requires confirmation, then calls deleteForm", async () => {
    getFormMock.mockResolvedValue({
      id: "f1",
      tenant_id: "tenant-1",
      name: "Newsletter",
      form_token: "tok-123",
      fields: [],
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    listFormSubmissionsMock.mockResolvedValue({ results: [], hasMore: false });
    deleteFormMock.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<FormDetailPage />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Newsletter" })).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteFormMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteFormMock).toHaveBeenCalledWith("tenant-1", "f1"));
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    getFormMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<FormDetailPage />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
