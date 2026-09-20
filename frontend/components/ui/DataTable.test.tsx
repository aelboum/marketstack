import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataTable } from "./DataTable";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

type Row = { id: string; name: string; email: string };

describe("DataTable", () => {
  const rows: Row[] = [
    { id: "1", name: "Jane Doe", email: "jane@example.com" },
    { id: "2", name: "John Roe", email: "john@example.com" },
  ];
  const columns = [
    { key: "name", header: "Name", render: (r: Row) => r.name },
    { key: "email", header: "Email", render: (r: Row) => r.email },
  ];

  it("renders column headers and every row's cells", () => {
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />);

    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Email" })).toBeInTheDocument();
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("john@example.com")).toBeInTheDocument();
  });

  it("wraps only the first column's content in a real, keyboard-reachable link when getRowHref is given", () => {
    render(
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        getRowHref={(r) => `/contacts/${r.id}`}
      />,
    );

    const link = screen.getByRole("link", { name: "Jane Doe" });
    expect(link).toHaveAttribute("href", "/contacts/1");
    // The second column's content is not itself a link.
    expect(screen.queryByRole("link", { name: "jane@example.com" })).not.toBeInTheDocument();
  });

  it("renders no row links when getRowHref is omitted", () => {
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
