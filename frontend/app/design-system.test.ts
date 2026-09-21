import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

// UI-9: the design-system conventions, asserted against the stylesheets
// themselves.
//
// These are deliberately source-level checks rather than rendered-DOM
// checks. jsdom applies no CSS module styling and evaluates no media
// query, so a component test cannot observe a breakpoint, a z-index or
// a transition duration at all. What *can* be protected is the thing
// that actually regressed before: the same concept written a different
// way in a new file. Each test below therefore pins a convention, and
// fails when a future change drifts from it.

const FRONTEND_ROOT = join(__dirname, "..");
const GLOBALS = readFileSync(join(FRONTEND_ROOT, "app", "globals.css"), "utf8");

function cssFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) cssFiles(full, found);
    else if (entry.endsWith(".css")) found.push(full);
  }
  return found;
}

const ALL_CSS = cssFiles(join(FRONTEND_ROOT, "components")).concat(
  join(FRONTEND_ROOT, "app", "globals.css"),
);

describe("breakpoint policy (UI-9)", () => {
  it("defines exactly one breakpoint, in rem, in globals.css", () => {
    expect(GLOBALS).toContain("--breakpoint-wide: 48rem");
  });

  it("every component media query uses the canonical breakpoint spelling", () => {
    // The drift this prevents: `768px` in the shell and `48rem` in
    // settings were the same breakpoint written two ways.
    const offenders: string[] = [];
    for (const file of ALL_CSS) {
      const css = readFileSync(file, "utf8");
      for (const match of css.matchAll(/@media\s*\(([^)]*width[^)]*)\)/g)) {
        const condition = match[1].replace(/\s+/g, " ").trim();
        if (condition !== "min-width: 48rem" && condition !== "max-width: 47.999rem") {
          offenders.push(`${file}: ${condition}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("layer policy (UI-9)", () => {
  it("defines the layer scale in a single ordered hierarchy", () => {
    const layers = ["base", "menu", "scrim", "drawer", "dialog", "skip-link"].map((name) => {
      const match = new RegExp(`--layer-${name}:\\s*(\\d+)`).exec(GLOBALS);
      expect(match, `--layer-${name} is not defined`).not.toBeNull();
      return Number((match as RegExpExecArray)[1]);
    });

    // The product's real stacking contract: a scrim must sit above page
    // content but below the drawer it dims, dialogs above both, and the
    // skip link above everything so keyboard escape is never covered.
    const sorted = [...layers].sort((a, b) => a - b);
    expect(layers).toEqual(sorted);
    expect(new Set(layers).size).toBe(layers.length);
  });

  it("no stylesheet hardcodes a raw z-index any more", () => {
    const offenders: string[] = [];
    for (const file of ALL_CSS) {
      for (const match of readFileSync(file, "utf8").matchAll(/z-index:\s*([^;]+);/g)) {
        if (!match[1].includes("--layer-")) offenders.push(`${file}: ${match[1].trim()}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("motion policy (UI-9)", () => {
  it("defines the motion scale", () => {
    expect(GLOBALS).toMatch(/--motion-fast:\s*\d+ms/);
    expect(GLOBALS).toMatch(/--motion-base:\s*\d+ms/);
    expect(GLOBALS).toMatch(/--motion-ease:/);
  });

  it("no stylesheet hardcodes a transition or animation duration", () => {
    const offenders: string[] = [];
    for (const file of ALL_CSS) {
      const css = readFileSync(file, "utf8");
      for (const match of css.matchAll(/(transition|animation):\s*([^;]+);/g)) {
        const value = match[2];
        // A bare `0.12s`/`700ms` literal is the drift being prevented.
        if (/\d+(\.\d+)?m?s/.test(value) && !value.includes("--motion-")) {
          offenders.push(`${file}: ${match[0].trim()}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("still reduces motion globally for users who ask for it (UI-8 behavior)", () => {
    expect(GLOBALS).toContain("@media (prefers-reduced-motion: reduce)");
    const block = GLOBALS.slice(GLOBALS.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(block).toContain("animation-duration: 0.01ms !important");
    expect(block).toContain("transition-duration: 0.01ms !important");
  });
});

describe("focus-visible policy (UI-9)", () => {
  const rule = GLOBALS.slice(GLOBALS.indexOf(":focus-visible {"));
  const body = rule.slice(0, rule.indexOf("}"));

  it("draws the ring with outline, so component shadows survive focus", () => {
    expect(body).toContain("outline:");
    expect(body).toContain("var(--focus-ring-color)");
    // The two destructive halves of the old rule.
    expect(body).not.toContain("box-shadow");
    expect(body).not.toContain("border-radius");
  });

  it("keeps an offset so the ring is legible against the control", () => {
    expect(body).toContain("outline-offset");
  });

  it("is still keyboard-only -- not a plain :focus rule", () => {
    expect(GLOBALS).toContain(":focus-visible {");
    expect(GLOBALS).not.toMatch(/\n:focus\s*\{/);
  });

  it("no component stylesheet removes a focus indicator", () => {
    const offenders: string[] = [];
    for (const file of ALL_CSS) {
      const css = readFileSync(file, "utf8");
      // `.main:focus { outline: none }` in the shell is deliberate: that
      // node is only ever focused programmatically by the skip link.
      for (const match of css.matchAll(/([^{}]*):focus(-visible)?[^{]*\{([^}]*)\}/g)) {
        if (/outline:\s*none/.test(match[3]) && !match[1].includes(".main")) {
          offenders.push(`${file}: ${match[1].trim()}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("viewport units (UI-9)", () => {
  it("pairs every full-height 100vh with a 100dvh fallback line", () => {
    // `vh` overstates the viewport on mobile while the URL bar is shown,
    // so a full-height container must resolve to `dvh` where supported.
    // The `vh` line is retained deliberately, as the fallback.
    const offenders: string[] = [];
    for (const file of ALL_CSS) {
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, index) => {
        const match = /^(\s*)([a-z-]+):\s*100vh;/.exec(line);
        if (!match) return;
        const next = lines[index + 1] ?? "";
        if (!next.includes(`${match[2]}: 100dvh;`)) {
          offenders.push(`${file}:${index + 1}: ${line.trim()}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });

  it("provides the shared full-page centring utility with both units", () => {
    const block = GLOBALS.slice(GLOBALS.indexOf(".full-page-center {"));
    expect(block.slice(0, block.indexOf("}"))).toContain("min-height: 100dvh");
  });
});
