import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// RTL's automatic per-test cleanup only self-registers when it detects
// Vitest's *global* afterEach; this project keeps `globals: false`
// (vitest.config.ts) so `tsc --noEmit` doesn't need an extra ambient-types
// dependency for `**/*.test.tsx`. Registering it explicitly here gets the
// same isolation (each test starts from an empty DOM) without that
// tradeoff.
afterEach(cleanup);
