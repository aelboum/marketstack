import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DashboardGrid } from "./DashboardGrid";

describe("DashboardGrid", () => {
  it("renders every child into one CSS Grid container -- no JS-driven layout", () => {
    render(
      <DashboardGrid>
        <div data-testid="a">A</div>
        <div data-testid="b">B</div>
      </DashboardGrid>,
    );

    const a = screen.getByTestId("a");
    const b = screen.getByTestId("b");
    expect(a.parentElement).toBe(b.parentElement);
    expect(a.parentElement?.className).toMatch(/grid/i);
  });
});
